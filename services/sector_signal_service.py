# ============================================
# services/sector_signal_service.py
# ============================================
# Publishes the daily ranked sector signals into `sector_signals` and
# returns the BUY/SELL/HOLD breakdown for the briefing layer.

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from config import (
    MAX_LONG_SECTORS, MAX_SHORT_SECTORS, PERSISTENCE_FILTER_SESSIONS,
)
from database.models import SectorFlowDaily, SectorSignal
from services.rotation_model_service import RotationModelService


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
        """Return {sector_code: accumulation_age} for sectors whose latest
        sector_flow_daily row has in_stealth semantics (accumulation_age > 0).
        """
        from sqlalchemy import func
        latest_dates = dict(
            self.session.query(
                SectorFlowDaily.sector_code,
                func.max(SectorFlowDaily.date),
            ).group_by(SectorFlowDaily.sector_code).all()
        )
        out: dict[str, int] = {}
        for code, d in latest_dates.items():
            row = (
                self.session.query(SectorFlowDaily)
                .filter_by(sector_code=code, date=d).one_or_none()
            )
            if row is not None and (row.accumulation_age or 0) > 0:
                out[code] = int(row.accumulation_age)
        return out

    def publish(self, model_run_id: int | None = None) -> pd.DataFrame:
        rms = RotationModelService(self.session)
        ranked = rms.predict_today()
        if ranked.empty:
            return ranked

        date = datetime.now().strftime("%Y-%m-%d")
        n = len(ranked)
        stealth = self._stealth_sectors()  # §16 ACCUMULATE set

        out_rows = []
        for i, row in ranked.iterrows():
            rank = int(row["rank"])
            persistence = self._persistence_ok(row["sector_code"])
            code = row["sector_code"]
            # §16.3 action precedence: ACCUMULATE > BUY > SELL > HOLD
            if code in stealth:
                action = "ACCUMULATE"
            elif rank <= MAX_LONG_SECTORS and persistence:
                action = "BUY"
            elif rank > n - MAX_SHORT_SECTORS and persistence:
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
