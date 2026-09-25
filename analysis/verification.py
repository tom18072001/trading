"""What the system publishes that has NOT passed an out-of-sample test -- one list.

Review 2026-09-24 §4.2 / §8 P0-6: the sector ranker, the HMM regime label and
the §16.1 stealth gate have no measured out-of-sample edge, yet the email and
Daily Insight printed each as an instruction ("size full weight on
ACCUMULATE triggers", "no new BUYs, prefer cash", "Tư thế tấn công"). Measured:

- ranker: walk-forward IC -0.010 (NW t -0.5); 2024 +0.015, 2025 -0.044,
  2026 +0.004 -- no year significant, quintiles not monotone;
- regime: replayed the way it is published (weekly refit, filtered), the
  "holds 5 sessions" number read 0.69-0.85 against a realised 0.28-0.58, Brier
  skill negative every year; after a risk_on day VNINDEX's next 20 sessions
  were 1.55% WORSE than after other days;
- stealth gate: 20 events, excess -0.10% at 20 sessions (p 0.50) on the stored
  data -- the same verdict as §16.14.

Until one of them beats NO GATE year by year (CLAUDE.md §16.12), every surface
that shows it prints its note from here. When one passes, delete its entry and
the labels go with it. The shortlist (`long_shortlist`) is not on this list:
it is measured, and its honest ceiling is printed beside it instead.

The frontend cannot import this module; `frontend/src/pages/DailyInsightPage.tsx`
reads the notes from `/api/insight/daily` (`market_context.unverified`).
"""
from __future__ import annotations

TAG = "chưa kiểm chứng"

RANKER = ("Xếp hạng ngành (BUY/SELL ngành) chưa kiểm chứng: walk-forward IC −0,01, "
          "không năm nào có ý nghĩa — không phải lệnh.")

REGIME = ("Nhãn regime chưa kiểm chứng: replay ngoài mẫu giữ nhãn chỉ 28-58% so với "
          "69-85% mô hình báo — không đổi tỷ trọng theo nhãn này.")

STEALTH = ("Cổng stealth §16.1 chưa kiểm chứng: chưa thắng base rate (§16.14) — "
           "watchlist, không phải lệnh.")


def as_dict() -> dict[str, str]:
    """The notes as the API ships them."""
    return {"tag": TAG, "ranker": RANKER, "regime": REGIME, "stealth": STEALTH}
