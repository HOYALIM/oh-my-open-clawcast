from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaResult:
    provider: str
    model: str
    auth_mode: str
    limit_tokens: Optional[int]
    used_tokens: Optional[int]
    remaining_tokens: Optional[int]
    confidence: str  # snapshot | cached | manual
    updated_at: str


@dataclass(frozen=True)
class QuotaOverride:
    limit_tokens: int
    used_tokens: int = 0
    updated_at: Optional[str] = None


def _key(provider: str, model: str, auth_mode: str) -> str:
    return f"{provider}/{model}|{auth_mode}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _parse_override(raw: dict) -> Optional[QuotaOverride]:
    try:
        limit = int(raw.get("limit_tokens", raw.get("limit", 0)))
        used = int(raw.get("used_tokens", raw.get("used", 0)))
    except Exception:
        return None
    if limit <= 0:
        return None
    return QuotaOverride(limit_tokens=limit, used_tokens=max(used, 0), updated_at=raw.get("updated_at"))


class QuotaResolver:
    """Resolve quota with fallback order: snapshot(file) -> cache -> manual(file)."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: int = 300,
        live_file: str | None = None,
        manual_file: str | None = None,
    ):
        self._cache_ttl_seconds = cache_ttl_seconds
        self._live_file = live_file
        self._manual_file = manual_file
        self._cache: dict[str, tuple[QuotaResult, float]] = {}

    def _match_override(
        self,
        overrides: dict,
        provider: str,
        model: str,
        auth_mode: str,
    ) -> Optional[QuotaOverride]:
        direct = overrides.get(_key(provider, model, auth_mode))
        if isinstance(direct, dict):
            parsed = _parse_override(direct)
            if parsed:
                return parsed

        per_model = overrides.get(f"{provider}/{model}")
        if isinstance(per_model, dict):
            parsed = _parse_override(per_model)
            if parsed:
                return parsed

        model_only = overrides.get(model)
        if isinstance(model_only, dict):
            parsed = _parse_override(model_only)
            if parsed:
                return parsed

        return None

    def _live_lookup(self, provider: str, model: str, auth_mode: str) -> Optional[QuotaResult]:
        live_raw = _parse_json(self._live_file)
        override = self._match_override(live_raw, provider=provider, model=model, auth_mode=auth_mode)
        if not override:
            return None
        remaining = max(override.limit_tokens - override.used_tokens, 0)
        updated = override.updated_at or _utc_now_iso()
        result = QuotaResult(
            provider=provider,
            model=model,
            auth_mode=auth_mode,
            limit_tokens=override.limit_tokens,
            used_tokens=override.used_tokens,
            remaining_tokens=remaining,
            confidence="snapshot",
            updated_at=updated,
        )
        logger.info("quota resolved from snapshot source for %s/%s (%s)", provider, model, auth_mode)
        return result

    def _cache_lookup(self, provider: str, model: str, auth_mode: str) -> Optional[QuotaResult]:
        k = _key(provider, model, auth_mode)
        hit = self._cache.get(k)
        if not hit:
            return None
        cached, ts = hit
        if (time.time() - ts) > self._cache_ttl_seconds:
            return None
        return QuotaResult(
            provider=cached.provider,
            model=cached.model,
            auth_mode=cached.auth_mode,
            limit_tokens=cached.limit_tokens,
            used_tokens=cached.used_tokens,
            remaining_tokens=cached.remaining_tokens,
            confidence="cached",
            updated_at=cached.updated_at,
        )

    def _manual_lookup(self, provider: str, model: str, auth_mode: str) -> Optional[QuotaResult]:
        manual_raw = _parse_json(self._manual_file)
        override = self._match_override(manual_raw, provider=provider, model=model, auth_mode=auth_mode)
        if not override:
            return None
        remaining = max(override.limit_tokens - override.used_tokens, 0)
        updated = override.updated_at or _utc_now_iso()
        result = QuotaResult(
            provider=provider,
            model=model,
            auth_mode=auth_mode,
            limit_tokens=override.limit_tokens,
            used_tokens=override.used_tokens,
            remaining_tokens=remaining,
            confidence="manual",
            updated_at=updated,
        )
        logger.info("quota resolved from manual source for %s/%s (%s)", provider, model, auth_mode)
        return result

    def resolve(self, provider: str, model: str, auth_mode: str = "api") -> Optional[QuotaResult]:
        live = self._live_lookup(provider=provider, model=model, auth_mode=auth_mode)
        if live:
            self._cache[_key(provider, model, auth_mode)] = (live, time.time())
            return live

        cached = self._cache_lookup(provider=provider, model=model, auth_mode=auth_mode)
        if cached:
            logger.info("quota resolved from cache for %s/%s (%s)", provider, model, auth_mode)
            return cached

        manual = self._manual_lookup(provider=provider, model=model, auth_mode=auth_mode)
        if manual:
            return manual
        return None

    def resolve_all(self, keys: list[tuple[str, str, str]]) -> list[QuotaResult]:
        out: list[QuotaResult] = []
        for provider, model, auth_mode in keys:
            result = self.resolve(provider=provider, model=model, auth_mode=auth_mode)
            if result:
                out.append(result)
        return out
