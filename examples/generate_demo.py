from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from oh_my_open_clawcast.forecast import (
    apply_cost_estimation,
    daily_token_moving_average,
    detect_anomalies,
    model_cost_summary,
    model_latency_percentiles,
    month_end_forecast,
)
from oh_my_open_clawcast.report import render_html_report


def make_demo_df(days: int = 45) -> pd.DataFrame:
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    providers_models = [
        ("openai", "gpt-4o"),
        ("openai", "gpt-4.1-mini"),
        ("anthropic", "claude-sonnet-4-5"),
    ]

    for day in range(days):
        date = now - timedelta(days=(days - day))
        for _ in range(random.randint(8, 22)):
            provider, model = random.choice(providers_models)
            in_tok = random.randint(500, 6000)
            out_tok = random.randint(200, 3500)
            dur = random.randint(500, 4500)
            status = "ok" if random.random() > 0.12 else "error"
            rows.append(
                {
                    "timestamp": date + timedelta(minutes=random.randint(0, 1439)),
                    "status": status,
                    "duration_ms": dur,
                    "provider": provider,
                    "model": model,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "cache_read_tokens": random.randint(0, 800),
                    "cache_write_tokens": 0,
                    "total_tokens": in_tok + out_tok,
                }
            )

    # Inject one anomaly spike
    rows.append(
        {
            "timestamp": now,
            "status": "error",
            "duration_ms": 16000,
            "provider": "openai",
            "model": "gpt-4o",
            "input_tokens": 120000,
            "output_tokens": 80000,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 200000,
        }
    )

    return pd.DataFrame(rows)


def main() -> None:
    df = make_demo_df()
    df2 = apply_cost_estimation(df)

    out = render_html_report(
        Path(__file__).resolve().parent / "demo_forecast_report.html",
        generated_at=datetime.now(timezone.utc),
        summary={
            "total_runs": len(df2),
            "ok_rate": float((df2["status"] == "ok").sum() / len(df2)),
            "total_tokens": float(df2["total_tokens"].sum()),
            "estimated_cost": float(df2["estimated_cost_usd"].sum()),
        },
        forecast=month_end_forecast(df2, lookback_days=14),
        latency_df=model_latency_percentiles(df2),
        cost_df=model_cost_summary(df2),
        ma_df=daily_token_moving_average(df2),
        anomalies_df=detect_anomalies(df2, z_threshold=2.2),
    )
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
