"""Per-model LLM prices, in micro-USD per million tokens.

Explicit table: the configured environment model keeps the environment price pair, any other
model is priced when it is a free one (the OpenRouter `:free` suffix, exact and lowercase) or
when `LLM_MODEL_PRICES` declares its price, and everything else has no price. The admin may only
select models that have one.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from eventssound.domain.agent_config import MODEL_ID_PATTERN

FREE_SUFFIX = ":free"
# Sanity ceiling for a declared price (1,000 USD per million tokens): rejects typos and unit mixups.
MAX_PRICE_MICRO_USD_PER_MTOK = 1_000_000_000
MAX_PRICED_MODELS = 50


class PriceSettings(Protocol):
    llm_model: str
    llm_input_price_micro_usd_per_mtok: int
    llm_output_price_micro_usd_per_mtok: int
    llm_model_prices: Mapping[str, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_micro_usd_per_mtok: int
    output_micro_usd_per_mtok: int
    free: bool


def is_free_model(model: str) -> bool:
    return model.endswith(FREE_SUFFIX)


def _price(value: object, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_PRICE_MICRO_USD_PER_MTOK
    ):
        raise ValueError(
            f"LLM_MODEL_PRICES {field} must be an integer from 0 to {MAX_PRICE_MICRO_USD_PER_MTOK}"
        )
    return value


def parse_model_prices(raw: object) -> dict[str, tuple[int, int]]:
    """`{"<model-id>": {"input": int, "output": int}}` (JSON text or a mapping) to a price table.

    Strict and fail closed. Messages never echo the raw text or any value, only field names.
    """
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("LLM_MODEL_PRICES must be a valid JSON object") from None
    if not isinstance(raw, Mapping) or len(raw) > MAX_PRICED_MODELS:
        raise ValueError(
            f"LLM_MODEL_PRICES must be an object of at most {MAX_PRICED_MODELS} models"
        )
    table: dict[str, tuple[int, int]] = {}
    for model, entry in raw.items():
        if not isinstance(model, str) or not MODEL_ID_PATTERN.fullmatch(model):
            raise ValueError("LLM_MODEL_PRICES has an invalid model id")
        if not isinstance(entry, Mapping) or set(entry) != {"input", "output"}:
            raise ValueError('LLM_MODEL_PRICES entries must be {"input": int, "output": int}')
        table[model] = (_price(entry["input"], "input"), _price(entry["output"], "output"))
    return table


def price_for(model: str, settings: PriceSettings) -> ModelPrice | None:
    """The price of `model`, or None when it is not the environment model, free or declared."""
    if model == settings.llm_model:
        pair = (
            settings.llm_input_price_micro_usd_per_mtok,
            settings.llm_output_price_micro_usd_per_mtok,
        )
        return ModelPrice(*pair, free=is_free_model(model) and not any(pair))
    declared = settings.llm_model_prices.get(model)
    if declared is not None:
        return ModelPrice(*declared, free=is_free_model(model) and not any(declared))
    if is_free_model(model):
        return ModelPrice(0, 0, True)
    return None
