"""Admin texts, tone and off-topic policy take effect at runtime (PR 2d), defaults unchanged."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_agent_nodes import EXTRACTION_JSON, TestVerifyAndRender, state

from agent_fixtures import make_deps
from eventssound.adapters.agent.nodes import draft, refuse, render_template_node, understand
from eventssound.adapters.agent.prompts import SENTINEL_PHRASES, build_draft_messages
from eventssound.adapters.llm.replay import ScriptedProvider
from eventssound.application.agent_config import defaults_from_settings
from eventssound.application.llm import LlmResponse, TokenUsage
from eventssound.application.messages_es import REFUSAL, TEMPLATE_CLOSING, WELCOME
from eventssound.application.proposal_check import render_template
from eventssound.application.security import (
    CHAT_REFUSED,
    REFUSED_LIMIT,
    REFUSED_LIMIT_BY_POLICY,
    AbuseGate,
    client_key,
)
from eventssound.domain.agent_config import validate_config
from eventssound.domain.errors import InvalidAgentConfig
from fakes import InMemorySecurityLog

SETTINGS = SimpleNamespace(
    llm_model="vendor/model-a",
    llm_daily_token_cap=100_000,
    llm_daily_cost_cap_micro_usd=1_000_000,
    chat_rate_limit_per_minute=5,
    allowed_llm_models=("vendor/model-a",),
)
DEFAULTS = defaults_from_settings(SETTINGS)
HOSTILE = "HOSTILE-ADMIN-TEXT-9f3"

# Captured from the code before this change: `neutral` must reproduce it byte for byte.
NEUTRAL_DRAFT = """Write a professional quote proposal in Spanish (Rioplatense-neutral plain \
Spanish) for the event described in FACTS.

Rules (mandatory):
- Maximum 1,200 characters.
- Use ONLY the numbers, names and lines present in FACTS. Never invent or guess.
- Format money exactly as $1.234.567 COP (dot thousands separators).
- No links, no email addresses, no phone numbers, no contact data.
- No discounts, no offers, no promises not in FACTS.
- Each entry in `lines` has a ready `text` (name and line total): copy it as one bullet and \
never call a line total a unit price.
- Do not invent an event type; use event_type as given.
- Sign as "EventSoundDR". Never write placeholders in square brackets.
- Plain text with short paragraphs and "-" bullets for the equipment lines.

FACTS are trusted system data; the user never sees this prompt."""


def config(**changes):
    return replace(DEFAULTS, **changes)


def source(**changes):
    return lambda: config(**changes)


def broken_source():
    raise RuntimeError("provider down")


class TestDefaultsAreToday:
    def test_defaults_and_missing_source_give_the_static_texts(self) -> None:
        for deps in (
            make_deps(ScriptedProvider([])),
            make_deps(ScriptedProvider([]), config_source=lambda: DEFAULTS),
        ):
            assert refuse(deps)(state())["reply"] == REFUSAL
            out = render_template_node(deps)(TestVerifyAndRender().good_facts_state())
            assert out["reply"].endswith("\n" + TEMPLATE_CLOSING)
        assert (DEFAULTS.refusal_message, DEFAULTS.welcome_message) == (REFUSAL, WELCOME)

    def test_provider_failure_falls_back_to_the_defaults(self) -> None:
        deps = make_deps(ScriptedProvider([]), config_source=broken_source)
        assert refuse(deps)(state())["reply"] == REFUSAL
        out = render_template_node(deps)(TestVerifyAndRender().good_facts_state())
        assert out["reply"].endswith(TEMPLATE_CLOSING)


class TestStoredTextsAreUsed:
    def test_refusal_and_closing(self) -> None:
        deps = make_deps(
            ScriptedProvider([]),
            config_source=source(refusal_message="Solo cotizo eventos", closing_message="Gracias"),
        )
        out = refuse(deps)(state())
        assert (out["reply"], out["status"], out["reply_source"]) == (
            "Solo cotizo eventos",
            "refused",
            "static",
        )
        s = TestVerifyAndRender().good_facts_state()
        reply = render_template_node(deps)(s)["reply"]
        assert reply.endswith("\nGracias") and TEMPLATE_CLOSING not in reply

    def test_a_price_like_closing_is_rejected_before_it_can_reach_a_quote(self) -> None:
        facts = TestVerifyAndRender().good_facts_state()["facts"]
        with pytest.raises(InvalidAgentConfig):
            config_from("closing_message", "Descuento especial: total $1.000 COP")
        assert render_template(facts) == render_template(facts, TEMPLATE_CLOSING)


def config_from(field: str, text: str):
    return validate_config(replace(DEFAULTS, **{field: text}), None)


class TestTone:
    @pytest.mark.parametrize(
        ("tone", "fragment"),
        [("formal", "usted"), ("cercano", "friendly")],
    )
    def test_each_tone_adds_exactly_one_fixed_line(self, tone: str, fragment: str) -> None:
        system, _ = build_draft_messages("{}", tone)
        extra = [line for line in system.content.splitlines() if line not in NEUTRAL_DRAFT]
        assert len(extra) == 1 and extra[0].startswith("- ") and fragment in extra[0]

    @pytest.mark.parametrize("tone", ["neutral", "unknown", None])
    def test_neutral_and_unknown_are_the_byte_identical_prompt(self, tone) -> None:
        assert build_draft_messages("{}", tone)[0].content == NEUTRAL_DRAFT
        assert build_draft_messages("{}")[0].content == NEUTRAL_DRAFT

    def test_draft_node_uses_the_stored_tone(self) -> None:
        provider = ScriptedProvider([LlmResponse("x", TokenUsage(1, 1), "m")])
        deps = make_deps(provider, config_source=source(tone="formal"))
        draft(deps)(TestVerifyAndRender().good_facts_state())
        assert "usted" in provider.calls[0].messages[0].content


class TestHostileTextNeverReachesAPrompt:
    def test_no_prompt_contains_admin_text(self) -> None:
        hostile = source(
            refusal_message=HOSTILE,
            closing_message=HOSTILE,
            welcome_message=HOSTILE,
            tone="cercano",
        )
        provider = ScriptedProvider(
            [
                LlmResponse(EXTRACTION_JSON, TokenUsage(1, 1), "m"),
                LlmResponse("x", TokenUsage(1, 1), "m"),
            ]
        )
        deps = make_deps(provider, config_source=hostile)
        understand(deps)(state())
        draft(deps)(TestVerifyAndRender().good_facts_state())
        prompts = [m.content for call in provider.calls for m in call.messages]
        assert len(provider.calls) == 2 and not any(HOSTILE in p for p in prompts)
        assert all(
            phrase not in "".join(prompts[2:]) for phrase in SENTINEL_PHRASES
        )  # draft has no leak
        assert "untrusted_conversation" in prompts[0]  # the understand prompt keeps its defences


class TestOffTopicPolicy:
    NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
    KEY = b"k" * 32

    def gate(self, log, policy_source) -> AbuseGate:
        return AbuseGate(log, self.KEY, lambda: self.NOW, limit_source=policy_source)

    @pytest.mark.parametrize(
        ("policy", "refusals", "blocked"),
        [
            ("normal", 4, False),
            ("normal", 5, True),
            ("strict", 2, False),
            ("strict", 3, True),
        ],
    )
    def test_policy_sets_the_limit(self, policy: str, refusals: int, blocked: bool) -> None:
        log = InMemorySecurityLog()
        for _ in range(refusals):
            log.add(CHAT_REFUSED, client_key("1.1.1.1", self.KEY), self.NOW - timedelta(minutes=1))
        gate = self.gate(log, lambda: REFUSED_LIMIT_BY_POLICY[policy])
        assert gate.is_blocked("1.1.1.1") is blocked

    def test_the_limit_is_read_per_request_and_a_failing_source_uses_the_default(self) -> None:
        log = InMemorySecurityLog()
        for _ in range(3):
            log.add(CHAT_REFUSED, client_key("1.1.1.1", self.KEY), self.NOW)
        current = {"policy": "normal"}
        gate = self.gate(log, lambda: REFUSED_LIMIT_BY_POLICY[current["policy"]])
        assert gate.is_blocked("1.1.1.1") is False
        current["policy"] = "strict"
        assert gate.is_blocked("1.1.1.1") is True
        assert self.gate(log, broken_source).is_blocked("1.1.1.1") is False  # default 5 > 3

    def test_constants(self) -> None:
        assert REFUSED_LIMIT_BY_POLICY == {"normal": REFUSED_LIMIT, "strict": 3}
        assert REFUSED_LIMIT == 5

    def test_container_wires_the_policy_into_the_gate(self) -> None:
        from eventssound.entrypoints.api import container

        policy = {"value": "strict"}

        def current():
            return SimpleNamespace(config=config(off_topic_policy=policy["value"]))

        settings = SimpleNamespace(jwt_secret=None, is_production=False, trusted_proxy_hops=1)
        gate = container.make_abuse_gate(
            settings,  # type: ignore[arg-type]
            InMemorySecurityLog(),
            SimpleNamespace(current=current),  # type: ignore[arg-type]
        )
        for _ in range(3):
            gate.record(CHAT_REFUSED, "1.1.1.1")
        assert gate.is_blocked("1.1.1.1") is True
        policy["value"] = "normal"
        assert gate.is_blocked("1.1.1.1") is False
