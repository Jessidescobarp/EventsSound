"""Graph nodes (D1, D9, D10): closures over `AgentDeps`, no money arithmetic, no HTTP.

Every node returns a partial `AgentState` update and a `route` key the graph edges read.
The only LLM calls happen in `understand` and `draft`; everything else is deterministic.
"""

import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from functools import partial
from typing import TYPE_CHECKING

from eventssound.adapters.agent.prompts import (
    SENTINEL_PHRASES,
    build_draft_messages,
    build_understand_messages,
)
from eventssound.adapters.agent.schemas import Extraction
from eventssound.adapters.agent.state import AgentState
from eventssound.adapters.agent.structured import (
    DeadlineExceeded,
    StructuredOutputInvalid,
    structured_call,
)
from eventssound.application.chat_input import looks_like_injection
from eventssound.application.llm import LlmBadResponse, LlmError, LlmProvider, LlmRequest
from eventssound.application.messages_es import (
    CLARIFICATION_FIELD_ORDER,
    CLARIFICATION_REPHRASE,
    REFUSAL,
    render_clarification,
    render_clarify_items,
)
from eventssound.application.proposal_check import (
    QuoteFacts,
    ShortageFact,
    facts_payload,
    render_template,
    verify_proposal,
)
from eventssound.application.quote_chat import AgentLimitExceeded, ChatLimits
from eventssound.application.search import EquipmentSearch
from eventssound.domain.availability import AvailabilityReport
from eventssound.domain.catalog import Catalog
from eventssound.domain.errors import InvalidEventRequest
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.pricing import Quote

if TYPE_CHECKING:
    from datetime import tzinfo

DRAFT_TEMPERATURE = 0.3
DRAFT_MAX_OUTPUT_TOKENS = 500
UNDERSTAND_MAX_OUTPUT_TOKENS = 400
MAX_HORIZON_DAYS = 730
MAX_OPTION_NAMES = 3
SEARCH_LIMIT = 5


@dataclass(frozen=True, slots=True)
class AgentDeps:
    """Everything a node may touch, injected once per process (the container wires it)."""

    provider: LlmProvider
    search: EquipmentSearch
    load_catalog: Callable[[], Catalog]
    check_availability: Callable[[EventRequest], AvailabilityReport]
    price: Callable[[EventRequest], Quote]
    limits: ChatLimits
    timezone: "tzinfo"
    scenario: str | None = None
    token_factory: Callable[[], str] = partial(secrets.token_hex, 8)
    monotonic: Callable[[], float] = time.monotonic


def missing_fields(extraction: Extraction) -> tuple[str, ...]:
    """The D9 policy, in fixed priority order; the clarify node shows at most 3."""
    missing: list[str] = []
    if extraction.event_date is None:
        missing.append("event_date")
    if extraction.start_time is None:
        missing.append("start_time")
    if extraction.end_time is None and extraction.duration_hours is None:
        missing.append("end_time_or_duration")
    if extraction.guest_count is None:
        missing.append("guest_count")
    if extraction.distance_km is None and extraction.locality is None:
        missing.append("distance_or_locality")
    if not extraction.items and not extraction.needs:
        missing.append("equipment")
    order = {code: index for index, code in enumerate(CLARIFICATION_FIELD_ORDER)}
    return tuple(sorted(missing, key=lambda code: order[code]))


def gate(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        if any(looks_like_injection(turn.content) for turn in state["turns"]):
            return {"route": "refuse"}
        return {"route": "understand"}

    return node


def understand(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        token = deps.token_factory()
        today = state["now"].astimezone(deps.timezone).date()
        messages = build_understand_messages(
            state["turns"],
            today=today,
            nonce=token,
            canary=token,
            schema_json=json.dumps(Extraction.model_json_schema()),
        )
        try:
            extraction = structured_call(
                provider=deps.provider,
                node="understand",
                messages=messages,
                model_cls=Extraction,
                meter=state["meter"],
                limits=deps.limits,
                deadline_monotonic=state["deadline"],
                max_output_tokens=UNDERSTAND_MAX_OUTPUT_TOKENS,
                scenario=deps.scenario,
            )
        except StructuredOutputInvalid:
            return {"route": "clarify", "missing_fields": ()}
        if extraction.intent != "quote":
            return {"route": "refuse"}
        missing = missing_fields(extraction)
        if missing:
            return {"extraction": extraction, "missing_fields": missing, "route": "clarify"}
        return {"extraction": extraction, "route": "resolve_items"}

    return node


def refuse(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        return {"status": "refused", "reply": REFUSAL, "reply_source": "static"}

    return node


def clarify(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        missing = state.get("missing_fields") or ()
        reply = render_clarification(missing) if missing else CLARIFICATION_REPHRASE
        return {"status": "clarification", "reply": reply, "reply_source": "static"}

    return node


def _catalog_name(catalog: Catalog, code: str) -> str:
    try:
        return catalog.item(code).name
    except Exception:
        return catalog.package(code).name


def resolve_items(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        extraction = state["extraction"]
        catalog = deps.load_catalog()
        queries = [mention.mention for mention in extraction.items]
        needs_query = " ".join(extraction.needs).strip() if extraction.needs else None
        if needs_query:
            queries.append(needs_query)
        results = deps.search.search(queries, None, SEARCH_LIMIT)
        degraded = any(result.degraded for result in results)
        resolved_items: list[RequestedLine] = []
        ambiguous: list[tuple[str, tuple[str, ...]]] = []
        unresolved: list[str] = []
        for mention, result in zip(extraction.items, results, strict=False):
            codes = list(dict.fromkeys(hit.code for hit in result.hits))
            if len(codes) == 1:
                resolved_items.append(RequestedLine(codes[0], mention.quantity))
            elif codes:
                ambiguous.append(
                    (
                        mention.mention,
                        tuple(_catalog_name(catalog, c) for c in codes[:MAX_OPTION_NAMES]),
                    )
                )
            else:
                unresolved.append(mention.mention)
        resolved_packages: list[RequestedLine] = []
        if needs_query is not None:
            codes = list(
                dict.fromkeys(hit.code for hit in results[-1].hits if hit.kind == "package")
            )
            if len(codes) == 1:
                resolved_packages.append(RequestedLine(codes[0], 1))
            elif codes:
                ambiguous.append(
                    (
                        needs_query,
                        tuple(_catalog_name(catalog, c) for c in codes[:MAX_OPTION_NAMES]),
                    )
                )
            else:
                unresolved.append(needs_query)
        update: dict = {
            "resolved_items": tuple(resolved_items),
            "resolved_packages": tuple(resolved_packages),
            "ambiguous": tuple(ambiguous),
            "unresolved": tuple(unresolved),
            "route": "clarify_items" if (ambiguous or unresolved) else "build_request",
        }
        if degraded:
            update["degraded"] = ["embedding_fallback"]
        return update

    return node


def clarify_items(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        reply = render_clarify_items(state.get("ambiguous", ()), state.get("unresolved", ()))
        return {"status": "clarification", "reply": reply, "reply_source": "static"}

    return node


def _event_end(extraction: Extraction, start: datetime) -> datetime:
    tzinfo = start.tzinfo
    if extraction.end_date is not None:
        if extraction.end_time is None:
            raise InvalidEventRequest("end_date requires end_time")
        return datetime.combine(
            date.fromisoformat(extraction.end_date),
            dtime.fromisoformat(extraction.end_time),
            tzinfo=tzinfo,
        )
    if extraction.duration_hours is not None:
        return start + timedelta(hours=extraction.duration_hours)
    end = datetime.combine(start.date(), dtime.fromisoformat(extraction.end_time), tzinfo=tzinfo)
    if end <= start:
        end += timedelta(days=1)
    return end


def build_request(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        extraction = state["extraction"]
        tzinfo = deps.timezone
        try:
            start = datetime.combine(
                date.fromisoformat(extraction.event_date),
                dtime.fromisoformat(extraction.start_time),
                tzinfo=tzinfo,
            )
            end = _event_end(extraction, start)
            request = EventRequest(
                event_type=EventType(extraction.event_type or "other"),
                start=start,
                end=end,
                guest_count=extraction.guest_count,
                distance_km=extraction.distance_km,
                venue=VenueType(extraction.venue or "indoor"),
                items=tuple(state.get("resolved_items", ())),
                packages=tuple(state.get("resolved_packages", ())),
            )
        except (InvalidEventRequest, ValueError):
            return {"route": "clarify", "missing_fields": ("event_date",)}
        now = state["now"]
        if request.start <= now or request.start > now + timedelta(days=MAX_HORIZON_DAYS):
            return {"route": "clarify", "missing_fields": ("event_date",)}
        return {"event_request": request, "route": "check_availability"}

    return node


def check_availability(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        report = deps.check_availability(state["event_request"])
        return {"availability": report, "route": "price"}

    return node


def price(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        quote = deps.price(state["event_request"])
        return {"quote": quote, "status": "quote", "route": "draft"}

    return node


def _complete_draft(deps: AgentDeps, state: AgentState, messages: tuple) -> str:
    meter = state["meter"]
    if meter.llm_calls >= deps.limits.max_llm_calls:
        raise AgentLimitExceeded(f"llm call cap {deps.limits.max_llm_calls} reached")
    remaining = state["deadline"] - deps.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded()
    meter.llm_calls += 1
    response = deps.provider.complete(
        LlmRequest(
            node="draft",
            messages=messages,
            temperature=DRAFT_TEMPERATURE,
            max_output_tokens=DRAFT_MAX_OUTPUT_TOKENS,
            timeout_s=min(25.0, remaining),
            scenario=deps.scenario,
        )
    )
    meter.prompt_tokens += response.usage.prompt_tokens
    meter.completion_tokens += response.usage.completion_tokens
    if response.finish_reason == "length":
        raise LlmBadResponse()
    return response.text


def draft(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        request = state["event_request"]
        catalog = deps.load_catalog()
        report = state["availability"]
        shortages = tuple(
            ShortageFact(
                item.item_code,
                _catalog_name(catalog, item.item_code),
                item.requested,
                item.remaining,
            )
            for item in report.shortages
        )
        canary = deps.token_factory()
        facts = QuoteFacts.from_quote(
            state["quote"],
            request,
            catalog,
            canary=canary,
            sentinel_phrases=SENTINEL_PHRASES,
            shortages=shortages,
        )
        # A shortage is served deterministically: the template renders the pinned Spanish
        # "hay N" lines, and the LLM draft is never trusted to restate stock.
        if report.shortages:
            return {"facts": facts, "route": "render_template"}
        payload = facts_payload(
            facts, event_type=request.event_type.value, available=report.is_available
        )
        try:
            text = _complete_draft(deps, state, build_draft_messages(json.dumps(payload)))
        except LlmError:
            return {"facts": facts, "route": "render_template"}
        return {"facts": facts, "draft": text, "route": "verify"}

    return node


def verify(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        result = verify_proposal(state["draft"], state["facts"])
        return {"route": "finalize" if result.ok else "render_template"}

    return node


def render_template_node(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        return {
            "reply": render_template(state["facts"]),
            "reply_source": "template",
            "status": "quote",
        }

    return node


def finalize(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        return {"reply": state["draft"], "reply_source": "llm", "status": "quote"}

    return node
