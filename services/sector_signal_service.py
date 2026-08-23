# ============================================
# services/sector_signal_service.py
# ============================================
# Publishes the daily ranked sector signals into `sector_signals` and
# returns the BUY/SELL/HOLD breakdown for the briefing layer.

from __future__ import annotations


import pandas as pd
from sqlalchemy.orm import Session

from config import (
    ACCUMULATE_MAX_AGE_SESSIONS, ALLOW_SHORT_SIGNALS, MAX_ACCUMULATE_SECTORS,
    MAX_LONG_SECTORS, MAX_SHORT_SECTORS, PERSISTENCE_FILTER_SESSIONS,
    TRADING_HALT,
)
from database.models import SectorFlowDaily, SectorSignal
from services.rotation_model_service import RotationModelService
from utils.clock import today_str


class SectorSignalService:
    def __init__(self, session: Session):
        self.session = session

    def _persistence_ok(self, sector_code: str) -> bool:
        rows = (
            self.session.query(SectorFlowDaily)
            .filter(SectorFlowDaily.sector_code == sector_code)
            .order_by(SectorFlowDaily.date.desc())
            .limit(PERSISTENCE_FILTER_SESSIONS)
            .all()
        )
        if len(rows) < PERSISTENCE_FILTER_SESSIONS:
            return False
        signs = [1 if (r.net_dollar_flow or 0) > 0 else -1 for r in rows]
        return all(s == signs[0] for s in signs)

    def _stealth_sectors(self) -> dict[str, int]:
        """{sector_code: accumulation_age} for sectors whose LATEST daily row
        is inside a stealth run.

        Review 2026-08-22, P3-4: this used to run one query per sector to find
        the latest date, then a second per sector to fetch the row -- 30
        round-trips for what one statement does.
        """
        from sqlalchemy import func, tuple_

        latest = (
            self.session.query(
                SectorFlowDaily.sector_code,
                func.max(SectorFlowDaily.date).label("d"),
            )
            .group_by(SectorFlowDaily.sector_code)
            .all()
        )
        if not latest:
            return {}

        rows = (
            self.session.query(SectorFlowDaily)
            .filter(tuple_(SectorFlowDaily.sector_code, SectorFlowDaily.date)
                    .in_([(c, d) for c, d in latest]))
            .all()
        )
        return {
            r.sector_code: int(r.accumulation_age)
            for r in rows
            if (r.accumulation_age or 0) > 0
        }

    def publish(self, model_run_id: int | None = None) -> pd.DataFrame:
        rms = RotationModelService(self.session)
        ranked = rms.predict_today()
        if ranked.empty:
            return ranked

        date = today_str()          # P1-6: market-local, not host-local
        n = len(ranked)
        stealth = self._stealth_sectors()  # §16 ACCUMULATE set

        # §16.9 — a stealth event that never broke out is dead money. Release
        # the slot rather than holding it forever (review 2026-08-22, P1-5).
        stale_stealth = [c for c, age in stealth.items()
                         if age > ACCUMULATE_MAX_AGE_SESSIONS]
        for code in stale_stealth:
            stealth.pop(code, None)
        if stale_stealth:
            print(f"[signals] released {len(stale_stealth)} stale ACCUMULATE "
                  f"(>{ACCUMULATE_MAX_AGE_SESSIONS} sessions): {', '.join(stale_stealth)}")

        # §16.9 — cap concurrent ACCUMULATE. Keep the oldest runs, which are
        # the ones closest to resolving; drop the rest to HOLD.
        if len(stealth) > MAX_ACCUMULATE_SECTORS:
            keep = dict(sorted(stealth.items(), key=lambda kv: -kv[1])[:MAX_ACCUMULATE_SECTORS])
            print(f"[signals] ACCUMULATE capped at {MAX_ACCUMULATE_SECTORS}: "
                  f"kept {', '.join(keep)} of {len(stealth)} candidates")
            stealth = keep

        # §18.4/20 — global kill-switch. No new long exposure while set.
        if TRADING_HALT:
            print("[signals] *** TRADING_HALT set — no ACCUMULATE/BUY will be emitted ***")

        # P1-2 — surface a degraded ranker rather than shipping its output as
        # if it were ranker-gated.
        degraded = getattr(rms.ranker, "is_degraded", False)
        if degraded:
            print("[signals] *** ranker is DEGRADED (mean-flow fallback) — "
                  "these ranks are close to 'sort sectors by size' ***")

        out_rows = []
        for _i, row in ranked.iterrows():
            rank = int(row["rank"])
            persistence = self._persistence_ok(row["sector_code"])
            code = row["sector_code"]
            # §16.3 action precedence: ACCUMULATE > BUY > SELL > HOLD
            if TRADING_HALT:
                action = "HOLD"
            elif code in stealth:
                action = "ACCUMULATE"
            elif rank <= MAX_LONG_SECTORS and persistence:
                action = "BUY"
            elif (ALLOW_SHORT_SIGNALS and rank > n - MAX_SHORT_SECTORS
                    and persistence):
                # §18.2/12 says the cash leg cannot short; set
                # ALLOW_SHORT_SIGNALS=0 to stop publishing this.
                action = "SELL"
            else:
                action = "HOLD"

            existing = (
                self.session.query(SectorSignal)
                .filter_by(date=date, sector_code=row["sector_code"]).one_or_none()
            )
            if existing is None:
                self.session.add(SectorSignal(
                    date=date, sector_code=row["sector_code"],
                    score=float(row["score"]), rank=rank, action=action,
                    persistence_ok=persistence, model_run_id=model_run_id,
                ))
            else:
                existing.score = float(row["score"]); existing.rank = rank
                existing.action = action; existing.persistence_ok = persistence
                existing.model_run_id = model_run_id
            out_rows.append({
                "date": date,
                "sector_code": row["sector_code"],
                "score": float(row["score"]),
                "rank": rank,
                "action": action,
                "persistence_ok": persistence,
            })

        self.session.commit()
        return pd.DataFrame(out_rows)

    def latest(self) -> pd.DataFrame:
        last = self.session.query(SectorSignal).order_by(SectorSignal.date.desc()).first()
        if not last:
            return pd.DataFrame()
        rows = (
            self.session.query(SectorSignal)
            .filter(SectorSignal.date == last.date)
            .order_by(SectorSignal.rank)
            .all()
        )
        return pd.DataFrame([{
            "date": r.date, "sector_code": r.sector_code, "score": r.score,
            "rank": r.rank, "action": r.action, "persistence_ok": r.persistence_ok,
        } for r in rows])
