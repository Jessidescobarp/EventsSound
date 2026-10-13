"""Deterministic hash-based fake embedder."""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.application.llm import LlmValidationError


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def embed(provider: FakeEmbeddingProvider, *texts: str) -> tuple[tuple[float, ...], ...]:
    return provider.embed(list(texts)).vectors


def test_vectors_have_the_configured_dimension_and_unit_norm() -> None:
    provider = FakeEmbeddingProvider(dimensions=64)

    vectors = embed(provider, "parlante activo 15 pulgadas", "maquina de humo", "!!!")

    assert [len(v) for v in vectors] == [64, 64, 64]
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-9)


def test_default_dimension_is_1024_and_same_text_gives_the_same_vector() -> None:
    assert FakeEmbeddingProvider().embed(["x"]).dimensions == 1024
    a = embed(FakeEmbeddingProvider(dimensions=32), "Luces LED")
    b = embed(FakeEmbeddingProvider(dimensions=32), "Luces LED")

    assert a == b


def test_vectors_are_stable_across_processes() -> None:
    code = (
        "from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider as F;"
        "print(F(dimensions=8).embed(['parlante activo']).vectors[0])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
            env={"PYTHONHASHSEED": "random", "PYTHONPATH": "src", "SYSTEMROOT": "C:/Windows"},
        ).stdout

    first, second = run(), run()

    assert first == second
    assert str(embed(FakeEmbeddingProvider(dimensions=8), "parlante activo")[0]) == first.strip()


def test_texts_sharing_tokens_are_more_similar_than_texts_sharing_none() -> None:
    first, second, third = embed(
        FakeEmbeddingProvider(),
        "parlante activo 15 pulgadas",
        "parlante potente",
        "maquina de humo",
    )

    assert cosine(first, second) > cosine(first, third)
    assert cosine(first, third) < 0.2


def test_case_accents_word_order_and_punctuation_do_not_matter() -> None:
    a, b = embed(FakeEmbeddingProvider(), "Amplificación Básica", "amplificacion basica")
    c, d = embed(FakeEmbeddingProvider(), "luces, led!", "led luces")

    assert a == b
    assert c == d


def test_aliases_make_a_synonym_retrievable_offline() -> None:
    plain = FakeEmbeddingProvider()
    aliased = FakeEmbeddingProvider(aliases={"amplificacion": "parlante"})
    query, doc = "amplificacion", "parlante activo"

    assert cosine(*(embed(plain, query, doc))) < 0.01
    assert cosine(*(embed(aliased, query, doc))) > 0.5


def test_text_without_tokens_maps_to_one_fixed_unit_vector() -> None:
    provider = FakeEmbeddingProvider(dimensions=16)
    for text in ("???", "- - -"):
        vector = embed(provider, text)[0]

        assert vector == embed(provider, "!!!")[0]
        assert sum(x * x for x in vector) == pytest.approx(1.0)
        assert vector != embed(provider, "algo real")[0]


def test_a_zero_sum_collision_still_returns_a_unit_vector() -> None:
    # With 1 dimension two tokens with opposite signs may cancel; the result must stay valid.
    provider = FakeEmbeddingProvider(dimensions=1)
    for word in ["a", "b", "c", "d", "e", "f", "g", "h"]:
        for other in ["i", "j", "k", "l", "m", "n"]:
            (vector,) = embed(provider, f"{word} {other}")
            assert vector in {(1.0,), (-1.0,)}


def test_usage_counts_tokens_as_estimated_and_model_is_reported() -> None:
    result = FakeEmbeddingProvider(model="fake-x").embed(["uno dos tres", "cuatro"])

    assert result.model == "fake-x"
    assert result.usage.estimated is True
    assert result.usage.prompt_tokens == 4
    assert result.usage.completion_tokens == 0


def test_empty_input_returns_an_empty_result() -> None:
    result = FakeEmbeddingProvider().embed([])

    assert result.vectors == ()
    assert result.usage.total == 0


def test_constructor_arguments_are_validated() -> None:
    for dimensions in (0, 2001, 1.5, True, None):
        with pytest.raises(LlmValidationError, match="dimensions"):
            FakeEmbeddingProvider(dimensions=dimensions)  # type: ignore[arg-type]
    for aliases in (["a"], {"a": 1}, {1: "a"}, {"": "a"}, "ab"):
        with pytest.raises(LlmValidationError, match="aliases"):
            FakeEmbeddingProvider(aliases=aliases)  # type: ignore[arg-type]


def test_inputs_are_validated_like_the_real_provider() -> None:
    with pytest.raises(LlmValidationError, match="texts"):
        FakeEmbeddingProvider().embed("a string")  # type: ignore[arg-type]
    for blank in ("", "\n\t "):
        with pytest.raises(LlmValidationError, match="blank"):
            FakeEmbeddingProvider().embed(["ok", blank])
