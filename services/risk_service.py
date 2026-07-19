# ============================================
# services/risk_service.py — Sector-Level Risk
# ============================================
# Computes sector exposure, parametric VaR/CVaR, and drawdown using
# sector_flow_daily as the return source.

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config import RISK_CONFIG
from database.models import SectorFlowDaily, SectorSignal


@dataclass
class VaRReport:
    sector_code: str
    n_obs: int
    mean: float
    std: float
    var_95: float
    cvar_95: float


class SectorRiskService:
    def __init__(self, session: Session):
        self.session = session

    # ----- helpers -----
    def _returns(self, sector_code: str, lookback: int) -> np.ndarray:
        rows = (
            self.session.query(SectorFlowDaily)
            .filter(SectorFlowDaily.sector_code == sector_code)
            .order_by(SectorFlowDaily.date.desc())
            .limit(lookback)
            .all()
        )
        rets = [r.return_1d for r in rows if r.return_1d is not None]
        return np.asarray(rets[::-1])  # ascending

    # ----- VaR / CVaR -----
    def var_report(self, sector_code: str) -> VaRReport:
        lookback = RISK_CONFIG["var_lookback_days"]
        alpha = 1 - RISK_CONFIG["var_confidence"]
        rets = self._returns(sector_code, lookback)
        if len(rets) < 5:
            return VaRReport(sector_code, len(rets), 0.0, 0.0, 0.0, 0.0)

        mu = float(rets.mean())
        sigma = float(rets.std(ddof=1))
        z = NormalDist().inv_cdf(alpha)  # negative
        var = -(mu + sigma * z)          # positive loss number
        # Analytic CVaR for normal: -(mu - sigma * pdf(z)/alpha)
        pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
        cvar = -(mu - sigma * pdf_z / alpha)
        return VaRReport(sector_code, len(rets), mu, sigma, var, cvar)

    # ----- exposure -----
    def current_exposure(self) -> pd.DataFrame:
        last = (
            self.session.query(SectorSignal)
            .order_by(SectorSignal.date.desc())
            .first()
        )
        if not last:
            return pd.DataFrame()
        rows = (
            self.session.query(SectorSignal)
            .filter(SectorSignal.date == last.date)
            .filter(SectorSignal.action.in_(["BUY", "SELL"]))
            .all()
        )
        if not rows:
            return pd.DataFrame()
        n = len(rows)
        return pd.DataFrame([{
            "sector_code": r.sector_code,
            "side": r.action,
            "weight": 1.0 / n,
            "rank": r.rank,
        } for r in rows])

    # ----- drawdown sentinel -----
    def stoploss_breaches(self) -> list[dict]:
        """Return sectors whose latest 1d return breached the ATR-stop multiple."""
        breaches = []
        sectors = {r.sector_code for r in self.session.query(SectorFlowDaily).all()}
        for code in sectors:
            rows = (
                self.session.query(SectorFlowDaily)
                .filter(SectorFlowDaily.sector_code == code)
                .order_by(SectorFlowDaily.date.desc())
                .limit(2)
                .all()
            )
            if not rows:
                continue
            r = rows[0]
            if r.atr_pct and r.return_1d is not None:
                threshold = -RISK_CONFIG["stop_atr_multiple"] * r.atr_pct
                if r.return_1d < threshold:
                    breaches.append({
                        "sector_code": code, "date": r.date,
                        "return_1d": r.return_1d, "threshold": threshold,
                        "severity": "CRITICAL",
                    })
        return breaches


RiskService = SectorRiskService  # backwards-compat alias
