"""Một chỗ duy nhất định nghĩa: chi phí, registry thuật toán, và phán quyết.

Vì sao file này tồn tại — đo được, không phải sở thích gọn gàng:
năm script đo cùng một thứ ở **bốn** mức chi phí khác nhau, và không ai thấy:

    ticker_alpha_bench.py       1,00%/vòng   slippage từ config (§18.2/9) ✓
    ticker_ranker_experiment.py 0,70%        gõ tay `2 * 0.0015`
    tplus_strategy_bench.py     0,70%        --slippage-bps mặc định 15
    picks_portfolio_sim.py      0,70%        --slippage-bps mặc định 15
    audit_past_picks.py         0,40%        không tính slippage, cột vẫn tên "net"

Ở khung 20 phiên, 1,00% so với 0,70% là **3,8 điểm %/năm** — lớn hơn toàn bộ
biên mà ensemble tuyên bố vượt VNINDEX (+1,0pp), nên "lần đầu vượt index" thật
ra là một sai số đơn vị. Cùng bài học §22.11 đã ghi cho bar breakout, và §16.15
cho bar 1,15%: một định nghĩa nằm ở nhiều file là nhiều định nghĩa sẽ lệch, và
lệch âm thầm — bench vẫn in ra một con số trông hợp lý.

Ai thêm một thuật toán mới thì **không sửa file này và không sửa bench** — viết
một file trong `scripts/factors/`, xem `scripts/factors/README.md`.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

from config import (
    BACKTEST_FEE_BPS,
    BACKTEST_SELL_TAX_BPS,
    BACKTEST_SLIPPAGE_MIN_PCT,
    HOLD_SESSIONS,
)

# ============================== chi phí ======================================
# Nguồn duy nhất. Mọi bench phải import từ đây; không script nào được gõ lại một
# hằng số chi phí, kể cả khi nó "tình cờ bằng" hôm nay.

ROUND_TRIP = (2 * BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 10_000.0
# Slippage trong bench là SÀN của §18.2/9, áp PHẲNG 0,3%/chiều cho mọi mã — KHÔNG
# phải công thức `max(0,3%, 0,5×ATR%)`. Chú thích cũ ghi công thức, còn code chỉ
# áp mức sàn (review 2026-09-24 §6). Cố ý: với mã ATR 3-4%/phiên, nguyên văn công
# thức cho 1,5-2%/chiều, tức 3,6-4,3%/vòng — không thực tế cho lệnh nhỏ trên mã
# đủ thanh khoản. Từ 2026-09-25 backtest ngành cũng phẳng 0,3%
# (`config.BACKTEST_SLIPPAGE_ATR_MULT = 0`): một mô hình trượt giá cho cả hai.
SLIPPAGE_PER_SIDE = BACKTEST_SLIPPAGE_MIN_PCT     # 0,3%/chiều, phẳng
SLIPPAGE = 2 * SLIPPAGE_PER_SIDE                  # trả cả lúc vào lẫn lúc ra
SLIPPAGE_BPS_PER_SIDE = SLIPPAGE_PER_SIDE * 10_000  # mặc định cho CLI --slippage-bps
TOTAL_COST = ROUND_TRIP + SLIPPAGE

SESSIONS_PER_YEAR = 252

# VNINDEX KHÔNG còn là hằng số (2026-09-25). `VNINDEX_CAGR = 0,157` từng được so
# với một con số quy năm SỐ HỌC (%/lệnh × số vòng), trên cửa sổ khác — hai lần
# không cùng thước (review 2026-09-24 §1). Nay mỗi lần chạy, bench dựng danh mục
# staggered của rule (`staggered_book`) và đo VNINDEX mua & giữ trên CÙNG các
# ngày đó (`book_stats`), rồi `judge()` so hai con số cùng cửa sổ.

# §26.9 kiểm bằng web: phí thật VPS là 0,2%/chiều chứ không phải 0,15% như
# config, nên TOTAL_COST ở trên vẫn là phía NHẸ của thực tế. Mọi kết luận rút ra
# từ nó là kết luận lạc quan, không phải bi quan.
COST_IS_OPTIMISTIC = True


def annualised(net_per_trade: float, horizon_sessions: int) -> float:
    """Lãi/lỗ mỗi lệnh -> quy năm. Đây là con số Tom đọc, không phải %/lệnh.

    %/lệnh không so sánh được giữa các khung giữ: +0,2%/lệnh ở T+3 là thảm hoạ
    còn ở 8 tuần là tốt. Số vòng/năm mới là thứ biến cái này thành tiền.
    """
    rebalances = SESSIONS_PER_YEAR / horizon_sessions
    return net_per_trade * rebalances


def rebalances_per_year(horizon_sessions: int) -> float:
    return SESSIONS_PER_YEAR / horizon_sessions


def cost_drag_per_year(horizon_sessions: int) -> float:
    """Thuế thuần của việc xoay vòng — số hạng lớn nhất trong cả hệ thống (§26.9)."""
    return TOTAL_COST * rebalances_per_year(horizon_sessions)


# ============================== thống kê =====================================
# Ba hàm dưới đây là thước đo mà review 2026-09-24 §1 dùng để chấm lại mọi luật
# (`docs/reviews/algo_review_2026-09-24/picks_eval.py`), chuyển về đây để bench
# production dùng CÙNG một định nghĩa thay vì một bản gõ lại.

def nw_t(x, lag: int) -> float:
    """t-stat Newey-West (Bartlett, `lag` bậc) của trung bình một chuỗi ngày.

    Lợi suất h phiên đo MỖI ngày chồng lên nhau h ngày, nên t thường coi chúng
    độc lập và thổi t lên ~√h lần: IC t của thứ tự ship từ 6,1 xuống 2,2 khi
    tính đúng (review §1). Dùng lag = h.
    """
    import numpy as np
    x = np.asarray([v for v in x if v == v], dtype=float)   # bỏ NaN
    n = len(x)
    if n < 10:
        return float("nan")
    e = x - x.mean()
    v = (e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(max(v, 1e-18) / n))


def staggered_book(sel, open_, close, horizon: int, cost: float = TOTAL_COST):
    """Lợi suất NGÀY của danh mục Jegadeesh-Titman chạy theo một bảng chọn mã.

    Ngày tín hiệu t: mua các mã được chọn ở giá mở t+1, chia đều, giữ tới giá
    đóng t+1+h. Vốn chia h+1 phần, mỗi ngày mở một phần; ngày không có mã thì
    phần đó nằm tiền mặt. Chi phí cả vòng trừ ngay ngày vào. Đây là cách duy
    nhất để một con số %/lệnh trở thành thứ so được với VNINDEX cùng ngày.

    `sel`, `open_`, `close`: DataFrame cùng index/columns; `sel` là bool.
    """
    import numpy as np
    import pandas as pd
    O = open_.values  # noqa: E741
    C = close.values
    S = sel.fillna(False).astype(bool).values
    T = C.shape[0]
    acc = np.zeros(T)
    slots = horizon + 1
    for t in range(T - 1):
        js = np.flatnonzero(S[t])
        i0, i1 = t + 1, min(t + 1 + horizon, T - 1)
        if js.size == 0:
            continue
        paths = []
        for j in js:
            e = O[i0, j]
            if not (np.isfinite(e) and e > 0):
                continue
            path = pd.Series(C[i0:i1 + 1, j] / e).ffill().fillna(1.0).values
            paths.append(path)
        if not paths:
            continue
        v = np.mean(np.vstack(paths), axis=0)
        r = v / np.concatenate([[1.0], v[:-1]]) - 1.0
        r[0] -= cost
        acc[i0:i0 + len(r)] += r / slots
    return pd.Series(acc, index=close.index)


def book_stats(daily_returns, start: str | None = None) -> dict:
    """CAGR / Sharpe / MaxDD của một chuỗi lợi suất ngày, từ `start`."""
    import numpy as np
    import pandas as pd
    r = pd.Series(daily_returns).dropna()
    if start:
        r = r[r.index >= pd.Timestamp(start)]
    if len(r) < 20:
        return {"cagr": float("nan"), "sharpe": float("nan"), "maxdd": float("nan")}
    eq = (1 + r).cumprod()
    yrs = len(r) / SESSIONS_PER_YEAR
    sd = r.std()
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1),
            "sharpe": float(r.mean() / sd * np.sqrt(SESSIONS_PER_YEAR)) if sd > 0 else float("nan"),
            "maxdd": float((eq / eq.cummax() - 1).min())}


# ============================== registry =====================================
# Mọi factor trả về một khung điểm. CAO HƠN = đáng mua hơn.

FACTORS: dict[str, Callable] = {}
_META: dict[str, dict] = {}


def register(name: str, *, doc: str = "", source: str = ""):
    """Đăng ký một thuật toán để bench chấm.

    `source` ghi thuật toán đến từ đâu (bài báo, §CLAUDE.md, hay "ý tưởng thô"),
    vì một kết quả không có xuất xứ là một kết quả không kiểm lại được.
    """
    def deco(fn):
        if name in FACTORS:
            raise ValueError(
                f"factor {name!r} đã đăng ký ở {_META[name].get('module')} — "
                "trùng tên là hai thuật toán khác nhau dùng chung một dòng kết quả")
        FACTORS[name] = fn
        _META[name] = {"doc": doc or (fn.__doc__ or "").strip().split("\n")[0],
                       "source": source, "module": fn.__module__}
        return fn
    return deco


def factor_meta(name: str) -> dict:
    return _META.get(name, {})


def load_plugins(package: str = "scripts.factors") -> list[str]:
    """Nạp mọi thuật toán trong `scripts/factors/` — thêm rule không phải sửa bench."""
    loaded = []
    try:
        pkg = importlib.import_module(package)
    except ModuleNotFoundError:
        return loaded
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        importlib.import_module(f"{package}.{mod.name}")
        loaded.append(mod.name)
    return loaded


# ============================== phán quyết ===================================
# Tiêu chí lấy từ doctrine, mỗi cái truy được về một §. Không phát minh ngưỡng
# mới ở đây: một ngưỡng không ai bảo vệ được là một ngưỡng vô nghĩa.

IC_T_SIGNIFICANT = 2.0   # |t| >= 2. §26.2 gọi t=0.4 là nhiễu, t=7.9 là thật.


@dataclass
class Criterion:
    key: str
    passed: bool
    detail: str
    section: str
    necessary: bool = False


@dataclass
class Verdict:
    factor: str
    horizon: int
    criteria: list[Criterion] = field(default_factory=list)
    annualised_net: float = 0.0

    @property
    def failed_necessary(self) -> list[Criterion]:
        return [c for c in self.criteria if c.necessary and not c.passed]

    @property
    def label(self) -> str:
        if self.failed_necessary:
            return "REJECT"
        if not all(c.passed for c in self.criteria):
            return "EDGE, DƯỚI TRẦN"
        return "VƯỢT TRẦN"

    @property
    def reason(self) -> str:
        bad = [c for c in self.criteria if not c.passed]
        if not bad:
            return "đạt mọi tiêu chí"
        return "; ".join(f"{c.key} ({c.section})" for c in bad)


def judge(factor: str, horizon: int, result: dict) -> Verdict:
    """Chấm một kết quả `evaluate()` theo đúng tiêu chí doctrine đặt ra.

    Hai tiêu chí là **bắt buộc**, trượt là loại, không thương lượng:
      - thắng base rate NO GATE TRONG TỪNG NĂM (§16.12) — base là MỌI mã đủ thanh
        khoản, không phải "mọi mã cùng qua cổng của chính factor" (review
        2026-09-24 §1: base có cổng xoá luôn phần đóng góp của chính cái cổng);
      - quintile đơn điệu (§18.7) — không đơn điệu nghĩa là model đang đoán.

    "Vượt VNINDEX" so DANH MỤC của rule với VNINDEX mua & giữ trên CÙNG các ngày
    — cả lợi nhuận lẫn Sharpe. Không còn so một con số quy năm số học với hằng
    số 15,7%. `annualised_net` của phán quyết là CAGR danh mục đó.
    """
    by_year = result["by_year"]
    years_neg = [int(y) for y in by_year.index if by_year.loc[y, "excess"] <= 0]
    q = list(result["quintiles"])
    ic_t = result.get("ic_nw_t", float("nan"))
    ex_t = result.get("excess_nw_t", float("nan"))
    spread_t = result.get("q_spread_nw_t", float("nan"))
    book, vni = result.get("book") or {}, result.get("vnindex") or {}
    cagr, vcagr = book.get("cagr", float("nan")), vni.get("cagr", float("nan"))
    shp, vshp = book.get("sharpe", float("nan")), vni.get("sharpe", float("nan"))

    crit = [
        Criterion("thắng base rate (gộp)", result["excess"] > 0,
                  f"excess {result['excess']*100:+.2f}% (NW t {ex_t:+.2f})", "§16.12"),
        Criterion("thắng base rate TỪNG NĂM", not years_neg,
                  "đủ mọi năm" if not years_neg else f"âm ở {years_neg}",
                  "§16.12", necessary=True),
        Criterion("quintile đơn điệu", q == sorted(q),
                  f"Q1..Q5 {' '.join(f'{v*100:+.2f}' for v in q)}",
                  "§18.7", necessary=True),
        Criterion("Q5−Q1 có ý nghĩa", spread_t == spread_t and spread_t >= IC_T_SIGNIFICANT,
                  f"NW t {spread_t:+.2f}", "§18.7"),
        Criterion("IC có ý nghĩa", ic_t == ic_t and abs(ic_t) >= IC_T_SIGNIFICANT,
                  f"NW t {ic_t:+.2f}", "§26.2"),
        Criterion("dương sau chi phí", result["pick_net"] > 0,
                  f"net {result['pick_net']*100:+.2f}%/lệnh", "§26.6"),
        Criterion("vượt VNINDEX (danh mục cùng ngày)",
                  cagr == cagr and vcagr == vcagr and cagr > vcagr and shp > vshp,
                  f"{cagr*100:+.1f}%/năm Sharpe {shp:.2f} vs VNINDEX "
                  f"{vcagr*100:+.1f}% Sharpe {vshp:.2f}", "§26.9"),
    ]
    return Verdict(factor=factor, horizon=horizon, criteria=crit,
                   annualised_net=cagr if cagr == cagr else float("-inf"))


def cost_banner() -> str:
    return (f"chi phí: phí+thuế {ROUND_TRIP*100:.2f}% + slippage {SLIPPAGE*100:.2f}% "
            f"= {TOTAL_COST*100:.2f}%/vòng  |  khung giữ {'/'.join(map(str, HOLD_SESSIONS))} phiên"
            + ("  |  ĐÂY LÀ PHÍA NHẸ: phí thật 0,2%/chiều (§26.9)"
               if COST_IS_OPTIMISTIC else ""))
