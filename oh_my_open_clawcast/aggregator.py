from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict
from zoneinfo import ZoneInfo

import pandas as pd

from .forecast import apply_cost_estimation, detect_anomalies, month_end_forecast
from .rates import DEFAULT_MODEL_RATES, ModelRate


@dataclass(frozen=True)
class PeriodSummary:
    start_iso: str
    end_iso: str
    total_runs: int
    ok_runs: int
    error_runs: int
    failure_rate: float
    total_tokens: float
    total_cost_usd: float
    by_model: list[dict]


def _to_utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class UsageAggregator:
    """Compute today/MTD usage, latency and alerts from normalized run records."""

    def __init__(
        self,
        df: pd.DataFrame,
        tz: str = "UTC",
        rates: Dict[str, ModelRate] | None = None,
        now: datetime | None = None,
    ):
        self._tz = ZoneInfo(tz)
        self._now_utc = _to_utc_datetime(now)
        table = rates or DEFAULT_MODEL_RATES
        self._df = apply_cost_estimation(df.copy(), rates=table)

        if "timestamp" not in self._df.columns:
            self._df["timestamp"] = pd.NaT
        self._df["timestamp"] = pd.to_datetime(self._df["timestamp"], errors="coerce", utc=True)

        for col in (
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
            "estimated_cost_usd",
        ):
            self._df[col] = pd.to_numeric(self._df.get(col), errors="coerce").fillna(0)

        if "status" not in self._df.columns:
            self._df["status"] = "ok"
        self._df["status"] = self._df["status"].astype(str).str.lower().fillna("ok")

        if "auth_mode" not in self._df.columns:
            self._df["auth_mode"] = "api"
        self._df["auth_mode"] = self._df["auth_mode"].astype(str).str.lower().fillna("api")
        self._df.loc[~self._df["auth_mode"].isin({"api", "oauth"}), "auth_mode"] = "api"

    def _now_local(self) -> datetime:
        return self._now_utc.astimezone(self._tz)

    def _range_df(self, start_local: datetime, end_local: datetime) -> pd.DataFrame:
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        mask = (self._df["timestamp"] >= start_utc) & (self._df["timestamp"] < end_utc)
        return self._df[mask].copy()

    @staticmethod
    def _aggregate_by_model(df: pd.DataFrame) -> list[dict]:
        if df.empty:
            return []
        grouped = (
            df.groupby(["provider", "model", "auth_mode"], dropna=False)
            .agg(
                runs=("status", "count"),
                ok_runs=("status", lambda s: int((s == "ok").sum())),
                error_runs=("status", lambda s: int((s != "ok").sum())),
                total_tokens=("total_tokens", "sum"),
                input_tokens=("input_tokens", "sum"),
                output_tokens=("output_tokens", "sum"),
                total_cost_usd=("estimated_cost_usd", "sum"),
                p50_ms=("duration_ms", lambda s: float(s.quantile(0.5))),
                p95_ms=("duration_ms", lambda s: float(s.quantile(0.95))),
            )
            .reset_index()
            .sort_values(["total_tokens", "runs"], ascending=[False, False])
            .reset_index(drop=True)
        )
        return grouped.to_dict("records")

    @staticmethod
    def _period_summary(df: pd.DataFrame, start_local: datetime, end_local: datetime) -> PeriodSummary:
        total_runs = int(df.shape[0])
        ok_runs = int((df["status"] == "ok").sum()) if total_runs else 0
        error_runs = total_runs - ok_runs
        failure_rate = float(error_runs / total_runs) if total_runs else 0.0
        return PeriodSummary(
            start_iso=start_local.isoformat(),
            end_iso=end_local.isoformat(),
            total_runs=total_runs,
            ok_runs=ok_runs,
            error_runs=error_runs,
            failure_rate=failure_rate,
            total_tokens=float(df["total_tokens"].sum()) if total_runs else 0.0,
            total_cost_usd=float(df["estimated_cost_usd"].sum()) if total_runs else 0.0,
            by_model=UsageAggregator._aggregate_by_model(df),
        )

    def daily(self) -> PeriodSummary:
        now_local = self._now_local()
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        subset = self._range_df(start_local, now_local)
        return self._period_summary(subset, start_local=start_local, end_local=now_local)

    def mtd(self) -> PeriodSummary:
        now_local = self._now_local()
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        subset = self._range_df(start_local, now_local)
        return self._period_summary(subset, start_local=start_local, end_local=now_local)

    def forecast(self, lookback_days: int = 14) -> dict:
        return month_end_forecast(self._df, lookback_days=lookback_days, now=self._now_utc)

    def alerts(self, z_threshold: float = 2.5, failure_sigma: float = 2.0) -> list[dict]:
        anomalies = detect_anomalies(self._df, z_threshold=z_threshold, failure_sigma=failure_sigma)
        if anomalies.empty:
            return []
        return anomalies.sort_values("date", ascending=False).to_dict("records")
