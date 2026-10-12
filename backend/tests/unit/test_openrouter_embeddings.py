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

    @pytest.mark.parametrize(
        "usage",
        [{}, {"prompt_tokens": -1}, {"prompt_tokens": True}, {"prompt_tokens": "7"}, [7], "7"],
    )
    def test_invalid_usage_is_estimated(self, usage: object) -> None:
        provider, _, _ = provider_for(reply(ok([vector(1)], usage=usage)))

        assert provider.embed(["abcdefgh"]).usage == TokenUsage(2, 0, estimated=True)

    def test_response_model_falls_back_to_the_configured_one(self) -> None:
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

    def test_dimension_follows_the_constructor_argument(self) -> None:
        provider, _, _ = provider_for(reply(ok([[1.0] * 8])), dimensions=8)

        assert provider.embed(["x"]).dimensions == 8

    def test_fewer_vectors_than_inputs_is_a_bad_response(self) -> None:
        provider, _, _ = provider_for(reply(ok([vector(1), vector(2)])))

        with pytest.raises(LlmBadResponse) as exc:
            provider.embed(["a", "b", "c"])

        assert not isinstance(exc.value, EmbeddingDimensionMismatch)

    def test_more_vectors_than_inputs_is_a_bad_response(self) -> None:
        provider, _, _ = provider_for(reply(ok([vector(1), vector(2)])))

        with pytest.raises(LlmBadResponse):
            provider.embed(["a"])

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.pop("data"),
            lambda p: p.update(data=None),
            lambda p: p.update(data="x"),
            lambda p: p.update(data=[1]),
            lambda p: p.update(data=[{"index": 0}]),
            lambda p: p.update(data=[{"embedding": [1, 2, 3, 4]}]),
            lambda p: p.update(data=[{"index": "0", "embedding": [1, 2, 3, 4]}]),
            lambda p: p.update(data=[{"index": True, "embedding": [1, 2, 3, 4]}]),
            lambda p: p.update(data=[{"index": 1, "embedding": [1, 2, 3, 4]}]),
            lambda p: p.update(data=[{"index": -1, "embedding": [1, 2, 3, 4]}]),
            lambda p: p.update(data=[{"index": 0, "embedding": "AAAA"}]),
            lambda p: p.update(data=[{"index": 0, "embedding": None}]),
            lambda p: p.update(data=[{"index": 0, "embedding": [1, 2, 3, "4"]}]),
            lambda p: p.update(data=[{"index": 0, "embedding": [1, 2, 3, None]}]),
            lambda p: p.update(data=[{"index": 0, "embedding": [1, 2, 3, True]}]),
        ],
        ids=[
            "no-data",
            "null-data",
            "str-data",
            "int-item",
            "no-embedding",
            "no-index",
            "str-index",
            "bool-index",
            "index-gap",
            "negative-index",
            "base64-embedding",
            "null-embedding",
            "str-component",
            "null-component",
            "bool-component",
        ],
    )
    def test_malformed_data_raises_bad_response_never_key_or_type_errors(self, mutate) -> None:  # type: ignore[no-untyped-def]
        payload = ok([vector(1)])
        mutate(payload)
        provider, script, _ = provider_for(reply(payload))

        with pytest.raises(LlmBadResponse):
            provider.embed(["x"])

        assert script.calls == 1

    def test_duplicate_indexes_are_rejected(self) -> None:
        payload = ok([vector(1), vector(2)])
        payload["data"][1]["index"] = 0  # type: ignore[index]
        provider, _, _ = provider_for(reply(payload))

        with pytest.raises(LlmBadResponse):
            provider.embed(["a", "b"])

    @pytest.mark.parametrize(
        "bad",
        [
            "NaN",
            "Infinity",
            "-Infinity",
            "1e999",
            "-1e999",
            "1" + "0" * 399,
            "-" + "9" * 400,
            str(2**53),
            "true",
            "false",
        ],
        ids=[
            "nan",
            "inf",
            "neg-inf",
            "1e999",
            "-1e999",
            "400-digit",
            "neg-400-digit",
            "2-pow-53",
            "true",
            "false",
        ],
    )
    def test_non_finite_components_are_rejected(self, bad: str) -> None:
        body = b'{"data": [{"index": 0, "embedding": [1, 2, 3, ' + bad.encode() + b"]}]}"
        provider, _, _ = provider_for(raw(body))

        with pytest.raises(LlmBadResponse):
            provider.embed(["x"])

    @pytest.mark.parametrize(
        "content",
        [
            b"",
            b"nope",
            b"[1]",
            b"null",
            b"\xff\xfe",
            pytest.param(b"[" * 200_000, id="deeply-nested"),
            b'{"data": [{"ind',
        ],
    )
    def test_non_object_or_non_json_bodies_are_bad_responses(self, content: bytes) -> None:
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
    @pytest.mark.parametrize(
        ("item", "error", "calls"),
        [
            (raw(b"{}", 401), LlmAuthError, 1),
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
        ],
        ids=[
            "401",
            "403",
            "402",
            "429-long",
            "429",
            "500",
            "503",
            "400",
            "timeout",
            "connect",
            "error-in-200",
        ],
    )
    def test_same_mapping_and_retry_policy_as_the_chat_adapter(
        self, item: object, error: type[LlmError], calls: int
    ) -> None:
        provider, script, _ = provider_for(*[item] * calls)

        with pytest.raises(error):
            provider.embed(["x"])

        assert script.calls == calls

    def test_transient_failure_then_success(self) -> None:
        provider, script, clock = provider_for(raw(b"x", 503), reply(ok([vector(1)])))

        assert provider.embed(["x"]).dimensions == DIM
        assert (script.calls, clock.sleeps) == (2, [0.5])

    def test_429_carries_retry_after(self) -> None:
        provider, _, _ = provider_for(raw(b"{}", 429, **{"retry-after": "9"}))

        with pytest.raises(LlmRateLimited) as exc:
            provider.embed(["x"])

        assert exc.value.retry_after_s == 9


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

    @pytest.mark.parametrize("index", range(len(FAILURES)))
    def test_no_error_path_leaks_the_key_or_provider_text(
        self, index: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        provider, _, _ = provider_for(*([self.FAILURES[index]] * 3))

        with pytest.raises(LlmError) as exc:
            provider.embed(["x"])

        surfaces = [str(exc.value), repr(exc.value), "".join(traceback.format_exception(exc.value))]
        surfaces.append(repr(provider))
        surfaces += [r.getMessage() + str(r.args) + (r.exc_text or "") for r in caplog.records]
        joined = "\n".join(surfaces)
        assert caplog.records, "the adapter must log, otherwise this check is vacuous"
        assert KEY not in joined and "SENTINEL-9f3a" not in joined
        assert BODY_SENTINEL not in joined

    def test_repr_shows_model_and_dimensions_but_not_the_key(self) -> None:
        provider, _, _ = provider_for()

        assert MODEL in repr(provider) and "4" in repr(provider)
        assert KEY not in repr(provider) and KEY not in repr(vars(provider))


class TestConstruction:
    @pytest.mark.parametrize("key", [None, "", "has space", 3])
    def test_invalid_keys_are_rejected(self, key: object) -> None:
        with pytest.raises(SecretError):
            OpenRouterEmbeddingProvider(key, MODEL, DIM)

    @pytest.mark.parametrize("model", ["", "has space", None, 3, "x" * 121])
    def test_invalid_model_ids_are_rejected(self, model: object) -> None:
        with pytest.raises(LlmValidationError, match="model"):
            OpenRouterEmbeddingProvider(KEY, model, DIM)  # type: ignore[arg-type]

    @pytest.mark.parametrize("dimensions", [0, -1, 2001, 1.5, True, "4", None])
    def test_dimensions_is_an_int_within_1_and_2000(self, dimensions: object) -> None:
        with pytest.raises(LlmValidationError, match="dimensions"):
            OpenRouterEmbeddingProvider(KEY, MODEL, dimensions)  # type: ignore[arg-type]

    @pytest.mark.parametrize("limit", [0, -1, 100_001, 1.5, True])
    def test_max_input_chars_is_bounded(self, limit: object) -> None:
        with pytest.raises(LlmValidationError, match="max_input_chars"):
            OpenRouterEmbeddingProvider(KEY, MODEL, DIM, max_input_chars=limit)  # type: ignore[arg-type]

    def test_over_long_inputs_are_rejected_before_any_request(self) -> None:
        provider, script, _ = provider_for(max_input_chars=10)

        with pytest.raises(LlmValidationError, match="characters"):
            provider.embed(["x" * 11])
        with pytest.raises(LlmValidationError, match="texts"):
            provider.embed("not a list")  # type: ignore[arg-type]
        assert script.calls == 0

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_blank_inputs_are_rejected_before_any_request(self, blank: str) -> None:
        provider, script, _ = provider_for()

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
