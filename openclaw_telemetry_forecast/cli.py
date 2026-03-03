from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from .forecast import (
    apply_cost_estimation,
    daily_token_moving_average,
    detect_anomalies,
    model_cost_summary,
    model_latency_percentiles,
    month_end_forecast,
    rate_table_to_dataframe,
)
from .loader import load_cron_runs
from .rates import DEFAULT_MODEL_RATES, ModelRate
from .report import render_html_report


def _load_rate_file(path: str | None) -> Dict[str, ModelRate]:
    if not path:
        return DEFAULT_MODEL_RATES
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: Dict[str, ModelRate] = {}
    for key, val in raw.items():
        out[key] = ModelRate(
            input_per_1m=float(val.get("input_per_1m", 0.0)),
            output_per_1m=float(val.get("output_per_1m", 0.0)),
            cache_read_per_1m=float(val.get("cache_read_per_1m", 0.0)),
            cache_write_per_1m=float(val.get("cache_write_per_1m", 0.0)),
        )
    return out


def _summary(df: pd.DataFrame) -> dict:
    total = len(df)
    ok = int((df["status"] == "ok").sum()) if total else 0
    return {
        "total_runs": total,
        "ok_rate": (ok / total) if total else 0.0,
        "total_tokens": float(pd.to_numeric(df.get("total_tokens"), errors="coerce").fillna(0).sum()) if total else 0.0,
        "estimated_cost": float(pd.to_numeric(df.get("estimated_cost_usd"), errors="coerce").fillna(0).sum()) if total else 0.0,
    }


def cmd_report(args: argparse.Namespace) -> int:
    rates = _load_rate_file(args.rates)
    df = load_cron_runs(openclaw_dir=args.dir, job_id=args.job)
    if df.empty:
        print("No cron run logs found.")
        return 1

    df2 = apply_cost_estimation(df, rates=rates)
    latency = model_latency_percentiles(df2)
    ma = daily_token_moving_average(df2, windows=(7, 30))
    cost = model_cost_summary(df2)
    forecast = month_end_forecast(df2, lookback_days=args.lookback)
    anomalies = detect_anomalies(df2, z_threshold=args.z_threshold, failure_sigma=args.failure_sigma)

    out = render_html_report(
        args.out,
        generated_at=datetime.now(timezone.utc),
        summary=_summary(df2),
        forecast=forecast,
        latency_df=latency,
        cost_df=cost,
        ma_df=ma,
        anomalies_df=anomalies,
    )

    print(f"Wrote report: {out}")
    print("\nTop model cost rows:")
    print(cost.head(10).to_string(index=False))
    if not anomalies.empty:
        print("\nAnomalies:")
        print(anomalies.to_string(index=False))
    return 0


def cmd_table(args: argparse.Namespace) -> int:
    rates = _load_rate_file(args.rates)
    df = load_cron_runs(openclaw_dir=args.dir, job_id=args.job)
    if df.empty:
        print("No cron run logs found.")
        return 1

    df2 = apply_cost_estimation(df, rates=rates)
    if args.what == "latency":
        table = model_latency_percentiles(df2)
    elif args.what == "cost":
        table = model_cost_summary(df2)
    elif args.what == "ma":
        table = daily_token_moving_average(df2, windows=(7, 30))
    elif args.what == "anomaly":
        table = detect_anomalies(df2, z_threshold=args.z_threshold, failure_sigma=args.failure_sigma)
    elif args.what == "rates":
        table = rate_table_to_dataframe(rates)
    else:
        raise ValueError(f"unknown table: {args.what}")

    print(table.to_string(index=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="oc-forecast", description="OpenClaw telemetry forecast toolkit")
    p.add_argument("--dir", help="OpenClaw state dir (defaults to env or ~/.openclaw)")
    p.add_argument("--rates", help="JSON file with model pricing table")
    p.add_argument("--job", help="Optional cron job id filter")

    sub = p.add_subparsers(dest="cmd", required=True)

    rep = sub.add_parser("report", help="Generate full HTML forecast report")
    rep.add_argument("--out", default="examples/forecast_report.html")
    rep.add_argument("--lookback", type=int, default=14)
    rep.add_argument("--z-threshold", type=float, default=2.5)
    rep.add_argument("--failure-sigma", type=float, default=2.0)
    rep.set_defaults(func=cmd_report)

    tbl = sub.add_parser("table", help="Print analysis table")
    tbl.add_argument("what", choices=["latency", "cost", "ma", "anomaly", "rates"])
    tbl.add_argument("--z-threshold", type=float, default=2.5)
    tbl.add_argument("--failure-sigma", type=float, default=2.0)
    tbl.set_defaults(func=cmd_table)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
