"""The LangGraph shared state (D5): forward-only keys, no back edges.

Values arrive once and stay: later nodes never mutate an earlier node's output. `degraded`
is the only reduced channel (appended), so a degraded search is visible on the final outcome.
"""

from datetime import datetime
from typing import Annotated, NotRequired, TypedDict

from eventssound.adapters.agent.schemas import Extraction
from eventssound.application.proposal_check import QuoteFacts
from eventssound.application.quote_chat import ChatTurn, UsageMeter
from eventssound.domain.availability import AvailabilityReport
from eventssound.domain.event_request import EventRequest, RequestedLine
from eventssound.domain.pricing import Quote


def _append(values: list[str], update: list[str]) -> list[str]:
    return values + update


class AgentState(TypedDict):
    # Input, set once by the runner.
    turns: tuple[ChatTurn, ...]
    now: datetime
    meter: UsageMeter
    deadline: float

    # Understand stage.
    extraction: NotRequired[Extraction]
    missing_fields: NotRequired[tuple[str, ...]]
    route: NotRequired[str]

    # Resolve stage.
    resolved_items: NotRequired[tuple[RequestedLine, ...]]
    resolved_packages: NotRequired[tuple[RequestedLine, ...]]
    ambiguous: NotRequired[tuple[tuple[str, tuple[str, ...]], ...]]
    unresolved: NotRequired[tuple[str, ...]]

    # Quote stage.
    event_request: NotRequired[EventRequest]
    availability: NotRequired[AvailabilityReport]
    quote: NotRequired[Quote]
    facts: NotRequired[QuoteFacts]
    draft: NotRequired[str]

    # Outcome.
    reply: NotRequired[str]
    reply_source: NotRequired[str]
    status: NotRequired[str]

    # Shared, append-only.
    degraded: Annotated[list[str], _append]
