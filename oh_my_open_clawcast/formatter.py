from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .aggregator import PeriodSummary
from .quota import QuotaResult


def _fmt_num(value: float) -> str:
    return f"{value:,.0f}"


def _fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def _model_lines(title: str, summary: PeriodSummary, *, max_rows: int = 5) -> list[str]:
    lines = [title]
    if not summary.by_model:
        lines.append("- no data")
        return lines

    for row in summary.by_model[:max_rows]:
        provider = str(row.get("provider") or "unknown")
        model = str(row.get("model") or "unknown")
        auth_mode = str(row.get("auth_mode") or "api").upper()
        tokens = _fmt_num(float(row.get("total_tokens") or 0))
        cost = _fmt_usd(float(row.get("total_cost_usd") or 0))
        p50 = float(row.get("p50_ms") or 0)
        p95 = float(row.get("p95_ms") or 0)
        lines.append(
            f"- {provider}/{model} | {auth_mode} | {tokens} tok | {cost} | p50 {p50:.0f}ms / p95 {p95:.0f}ms"
        )
    return lines


def _quota_lines(quotas: Iterable[QuotaResult], *, max_rows: int = 6) -> list[str]:
    rows = list(quotas)
    lines = ["Quota"]
    if not rows:
        lines.append("- no quota data (set --quota-live-file / --quota-manual-file)")
        return lines

    for q in rows[:max_rows]:
        limit = _fmt_num(float(q.limit_tokens or 0)) if q.limit_tokens is not None else "n/a"
        used = _fmt_num(float(q.used_tokens or 0)) if q.used_tokens is not None else "n/a"
        remain = _fmt_num(float(q.remaining_tokens or 0)) if q.remaining_tokens is not None else "n/a"
        pct = ""
        if q.limit_tokens and q.used_tokens is not None and q.limit_tokens > 0:
            pct_val = (q.used_tokens / q.limit_tokens) * 100
            pct = f" ({pct_val:.1f}%)"
        lines.append(
            f"- {q.provider}/{q.model} [{q.auth_mode.upper()}] used {used}/{limit}{pct}, remaining {remain} ({q.confidence})"
        )
    return lines


def _latency_lines(daily: PeriodSummary, mtd: PeriodSummary, *, max_rows: int = 6) -> list[str]:
    lines = ["Latency"]
    seen: dict[str, dict] = {}
    for source in (daily.by_model, mtd.by_model):
        for row in source:
            key = f"{row.get('provider', '?')}/{row.get('model', '?')}"
            if key not in seen:
                seen[key] = row
    if not seen:
        lines.append("- no latency data")
        return lines
    for key, row in list(seen.items())[:max_rows]:
        p50 = float(row.get("p50_ms") or 0)
        p95 = float(row.get("p95_ms") or 0)
        lines.append(f"- {key}: p50 {p50:.0f}ms | p95 {p95:.0f}ms")
    return lines


def _alert_lines(alerts: list[dict], *, max_rows: int = 5) -> list[str]:
    lines = ["Alerts"]
    if not alerts:
        lines.append("- none")
        return lines
    for item in alerts[:max_rows]:
        severity = str(item.get("severity", "?")).upper()
        lines.append(
            f"- [{severity}] {item.get('date')} {item.get('type')} "
            f"value={item.get('value'):.1f} baseline={item.get('baseline'):.1f} z={item.get('zscore'):.2f}"
        )
    return lines


def render_clawcast_message(
    *,
    now_local: datetime,
    timezone_name: str,
    daily: PeriodSummary,
    mtd: PeriodSummary,
    forecast: dict,
    quotas: list[QuotaResult],
    alerts: list[dict],
) -> str:
    lines: list[str] = []
    lines.append("[Clawcast]")
    lines.append(f"Generated: {now_local.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name})")
    lines.append("")

    lines.append("Today")
    lines.append(
        f"- totals: {_fmt_num(daily.total_tokens)} tok, {_fmt_usd(daily.total_cost_usd)}, "
        f"runs {daily.total_runs}, failure {daily.failure_rate * 100:.1f}%"
    )
    lines.extend(_model_lines("Today by model", daily))
    lines.append("")

    lines.append("Month-to-date")
    lines.append(
        f"- totals: {_fmt_num(mtd.total_tokens)} tok, {_fmt_usd(mtd.total_cost_usd)}, "
        f"runs {mtd.total_runs}, failure {mtd.failure_rate * 100:.1f}%"
    )
    lines.extend(_model_lines("MTD by model", mtd))
    lines.append("")

    lines.append("Forecast")
    tok_fc = float(forecast.get("month_tokens_forecast", 0.0))
    cost_fc = float(forecast.get("month_cost_forecast", 0.0))
    lookback = int(forecast.get("lookback_days", 0))
    daily_tok_avg = float(forecast.get("daily_tokens_avg_recent", 0.0))
    daily_cost_avg = float(forecast.get("daily_cost_avg_recent", 0.0))
    if tok_fc > 0:
        lines.append(
            f"- month-end projected: {_fmt_num(tok_fc)} tok, {_fmt_usd(cost_fc)} (lookback {lookback}d)"
        )
        lines.append(
            f"- daily avg ({lookback}d): {_fmt_num(daily_tok_avg)} tok / {_fmt_usd(daily_cost_avg)}"
        )
    else:
        lines.append("- insufficient data for forecast")
    lines.append("")

    lines.extend(_quota_lines(quotas))
    lines.append("")
    lines.extend(_latency_lines(daily, mtd))
    lines.append("")
    lines.extend(_alert_lines(alerts))
    return "\n".join(lines).strip()
