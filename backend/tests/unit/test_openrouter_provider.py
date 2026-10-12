"""OpenRouter chat adapter over httpx.MockTransport: no network, ever."""

import logging
import traceback

import httpx
import pytest
from http_fakes import BODY_SENTINEL, KEY, FakeClock, Script, chat_ok, raw, reply

from eventssound.adapters.llm.openrouter import DEFAULT_BASE_URL, OpenRouterProvider
from eventssound.adapters.secret import Secret, SecretError
from eventssound.application.llm import (
    JsonSchemaSpec,
    LlmAuthError,
    LlmBadResponse,
    LlmError,
    LlmMessage,
    LlmRateLimited,
    LlmRequest,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    ResponseFormat,
    Role,
    TokenUsage,
)

MODEL = "vendor/model-a:free"


def make_request(**overrides: object) -> LlmRequest:
    fields: dict[str, object] = {
        "node": "understand",
        "messages": [LlmMessage(Role.SYSTEM, "rules"), LlmMessage(Role.USER, "hola mundo")],
        "temperature": 0.3,
        "max_output_tokens": 256,
        "timeout_s": 20,
    }
    fields.update(overrides)
    return LlmRequest(**fields)  # type: ignore[arg-type]


def provider_for(*items: object, **kwargs: object) -> tuple[OpenRouterProvider, Script, FakeClock]:
    script = Script(*items)  # type: ignore[arg-type]
    clock = FakeClock()
    options: dict[str, object] = {
        "transport": script.transport,
        "sleep": clock.sleep,
        "clock": clock,
        "jitter": lambda: 1.0,
    }
    options.update(kwargs)
    return OpenRouterProvider(KEY, MODEL, **options), script, clock  # type: ignore[arg-type]


class TestSuccess:
    def test_maps_the_completion_to_an_llm_response(self) -> None:
        provider, _, _ = provider_for(reply(chat_ok("Hola!", finish_reason="stop")))

        response = provider.complete(make_request())

        assert response.text == "Hola!"
        assert response.usage == TokenUsage(410, 120, estimated=False)
        assert response.model == "provider/model-x"
        assert response.finish_reason == "stop"
        assert response.parsed is None

    def test_latency_is_measured_with_the_injected_clock(self) -> None:
        clock = FakeClock()

        def slow(request: httpx.Request) -> httpx.Response:
            clock.now += 1.25
            return reply(chat_ok())

        provider, _, _ = provider_for(slow, clock=clock, sleep=clock.sleep)

        assert provider.complete(make_request()).latency_ms == 1250

    def test_request_body_and_endpoint(self) -> None:
        provider, script, _ = provider_for(reply(chat_ok()))

        provider.complete(make_request())

        sent = script.requests[0]
        assert (sent.method, str(sent.url)) == ("POST", f"{DEFAULT_BASE_URL}/chat/completions")
        assert script.body() == {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "hola mundo"},
            ],
            "temperature": 0.3,
            "max_tokens": 256,
            "stream": False,
        }

    def test_key_is_only_in_the_authorization_header(self) -> None:
        provider, script, _ = provider_for(reply(chat_ok()))

        provider.complete(make_request())

        sent = script.requests[0]
        assert sent.headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in str(sent.url)
        assert KEY.encode() not in sent.content
        others = {k: v for k, v in sent.headers.items() if k != "authorization"}
        assert KEY not in repr(others)

    def test_json_mode_requests_json_object_and_parses_the_text(self) -> None:
        provider, script, _ = provider_for(reply(chat_ok('{"intent": "quote"}')))

        response = provider.complete(make_request(response_format=ResponseFormat.JSON))

        assert script.body()["response_format"] == {"type": "json_object"}
        assert response.parsed == {"intent": "quote"}

    def test_json_schema_is_sent_as_a_strict_json_schema(self) -> None:
        spec = JsonSchemaSpec.from_schema("extraction", {"type": "object"})
        provider, script, _ = provider_for(reply(chat_ok("{}")))

        provider.complete(make_request(response_format=ResponseFormat.JSON, json_schema=spec))

        assert script.body()["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "extraction", "schema": {"type": "object"}, "strict": True},
        }

    @pytest.mark.parametrize("text", ["plain words", "[1, 2]", '"x"', '{"a": '])
    def test_json_mode_with_non_object_content_is_a_bad_response(self, text: str) -> None:
        provider, _, _ = provider_for(reply(chat_ok(text)))

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request(response_format=ResponseFormat.JSON))

    def test_response_model_falls_back_to_the_configured_one(self) -> None:
        for model in (None, "", 3, "x" * 201):
            provider, _, _ = provider_for(reply(chat_ok(model=model)))

            assert provider.complete(make_request()).model == MODEL

    @pytest.mark.parametrize("finish", [None, 3, ["stop"]])
    def test_unusable_finish_reason_becomes_none(self, finish: object) -> None:
        provider, _, _ = provider_for(reply(chat_ok(finish_reason=finish)))

        assert provider.complete(make_request()).finish_reason is None


class TestUsage:
    def test_missing_usage_is_estimated_from_characters_and_never_zero(self) -> None:
        text = "x" * 41
        provider, _, _ = provider_for(reply(chat_ok(text, usage="omit")))

        usage = provider.complete(make_request()).usage

        # prompt: len("rules") + len("hola mundo") = 15 chars -> 4; completion: 41 -> 11
        assert usage == TokenUsage(4, 11, estimated=True)

    @pytest.mark.parametrize(
        "bad_usage",
        [
            {},
            {"prompt_tokens": 5},
            {"prompt_tokens": -1, "completion_tokens": 2},
            {"prompt_tokens": True, "completion_tokens": 2},
            {"prompt_tokens": "5", "completion_tokens": 2},
            {"prompt_tokens": 1.5, "completion_tokens": 2},
            {"prompt_tokens": 5, "completion_tokens": 2**40},
            [1, 2],
            "lots",
        ],
    )
    def test_invalid_usage_is_estimated_instead_of_trusted(self, bad_usage: object) -> None:
        provider, _, _ = provider_for(reply(chat_ok("abcd", usage=bad_usage)))

        usage = provider.complete(make_request()).usage

        assert usage.estimated is True
        assert usage.prompt_tokens >= 1 and usage.completion_tokens == 1

    def test_zero_reported_tokens_are_trusted_as_reported(self) -> None:
        provider, _, _ = provider_for(
            reply(chat_ok(usage={"prompt_tokens": 0, "completion_tokens": 0}))
        )

        assert provider.complete(make_request()).usage == TokenUsage(0, 0, estimated=False)


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("status", "error", "attempts"),
        [
            (401, LlmAuthError, 1),
            (403, LlmAuthError, 1),
            (402, LlmUnavailable, 1),
            (408, LlmTimeout, 1),
            (400, LlmBadResponse, 1),
            (404, LlmBadResponse, 1),
            (422, LlmBadResponse, 1),
            (301, LlmBadResponse, 1),
            (500, LlmUnavailable, 1),
            (501, LlmUnavailable, 1),
            (502, LlmUnavailable, 3),
            (503, LlmUnavailable, 3),
            (504, LlmUnavailable, 3),
            (204, LlmBadResponse, 1),
        ],
    )
    def test_status_maps_to_a_typed_error_and_retries_only_transient_ones(
        self, status: int, error: type[LlmError], attempts: int
    ) -> None:
        items = [raw(f'{{"detail": "{BODY_SENTINEL}"}}'.encode(), status, location="http://evil/")]
        provider, script, _ = provider_for(*items * attempts)

        with pytest.raises(error):
            provider.complete(make_request())

        assert script.calls == attempts

    def test_a_redirect_is_never_followed(self) -> None:
        provider, script, _ = provider_for(
            raw(b"", 307, location="https://elsewhere.example/steal"), reply(chat_ok())
        )

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

        assert script.calls == 1

    def test_429_with_a_long_retry_after_is_not_retried_and_reports_it(self) -> None:
        provider, script, clock = provider_for(raw(b"{}", 429, **{"retry-after": "7"}))

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s == 7
        assert (script.calls, clock.sleeps) == (1, [])

    def test_429_with_a_short_retry_after_waits_that_long_then_succeeds(self) -> None:
        provider, script, clock = provider_for(
            raw(b"{}", 429, **{"retry-after": "2"}), reply(chat_ok("ok"))
        )

        assert provider.complete(make_request()).text == "ok"
        assert (script.calls, clock.sleeps) == (2, [2])

    def test_429_without_retry_after_backs_off_and_reports_none(self) -> None:
        provider, script, clock = provider_for(*[raw(b"{}", 429)] * 3)

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s is None
        assert (script.calls, clock.sleeps) == (3, [0.5, 1.0])

    @pytest.mark.parametrize("header", ["soon", "-3", "1.5", "Wed, 21 Oct 2026 07:28:00 GMT", ""])
    def test_unparseable_retry_after_is_ignored(self, header: str) -> None:
        provider, _, _ = provider_for(
            raw(b"{}", 429, **{"retry-after": header}), *[raw(b"{}", 429)] * 2
        )

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s is None


class TestRetryAfterHeader:
    @pytest.mark.parametrize(
        ("header", "reported"),
        [("86400", 86400), ("86401", 86400), ("999999", 86400), ("100000", 86400)],
    )
    def test_huge_values_are_clamped_and_never_escape_as_validation_errors(
        self, header: str, reported: int
    ) -> None:
        provider, script, clock = provider_for(raw(b"{}", 429, **{"retry-after": header}))

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s == reported
        assert (script.calls, clock.sleeps) == (1, [])  # far above the 5 s sleep rule

    def test_zero_retry_after_retries_immediately(self) -> None:
        provider, script, clock = provider_for(
            raw(b"{}", 429, **{"retry-after": "0"}), reply(chat_ok("ok"))
        )

        assert provider.complete(make_request()).text == "ok"
        assert (script.calls, clock.sleeps) == (2, [0.0])

    @pytest.mark.parametrize(
        ("header", "retried"), [("4", True), ("5", True), ("6", False), ("7", False)]
    )
    def test_the_five_second_sleep_rule_boundary(self, header: str, retried: bool) -> None:
        provider, script, clock = provider_for(
            raw(b"{}", 429, **{"retry-after": header}), reply(chat_ok("ok"))
        )

        if retried:
            assert provider.complete(make_request()).text == "ok"
            assert (script.calls, clock.sleeps) == (2, [float(header)])
        else:
            with pytest.raises(LlmRateLimited) as exc:
                provider.complete(make_request())
            assert (script.calls, clock.sleeps, exc.value.retry_after_s) == (1, [], int(header))

    @pytest.mark.parametrize(
        "header",
        [
            "-1",
            "",
            "  ",
            "1.5",
            "٣",
            "１２",
            "1e3",
            "0x10",
            "Wed, 21 Oct 2026 07:28:00 GMT",
            "9999999",
        ],
    )
    def test_unusable_forms_are_ignored_and_never_raise_validation_errors(
        self, header: str
    ) -> None:
        response = httpx.Response(429, headers=[(b"retry-after", header.encode("utf-8"))])
        provider, script, _ = provider_for(response, response, response)

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s is None  # unusable forms behave as if absent
        assert script.calls == 3  # ...so the normal backoff retries apply

    def test_multiple_retry_after_headers_are_ignored(self) -> None:
        response = httpx.Response(429, headers=[("retry-after", "2"), ("retry-after", "3")])
        provider, _, _ = provider_for(response, response, response)

        with pytest.raises(LlmRateLimited) as exc:
            provider.complete(make_request())

        assert exc.value.retry_after_s is None

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        provider, _, clock = provider_for(
            raw(b"{}", 429, **{"retry-after": " 2 "}), reply(chat_ok("ok"))
        )

        provider.complete(make_request())

        assert clock.sleeps == [2.0]


class TestRetries:
    def test_transient_failures_then_success_uses_exponential_backoff(self) -> None:
        provider, script, clock = provider_for(
            raw(b"x", 502), raw(b"x", 503), reply(chat_ok("third time"))
        )

        assert provider.complete(make_request()).text == "third time"
        assert (script.calls, clock.sleeps) == (3, [0.5, 1.0])

    def test_attempts_are_bounded_at_one_plus_two_retries(self) -> None:
        provider, script, _ = provider_for(*[raw(b"x", 503)] * 5)

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert script.calls == 3

    def test_backoff_uses_full_jitter(self) -> None:
        provider, _, clock = provider_for(
            raw(b"x", 503), raw(b"x", 503), raw(b"x", 503), jitter=lambda: 0.5
        )

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert clock.sleeps == [0.25, 0.5]

    def test_max_retries_zero_means_a_single_attempt(self) -> None:
        provider, script, _ = provider_for(raw(b"x", 503), max_retries=0)

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert script.calls == 1

    def test_connect_errors_are_retried(self) -> None:
        provider, script, _ = provider_for(httpx.ConnectError("boom"), reply(chat_ok("ok")))

        assert provider.complete(make_request()).text == "ok"
        assert script.calls == 2

    def test_connect_errors_that_persist_become_unavailable(self) -> None:
        provider, script, _ = provider_for(*[httpx.ConnectError("boom")] * 3)

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert script.calls == 3

    @pytest.mark.parametrize(
        "timeout",
        [httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("slow")],
    )
    def test_timeouts_are_not_retried_because_the_provider_may_have_billed(
        self, timeout: Exception
    ) -> None:
        provider, script, _ = provider_for(timeout, reply(chat_ok()))

        with pytest.raises(LlmTimeout):
            provider.complete(make_request())

        assert script.calls == 1

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ReadError("reset"),
            httpx.RemoteProtocolError("bad"),
            httpx.ProxyError("proxy"),
            httpx.UnsupportedProtocol("nope"),
        ],
    )
    def test_other_transport_failures_are_unavailable_and_not_retried(
        self, failure: Exception
    ) -> None:
        provider, script, _ = provider_for(failure, reply(chat_ok()))

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert script.calls == 1

    def test_retries_stop_when_the_request_deadline_would_be_exceeded(self) -> None:
        provider, script, clock = provider_for(*[raw(b"x", 503)] * 3)

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request(timeout_s=1))

        # delays are 0.5 then 1.0; the second would end past the 1 s deadline.
        assert (script.calls, clock.sleeps) == (2, [0.5])

    def test_each_attempt_gets_the_remaining_budget_as_its_read_timeout(self) -> None:
        seen: list[float | None] = []

        def capture(request: httpx.Request) -> httpx.Response:
            seen.append(request.extensions["timeout"]["read"])
            return raw(b"x", 503) if len(seen) == 1 else reply(chat_ok())

        provider, _, _ = provider_for(capture, capture)

        provider.complete(make_request(timeout_s=10))

        assert seen == [10, 9.5]


class TestDeadlineAndTimeouts:
    def test_the_total_deadline_is_enforced_while_streaming_the_body(self) -> None:
        clock = FakeClock()
        produced: list[int] = []

        def slow_body():  # type: ignore[no-untyped-def]
            for i in range(100):
                produced.append(i)
                clock.now += 0.5  # each chunk takes half a second
                yield b" "

        provider, _, _ = provider_for(
            httpx.Response(200, content=slow_body()), clock=clock, sleep=clock.sleep
        )

        with pytest.raises(LlmTimeout):
            provider.complete(make_request(timeout_s=2))

        assert 2 <= len(produced) <= 6  # stopped near the deadline, not after 100 chunks

    def test_a_fast_body_inside_the_deadline_is_read_completely(self) -> None:
        import json

        clock = FakeClock()
        body = json.dumps(chat_ok("ok")).encode()

        def chunks():  # type: ignore[no-untyped-def]
            for i in range(0, len(body), 10):
                clock.now += 0.01
                yield body[i : i + 10]

        provider, _, _ = provider_for(
            httpx.Response(200, content=chunks()), clock=clock, sleep=clock.sleep
        )

        assert provider.complete(make_request(timeout_s=2)).text == "ok"

    @pytest.mark.parametrize(
        ("budget", "expected"),
        [
            (20, {"connect": 5, "read": 20, "write": 10, "pool": 5}),
            (3, {"connect": 3, "read": 3, "write": 3, "pool": 3}),
            (7, {"connect": 5, "read": 7, "write": 7, "pool": 5}),
        ],
    )
    def test_connect_write_and_pool_timeouts_are_capped_by_the_remaining_budget(
        self, budget: int, expected: dict[str, float]
    ) -> None:
        seen: list[dict[str, float | None]] = []

        def capture(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.extensions["timeout"]))
            return reply(chat_ok())

        provider, _, _ = provider_for(capture)

        provider.complete(make_request(timeout_s=budget))

        assert seen == [expected]


class TestEncodingAndCredentialsInFrames:
    def test_requests_ask_for_unencoded_bodies_so_the_cap_counts_raw_bytes(self) -> None:
        provider, script, _ = provider_for(reply(chat_ok()))

        provider.complete(make_request())

        assert script.requests[0].headers["accept-encoding"] == "identity"

    def test_a_compressed_response_is_rejected_before_reading_it(self) -> None:
        import gzip
        import json

        compressed = gzip.compress(json.dumps(chat_ok("ok")).encode())
        provider, script, _ = provider_for(
            raw(compressed, **{"content-encoding": "gzip"}), reply(chat_ok())
        )

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

        assert script.calls == 1

    def test_a_gzip_bomb_is_rejected_without_inflating_it(self) -> None:
        import gzip

        bomb = gzip.compress(b"0" * 50_000_000)
        provider, _, _ = provider_for(raw(bomb, **{"content-encoding": "gzip"}))

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

    def test_identity_content_encoding_is_fine(self) -> None:
        provider, _, _ = provider_for(
            httpx.Response(200, json=chat_ok("ok"), headers={"content-encoding": "identity"})
        )

        assert provider.complete(make_request()).text == "ok"

    @pytest.mark.parametrize(
        "failing",
        [
            raw(b"x" * 100, **{"content-length": "100"}),  # oversize, raised inside _send
            raw(b"{}", 500),  # mapped status, raised in post_json
            reply({"choices": []}),  # bad body, raised in the provider
            raw(b"{}", 429, **{"retry-after": "9"}),
        ],
        ids=["oversize", "status-500", "empty-choices", "rate-limited"],
    )
    def test_no_frame_in_the_traceback_holds_the_key_or_authorization_header(
        self, failing: httpx.Response
    ) -> None:
        provider, _, _ = provider_for(failing, max_response_bytes=50)

        with pytest.raises(LlmError) as exc:
            provider.complete(make_request())

        tb = exc.value.__traceback__
        frames = 0
        while tb is not None:
            frames += 1
            for name, value in tb.tb_frame.f_locals.items():
                rendered = repr(value) + (value if isinstance(value, str) else "")
                if isinstance(value, bytes):
                    rendered += value.decode("latin-1")
                assert KEY not in rendered, f"{name} in {tb.tb_frame.f_code.co_name}"
                assert "Bearer" not in rendered, f"{name} in {tb.tb_frame.f_code.co_name}"
            tb = tb.tb_next
        assert frames >= 2  # the walk really visited several frames


class TestMalformedBodies:
    @pytest.mark.parametrize(
        "content",
        [
            b"",
            b"not json",
            b"\xff\xfe\x00bad utf8",
            b"[1, 2, 3]",
            b'"text"',
            b"null",
            b"{}",
            b'{"choices": []}',
            b'{"choices": null}',
            b'{"choices": "x"}',
            b'{"choices": [1]}',
            b'{"choices": [{}]}',
            b'{"choices": [{"message": null}]}',
            b'{"choices": [{"message": {}}]}',
            b'{"choices": [{"message": {"content": null}}]}',
            b'{"choices": [{"message": {"content": ""}}]}',
            b'{"choices": [{"message": {"content": "   "}}]}',
            b'{"choices": [{"message": {"content": ["part"]}}]}',
            b'{"choices": [{"message": {"content": 5}}]}',
            b'{"choices": [{"message": {"content": "truncated',
            b"[" * 200_000,
        ],
        ids=[
            "empty",
            "not-json",
            "bad-utf8",
            "list",
            "string",
            "null",
            "empty-object",
            "empty-choices",
            "null-choices",
            "str-choices",
            "int-choice",
            "no-message",
            "null-message",
            "no-content",
            "null-content",
            "empty-content",
            "blank-content",
            "parts-content",
            "int-content",
            "truncated",
            "deeply-nested",
        ],
    )
    def test_malformed_200_bodies_raise_bad_response_never_key_or_type_errors(
        self, content: bytes
    ) -> None:
        provider, script, _ = provider_for(raw(content))

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

        assert script.calls == 1  # malformed bodies are not retried

    @pytest.mark.parametrize(
        ("code", "error"),
        [
            (401, LlmAuthError),
            (402, LlmUnavailable),
            (408, LlmTimeout),
            (429, LlmRateLimited),
            (500, LlmUnavailable),
            (400, LlmBadResponse),
            (None, LlmUnavailable),
            ("429", LlmUnavailable),
            (True, LlmUnavailable),
            (9999, LlmUnavailable),
        ],
    )
    def test_error_object_inside_a_200_is_mapped_by_its_numeric_code(
        self, code: object, error: type[LlmError]
    ) -> None:
        body = {
            "error": {"code": code, "message": BODY_SENTINEL},
            "choices": [{"message": {"content": "x"}}],
        }
        provider, _, _ = provider_for(reply(body))

        with pytest.raises(error):
            provider.complete(make_request())

    @pytest.mark.parametrize("error", ["boom", None, [1], 3])
    def test_error_value_of_any_shape_is_an_unavailable_provider(self, error: object) -> None:
        provider, _, _ = provider_for(reply({"error": error, **chat_ok()}))

        if error is None:
            assert provider.complete(make_request()).text == "hola"  # null error means no error
        else:
            with pytest.raises(LlmUnavailable):
                provider.complete(make_request())


class TestBodySizeCap:
    def test_oversized_content_length_is_rejected_without_reading(self) -> None:
        provider, _, _ = provider_for(
            raw(b"x" * 100, **{"content-length": "100"}), max_response_bytes=50
        )

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

    def test_streamed_body_stops_reading_at_the_cap(self) -> None:
        produced: list[int] = []

        def chunks():  # type: ignore[no-untyped-def]
            for i in range(10_000):
                produced.append(i)
                yield b"x" * 100

        provider, _, _ = provider_for(
            httpx.Response(200, content=chunks()), max_response_bytes=1_000
        )

        with pytest.raises(LlmBadResponse):
            provider.complete(make_request())

        assert 0 < len(produced) < 50  # nowhere near all 10,000 chunks

    def test_a_body_exactly_at_the_cap_is_accepted(self) -> None:
        import json

        body = json.dumps(chat_ok("ok")).encode()
        provider, _, _ = provider_for(raw(body), max_response_bytes=len(body))

        assert provider.complete(make_request()).text == "ok"

    def test_error_responses_are_never_read(self) -> None:
        produced: list[int] = []

        def chunks():  # type: ignore[no-untyped-def]
            for i in range(1_000):
                produced.append(i)
                yield BODY_SENTINEL.encode()

        provider, _, _ = provider_for(httpx.Response(500, content=chunks()))

        with pytest.raises(LlmUnavailable):
            provider.complete(make_request())

        assert produced == []


class TestSecretHygiene:
    FAILURES = [
        raw(f'{{"error": "{KEY} {BODY_SENTINEL}"}}'.encode(), 401),
        raw(f'{{"error": "{KEY} {BODY_SENTINEL}"}}'.encode(), 429, **{"retry-after": "1"}),
        raw(f'{{"error": "{KEY} {BODY_SENTINEL}"}}'.encode(), 500),
        raw(f"{KEY} {BODY_SENTINEL}".encode(), 200),
        reply({"error": {"code": 500, "message": f"{KEY} {BODY_SENTINEL}"}}),
        reply(chat_ok(f"{KEY} {BODY_SENTINEL}"), 200),
        httpx.ConnectError(f"{KEY} {BODY_SENTINEL}"),
        httpx.ReadTimeout(f"{KEY} {BODY_SENTINEL}"),
        httpx.ReadError(f"{KEY} {BODY_SENTINEL}"),
    ]

    @pytest.mark.parametrize("index", range(len(FAILURES)))
    def test_no_error_path_leaks_the_key_or_provider_text(
        self, index: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        item = self.FAILURES[index]
        provider, _, _ = provider_for(*([item] * 3), max_retries=2)
        is_success_body = index == 5  # a 200 that carries the sentinel as model text

        try:
            response = provider.complete(make_request())
        except LlmError as exc:
            surfaces = [
                str(exc),
                repr(exc),
                "".join(traceback.format_exception(exc)),
            ]
        else:
            assert is_success_body
            surfaces = [repr(response.usage), repr(provider)]

        surfaces.append(repr(provider))
        for record in caplog.records:
            surfaces += [record.getMessage(), str(record.args), record.exc_text or ""]
        joined = "\n".join(surfaces)
        assert KEY not in joined
        assert "SENTINEL-9f3a" not in joined
        assert BODY_SENTINEL not in joined if not is_success_body else True

    def test_the_adapter_logs_something_so_the_hygiene_check_is_not_vacuous(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        provider, _, _ = provider_for(raw(b"x", 503), reply(chat_ok()))

        provider.complete(make_request(node="understand"))

        messages = [r.getMessage() for r in caplog.records if r.name == "eventssound.openrouter"]
        assert len(messages) == 2
        assert "node=understand" in messages[0] and "status=503" in messages[0]
        assert "status=200" in messages[1]
        assert MODEL in messages[0]

    def test_key_is_not_reachable_through_repr_or_public_attributes(self) -> None:
        provider, _, _ = provider_for(reply(chat_ok()))

        assert KEY not in repr(provider)
        assert MODEL in repr(provider)
        assert KEY not in repr(vars(provider))


class TestConstruction:
    @pytest.mark.parametrize("key", [None, "", "has space", "bad\nkey", 7, b"bytes"])
    def test_invalid_keys_are_rejected(self, key: object) -> None:
        with pytest.raises(SecretError):
            OpenRouterProvider(key, MODEL)  # type: ignore[arg-type]

    def test_secret_wrapped_and_secretstr_like_keys_work(self) -> None:
        class Like:
            def get_secret_value(self) -> str:
                return KEY

        for key in (Secret(KEY), Like()):
            script = Script(reply(chat_ok()))
            OpenRouterProvider(key, MODEL, transport=script.transport).complete(make_request())
            assert script.requests[0].headers["authorization"] == f"Bearer {KEY}"

    @pytest.mark.parametrize("model", ["", " ", "has space", "a\nb", "x" * 121, None, 3, "ñ/model"])
    def test_invalid_model_ids_are_rejected(self, model: object) -> None:
        with pytest.raises(LlmValidationError, match="model"):
            OpenRouterProvider(KEY, model)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "url",
        [
            "http://openrouter.ai/api/v1",
            "ftp://x",
            "https://",
            "openrouter.ai",
            "",
            None,
            "https://u:p@h/x",
        ],
    )
    def test_base_url_must_be_plain_https(self, url: object) -> None:
        with pytest.raises(LlmValidationError, match="base_url"):
            OpenRouterProvider(KEY, MODEL, base_url=url)  # type: ignore[arg-type]

    def test_custom_https_base_url_is_used_and_trailing_slash_trimmed(self) -> None:
        script = Script(reply(chat_ok()))
        provider = OpenRouterProvider(
            KEY, MODEL, base_url="https://proxy.example/v9/", transport=script.transport
        )

        provider.complete(make_request())

        assert str(script.requests[0].url) == "https://proxy.example/v9/chat/completions"

    @pytest.mark.parametrize("retries", [-1, 6, 1.5, True, "2", None])
    def test_max_retries_is_a_small_non_negative_int(self, retries: object) -> None:
        with pytest.raises(LlmValidationError, match="max_retries"):
            OpenRouterProvider(KEY, MODEL, max_retries=retries)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "backoff",
        [-0.1, float("nan"), float("inf"), True, "1", None, pytest.param(1 << 1500, id="huge"), 61],
    )
    def test_backoff_base_must_be_a_finite_small_non_negative_number(self, backoff: object) -> None:
        with pytest.raises(LlmValidationError, match="backoff_base_s"):
            OpenRouterProvider(KEY, MODEL, backoff_base_s=backoff)  # type: ignore[arg-type]

    def test_backoff_base_zero_means_retry_without_waiting(self) -> None:
        provider, _, clock = provider_for(raw(b"x", 503), reply(chat_ok()), backoff_base_s=0)

        provider.complete(make_request())

        assert clock.sleeps == [0.0]

    @pytest.mark.parametrize("cap", [0, -1, 1.5, True, 2**31])
    def test_response_cap_must_be_a_positive_bounded_int(self, cap: object) -> None:
        with pytest.raises(LlmValidationError, match="max_response_bytes"):
            OpenRouterProvider(KEY, MODEL, max_response_bytes=cap)  # type: ignore[arg-type]

    def test_complete_rejects_a_non_request(self) -> None:
        provider, script, _ = provider_for()

        with pytest.raises(LlmValidationError, match="request"):
            provider.complete({"node": "x"})  # type: ignore[arg-type]
        assert script.calls == 0

    def test_close_and_context_manager(self) -> None:
        script = Script(reply(chat_ok()))
        with OpenRouterProvider(KEY, MODEL, transport=script.transport) as provider:
            provider.complete(make_request())

        with pytest.raises(RuntimeError):  # the owned httpx client is closed
            provider.complete(make_request())
