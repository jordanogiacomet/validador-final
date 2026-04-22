from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

LLM_PRICING_ENV = "VALIDATOR_LLM_PRICING_JSON"


@dataclass(frozen=True)
class LLMModelPricing:
    input_per_million_tokens_usd: float
    output_per_million_tokens_usd: float


def load_llm_model_pricing(
    env: Mapping[str, str] | None = None,
) -> dict[str, LLMModelPricing]:
    raw_value = (env or os.environ).get(LLM_PRICING_ENV, "").strip()
    if not raw_value:
        return {}

    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        raise ValueError(f"{LLM_PRICING_ENV} must be a JSON object")

    pricing: dict[str, LLMModelPricing] = {}
    for raw_model, raw_rates in payload.items():
        model = str(raw_model).strip()
        if not model:
            continue
        if not isinstance(raw_rates, dict):
            raise ValueError(f"{LLM_PRICING_ENV}.{model} must be a JSON object")

        input_rate = _coerce_non_negative_float(
            raw_rates.get("input_per_million_tokens_usd", 0.0)
        )
        output_rate = _coerce_non_negative_float(
            raw_rates.get("output_per_million_tokens_usd", 0.0)
        )
        pricing[model] = LLMModelPricing(
            input_per_million_tokens_usd=input_rate,
            output_per_million_tokens_usd=output_rate,
        )
    return pricing


def estimate_llm_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: Mapping[str, LLMModelPricing] | None = None,
) -> float | None:
    normalized_model = model.strip()
    if not normalized_model:
        return None

    resolved_pricing = pricing or load_llm_model_pricing()
    model_pricing = resolved_pricing.get(normalized_model)
    if model_pricing is None:
        return None

    normalized_input_tokens = max(int(input_tokens), 0)
    normalized_output_tokens = max(int(output_tokens), 0)
    input_cost = (
        normalized_input_tokens / 1_000_000
    ) * model_pricing.input_per_million_tokens_usd
    output_cost = (
        normalized_output_tokens / 1_000_000
    ) * model_pricing.output_per_million_tokens_usd
    return round(input_cost + output_cost, 8)


def _coerce_non_negative_float(value: object) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid LLM pricing value: {value!r}") from None
