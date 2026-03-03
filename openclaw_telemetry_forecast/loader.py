from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"


def resolve_openclaw_dir(base: Optional[str] = None) -> Path:
    if base:
        return Path(base)
    for env_name in ("OPENCLAW_STATE_DIR", "CLAWDBOT_STATE_DIR", "OPENCLAW_DIR"):
        val = os.environ.get(env_name)
        if val:
            return Path(val)
    return DEFAULT_OPENCLAW_DIR


def _read_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not filepath.exists():
        return out
    with filepath.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
    return out


def _ts_to_datetime(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, (int, float)) or not ts:
        return None
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def empty_cron_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "ts_epoch_ms",
            "job_id",
            "run_id",
            "status",
            "error",
            "summary",
            "duration_ms",
            "model",
            "provider",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
            "delivery_status",
            "delivery_error",
            "session_id",
        ]
    )


def load_cron_runs(openclaw_dir: Optional[str] = None, job_id: Optional[str] = None) -> pd.DataFrame:
    base = resolve_openclaw_dir(openclaw_dir)
    runs_dir = base / "cron" / "runs"
    if not runs_dir.exists():
        return empty_cron_df()

    files = sorted(runs_dir.glob("*.jsonl"))
    if job_id:
        target = runs_dir / f"{job_id}.jsonl"
        files = [target] if target.exists() else []

    rows: List[Dict[str, Any]] = []
    for fp in files:
        default_job_id = fp.stem
        for entry in _read_jsonl(fp):
            if entry.get("action") != "finished":
                continue
            ts = entry.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            usage = entry.get("usage") or {}
            rows.append(
                {
                    "timestamp": _ts_to_datetime(ts),
                    "ts_epoch_ms": ts,
                    "job_id": entry.get("jobId", default_job_id),
                    "run_id": entry.get("runId"),
                    "status": entry.get("status"),
                    "error": entry.get("error"),
                    "summary": entry.get("summary"),
                    "duration_ms": entry.get("durationMs"),
                    "model": entry.get("model"),
                    "provider": entry.get("provider"),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "cache_read_tokens": usage.get("cache_read_tokens"),
                    "cache_write_tokens": usage.get("cache_write_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "delivery_status": entry.get("deliveryStatus"),
                    "delivery_error": entry.get("deliveryError"),
                    "session_id": entry.get("sessionId"),
                }
            )

    if not rows:
        return empty_cron_df()

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    for col in (
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["status"] = df["status"].astype("category")
    if "delivery_status" in df.columns:
        df["delivery_status"] = df["delivery_status"].astype("category")

    return df
