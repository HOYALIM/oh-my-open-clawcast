from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from oh_my_open_clawcast.forecast import (
    apply_cost_estimation,
    daily_token_moving_average,
    detect_anomalies,
    model_cost_summary,
    model_latency_percentiles,
    month_end_forecast,
)
from oh_my_open_clawcast.rates import ModelRate


def _sample_df(days: int = 20) -> pd.DataFrame:
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for i in range(days):
        ts = now - timedelta(days=(days - i))
        rows.append(
            {
                "timestamp": ts,
                "status": "ok" if i % 6 else "error",
                "duration_ms": 800 + i * 20,
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 1000 + i * 10,
                "output_tokens": 400 + i * 5,
                "cache_read_tokens": 100,
                "cache_write_tokens": 0,
                "total_tokens": 1500 + i * 20,
            }
        )
    return pd.DataFrame(rows)


def test_latency_percentiles_present() -> None:
    df = _sample_df()
    lat = model_latency_percentiles(df)
    assert not lat.empty
    assert {"p50_duration_ms", "p95_duration_ms"}.issubset(set(lat.columns))
    assert float(lat.iloc[0]["p95_duration_ms"]) >= float(lat.iloc[0]["p50_duration_ms"])


def test_daily_moving_average_columns() -> None:
    df = _sample_df()
    ma = daily_token_moving_average(df)
    assert {"date", "daily_tokens", "ma_7d", "ma_30d"}.issubset(set(ma.columns))


def test_cost_estimation_and_summary() -> None:
    df = _sample_df()
    rates = {"openai/gpt-4o": ModelRate(input_per_1m=5.0, output_per_1m=15.0, cache_read_per_1m=1.25)}
    out = apply_cost_estimation(df, rates=rates)
    assert "estimated_cost_usd" in out.columns
    assert out["estimated_cost_usd"].sum() > 0
    summary = model_cost_summary(out)
    assert not summary.empty
    assert summary.iloc[0]["estimated_cost_usd"] > 0


def test_month_end_forecast_fields() -> None:
    df = apply_cost_estimation(_sample_df())
    fc = month_end_forecast(df, lookback_days=7)
    assert fc["lookback_days"] == 7
    assert fc["month_tokens_forecast"] >= fc["month_tokens_actual"]
    assert fc["month_cost_forecast"] >= fc["month_cost_actual"]


def test_month_end_forecast_respects_timezone_boundaries() -> None:
    now_utc = datetime(2026, 2, 28, 16, 0, tzinfo=timezone.utc)  # 2026-03-01 01:00 Asia/Seoul
    df = pd.DataFrame(
        [
            {
                "timestamp": datetime(2026, 2, 28, 15, 30, tzinfo=timezone.utc),  # 2026-03-01 00:30 KST
                "status": "ok",
                "duration_ms": 500,
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 100,
            },
            {
                "timestamp": datetime(2026, 2, 28, 14, 30, tzinfo=timezone.utc),  # 2026-02-28 23:30 KST
                "status": "ok",
                "duration_ms": 500,
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 999,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 999,
            },
        ]
    )
    out = apply_cost_estimation(df)
    fc = month_end_forecast(out, lookback_days=7, now=now_utc, tz="Asia/Seoul")
    assert fc["days_elapsed"] == 1
    assert fc["month_tokens_actual"] == 100.0


def test_anomaly_detection_token_spike() -> None:
    df = _sample_df()
    # Inject abnormal spike
    df.loc[len(df) - 1, "total_tokens"] = 500_000
    out = apply_cost_estimation(df)
    anomalies = detect_anomalies(out, z_threshold=2.0)
    assert not anomalies.empty
    assert "token_spike" in set(anomalies["type"])
