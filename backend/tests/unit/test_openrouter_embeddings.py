"""OpenRouter /embeddings adapter over httpx.MockTransport: no network, ever."""

import logging
import traceback

import httpx
import pytest
from http_fakes import BODY_SENTINEL, KEY, FakeClock, Script, raw, reply

from eventssound.adapters.embeddings.openrouter import OpenRouterEmbeddingProvider
from eventssound.adapters.openrouter_http import DEFAULT_BASE_URL
from eventssound.adapters.secret import SecretError
from eventssound.application.embeddings import EmbeddingDimensionMismatch
from eventssound.application.llm import (
    LlmAuthError,
    LlmBadResponse,
    LlmError,
    LlmRateLimited,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    TokenUsage,
)

MODEL = "vendor/embed-model"  # a placeholder id: the real free model id is unverified
DIM = 4


def vector(seed: float) -> list[float]:
    return [seed, seed + 1, seed + 2, seed + 3]


def ok(
    vectors: list[list[float]], usage: object = None, model: object = "vendor/embed-model"
) -> dict:
    payload: dict[str, object] = {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
        ],
    }
    payload["usage"] = {"prompt_tokens": 7, "total_tokens": 7} if usage is None else usage
    return payload


def provider_for(
    *items: object, dimensions: int = DIM, **kwargs: object
) -> tuple[OpenRouterEmbeddingProvider, Script, FakeClock]:
    script = Script(*items)  # type: ignore[arg-type]
    clock = FakeClock()
    options: dict[str, object] = {
        "transport": script.transport,
        "sleep": clock.sleep,
        "clock": clock,
        "jitter": lambda: 1.0,
    }
    options.update(kwargs)
    provider = OpenRouterEmbeddingProvider(KEY, MODEL, dimensions, **options)  # type: ignore[arg-type]
    return provider, script, clock


class TestSuccess:
    def test_returns_vectors_in_input_order_with_reported_usage(self) -> None:
        provider, _, _ = provider_for(reply(ok([vector(1), vector(10)])))

        result = provider.embed(["uno", "dos"])

        assert result.vectors == ((1.0, 2.0, 3.0, 4.0), (10.0, 11.0, 12.0, 13.0))
        assert result.usage == TokenUsage(7, 0)
        assert result.model == "vendor/embed-model"
        assert result.dimensions == DIM

    def test_data_is_reordered_by_index(self) -> None:
        payload = ok([vector(1), vector(10), vector(20)])
        payload["data"] = [payload["data"][2], payload["data"][0], payload["data"][1]]  # type: ignore[index]
        provider, _, _ = provider_for(reply(payload))

        result = provider.embed(["a", "b", "c"])

        assert [v[0] for v in result.vectors] == [1.0, 10.0, 20.0]

    def test_request_shape_and_key_placement(self) -> None:
        provider, script, _ = provider_for(reply(ok([vector(1), vector(2)])))

        provider.embed(["hola", "mundo"], timeout_s=5)

        sent = script.requests[0]
        assert (sent.method, str(sent.url)) == ("POST", f"{DEFAULT_BASE_URL}/embeddings")
        assert script.body() == {"model": MODEL, "input": ["hola", "mundo"]}
        assert sent.headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in str(sent.url) and KEY.encode() not in sent.content

    def test_empty_input_returns_an_empty_result_without_a_request(self) -> None:
        provider, script, _ = provider_for()

        result = provider.embed([])

        assert result.vectors == () and result.usage.total == 0 and result.model == MODEL
        assert script.calls == 0

    def test_integer_components_and_missing_usage_are_handled(self) -> None:
        payload = ok([[1, 2, 3, 4]], usage="omit")
        del payload["usage"]
        provider, _, _ = provider_for(reply(payload))

        result = provider.embed(["abcdefgh"])

        assert result.vectors == ((1.0, 2.0, 3.0, 4.0),)
        assert result.usage == TokenUsage(2, 0, estimated=True)

    def test_invalid_usage_is_estimated_and_unusable_model_falls_back(self) -> None:
        bad_usages: list[object] = [{}, {"prompt_tokens": -1}, {"prompt_tokens": True}, [7], "7"]
        for usage in bad_usages:
            provider, _, _ = provider_for(reply(ok([vector(1)], usage=usage)))

            assert provider.embed(["abcdefgh"]).usage == TokenUsage(2, 0, estimated=True), usage

        provider, _, _ = provider_for(reply(ok([vector(1)], model=None)))
        assert provider.embed(["x"]).model == MODEL


class TestDimensionAndStructure:
    def test_wrong_dimension_is_rejected_with_the_specific_error(self) -> None:
        provider, _, _ = provider_for(reply(ok([[1.0, 2.0, 3.0]])))

        with pytest.raises(EmbeddingDimensionMismatch):
            provider.embed(["x"])

    def test_one_wrong_vector_among_good_ones_rejects_the_whole_batch(self) -> None:
        provider, _, _ = provider_for(reply(ok([vector(1), [1.0] * 5])))

        with pytest.raises(EmbeddingDimensionMismatch):
            provider.embed(["a", "b"])

    def test_a_different_number_of_vectors_than_inputs_is_a_bad_response(self) -> None:
        for inputs in (["a", "b", "c"], ["a"]):
            provider, _, _ = provider_for(reply(ok([vector(1), vector(2)])))

            with pytest.raises(LlmBadResponse) as exc:
                provider.embed(inputs)

            assert not isinstance(exc.value, EmbeddingDimensionMismatch)

    def test_malformed_data_raises_bad_response_never_key_or_type_errors(self) -> None:
        good = [1, 2, 3, 4]
        bad_data: list[object] = [
            None,
            "x",
            [1],
            [{"index": 0}],
            [{"embedding": good}],
            [{"index": "0", "embedding": good}],
            [{"index": True, "embedding": good}],
            [{"index": 1, "embedding": good}],
            [{"index": -1, "embedding": good}],
            [{"index": 0, "embedding": "AAAA"}],
            [{"index": 0, "embedding": [1, 2, 3, "4"]}],
            [{"index": 0, "embedding": [1, 2, 3, True]}],
        ]
        for data in bad_data:
            payload = ok([vector(1)])
            payload["data"] = data
            provider, script, _ = provider_for(reply(payload))

            with pytest.raises(LlmBadResponse):
                provider.embed(["x"])

            assert script.calls == 1, data

        payload = ok([vector(1)])
        del payload["data"]
        provider, _, _ = provider_for(reply(payload))
        with pytest.raises(LlmBadResponse):
            provider.embed(["x"])

    def test_duplicate_indexes_are_rejected(self) -> None:
        payload = ok([vector(1), vector(2)])
        payload["data"][1]["index"] = 0  # type: ignore[index]
        provider, _, _ = provider_for(reply(payload))

        with pytest.raises(LlmBadResponse):
            provider.embed(["a", "b"])

    def test_non_finite_components_are_rejected(self) -> None:
        bad_numbers = ["NaN", "-Infinity", "1e999", "1" + "0" * 399, str(2**53), "true"]
        for bad in bad_numbers:
            body = b'{"data": [{"index": 0, "embedding": [1, 2, 3, ' + bad.encode() + b"]}]}"
            provider, _, _ = provider_for(raw(body))

            with pytest.raises(LlmBadResponse):
                provider.embed(["x"])

    def test_non_object_or_non_json_bodies_are_bad_responses(self) -> None:
        for content in (b"", b"nope", b"[1]", b"\xff\xfe", b"[" * 200_000, b'{"data": [{"ind'):
            provider, _, _ = provider_for(raw(content))

            with pytest.raises(LlmBadResponse):
                provider.embed(["x"])

    def test_oversized_body_is_rejected(self) -> None:
        provider, _, _ = provider_for(
            raw(b"x" * 200, **{"content-length": "200"}), max_response_bytes=100
        )

        with pytest.raises(LlmBadResponse):
            provider.embed(["x"])


class TestErrorMappingAndRetries:
    def test_same_mapping_and_retry_policy_as_the_chat_adapter(self) -> None:
        cases: list[tuple[httpx.Response | Exception, type[LlmError], int]] = [
            (raw(b"{}", 403), LlmAuthError, 1),
            (raw(b"{}", 402), LlmUnavailable, 1),
            (raw(b"{}", 429, **{"retry-after": "9"}), LlmRateLimited, 1),
            (raw(b"{}", 429), LlmRateLimited, 3),
            (raw(b"{}", 500), LlmUnavailable, 1),
            (raw(b"{}", 503), LlmUnavailable, 3),
            (raw(b"{}", 400), LlmBadResponse, 1),
            (httpx.ReadTimeout("t"), LlmTimeout, 1),
            (httpx.ConnectError("c"), LlmUnavailable, 3),
            (reply({"error": {"code": 429}}), LlmRateLimited, 1),
        ]
        for item, error, calls in cases:
            provider, script, _ = provider_for(*[item] * calls)

            with pytest.raises(error):
                provider.embed(["x"])

            assert script.calls == calls, item

    def test_transient_failure_then_success(self) -> None:
        provider, script, clock = provider_for(raw(b"x", 503), reply(ok([vector(1)])))

        assert provider.embed(["x"]).dimensions == DIM
        assert (script.calls, clock.sleeps) == (2, [0.5])


class TestSecretHygiene:
    FAILURES = [
        raw(f'{{"error": "{KEY} {BODY_SENTINEL}"}}'.encode(), 401),
        raw(f'{{"error": "{KEY} {BODY_SENTINEL}"}}'.encode(), 500),
        raw(f"{KEY} {BODY_SENTINEL}".encode(), 200),
        reply(
            {"data": [{"index": 0, "embedding": [1, 2, 3]}], "error": {"message": BODY_SENTINEL}}
        ),
        httpx.ConnectError(f"{KEY} {BODY_SENTINEL}"),
        httpx.ReadTimeout(f"{KEY} {BODY_SENTINEL}"),
        reply(ok([[1.0, 2.0]])),
    ]

    def test_no_error_path_leaks_the_key_or_provider_text(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        for index, item in enumerate(self.FAILURES):
            caplog.clear()
            provider, _, _ = provider_for(*([item] * 3))

            with pytest.raises(LlmError) as exc:
                provider.embed(["x"])

            surfaces = [
                str(exc.value),
                repr(exc.value),
                "".join(traceback.format_exception(exc.value)),
                repr(provider),
            ]
            surfaces += [r.getMessage() + str(r.args) + (r.exc_text or "") for r in caplog.records]
            joined = "\n".join(surfaces)
            assert caplog.records, "the adapter must log, otherwise this check is vacuous"
            assert KEY not in joined and "SENTINEL-9f3a" not in joined, index
            assert BODY_SENTINEL not in joined, index

    def test_repr_shows_model_and_dimensions_but_not_the_key(self) -> None:
        provider, _, _ = provider_for()

        assert MODEL in repr(provider) and "4" in repr(provider)
        assert KEY not in repr(provider) and KEY not in repr(vars(provider))


class TestConstruction:
    def test_invalid_constructor_arguments_are_rejected(self) -> None:
        for key in (None, "", "has space", 3):
            with pytest.raises(SecretError):
                OpenRouterEmbeddingProvider(key, MODEL, DIM)
        for model in ("", "has space", None, "x" * 121):
            with pytest.raises(LlmValidationError, match="model"):
                OpenRouterEmbeddingProvider(KEY, model, DIM)  # type: ignore[arg-type]
        for dimensions in (0, 2001, 1.5, True, None):
            with pytest.raises(LlmValidationError, match="dimensions"):
                OpenRouterEmbeddingProvider(KEY, MODEL, dimensions)  # type: ignore[arg-type]
        for limit in (0, 100_001, 1.5, True):
            with pytest.raises(LlmValidationError, match="max_input_chars"):
                OpenRouterEmbeddingProvider(KEY, MODEL, DIM, max_input_chars=limit)  # type: ignore[arg-type]

    def test_over_long_inputs_are_rejected_before_any_request(self) -> None:
        provider, script, _ = provider_for(max_input_chars=10)

        with pytest.raises(LlmValidationError, match="characters"):
            provider.embed(["x" * 11])
        with pytest.raises(LlmValidationError, match="texts"):
            provider.embed("not a list")  # type: ignore[arg-type]
        assert script.calls == 0

    def test_blank_inputs_are_rejected_before_any_request(self) -> None:
        provider, script, _ = provider_for()

        for blank in ("", "  "):
            with pytest.raises(LlmValidationError, match="blank"):
                provider.embed(["fine", blank])

        assert script.calls == 0

    def test_no_model_id_is_hard_coded_as_a_default(self) -> None:
        import inspect

        signature = inspect.signature(OpenRouterEmbeddingProvider.__init__)

        assert signature.parameters["model"].default is inspect.Parameter.empty
        assert signature.parameters["dimensions"].default is inspect.Parameter.empty

    def test_timeout_argument_is_validated(self) -> None:
        provider, script, _ = provider_for()

        for bad in (0, -1, float("nan"), True, "5", 301):
            with pytest.raises(LlmValidationError, match="timeout_s"):
                provider.embed(["x"], timeout_s=bad)  # type: ignore[arg-type]
        assert script.calls == 0

    def test_close_and_context_manager(self) -> None:
        script = Script(reply(ok([vector(1)])))
        with OpenRouterEmbeddingProvider(KEY, MODEL, DIM, transport=script.transport) as provider:
            provider.embed(["x"])

        with pytest.raises(RuntimeError):
            provider.embed(["x"])
