from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


def _as_png_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _tokens_ma_chart(ma_df: pd.DataFrame) -> str:
    if ma_df.empty:
        return ""
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(ma_df["date"], ma_df["daily_tokens"], label="daily", alpha=0.4)
    if "ma_7d" in ma_df.columns:
        ax.plot(ma_df["date"], ma_df["ma_7d"], label="MA 7d", linewidth=2)
    if "ma_30d" in ma_df.columns:
        ax.plot(ma_df["date"], ma_df["ma_30d"], label="MA 30d", linewidth=2)
    ax.set_title("Daily Tokens + Moving Average")
    ax.set_ylabel("tokens")
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend()
    return _as_png_base64(fig)


def _latency_chart(lat_df: pd.DataFrame) -> str:
    if lat_df.empty:
        return ""
    top = lat_df.head(12).copy()
    labels = [f"{p}/{m}" for p, m in zip(top["provider"], top["model"])]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(top))
    ax.bar(x, top["p50_duration_ms"], label="p50")
    ax.bar(x, top["p95_duration_ms"], alpha=0.7, label="p95")
    ax.set_title("Model Latency Percentiles")
    ax.set_ylabel("ms")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend()
    return _as_png_base64(fig)


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return "$0.00"


def render_html_report(
    output_path: str | Path,
    *,
    generated_at: datetime,
    summary: dict,
    forecast: dict,
    latency_df: pd.DataFrame,
    cost_df: pd.DataFrame,
    ma_df: pd.DataFrame,
    anomalies_df: pd.DataFrame,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    tokens_img = _tokens_ma_chart(ma_df)
    latency_img = _latency_chart(latency_df)

    summary_rows = {
        "total_runs": summary.get("total_runs", 0),
        "ok_rate": f"{summary.get('ok_rate', 0) * 100:.1f}%",
        "total_tokens": f"{summary.get('total_tokens', 0):,.0f}",
        "estimated_cost": _fmt_money(summary.get("estimated_cost", 0.0)),
    }

    html = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OpenClaw Telemetry Forecast Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #1f2937; }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ margin-top: 28px; font-size: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px; background: #f9fafb; }}
    .k {{ font-size: 12px; color: #6b7280; }}
    .v {{ font-size: 22px; font-weight: 700; margin-top: 6px; }}
    .meta {{ color: #6b7280; margin: 6px 0 16px 0; font-size: 13px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; }}
    .warn {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 10px; border-radius: 6px; }}
    .ok {{ background: #ecfdf5; border-left: 4px solid #10b981; padding: 10px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>OpenClaw Telemetry Forecast Report</h1>
  <div class="meta">generated: {generated_at.isoformat()}</div>

  <div class="grid">
    <div class="card"><div class="k">runs</div><div class="v">{summary_rows['total_runs']}</div></div>
    <div class="card"><div class="k">ok rate</div><div class="v">{summary_rows['ok_rate']}</div></div>
    <div class="card"><div class="k">total tokens</div><div class="v">{summary_rows['total_tokens']}</div></div>
    <div class="card"><div class="k">estimated cost</div><div class="v">{summary_rows['estimated_cost']}</div></div>
  </div>

  <h2>Month-End Forecast</h2>
  <div class="card">
    <div>lookback: <b>{forecast.get('lookback_days', 14)}d</b>, elapsed: <b>{forecast.get('days_elapsed', 0)}</b>, remaining: <b>{forecast.get('days_remaining', 0)}</b></div>
    <div style="margin-top:6px;">forecast tokens: <b>{forecast.get('month_tokens_forecast', 0):,.0f}</b></div>
    <div>forecast cost: <b>{_fmt_money(forecast.get('month_cost_forecast', 0.0))}</b></div>
  </div>

  <h2>Token Trend</h2>
  {f'<img src="data:image/png;base64,{tokens_img}" alt="tokens" />' if tokens_img else '<div class="warn">No token trend data.</div>'}

  <h2>Latency Percentiles (p50/p95)</h2>
  {f'<img src="data:image/png;base64,{latency_img}" alt="latency" />' if latency_img else '<div class="warn">No latency data.</div>'}

  <h2>Model Cost Summary</h2>
  {cost_df.head(30).to_html(index=False, border=0) if not cost_df.empty else '<div class="warn">No cost rows.</div>'}

  <h2>Anomaly Detection</h2>
  {anomalies_df.to_html(index=False, border=0) if not anomalies_df.empty else '<div class="ok">No anomaly found in current window.</div>'}

  <h2>Latency Table</h2>
  {latency_df.head(30).to_html(index=False, border=0) if not latency_df.empty else '<div class="warn">No latency rows.</div>'}
</body>
</html>
"""

    out.write_text(html, encoding="utf-8")
    return out
