from __future__ import annotations

import calendar
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, Iterable

import numpy as np
import pandas as pd

from .rates import DEFAULT_MODEL_RATES, ModelRate, resolve_rate


def _ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "timestamp" not in out.columns:
        out["timestamp"] = pd.NaT
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
    return out


def model_latency_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    """Return model/provider latency metrics including p50/p95 in milliseconds."""
    data = _ensure_datetime(df)
    if data.empty:
        return pd.DataFrame(
            columns=["provider", "model", "runs", "avg_duration_ms", "p50_duration_ms", "p95_duration_ms"]
        )

    grouped = (
        data.groupby(["provider", "model"], dropna=False)["duration_ms"]
        .agg(
            runs="count",
            avg_duration_ms="mean",
            p50_duration_ms=lambda s: s.quantile(0.5),
            p95_duration_ms=lambda s: s.quantile(0.95),
        )
        .reset_index()
    )
    grouped = grouped.sort_values(["runs", "p95_duration_ms"], ascending=[False, False]).reset_index(drop=True)
    return grouped


def daily_token_moving_average(df: pd.DataFrame, windows: Iterable[int] = (7, 30)) -> pd.DataFrame:
    """Daily token totals with rolling moving averages."""
    data = _ensure_datetime(df)
    if data.empty:
        cols = ["date", "daily_tokens"] + [f"ma_{w}d" for w in windows]
        return pd.DataFrame(columns=cols)

    daily = (
        data.assign(date=data["timestamp"].dt.date)
        .groupby("date", as_index=False)["total_tokens"]
        .sum()
        .rename(columns={"total_tokens": "daily_tokens"})
    )
    daily["daily_tokens"] = pd.to_numeric(daily["daily_tokens"], errors="coerce").fillna(0)
    for w in windows:
        daily[f"ma_{w}d"] = daily["daily_tokens"].rolling(window=w, min_periods=1).mean()
    return daily


def apply_cost_estimation(
    df: pd.DataFrame,
    rates: Dict[str, ModelRate] | None = None,
) -> pd.DataFrame:
    """Attach per-run estimated USD costs using model/provider token rates.

    Billing policy:
    - `theoretical_api_cost_usd`: cost if the run were billed as API.
    - `estimated_cost_usd`: effective billable cost for current auth mode.
      For `auth_mode=oauth`, default is 0 (assume plan-covered unless overage model is provided).
    """
    table = rates or DEFAULT_MODEL_RATES
    out = df.copy()

    for col in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        out[col] = pd.to_numeric(out.get(col), errors="coerce").fillna(0)

    if "auth_mode" not in out.columns:
        out["auth_mode"] = "api"
    out["auth_mode"] = out["auth_mode"].astype(str).str.lower().fillna("api")

    estimated: list[float] = []
    rate_keys: list[str | None] = []

    for row in out.itertuples(index=False):
        rate = resolve_rate(getattr(row, "provider", None), getattr(row, "model", None), table)
        if rate is None:
            estimated.append(0.0)
            rate_keys.append(None)
            continue
        key = f"{getattr(row, 'provider', '')}/{getattr(row, 'model', '')}".strip("/")
        rate_keys.append(key)
        cost = (
            (float(getattr(row, "input_tokens", 0)) / 1_000_000) * rate.input_per_1m
            + (float(getattr(row, "output_tokens", 0)) / 1_000_000) * rate.output_per_1m
            + (float(getattr(row, "cache_read_tokens", 0)) / 1_000_000) * rate.cache_read_per_1m
            + (float(getattr(row, "cache_write_tokens", 0)) / 1_000_000) * rate.cache_write_per_1m
        )
        estimated.append(cost)

    out["theoretical_api_cost_usd"] = estimated
    out["estimated_cost_usd"] = [
        0.0 if str(auth).lower() == "oauth" else float(cost)
        for auth, cost in zip(out["auth_mode"], estimated, strict=False)
    ]
    out["rate_key"] = rate_keys
    return out


def model_cost_summary(df_with_cost: pd.DataFrame) -> pd.DataFrame:
    """Aggregate estimated costs/tokens by provider/model."""
    if df_with_cost.empty:
        return pd.DataFrame(
            columns=["provider", "model", "runs", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd"]
        )
    out = (
        df_with_cost.groupby(["provider", "model"], dropna=False)
        .agg(
            runs=("status", "count"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            estimated_cost_usd=("estimated_cost_usd", "sum"),
        )
        .reset_index()
        .sort_values("estimated_cost_usd", ascending=False)
        .reset_index(drop=True)
    )
    return out


def month_end_forecast(
    df_with_cost: pd.DataFrame,
    lookback_days: int = 14,
    now: datetime | None = None,
) -> dict:
    """
    Forecast month-end tokens and cost using average daily usage over recent lookback window.
    """
    data = _ensure_datetime(df_with_cost)
    if data.empty:
        return {
            "lookback_days": lookback_days,
            "days_elapsed": 0,
            "days_remaining": 0,
            "month_tokens_actual": 0.0,
            "month_cost_actual": 0.0,
            "daily_tokens_avg_recent": 0.0,
            "daily_cost_avg_recent": 0.0,
            "month_tokens_forecast": 0.0,
            "month_cost_forecast": 0.0,
        }

    now_dt = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    first_day = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_num = calendar.monthrange(now_dt.year, now_dt.month)[1]
    last_day = now_dt.replace(day=last_day_num, hour=23, minute=59, second=59, microsecond=999999)

    month_df = data[(data["timestamp"] >= first_day) & (data["timestamp"] <= last_day)].copy()
    if month_df.empty:
        return {
            "lookback_days": lookback_days,
            "days_elapsed": now_dt.day,
            "days_remaining": max(last_day_num - now_dt.day, 0),
            "month_tokens_actual": 0.0,
            "month_cost_actual": 0.0,
            "daily_tokens_avg_recent": 0.0,
            "daily_cost_avg_recent": 0.0,
            "month_tokens_forecast": 0.0,
            "month_cost_forecast": 0.0,
        }

    month_df["date"] = month_df["timestamp"].dt.date
    month_df["total_tokens"] = pd.to_numeric(month_df.get("total_tokens"), errors="coerce").fillna(0)
    month_df["estimated_cost_usd"] = pd.to_numeric(month_df.get("estimated_cost_usd"), errors="coerce").fillna(0)

    daily = month_df.groupby("date", as_index=False).agg(
        daily_tokens=("total_tokens", "sum"),
        daily_cost=("estimated_cost_usd", "sum"),
    )

    cutoff = (now_dt - pd.Timedelta(days=lookback_days - 1)).date()
    recent = daily[daily["date"] >= cutoff]
    if recent.empty:
        recent = daily

    avg_tokens = float(recent["daily_tokens"].mean())
    avg_cost = float(recent["daily_cost"].mean())

    days_remaining = max(last_day_num - now_dt.day, 0)
    month_tokens_actual = float(daily["daily_tokens"].sum())
    month_cost_actual = float(daily["daily_cost"].sum())

    return {
        "lookback_days": lookback_days,
        "days_elapsed": now_dt.day,
        "days_remaining": days_remaining,
        "month_tokens_actual": month_tokens_actual,
        "month_cost_actual": month_cost_actual,
        "daily_tokens_avg_recent": avg_tokens,
        "daily_cost_avg_recent": avg_cost,
        "month_tokens_forecast": month_tokens_actual + avg_tokens * days_remaining,
        "month_cost_forecast": month_cost_actual + avg_cost * days_remaining,
    }


def detect_anomalies(
    df_with_cost: pd.DataFrame,
    z_threshold: float = 2.5,
    failure_sigma: float = 2.0,
) -> pd.DataFrame:
    """
    Detect anomaly candidates:
    - Daily token spike (z-score)
    - Daily latency spike (z-score on avg duration)
    - Daily failure-rate surge (mean + N*std)
    """
    data = _ensure_datetime(df_with_cost)
    if data.empty:
        return pd.DataFrame(columns=["date", "type", "metric", "value", "baseline", "zscore", "severity"])

    temp = data.copy()
    temp["date"] = temp["timestamp"].dt.date
    temp["total_tokens"] = pd.to_numeric(temp.get("total_tokens"), errors="coerce").fillna(0)
    temp["duration_ms"] = pd.to_numeric(temp.get("duration_ms"), errors="coerce")

    daily = temp.groupby("date", as_index=False).agg(
        daily_tokens=("total_tokens", "sum"),
        avg_duration_ms=("duration_ms", "mean"),
        runs=("status", "count"),
        errors=("status", lambda s: (s == "error").sum()),
    )
    daily["failure_rate"] = np.where(daily["runs"] > 0, daily["errors"] / daily["runs"], 0)

    def _zscore(series: pd.Series) -> pd.Series:
        mean = series.mean()
        std = series.std(ddof=0)
        if std == 0 or np.isnan(std):
            return pd.Series([0.0] * len(series), index=series.index)
        return (series - mean) / std

    daily["z_tokens"] = _zscore(daily["daily_tokens"])
    daily["z_latency"] = _zscore(daily["avg_duration_ms"].fillna(daily["avg_duration_ms"].mean()))

    fr_mean = float(daily["failure_rate"].mean())
    fr_std = float(daily["failure_rate"].std(ddof=0) or 0)
    fr_threshold = fr_mean + failure_sigma * fr_std

    findings: list[dict] = []

    for r in daily.itertuples(index=False):
        if abs(r.z_tokens) >= z_threshold:
            findings.append(
                {
                    "date": str(r.date),
                    "type": "token_spike",
                    "metric": "daily_tokens",
                    "value": float(r.daily_tokens),
                    "baseline": float(daily["daily_tokens"].mean()),
                    "zscore": float(r.z_tokens),
                    "severity": "high" if abs(r.z_tokens) >= (z_threshold + 1.0) else "medium",
                }
            )
        if abs(r.z_latency) >= z_threshold:
            findings.append(
                {
                    "date": str(r.date),
                    "type": "latency_spike",
                    "metric": "avg_duration_ms",
                    "value": float(r.avg_duration_ms) if not np.isnan(r.avg_duration_ms) else 0.0,
                    "baseline": float(daily["avg_duration_ms"].mean(skipna=True) or 0.0),
                    "zscore": float(r.z_latency),
                    "severity": "high" if abs(r.z_latency) >= (z_threshold + 1.0) else "medium",
                }
            )
        if r.failure_rate > fr_threshold and r.failure_rate > 0:
            findings.append(
                {
                    "date": str(r.date),
                    "type": "failure_rate_surge",
                    "metric": "failure_rate",
                    "value": float(r.failure_rate),
                    "baseline": float(fr_mean),
                    "zscore": float((r.failure_rate - fr_mean) / fr_std) if fr_std > 0 else 0.0,
                    "severity": "high" if r.failure_rate >= max(0.5, fr_threshold * 1.25) else "medium",
                }
            )

    return pd.DataFrame(findings).sort_values(["severity", "date"], ascending=[False, False]).reset_index(drop=True) if findings else pd.DataFrame(columns=["date", "type", "metric", "value", "baseline", "zscore", "severity"])


def rate_table_to_dataframe(rates: Dict[str, ModelRate] | None = None) -> pd.DataFrame:
    table = rates or DEFAULT_MODEL_RATES
    rows = [{"key": k, **asdict(v)} for k, v in table.items()]
    return pd.DataFrame(rows).sort_values("key").reset_index(drop=True)
