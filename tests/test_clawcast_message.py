from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from oh_my_open_clawcast.aggregator import UsageAggregator
from oh_my_open_clawcast.forecast import apply_cost_estimation, month_end_forecast
from oh_my_open_clawcast.formatter import render_clawcast_message
from oh_my_open_clawcast.loader import infer_auth_mode, load_cron_runs
from oh_my_open_clawcast.quota import QuotaResolver
from oh_my_open_clawcast.rates import ModelRate
from oh_my_open_clawcast import cli as clawcast_cli


def test_infer_auth_mode_prefers_explicit_oauth() -> None:
    # Keep this matrix strict so auth classification regressions are caught quickly.
    entry = {"authMode": "OAuth"}
    assert infer_auth_mode(entry, provider="openai", model="gpt-4o") == "oauth"
    assert infer_auth_mode({"authMode": "API"}, provider="openai", model="gpt-4o") == "api"
    assert infer_auth_mode({"oauth": True}, provider="openai", model="gpt-4o") == "oauth"
    assert infer_auth_mode({}, provider="openai", model="gpt-4o") == "api"


def test_loader_reads_auth_mode_and_defaults_api(tmp_path: Path) -> None:
    runs_dir = tmp_path / "cron" / "runs"
    runs_dir.mkdir(parents=True)
    fp = runs_dir / "daily-job.jsonl"
    rows = [
        {
            "action": "finished",
            "ts": 1_700_000_000_000,
            "status": "ok",
            "provider": "openai",
            "model": "gpt-4o",
            "authMode": "oauth",
            "usage": {"total_tokens": 100, "input_tokens": 40, "output_tokens": 60},
        },
        {
            "action": "finished",
            "ts": 1_700_000_100_000,
            "status": "ok",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "usage": {"total_tokens": 200, "input_tokens": 80, "output_tokens": 120},
        },
    ]
    fp.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    df = load_cron_runs(openclaw_dir=str(tmp_path))
    assert len(df) == 2
    assert df.iloc[0]["auth_mode"] == "oauth"
    assert df.iloc[1]["auth_mode"] == "api"


def test_daily_and_mtd_boundaries_are_local_time_correct() -> None:
    # Local timezone in test: Asia/Seoul (UTC+9)
    # now_local = 2026-03-04 15:00:00+09:00 -> now_utc = 2026-03-04 06:00:00+00:00
    now_utc = datetime(2026, 3, 4, 6, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame(
        [
            # Local 2026-03-04 00:30 => included in daily and MTD
            {
                "timestamp": datetime(2026, 3, 3, 15, 30, tzinfo=timezone.utc),
                "status": "ok",
                "provider": "openai",
                "model": "gpt-4o",
                "auth_mode": "api",
                "duration_ms": 1000,
                "input_tokens": 200,
                "output_tokens": 300,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 500,
            },
            # Local 2026-03-03 23:30 => excluded from daily, included in MTD
            {
                "timestamp": datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc),
                "status": "ok",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "auth_mode": "oauth",
                "duration_ms": 1200,
                "input_tokens": 400,
                "output_tokens": 100,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 500,
            },
            # Local 2026-02-28 20:00 => excluded from MTD
            {
                "timestamp": datetime(2026, 2, 28, 11, 0, tzinfo=timezone.utc),
                "status": "ok",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "auth_mode": "api",
                "duration_ms": 900,
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 1500,
            },
        ]
    )
    agg = UsageAggregator(
        df,
        tz="Asia/Seoul",
        now=now_utc,
        rates={
            "openai/gpt-4o": ModelRate(input_per_1m=5, output_per_1m=15),
            "openai/gpt-4.1-mini": ModelRate(input_per_1m=1, output_per_1m=1),
            "anthropic/claude-sonnet-4-5": ModelRate(input_per_1m=3, output_per_1m=15),
        },
    )
    daily = agg.daily()
    mtd = agg.mtd()

    assert daily.total_tokens == 500
    assert mtd.total_tokens == 1000
    assert len(daily.by_model) == 1
    assert len(mtd.by_model) == 2


def test_quota_resolver_fallback_live_cached_manual(tmp_path: Path) -> None:
    live_file = tmp_path / "quota_live.json"
    manual_file = tmp_path / "quota_manual.json"

    live_file.write_text(
        json.dumps({"openai/gpt-4o|api": {"limit_tokens": 1000, "used_tokens": 250}}),
        encoding="utf-8",
    )
    manual_file.write_text(
        json.dumps({"openai/gpt-4o|api": {"limit_tokens": 1000, "used_tokens": 100}}),
        encoding="utf-8",
    )

    resolver = QuotaResolver(
        cache_ttl_seconds=600,
        live_file=str(live_file),
        manual_file=str(manual_file),
    )

    first = resolver.resolve("openai", "gpt-4o", "api")
    assert first is not None
    assert first.confidence == "snapshot"
    assert first.used_tokens == 250

    # Remove live data, cached result should be used.
    live_file.write_text("{}", encoding="utf-8")
    second = resolver.resolve("openai", "gpt-4o", "api")
    assert second is not None
    assert second.confidence == "cached"
    assert second.used_tokens == 250

    # Fresh resolver with no live data should use manual.
    resolver2 = QuotaResolver(
        cache_ttl_seconds=600,
        live_file=str(live_file),
        manual_file=str(manual_file),
    )
    third = resolver2.resolve("openai", "gpt-4o", "api")
    assert third is not None
    assert third.confidence == "manual"
    assert third.used_tokens == 100


def test_message_contains_required_sections() -> None:
    now_utc = datetime(2026, 3, 4, 6, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame(
        [
            {
                "timestamp": datetime(2026, 3, 4, 1, 0, tzinfo=timezone.utc),
                "status": "ok",
                "provider": "openai",
                "model": "gpt-4o",
                "auth_mode": "api",
                "duration_ms": 1000,
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 300,
            }
        ]
    )
    agg = UsageAggregator(df, tz="UTC", now=now_utc)
    message = render_clawcast_message(
        now_local=now_utc,
        timezone_name="UTC",
        daily=agg.daily(),
        mtd=agg.mtd(),
        forecast=agg.forecast(lookback_days=7),
        quotas=[],
        alerts=agg.alerts(),
    )

    assert "[Clawcast]" in message
    assert "Today" in message
    assert "Month-to-date" in message
    assert "Forecast" in message
    assert "Quota" in message
    assert "Latency" in message
    assert "Alerts" in message
    assert "Generated:" in message


def test_forecast_rising_trend_sanity() -> None:
    """Forecast with rising usage should produce forecast >= actual."""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(14):
        ts = now - timedelta(days=(14 - i))
        rows.append({
            "timestamp": ts,
            "status": "ok",
            "duration_ms": 800 + i * 30,
            "provider": "openai",
            "model": "gpt-4o",
            "input_tokens": 1000 + i * 100,
            "output_tokens": 400 + i * 50,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 1400 + i * 150,
            "auth_mode": "api",
        })
    df = pd.DataFrame(rows)
    rates = {"openai/gpt-4o": ModelRate(input_per_1m=5.0, output_per_1m=15.0)}
    df_cost = apply_cost_estimation(df, rates=rates)
    fc = month_end_forecast(df_cost, lookback_days=7, now=now)

    assert fc["month_tokens_forecast"] >= fc["month_tokens_actual"]
    assert fc["month_cost_forecast"] >= fc["month_cost_actual"]
    assert fc["days_remaining"] >= 0


def test_latency_p50_p95_calculations() -> None:
    """Latency p50/p95 values are correct and p50 <= p95."""
    now_utc = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
    durations = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    rows = []
    for i, d in enumerate(durations):
        rows.append({
            "timestamp": now_utc - timedelta(hours=i + 1),
            "status": "ok",
            "duration_ms": d,
            "provider": "openai",
            "model": "gpt-4o",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 150,
            "auth_mode": "api",
        })
    df = pd.DataFrame(rows)
    agg = UsageAggregator(df, tz="UTC", now=now_utc)
    daily = agg.daily()

    assert len(daily.by_model) == 1
    model_row = daily.by_model[0]
    p50 = model_row["p50_ms"]
    p95 = model_row["p95_ms"]
    assert p50 > 0
    assert p95 > 0
    assert p50 <= p95


def test_missing_data_graceful_handling() -> None:
    """Empty DataFrame produces valid output with informative text."""
    now_utc = datetime(2026, 3, 4, 6, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame(columns=[
        "timestamp", "status", "duration_ms", "provider", "model",
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "total_tokens", "auth_mode",
    ])
    agg = UsageAggregator(df, tz="UTC", now=now_utc)

    daily = agg.daily()
    mtd = agg.mtd()
    assert daily.total_runs == 0
    assert daily.total_tokens == 0.0
    assert daily.total_cost_usd == 0.0
    assert daily.by_model == []
    assert mtd.total_runs == 0

    message = render_clawcast_message(
        now_local=now_utc,
        timezone_name="UTC",
        daily=daily,
        mtd=mtd,
        forecast=agg.forecast(),
        quotas=[],
        alerts=agg.alerts(),
    )
    assert "[Clawcast]" in message
    assert "no data" in message.lower() or "0" in message


def test_oauth_cost_defaults_to_zero_but_tracks_theoretical_api_cost() -> None:
    now_utc = datetime(2026, 3, 4, 6, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame(
        [
            {
                "timestamp": now_utc,
                "status": "ok",
                "provider": "openai",
                "model": "gpt-4o",
                "auth_mode": "oauth",
                "duration_ms": 500,
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 1_000_000,
            }
        ]
    )
    out = apply_cost_estimation(df, rates={"openai/gpt-4o": ModelRate(input_per_1m=5, output_per_1m=15)})
    assert float(out.iloc[0]["theoretical_api_cost_usd"]) == 5.0
    assert float(out.iloc[0]["estimated_cost_usd"]) == 0.0


def test_cmd_message_returns_success_for_empty_dir(tmp_path: Path, capsys) -> None:
    parser = clawcast_cli.build_parser()
    args = parser.parse_args(["message", "--dir", str(tmp_path), "--tz", "UTC"])
    rc = clawcast_cli.cmd_message(args)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[Clawcast]" in captured.out
