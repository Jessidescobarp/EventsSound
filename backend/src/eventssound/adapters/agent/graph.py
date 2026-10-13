"""The LangGraph wiring (D5): forward-only edges, no back edges, recursion limit 16.

The graph is pure plumbing: every decision lives in a node's `route` key, and the only
model-dependent steps are `understand` and `draft`.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from eventssound.adapters.agent.nodes import (
    AgentDeps,
    build_request,
    check_availability,
    clarify,
    clarify_items,
    draft,
    finalize,
    gate,
    price,
    refuse,
    render_template_node,
    resolve_items,
    understand,
    verify,
)
from eventssound.adapters.agent.state import AgentState
from eventssound.application.quote_chat import AgentInput, AgentOutcome, AgentStatus

RECURSION_LIMIT = 16

_NODES = {
    "gate": gate,
    "understand": understand,
    "refuse": refuse,
    "clarify": clarify,
    "resolve_items": resolve_items,
    "clarify_items": clarify_items,
    "build_request": build_request,
    "check_availability": check_availability,
    "price": price,
    "draft": draft,
    "verify": verify,
    "render_template": render_template_node,
    "finalize": finalize,
}

_ROUTES = {
    "gate": {"refuse": "refuse", "understand": "understand"},
    "understand": {
        "refuse": "refuse",
        "clarify": "clarify",
        "resolve_items": "resolve_items",
    },
    "resolve_items": {"clarify_items": "clarify_items", "build_request": "build_request"},
    "build_request": {"clarify": "clarify", "check_availability": "check_availability"},
    "draft": {"verify": "verify", "render_template": "render_template"},
    "verify": {"finalize": "finalize", "render_template": "render_template"},
}

_ENDING_NODES = ("refuse", "clarify", "clarify_items", "render_template", "finalize")


def _route(state: AgentState) -> str:
    return state["route"]


def build_graph(deps: AgentDeps) -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    for name, factory in _NODES.items():
        graph.add_node(name, factory(deps))
    graph.add_edge(START, "gate")
    for name, routes in _ROUTES.items():
        graph.add_conditional_edges(name, _route, routes)
    for name in _ENDING_NODES:
        graph.add_edge(name, END)
    graph.add_edge("check_availability", "price")
    graph.add_edge("price", "draft")
    return graph.compile()


class GraphQuoteAgent:
    """The `QuoteAgent` implementation: AgentInput in, AgentOutcome out (D5)."""

    def __init__(self, deps: AgentDeps) -> None:
        self._graph = build_graph(deps)

    def run(self, data: AgentInput) -> AgentOutcome:
        initial: AgentState = {
            "turns": data.turns,
            "now": data.now,
            "meter": data.meter,
            "deadline": data.deadline_monotonic,
            "degraded": [],
        }
        final = self._graph.invoke(initial, {"recursion_limit": RECURSION_LIMIT})
        return AgentOutcome(
            status=AgentStatus(final["status"]),
            reply=final.get("reply", ""),
            reply_source=final.get("reply_source", "static"),
            quote=final.get("quote"),
            event_request=final.get("event_request"),
            availability=final.get("availability"),
            missing_fields=final.get("missing_fields", ()),
            degraded=tuple(final.get("degraded", ())),
        )
