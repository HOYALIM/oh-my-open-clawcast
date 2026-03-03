from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    output_per_1m: float
    cache_read_per_1m: float = 0.0
    cache_write_per_1m: float = 0.0


# Example baseline table. Replace with your real contracted pricing.
DEFAULT_MODEL_RATES: Dict[str, ModelRate] = {
    "openai/gpt-4o": ModelRate(input_per_1m=5.0, output_per_1m=15.0, cache_read_per_1m=1.25),
    "openai/gpt-4.1": ModelRate(input_per_1m=2.0, output_per_1m=8.0),
    "openai/gpt-4.1-mini": ModelRate(input_per_1m=0.4, output_per_1m=1.6),
    "anthropic/claude-sonnet-4-5": ModelRate(input_per_1m=3.0, output_per_1m=15.0),
    "anthropic/claude-opus-4-6": ModelRate(input_per_1m=15.0, output_per_1m=75.0),
    "google/gemini-2.5-pro": ModelRate(input_per_1m=3.5, output_per_1m=10.5),
}


def resolve_rate(provider: Optional[str], model: Optional[str], rates: Dict[str, ModelRate]) -> Optional[ModelRate]:
    p = (provider or "").strip()
    m = (model or "").strip()

    if p and m:
        exact = f"{p}/{m}"
        if exact in rates:
            return rates[exact]

    if m and m in rates:
        return rates[m]

    if p and p in rates:
        return rates[p]

    return None
