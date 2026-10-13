"""Embedding port DTOs and input normalisation."""

import math

import pytest

from eventssound.application.embeddings import (
    EmbeddingDimensionMismatch,
    EmbeddingResult,
    normalize_texts,
)
from eventssound.application.llm import LlmBadResponse, LlmError, LlmValidationError, TokenUsage

USAGE = TokenUsage(3, 0)


class TestEmbeddingResult:
    def test_coerces_to_tuples_and_floats_and_is_hashable(self) -> None:
        result = EmbeddingResult(vectors=[[1, 0.5], [0.25, 2]], usage=USAGE, model="m")

        assert result.vectors == ((1.0, 0.5), (0.25, 2.0))
        assert all(type(x) is float for v in result.vectors for x in v)
        assert result.dimensions == 2
        assert hash(result) == hash(EmbeddingResult(((1, 0.5), (0.25, 2)), USAGE, "m"))
        assert EmbeddingResult((), USAGE, "m").dimensions == 0

    def test_integers_just_below_2_pow_53_are_accepted(self) -> None:
        result = EmbeddingResult([[2**53 - 1, -(2**53 - 1)]], USAGE, "m")

        assert result.vectors == ((float(2**53 - 1), float(-(2**53 - 1))),)

    def test_invalid_vectors_are_rejected(self) -> None:
        invalid: list[object] = [
            "ab",
            None,
            ["ab"],
            [None],
            [[]],
            [[1.0], [1.0, 2.0]],
            [[True]],
            [["1"]],
            [[math.nan]],
            [[1.0, -math.inf]],
            [[1 << 1500]],
            [[2**53]],
        ]
        for vectors in invalid:
            with pytest.raises(LlmValidationError, match="vectors"):
                EmbeddingResult(vectors, USAGE, "m")  # type: ignore[arg-type]

    def test_usage_and_model_are_validated(self) -> None:
        with pytest.raises(LlmValidationError, match="usage"):
            EmbeddingResult(((1.0,),), (1, 0), "m")  # type: ignore[arg-type]
        with pytest.raises(LlmValidationError, match="model"):
            EmbeddingResult(((1.0,),), USAGE, "")


class TestNormalizeTexts:
    def test_returns_a_tuple_of_the_same_strings_and_allows_empty_input(self) -> None:
        assert normalize_texts(["a", "bb"]) == ("a", "bb")
        assert normalize_texts(iter(["a"])) == ("a",)
        assert normalize_texts([]) == ()

    def test_a_string_is_never_an_iterable_of_texts(self) -> None:
        for texts in ("abc", b"abc", None, 3, ["ok", None], [b"x"]):
            with pytest.raises(LlmValidationError, match="texts"):
                normalize_texts(texts)  # type: ignore[arg-type]

    def test_empty_and_blank_strings_are_rejected_with_a_typed_error(self) -> None:
        for blank in ("", " ", "\t \n"):
            with pytest.raises(LlmValidationError, match="blank"):
                normalize_texts(["fine", blank])

    def test_count_and_length_are_bounded(self) -> None:
        assert len(normalize_texts(["x"] * 3, max_texts=3)) == 3
        with pytest.raises(LlmValidationError, match="texts"):
            normalize_texts(["x"] * 4, max_texts=3)
        assert normalize_texts(["x" * 5], max_chars=5) == ("xxxxx",)
        with pytest.raises(LlmValidationError, match="characters"):
            normalize_texts(["x" * 6], max_chars=5)


def test_dimension_mismatch_is_a_bad_response_provider_error() -> None:
    error = EmbeddingDimensionMismatch()

    assert isinstance(error, LlmBadResponse) and isinstance(error, LlmError)
    assert "dimension" in str(error)
