"""Cost estimate (pure integer math) and the conservative token estimate."""

import pytest

from eventssound.application.llm import (
    LlmValidationError,
    TokenUsage,
    estimate_cost_micro_usd,
    estimate_tokens,
)

MILLION = 1_000_000


def test_priced_model_costs_tokens_times_price_per_million() -> None:
    assert estimate_cost_micro_usd(TokenUsage(2_000, 0), MILLION, 0) == 2_000


def test_input_and_output_are_priced_separately() -> None:
    usage = TokenUsage(1_000, 500)

    assert estimate_cost_micro_usd(usage, 150_000, 600_000) == 150 + 300


def test_free_model_costs_zero_but_usage_still_counts() -> None:
    usage = TokenUsage(500, 100)

    assert estimate_cost_micro_usd(usage, 0, 0) == 0
    assert usage.total == 600


def test_cost_rounds_up_per_side_so_it_is_never_underestimated() -> None:
    # 1 token at 1 micro-USD per million is 1e-6 micro-USD: rounds up to 1 per side.
    assert estimate_cost_micro_usd(TokenUsage(1, 1), 1, 1) == 2


def test_zero_tokens_cost_zero_even_with_a_price() -> None:
    assert estimate_cost_micro_usd(TokenUsage(0, 0), MILLION, MILLION) == 0


@pytest.mark.parametrize("bad", [-1, 1.5, True, "1", None])
@pytest.mark.parametrize("side", ["input_price", "output_price"])
def test_prices_must_be_non_negative_ints(side: str, bad: object) -> None:
    prices: dict[str, object] = {"input_price": 1, "output_price": 1, side: bad}

    with pytest.raises(LlmValidationError, match=side):
        estimate_cost_micro_usd(TokenUsage(1, 1), **prices)  # type: ignore[arg-type]


def test_usage_must_be_a_token_usage() -> None:
    with pytest.raises(LlmValidationError, match="usage"):
        estimate_cost_micro_usd((1, 1), 1, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("chars", "tokens"), [(0, 1), (1, 1), (4, 1), (5, 2), (400, 100), (401, 101)]
)
def test_token_estimate_is_ceil_chars_over_four_and_never_zero(chars: int, tokens: int) -> None:
    assert estimate_tokens(chars) == tokens


@pytest.mark.parametrize("bad", [-1, 1.5, True, None])
def test_token_estimate_rejects_non_int_or_negative(bad: object) -> None:
    with pytest.raises(LlmValidationError, match="chars"):
        estimate_tokens(bad)  # type: ignore[arg-type]
