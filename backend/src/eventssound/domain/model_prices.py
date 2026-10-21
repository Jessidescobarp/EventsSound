"""Per-model LLM prices, in micro-USD per million tokens.

Explicit table: the configured environment model keeps the environment price pair, any other
model is priced only when it is a free one (the OpenRouter `:free` suffix, exact and lowercase),
and everything else has no price. The admin may only select models that have one.
"""

from dataclasses import dataclass
from typing import Protocol

FREE_SUFFIX = ":free"


class PriceSettings(Protocol):
    llm_model: str
    llm_input_price_micro_usd_per_mtok: int
    llm_output_price_micro_usd_per_mtok: int


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_micro_usd_per_mtok: int
    output_micro_usd_per_mtok: int
    free: bool


def is_free_model(model: str) -> bool:
    return model.endswith(FREE_SUFFIX)


def price_for(model: str, settings: PriceSettings) -> ModelPrice | None:
    """The price of `model`, or None when it is neither the environment model nor a free one."""
    if model == settings.llm_model:
        pair = (
            settings.llm_input_price_micro_usd_per_mtok,
            settings.llm_output_price_micro_usd_per_mtok,
        )
        return ModelPrice(*pair, free=is_free_model(model) and not any(pair))
    if is_free_model(model):
        return ModelPrice(0, 0, True)
    return None
