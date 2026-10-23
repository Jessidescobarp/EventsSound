"""Graph nodes (D1, D9, D10): closures over `AgentDeps`, no money arithmetic, no HTTP.

Every node returns a partial `AgentState` update and a `route` key the graph edges read.
The only LLM calls happen in `understand` and `draft`; everything else is deterministic.
"""

import json
import logging
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
from eventssound.adapters.agent.schemas import Extraction, ItemMention
from eventssound.adapters.agent.state import AgentState
from eventssound.adapters.agent.structured import (
    DeadlineExceeded,
    StructuredOutputInvalid,
    structured_call,
)
from eventssound.application.answer_binding import parse_field_answer, pick_option
from eventssound.application.chat_input import looks_like_injection
from eventssound.application.llm import LlmBadResponse, LlmError, LlmProvider, LlmRequest
from eventssound.application.messages_es import (
    CLARIFICATION_FIELD_ORDER,
    CLARIFICATION_REPHRASE,
    REFUSAL,
    TEMPLATE_CLOSING,
    asked_fields,
    clarified_mentions,
    clarify_item_options,
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
from eventssound.application.search import EquipmentSearch, SearchHit
from eventssound.application.spanish_dates import parse_spanish_date
from eventssound.application.spanish_facts import (
    fold,
    parse_clock_time,
    parse_clock_times,
    parse_duration_hours,
    parse_guest_count,
)
from eventssound.domain.agent_config import AgentConfig
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
BROAD_WISH_MIN = 2  # this many unresolved mentions read as a broad wish, not a precise ask
EVENT_WORD_ES = {
    "wedding": "boda",
    "corporate": "evento corporativo",
    "birthday": "cumpleanos",
    "quinceanera": "quinceanera",
    "graduation": "grado",
    "concert": "concierto",
}
SEARCH_LIMIT = 5
logger = logging.getLogger(__name__)


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
    config_source: Callable[[], AgentConfig] | None = None
    token_factory: Callable[[], str] = partial(secrets.token_hex, 8)
    monotonic: Callable[[], float] = time.monotonic


def _active(deps: AgentDeps) -> AgentConfig | None:
    """The active admin config, or None (static defaults) when there is none or it fails."""
    if deps.config_source is None:
        return None
    try:
        return deps.config_source()
    except Exception:  # noqa: BLE001  (fail-safe: the chat keeps today's behavior)
        return None


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
    if extraction.distance_km is None:  # a locality alone cannot be priced: no km mapping exists
        missing.append("distance_or_locality")
    if not extraction.items and not extraction.needs:
        missing.append("equipment")
    order = {code: index for index, code in enumerate(CLARIFICATION_FIELD_ORDER)}
    return tuple(sorted(missing, key=lambda code: order[code]))


def _with_resolved_date(extraction: Extraction, turns: tuple, today: date) -> Extraction:
    """Code owns Spanish dates: fill a missing or past date from the user's own words."""
    if extraction.event_date is not None and date.fromisoformat(extraction.event_date) >= today:
        return extraction
    for turn in reversed(turns):
        if turn.role != "user":
            continue
        parsed = parse_spanish_date(turn.content, today)
        if parsed is not None:
            return extraction.model_copy(update={"event_date": parsed.isoformat()})
    return extraction


def _with_carried_facts(extraction: Extraction, turns: tuple) -> Extraction:
    """Fill facts the model dropped from earlier user turns; never override a value it gave.

    The agent is stateless, so a turn that only picks an option ("Paquete Boda") makes the model
    forget the time, duration and guest count stated before. Latest user turn wins.
    """
    user_texts = [turn.content for turn in reversed(turns) if turn.role == "user"]
    update: dict = {}
    if extraction.start_time is None:
        update["start_time"] = next((t for x in user_texts if (t := parse_clock_time(x))), None)
    if extraction.end_time is None and extraction.duration_hours is None:
        update["duration_hours"] = next(
            (h for x in user_texts if (h := parse_duration_hours(x))), None
        )
    if extraction.guest_count is None:
        update["guest_count"] = next((g for x in user_texts if (g := parse_guest_count(x))), None)
    update = {key: value for key, value in update.items() if value is not None}
    return extraction.model_copy(update=update) if update else extraction


def _previous_assistant(turns: tuple) -> str | None:
    """The assistant turn the latest user turn answers (client-supplied, so never trusted)."""
    if len(turns) >= 2 and turns[-1].role == "user" and turns[-2].role == "assistant":  # noqa: PLR2004
        return turns[-2].content
    return None


def _with_bound_option(
    extraction: Extraction, turns: tuple, catalog: Catalog
) -> tuple[Extraction, bool]:
    """A reply that is exactly a catalog name IS that choice, whatever the model re-extracted.

    The chosen name replaces the mention the previous clarification asked about (keeping its
    quantity). A package also drops the vague `needs`, which it covers; an item drops only the
    need that was the clarified mention, so unrelated needs still get asked about.
    """
    packages = {fold(p.name) for p in catalog.packages}
    names = tuple(p.name for p in catalog.packages) + tuple(i.name for i in catalog.items)
    last = turns[-1] if turns else None
    chosen = pick_option(last.content, names) if last and last.role == "user" else None
    if chosen is None:
        return extraction, False
    asked = {fold(m) for m in clarified_mentions(_previous_assistant(turns) or "") or ()}
    replaced = [m for m in extraction.items if fold(m.mention) in asked | {fold(chosen)}]
    try:
        pick = ItemMention(mention=chosen, quantity=max((m.quantity for m in replaced), default=1))
    except ValueError:
        return extraction, False
    items = [m for m in extraction.items if m not in replaced] + [pick]
    covered = fold(chosen) in packages or fold(" ".join(extraction.needs)) in asked
    update = {"items": items, "needs": [] if covered else extraction.needs}
    return extraction.model_copy(update=update), True


def _bound_answer(turns: tuple, today: date) -> dict:
    """The latest user turn read as the answer to the FIRST field the last question asked."""
    asked = asked_fields(_previous_assistant(turns) or "")
    return parse_field_answer(asked[0], turns[-1].content, today) if asked else {}


def _without_invented_end(extraction: Extraction, turns: tuple, answer: dict) -> Extraction:
    """Drop a model end time that no user turn stated while a duration was stated.

    Such an end (e.g. echoing the start) fails validation and made the duration question repeat
    even though "por 4 horas" was in the first turn. The user's own words beat the model's guess.
    """
    texts = [t.content for t in turns if t.role == "user"]
    clocks = [c for x in texts for c in parse_clock_times(x)]
    start = extraction.start_time or next(iter(clocks), None)
    stated = {c for c in clocks if c != start} | {answer.get("end_time")}  # an end is not the start
    duration = answer.get("duration_hours") or next(
        (h for x in texts if (h := parse_duration_hours(x))), None
    )
    if (
        extraction.end_time is None
        or extraction.end_time in stated
        or extraction.duration_hours is not None
        or not (duration or answer.get("end_time"))
    ):
        return extraction
    return extraction.model_copy(update={"end_time": None, "end_date": None})


_END_KEYS = ("end_time", "duration_hours")  # one field: a newer answer replaces an older one


def _overlay(base: dict, new: dict) -> dict:
    kept = (
        {k: v for k, v in base.items() if k not in _END_KEYS}
        if new.keys() & set(_END_KEYS)
        else base
    )
    return kept | new


def _with_bound_field(
    extraction: Extraction, turns: tuple, answer: dict, today: date
) -> Extraction:
    """Fill answered fields from this reply and earlier replies to our questions.

    The model forgets them on later turns ("10 KM" is not re-extracted after "Paquete Boda").
    A model value always wins; later replies win over earlier ones.
    """
    merged: dict = {}
    for end in range(2, len(turns)):
        merged = _overlay(merged, _bound_answer(turns[:end], today))
    update = {k: v for k, v in _overlay(merged, answer).items() if getattr(extraction, k) is None}
    if extraction.end_time is not None or extraction.duration_hours is not None:
        update = {k: v for k, v in update.items() if k not in _END_KEYS}
    return extraction.model_copy(update=update) if update else extraction


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
        catalog = deps.load_catalog()
        extraction, chose = _with_bound_option(extraction, state["turns"], catalog)
        answer = _bound_answer(state["turns"], today)
        extraction = _without_invented_end(extraction, state["turns"], answer)
        extraction = _with_bound_field(extraction, state["turns"], answer, today)
        previous = _previous_assistant(state["turns"]) or ""
        ours = bool(asked_fields(previous)) or clarified_mentions(previous) is not None
        if extraction.intent != "quote":
            # The gate already refused injections on every turn. A short reply that parsed as the
            # answer to one of OUR questions is on-topic by construction, whatever the model said.
            if not ((chose or answer) and ours):
                return {"route": "refuse"}
            extraction = extraction.model_copy(update={"intent": "quote"})
        extraction = _with_resolved_date(extraction, state["turns"], today)
        # A reply already bound to its question ("11 PM" = end) must not also be mined as a start.
        extraction = _with_carried_facts(
            extraction, state["turns"][:-1] if answer else state["turns"]
        )
        missing = missing_fields(extraction)
        if missing:
            return {"extraction": extraction, "missing_fields": missing, "route": "clarify"}
        return {"extraction": extraction, "route": "resolve_items"}

    return node


def refuse(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        active = _active(deps)
        reply = active.refusal_message if active else REFUSAL
        return {"status": "refused", "reply": reply, "reply_source": "static"}

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


def _leading_package(hits: tuple[SearchHit, ...]) -> str | None:
    """The first hit when it is a package both search legs found and no rival ties it."""
    if not hits or hits[0].kind != "package":
        return None
    top = hits[0]
    if top.keyword_score is None or top.vector_similarity is None:
        return None
    rival = hits[1].keyword_score if len(hits) > 1 else None
    return top.code if rival is None or top.keyword_score > rival else None


def resolve_items(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        extraction = state["extraction"]
        catalog = deps.load_catalog()
        by_name = {fold(i.name): i.code for i in catalog.items}
        by_name |= {fold(p.name): p.code for p in catalog.packages}
        package_codes = {p.code for p in catalog.packages}
        # A mention that is exactly a catalog name needs no search ranking to be understood.
        exact = [by_name.get(fold(m.mention)) for m in extraction.items]
        queries = [mention.mention for mention in extraction.items]
        needs_query = " ".join(extraction.needs).strip() if extraction.needs else None
        if any(code in package_codes for code in exact):
            # The user named a package: the vague `needs` the model keeps re-extracting from the
            # first turn ("sonido y luces") is that same intent, so it must not ask again.
            needs_query = None
        event_word = EVENT_WORD_ES.get(extraction.event_type or "", "")
        if needs_query:
            queries.append(f"{event_word} {needs_query}".strip())
        results = deps.search.search(queries, None, SEARCH_LIMIT)
        degraded = any(result.degraded for result in results)
        resolved_items: list[RequestedLine] = []
        ambiguous: list[tuple[str, tuple[str, ...]]] = []
        unresolved: list[str] = []
        resolved_packages: list[RequestedLine] = []
        for mention, result, exact_code in zip(extraction.items, results, exact, strict=False):
            codes = list(dict.fromkeys(hit.code for hit in result.hits))
            if exact_code is not None or len(codes) == 1 or result.confident_code is not None:
                code = exact_code or result.confident_code or codes[0]
                if code in package_codes:  # a package is a package line, never an item line
                    resolved_packages.append(RequestedLine(code, 1))
                else:
                    resolved_items.append(RequestedLine(code, mention.quantity))
            elif codes:
                ambiguous.append(
                    (
                        mention.mention,
                        tuple(_catalog_name(catalog, c) for c in codes[:MAX_OPTION_NAMES]),
                    )
                )
            else:
                unresolved.append(mention.mention)
        if len(ambiguous) + len(unresolved) >= BROAD_WISH_MIN and needs_query is None:
            # Several vague mentions ("sonido, luces, DJ") describe a whole service: when the
            # search puts a package first for them plus the event type, that package covers them.
            wish = " ".join(
                [EVENT_WORD_ES.get(extraction.event_type or "", ""), *(m for m, _ in ambiguous)]
                + unresolved
            ).strip()
            top = deps.search.search([wish], None, SEARCH_LIMIT)[0].hits[:1]
            if top and top[0].kind == "package":
                resolved_packages.append(RequestedLine(top[0].code, 1))
                ambiguous, unresolved = [], []
        if needs_query is not None:
            codes = list(
                dict.fromkeys(hit.code for hit in results[-1].hits if hit.kind == "package")
            )
            leader = _leading_package(results[-1].hits)
            if len(codes) == 1 or leader is not None:
                resolved_packages.append(RequestedLine(leader or codes[0], 1))
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
        ambiguous, unresolved = state.get("ambiguous", ()), state.get("unresolved", ())
        reply = render_clarify_items(ambiguous, unresolved)
        # With no match at all, suggest the first catalog packages (deterministic and cheap).
        suggestions = tuple(p.name for p in deps.load_catalog().packages[:MAX_OPTION_NAMES])
        options = clarify_item_options(ambiguous, unresolved, suggestions)
        return {
            "status": "clarification",
            "reply": reply,
            "reply_source": "static",
            "options": options,
        }

    return node


def _event_end(extraction: Extraction, start: datetime) -> datetime:
    tzinfo = start.tzinfo
    if extraction.end_date is not None and extraction.end_time is not None:
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


# Domain validation messages name the offending field. Anything unlisted gets the generic
# "rephrase" clarification (None): it must never be mislabeled as a date question.
_ERROR_FIELDS = (
    ("distance_km", "distance_or_locality"),
    ("guest_count", "guest_count"),
    ("end must be after start", "end_time_or_duration"),
    ("at most 31 days", "end_time_or_duration"),
    ("a request needs", "equipment"),
)


def _failed_field(error: Exception) -> str | None:
    return next((code for key, code in _ERROR_FIELDS if key in str(error)), None)


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
        except (InvalidEventRequest, ValueError) as error:
            logger.info("build_request rejected the extraction: %s", type(error).__name__)
            field = _failed_field(error)
            return {"route": "clarify", "missing_fields": (field,) if field else ()}
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
        active = _active(deps)
        tone = active.tone if active else None
        try:
            text = _complete_draft(deps, state, build_draft_messages(json.dumps(payload), tone))
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
        active = _active(deps)
        closing = active.closing_message if active else TEMPLATE_CLOSING
        return {
            "reply": render_template(state["facts"], closing),
            "reply_source": "template",
            "status": "quote",
        }

    return node


def finalize(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def node(state: AgentState) -> dict:
        return {"reply": state["draft"], "reply_source": "llm", "status": "quote"}

    return node
