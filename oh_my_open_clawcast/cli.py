from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from zoneinfo import ZoneInfo

import pandas as pd

from .aggregator import UsageAggregator
from .formatter import render_clawcast_message
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
from .quota import QuotaResolver
from .rates import DEFAULT_MODEL_RATES, ModelRate
from .report import render_html_report


def _default_timezone() -> str:
    env = os.environ.get("CLAWCAST_TZ")
    if env and env.strip():
        return env.strip()
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        key = getattr(local_tz, "key", None)
        if isinstance(key, str) and key.strip():
            return key
    return "UTC"


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", help="OpenClaw state dir (defaults to env or ~/.openclaw)")
    parser.add_argument("--rates", help="JSON file with model pricing table")
    parser.add_argument("--job", help="Optional cron job id filter")


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
    forecast = month_end_forecast(df2, lookback_days=args.lookback, tz=args.tz)
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


def cmd_message(args: argparse.Namespace) -> int:
    rates = _load_rate_file(args.rates)
    df = load_cron_runs(openclaw_dir=args.dir, job_id=args.job)

    tz_name = args.tz or _default_timezone()
    now_local = datetime.now(ZoneInfo(tz_name))

    agg = UsageAggregator(
        df=df,
        tz=tz_name,
        rates=rates,
    )
    daily = agg.daily()
    mtd = agg.mtd()
    forecast = agg.forecast(lookback_days=args.lookback)
    alerts = agg.alerts(z_threshold=args.z_threshold, failure_sigma=args.failure_sigma)

    model_keys: list[tuple[str, str, str]] = []
    for row in daily.by_model[: args.max_models]:
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        auth_mode = str(row.get("auth_mode") or "api")
        if provider and model:
            model_keys.append((provider, model, auth_mode))

    # Fill from MTD when today is sparse.
    if len(model_keys) < args.max_models:
        for row in mtd.by_model:
            provider = str(row.get("provider") or "")
            model = str(row.get("model") or "")
            auth_mode = str(row.get("auth_mode") or "api")
            candidate = (provider, model, auth_mode)
            if provider and model and candidate not in model_keys:
                model_keys.append(candidate)
            if len(model_keys) >= args.max_models:
                break

    quota = QuotaResolver(
        cache_ttl_seconds=args.quota_cache_ttl,
        live_file=args.quota_live_file,
        manual_file=args.quota_manual_file,
    )
    quotas = quota.resolve_all(model_keys)

    message = render_clawcast_message(
        now_local=now_local,
        timezone_name=tz_name,
        daily=daily,
        mtd=mtd,
        forecast=forecast,
        quotas=quotas,
        alerts=alerts,
    )
    print(message)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clawcast", description="Oh My Open Clawcast telemetry forecast toolkit")
    _add_common_args(p)

    sub = p.add_subparsers(dest="cmd")

    rep = sub.add_parser("report", help="Generate full HTML forecast report")
    _add_common_args(rep)
    rep.add_argument("--out", default="examples/forecast_report.html")
    rep.add_argument("--tz", default=_default_timezone(), help="Timezone for month/day boundaries")
    rep.add_argument("--lookback", type=int, default=14)
    rep.add_argument("--z-threshold", type=float, default=2.5)
    rep.add_argument("--failure-sigma", type=float, default=2.0)
    rep.set_defaults(func=cmd_report)

    tbl = sub.add_parser("table", help="Print analysis table")
    _add_common_args(tbl)
    tbl.add_argument("what", choices=["latency", "cost", "ma", "anomaly", "rates"])
    tbl.add_argument("--z-threshold", type=float, default=2.5)
    tbl.add_argument("--failure-sigma", type=float, default=2.0)
    tbl.set_defaults(func=cmd_table)

    msg = sub.add_parser("message", help="Print messenger-friendly /clawcast default summary text")
    _add_common_args(msg)
    msg.add_argument("--tz", default=_default_timezone(), help="Timezone for daily/month boundaries, e.g. Asia/Seoul")
    msg.add_argument("--lookback", type=int, default=14, help="Forecast lookback days")
    msg.add_argument("--z-threshold", type=float, default=2.5)
    msg.add_argument("--failure-sigma", type=float, default=2.0)
    msg.add_argument("--max-models", type=int, default=6)
    msg.add_argument("--quota-live-file", help="JSON file with live quota snapshots")
    msg.add_argument("--quota-manual-file", help="JSON file with manual quota limits")
    msg.add_argument("--quota-cache-ttl", type=int, default=300)
    msg.set_defaults(func=cmd_message)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd is None:
        # Default: run message subcommand with defaults
        defaults = parser.parse_args(["message"])
        # Merge any top-level args (--dir, --rates, --job) into defaults
        for key in ("dir", "rates", "job"):
            val = getattr(args, key, None)
            if val is not None:
                setattr(defaults, key, val)
        args = defaults
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
