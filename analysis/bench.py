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
SLIPPAGE_PER_SIDE = BACKTEST_SLIPPAGE_MIN_PCT     # §18.2/9: max(0,3%, 0,5×ATR%)
SLIPPAGE = 2 * SLIPPAGE_PER_SIDE                  # trả cả lúc vào lẫn lúc ra
SLIPPAGE_BPS_PER_SIDE = SLIPPAGE_PER_SIDE * 10_000  # mặc định cho CLI --slippage-bps
TOTAL_COST = ROUND_TRIP + SLIPPAGE

SESSIONS_PER_YEAR = 252

# Đo được, không phải giả định: VNINDEX buy-and-hold 2023-01 → 2026-09 trong
# `scripts/ticker_alpha_bench.py` (§26.9). Đây là **trần trung thực** — một rule
# không vượt được nó thì không phải lý do chọn cổ phiếu thay vì mua index.
VNINDEX_CAGR = 0.157
VNINDEX_SHARPE = 0.91
VNINDEX_MAXDD = -0.181

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
      - thắng base rate TRONG TỪNG NĂM (§16.12) — gộp lại là thứ che được một
        2026 ngang mức ngẫu nhiên;
      - quintile đơn điệu (§18.7) — không đơn điệu nghĩa là model đang đoán.
    """
    by_year = result["by_year"]
    years_neg = [int(y) for y in by_year.index if by_year.loc[y, "excess"] <= 0]
    q = list(result["quintiles"])
    ic_t = result.get("ic_t", float("nan"))
    ann = annualised(result["pick_net"], horizon)

    crit = [
        Criterion("thắng base rate (gộp)", result["excess"] > 0,
                  f"excess {result['excess']*100:+.2f}%", "§16.12"),
        Criterion("thắng base rate TỪNG NĂM", not years_neg,
                  "đủ mọi năm" if not years_neg else f"âm ở {years_neg}",
                  "§16.12", necessary=True),
        Criterion("quintile đơn điệu", q == sorted(q),
                  f"Q1..Q5 {' '.join(f'{v*100:+.2f}' for v in q)}",
                  "§18.7", necessary=True),
        Criterion("IC có ý nghĩa", abs(ic_t) >= IC_T_SIGNIFICANT if ic_t == ic_t else False,
                  f"t {ic_t:+.2f}", "§26.2"),
        Criterion("dương sau chi phí", result["pick_net"] > 0,
                  f"net {result['pick_net']*100:+.2f}%/lệnh", "§26.6"),
        Criterion("vượt VNINDEX", ann > VNINDEX_CAGR,
                  f"quy năm {ann*100:+.1f}% vs {VNINDEX_CAGR*100:.1f}%", "§26.9"),
    ]
    return Verdict(factor=factor, horizon=horizon, criteria=crit, annualised_net=ann)


def cost_banner() -> str:
    return (f"chi phí: phí+thuế {ROUND_TRIP*100:.2f}% + slippage {SLIPPAGE*100:.2f}% "
            f"= {TOTAL_COST*100:.2f}%/vòng  |  khung giữ {'/'.join(map(str, HOLD_SESSIONS))} phiên"
            + ("  |  ĐÂY LÀ PHÍA NHẸ: phí thật 0,2%/chiều (§26.9)"
               if COST_IS_OPTIMISTIC else ""))
