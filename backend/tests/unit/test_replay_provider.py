"""Replay adapter (keyed by scenario and node), scripted fake and the opt-in recorder."""

import json
import threading
from pathlib import Path

import pytest

from eventssound.adapters.llm.recording import RecordingProvider
from eventssound.adapters.llm.replay import (
    ReplayEntry,
    ReplayMissing,
    ReplayNotConsumed,
    ReplayProvider,
    ScriptedProvider,
    ScriptExhausted,
)
from eventssound.application.llm import (
    LlmAuthError,
    LlmBadResponse,
    LlmMessage,
    LlmRateLimited,
    LlmRequest,
    LlmResponse,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    ResponseFormat,
    Role,
    TokenUsage,
)


def request(
    node: str = "understand",
    scenario: str | None = None,
    system: str = "be brief",
    response_format: ResponseFormat = ResponseFormat.TEXT,
) -> LlmRequest:
    return LlmRequest(
        node=node,
        scenario=scenario,
        messages=[LlmMessage(Role.SYSTEM, system), LlmMessage(Role.USER, "hola")],
        response_format=response_format,
    )


def entry(text: str, prompt: int = 10, completion: int = 5, **kw: object) -> ReplayEntry:
    return ReplayEntry(text=text, usage=TokenUsage(prompt, completion), **kw)  # type: ignore[arg-type]


def scripts() -> dict[str, dict[str, list[ReplayEntry]]]:
    return {
        "boda_simple": {"understand": [entry("first"), entry("second")], "draft": [entry("d")]},
        "otra": {"understand": [entry("other")]},
    }


class TestLookup:
    def test_returns_the_entry_for_scenario_and_node_with_hand_set_usage(self) -> None:
        provider = ReplayProvider(scripts())

        response = provider.complete(request("draft", "boda_simple"))

        assert response.text == "d"
        assert response.usage == TokenUsage(10, 5)
        assert response.model == "replay-model"

    def test_different_scenarios_do_not_share_entries(self) -> None:
        provider = ReplayProvider(scripts())

        assert provider.complete(request(scenario="otra")).text == "other"
        assert provider.complete(request(scenario="boda_simple")).text == "first"

    def test_prompt_wording_does_not_change_the_lookup(self) -> None:
        provider = ReplayProvider(scripts())

        a = provider.complete(request(scenario="boda_simple", system="version one"))
        b = ReplayProvider(scripts()).complete(
            request(scenario="boda_simple", system="completely different prompt")
        )

        assert a.text == b.text == "first"

    def test_constructor_scenario_is_the_default_and_the_request_overrides_it(self) -> None:
        provider = ReplayProvider(scripts(), scenario="boda_simple")

        assert provider.complete(request()).text == "first"
        assert provider.complete(request(scenario="otra")).text == "other"

    def test_entries_are_consumed_in_order_then_miss(self) -> None:
        provider = ReplayProvider(scripts(), scenario="boda_simple")

        assert [provider.complete(request()).text for _ in range(2)] == ["first", "second"]
        with pytest.raises(ReplayMissing) as exc:
            provider.complete(request())
        assert (exc.value.scenario, exc.value.node, exc.value.index) == (
            "boda_simple",
            "understand",
            2,
        )

    @pytest.mark.parametrize(
        ("scenario", "node"), [("nope", "understand"), ("boda_simple", "draft_x"), (None, "draft")]
    )
    def test_missing_key_names_scenario_and_node_but_no_prompt_text(
        self, scenario: str | None, node: str
    ) -> None:
        provider = ReplayProvider(scripts())

        with pytest.raises(ReplayMissing) as exc:
            provider.complete(request(node, scenario, system="SECRET-PROMPT"))

        assert node in str(exc.value)
        assert str(scenario) in str(exc.value)
        assert "SECRET-PROMPT" not in str(exc.value) + repr(exc.value)

    def test_replay_missing_is_not_a_provider_error(self) -> None:
        from eventssound.application.llm import LlmError

        assert not issubclass(ReplayMissing, LlmError)

    def test_provider_can_be_called_from_many_threads_without_double_consumption(self) -> None:
        many = {"s": {"n": [entry(str(i)) for i in range(40)]}}
        provider = ReplayProvider(many, scenario="s")
        seen: list[str] = []

        def work() -> None:
            for _ in range(10):
                seen.append(provider.complete(request("n")).text)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(seen, key=int) == [str(i) for i in range(40)]


class TestErrorEntries:
    @pytest.mark.parametrize(
        ("name", "error"),
        [
            ("timeout", LlmTimeout),
            ("rate_limited", LlmRateLimited),
            ("unavailable", LlmUnavailable),
            ("auth", LlmAuthError),
            ("bad_response", LlmBadResponse),
        ],
    )
    def test_error_entry_raises_the_matching_typed_error(self, name: str, error: type) -> None:
        provider = ReplayProvider({"s": {"n": [ReplayEntry(error=name)]}}, scenario="s")

        with pytest.raises(error):
            provider.complete(request("n"))

    def test_error_entry_then_success_covers_a_repair_sequence(self) -> None:
        provider = ReplayProvider(
            {"s": {"n": [ReplayEntry(error="timeout"), entry("ok")]}}, scenario="s"
        )

        with pytest.raises(LlmTimeout):
            provider.complete(request("n"))
        assert provider.complete(request("n")).text == "ok"

    def test_unknown_error_name_is_rejected_at_construction(self) -> None:
        with pytest.raises(LlmValidationError, match="error"):
            ReplayEntry(error="explode")


class TestJsonResponses:
    def test_json_request_parses_the_entry_text(self) -> None:
        provider = ReplayProvider({"s": {"n": [entry('{"intent": "quote"}')]}}, scenario="s")

        response = provider.complete(request("n", response_format=ResponseFormat.JSON))

        assert response.parsed == {"intent": "quote"}

    @pytest.mark.parametrize("text", ["not json", "[1, 2]", '"x"', ""])
    def test_json_request_with_non_object_text_is_a_bad_response(self, text: str) -> None:
        provider = ReplayProvider({"s": {"n": [entry(text)]}}, scenario="s")

        with pytest.raises(LlmBadResponse):
            provider.complete(request("n", response_format=ResponseFormat.JSON))

    def test_text_request_leaves_parsed_empty(self) -> None:
        provider = ReplayProvider({"s": {"n": [entry('{"a": 1}')]}}, scenario="s")

        assert provider.complete(request("n")).parsed is None


class TestConsumedCheck:
    def test_passes_when_every_entry_was_used(self) -> None:
        provider = ReplayProvider({"s": {"n": [entry("a")]}}, scenario="s")
        provider.complete(request("n"))

        provider.assert_all_consumed()

    def test_fails_naming_the_stale_entries(self) -> None:
        provider = ReplayProvider({"s": {"n": [entry("a"), entry("b")]}}, scenario="s")
        provider.complete(request("n"))

        with pytest.raises(ReplayNotConsumed, match=r"s/n: 1 of 2"):
            provider.assert_all_consumed()


class TestEntryValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("text", None),
            ("text", b"x"),
            ("usage", (1, 2)),
            ("model", ""),
            ("finish_reason", 3),
            ("error", 5),
        ],
    )
    def test_invalid_entry_fields_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(LlmValidationError, match=field):
            ReplayEntry(**{"text": "x", "usage": TokenUsage(1, 1), field: value})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "scripts_arg",
        [
            {"bad name": {"n": [entry("x")]}},
            {"s": {"Bad Node": [entry("x")]}},
            {"s": {"n": "not entries"}},
            {"s": {"n": ["x"]}},
            {"s": {"n": []}},
            {"s": "nope"},
            [],
        ],
        ids=["scenario", "node", "string-entries", "str-entry", "empty-entries", "calls", "list"],
    )
    def test_invalid_scripts_are_rejected(self, scripts_arg: object) -> None:
        with pytest.raises(LlmValidationError):
            ReplayProvider(scripts_arg)  # type: ignore[arg-type]

    def test_constructor_scenario_must_be_an_identifier(self) -> None:
        with pytest.raises(LlmValidationError, match="scenario"):
            ReplayProvider(scripts(), scenario="bad name")


def document(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "scenario": "wedding",
        "description": "ignored",
        "trigger": "ignored",
        "now": "2026-10-12T10:00:00-05:00",
        "model": "replay-model-x",
        "calls": {
            "understand": [
                {
                    "text": '{"intent": "quote"}',
                    "usage": {"prompt_tokens": 410, "completion_tokens": 120},
                },
                {"error": "timeout"},
            ],
            "draft": [
                {"text": "Hola", "usage": {"prompt_tokens": 5, "completion_tokens": 6}},
            ],
        },
    }
    doc.update(overrides)
    return doc


class TestDocuments:
    def test_loads_the_design_fixture_format(self) -> None:
        provider = ReplayProvider.from_documents([document()], scenario="wedding")

        first = provider.complete(request("understand", response_format=ResponseFormat.JSON))
        assert first.parsed == {"intent": "quote"}
        assert first.usage == TokenUsage(410, 120)
        assert first.model == "replay-model-x"
        with pytest.raises(LlmTimeout):
            provider.complete(request("understand"))
        assert provider.complete(request("draft")).text == "Hola"
        provider.assert_all_consumed()

    def test_loads_several_documents_and_a_file_round_trip(self, tmp_path: Path) -> None:
        other = document(scenario="other")
        path = tmp_path / "other.json"
        path.write_text(json.dumps(other), encoding="utf-8")

        provider = ReplayProvider.from_documents(
            [document(), json.loads(path.read_text(encoding="utf-8"))]
        )

        assert provider.complete(request("draft", "other")).text == "Hola"
        assert provider.complete(request("draft", "wedding")).text == "Hola"

    def test_model_defaults_when_the_document_has_none(self) -> None:
        doc = document()
        del doc["model"]

        provider = ReplayProvider.from_documents([doc], scenario="wedding")

        assert provider.complete(request("draft")).model == "replay-model"

    @pytest.mark.parametrize(
        "bad",
        [
            document(scenario=None),
            document(scenario="bad name"),
            document(calls=None),
            document(calls=[]),
            document(calls={"understand": "x"}),
            document(calls={"understand": [3]}),
            document(calls={"understand": [{"text": "x"}]}),
            document(calls={"understand": [{"text": "x", "usage": {"prompt_tokens": "1"}}]}),
            document(
                calls={
                    "understand": [
                        {"text": "x", "usage": {"prompt_tokens": 1, "completion_tokens": True}}
                    ]
                }
            ),
            document(calls={"understand": [{"error": "nope"}]}),
            document(model=3),
        ],
        ids=[
            "no-scenario",
            "bad-scenario",
            "no-calls",
            "list-calls",
            "str-entries",
            "int-entry",
            "no-usage",
            "str-tokens",
            "bool-tokens",
            "bad-error",
            "bad-model",
        ],
    )
    def test_malformed_documents_raise_validation_errors(self, bad: dict[str, object]) -> None:
        with pytest.raises(LlmValidationError):
            ReplayProvider.from_documents([bad])

    def test_non_mapping_document_and_duplicate_scenarios_are_rejected(self) -> None:
        with pytest.raises(LlmValidationError, match="document"):
            ReplayProvider.from_documents(["x"])  # type: ignore[list-item]
        with pytest.raises(LlmValidationError, match="duplicate"):
            ReplayProvider.from_documents([document(), document()])
        with pytest.raises(LlmValidationError, match="documents"):
            ReplayProvider.from_documents(document())  # type: ignore[arg-type]


class TestScriptedProvider:
    def test_returns_queued_responses_in_order_and_records_requests(self) -> None:
        first = LlmResponse("a", TokenUsage(1, 1), "m")
        second = LlmResponse("b", TokenUsage(2, 2), "m")
        provider = ScriptedProvider([first, second])
        r1, r2 = request("understand"), request("draft")

        assert provider.complete(r1) is first
        assert provider.complete(r2) is second
        assert provider.calls == [r1, r2]

    def test_raises_queued_errors_in_call_order(self) -> None:
        ok = LlmResponse("a", TokenUsage(1, 1), "m")
        provider = ScriptedProvider([LlmTimeout(), ok])

        with pytest.raises(LlmTimeout):
            provider.complete(request())
        assert provider.complete(request()) is ok
        assert len(provider.calls) == 2

    def test_exhausted_queue_fails_loudly_but_still_records_the_call(self) -> None:
        provider = ScriptedProvider([])
        asked = request("draft")

        with pytest.raises(ScriptExhausted):
            provider.complete(asked)
        assert provider.calls == [asked]

    @pytest.mark.parametrize("item", ["text", LlmTimeout, None, ValueError("x")])
    def test_only_responses_and_llm_errors_can_be_queued(self, item: object) -> None:
        with pytest.raises(LlmValidationError, match="script"):
            ScriptedProvider([item])  # type: ignore[list-item]

    def test_a_string_is_not_a_script(self) -> None:
        with pytest.raises(LlmValidationError, match="script"):
            ScriptedProvider("ab")  # type: ignore[arg-type]


class TestRecordingProvider:
    def inner(self) -> ScriptedProvider:
        return ScriptedProvider(
            [
                LlmResponse('{"a": 1}', TokenUsage(7, 3), "real/model", "stop", 99),
                LlmResponse("Hola", TokenUsage(4, 2), "real/model", "stop", 10),
            ]
        )

    def test_is_off_by_default_and_passes_through_without_recording(self) -> None:
        recorder = RecordingProvider(self.inner(), "wedding")

        response = recorder.complete(request("understand"))

        assert response.text == '{"a": 1}'
        assert recorder.to_fixture()["calls"] == {}
        with pytest.raises(LlmValidationError, match="disabled"):
            recorder.write(Path("unused.json"))

    def test_when_enabled_it_records_by_node_in_order_without_request_messages(self) -> None:
        recorder = RecordingProvider(self.inner(), "wedding", enabled=True)
        recorder.complete(request("understand", system="SECRET-PROMPT"))
        recorder.complete(request("draft"))

        fixture = recorder.to_fixture()

        assert fixture["scenario"] == "wedding"
        assert set(fixture["calls"]) == {"understand", "draft"}  # type: ignore[arg-type]
        assert fixture["calls"]["understand"][0]["usage"] == {  # type: ignore[index]
            "prompt_tokens": 7,
            "completion_tokens": 3,
        }
        assert "SECRET-PROMPT" not in json.dumps(fixture)

    def test_recorded_fixture_replays_the_same_responses(self, tmp_path: Path) -> None:
        recorder = RecordingProvider(self.inner(), "wedding", enabled=True)
        live = [recorder.complete(request("understand")), recorder.complete(request("draft"))]
        path = tmp_path / "wedding.json"
        recorder.write(path)

        replay = ReplayProvider.from_documents(
            [json.loads(path.read_text(encoding="utf-8"))], scenario="wedding"
        )

        replayed = [replay.complete(request("understand")), replay.complete(request("draft"))]
        assert [(r.text, r.usage, r.model) for r in replayed] == [
            (r.text, r.usage, r.model) for r in live
        ]
        replay.assert_all_consumed()

    def test_failed_inner_calls_propagate_and_are_not_recorded(self) -> None:
        recorder = RecordingProvider(ScriptedProvider([LlmTimeout()]), "w", enabled=True)

        with pytest.raises(LlmTimeout):
            recorder.complete(request())

        assert recorder.to_fixture()["calls"] == {}

    def test_enabled_must_be_a_real_bool_and_scenario_an_identifier(self) -> None:
        with pytest.raises(LlmValidationError, match="enabled"):
            RecordingProvider(self.inner(), "w", enabled="yes")  # type: ignore[arg-type]
        with pytest.raises(LlmValidationError, match="scenario"):
            RecordingProvider(self.inner(), "bad name")


class TestRecordingIsOptIn:
    def test_the_default_is_disabled_in_the_signature_itself(self) -> None:
        import inspect

        default = inspect.signature(RecordingProvider.__init__).parameters["enabled"].default

        assert default is False

    @pytest.mark.parametrize("flag", [1, "true", None, [True]])
    def test_only_a_real_true_enables_recording(self, flag: object) -> None:
        with pytest.raises(LlmValidationError, match="enabled"):
            RecordingProvider(ScriptedProvider([]), "w", enabled=flag)  # type: ignore[arg-type]

    def test_enabled_recording_through_the_real_adapter_never_stores_messages_or_the_key(
        self,
    ) -> None:
        from http_fakes import KEY, Script, chat_ok, reply

        from eventssound.adapters.llm.openrouter import OpenRouterProvider

        script = Script(reply(chat_ok("respuesta")))
        live = OpenRouterProvider(KEY, "vendor/model", transport=script.transport)
        recorder = RecordingProvider(live, "w", enabled=True)

        recorder.complete(request("understand", system="SECRET-PROMPT-TEXT"))

        stored = json.dumps(recorder.to_fixture())
        assert "respuesta" in stored  # the response text IS stored (reviewed before commit)
        assert "SECRET-PROMPT-TEXT" not in stored and "hola" not in stored
        assert KEY not in stored and "Bearer" not in stored
