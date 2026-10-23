import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.llm import LlmError
from eventssound.application.messages_es import WELCOME
from eventssound.application.messages_es_chat import CHAT_ERRORS
from eventssound.application.quote_chat import (
    AgentStatus,
    BudgetExhausted,
    ChatTurn,
    InvalidChat,
    RateLimited,
    quote_chat,
)
from eventssound.application.quotes import NewQuote, record_quote
from eventssound.application.security import CHAT_REFUSED
from eventssound.entrypoints.api.auth_kit import optional_principal
from eventssound.entrypoints.api.client_ip import client_ip
from eventssound.entrypoints.api.guards import ChatRefusal, chat_guard
from eventssound.entrypoints.api.schemas import (
    ChatErrorOut,
    ChatInvalidOut,
    ChatRequestIn,
    ChatResponseOut,
    QuoteConfigOut,
)

router = APIRouter(prefix="/quote", tags=["Quote agent"], dependencies=[Depends(chat_guard)])

# Public and read-only, so it skips the chat guard: the greeting is still shown when chat is off.
config_router = APIRouter(prefix="/quote", tags=["Quote agent"])

logger = logging.getLogger(__name__)

BLOCK_RETRY_SECONDS = 600  # the block window; the real end can be sooner

_QUOTE_LINE = {"periods": 1, "rate_bps": None, "basis": None}
RESPONSE_EXAMPLES: dict[str, dict[str, object]] = {
    "quote_ready": {
        "request_id": "4f0c1d7e9a3b4c5d8e6f708192a3b4c5",
        "status": "quote",
        "reply": "Esta es tu propuesta:\n- 2 x Parlante activo 15 pulgadas: $240.000 COP\n"
        "- 1 x Mezcladora 16 canales: $79.900 COP\n- Ajuste de redondeo: $100 COP\n"
        "Total: $320.000 COP\nLos valores los calcula nuestro sistema de precios.",
        "quote": {
            "version": 1,
            "rules_version": "synthetic-v1",
            "currency": "COP",
            "rental_days": 1,
            "lines": [
                {
                    **_QUOTE_LINE,
                    "kind": "item",
                    "code": "sound_speaker_active_15",
                    "label": "Parlante activo 15 pulgadas",
                    "quantity": 2,
                    "unit_amount": 120000,
                    "amount": 240000,
                },
                {
                    **_QUOTE_LINE,
                    "kind": "item",
                    "code": "sound_mixer_16ch",
                    "label": "Mezcladora 16 canales",
                    "quantity": 1,
                    "unit_amount": 79900,
                    "amount": 79900,
                },
                {
                    **_QUOTE_LINE,
                    "kind": "rounding",
                    "code": "rounding",
                    "label": None,
                    "quantity": 1,
                    "unit_amount": None,
                    "amount": 100,
                },
            ],
            "subtotal": 319900,
            "total": 320000,
        },
        "event_request": {
            "event_type": "other",
            "start": "2026-10-17T20:00:00-05:00",
            "end": "2026-10-17T23:30:00-05:00",
            "guest_count": 150,
            "distance_km": 45,
            "venue": "indoor",
            "items": [
                {"code": "sound_speaker_active_15", "quantity": 2},
                {"code": "sound_mixer_16ch", "quantity": 1},
            ],
            "packages": [],
        },
        "availability": {"is_available": True, "shortages": []},
        "missing_fields": [],
        "reply_source": "llm",
    },
    "needs_more_info": {
        "request_id": "9a1b2c3d4e5f60718293a4b5c6d7e8f9",
        "status": "clarification",
        "reply": "Para armar tu cotizacion: Cuantos invitados habra? (por ejemplo: 60)",
        "quote": None,
        "event_request": None,
        "availability": None,
        "missing_fields": ["guest_count"],
        "reply_source": "static",
        "options": [],
    },
    "refused": {
        "request_id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        "status": "refused",
        "reply": "Solo puedo ayudarte a cotizar equipos de sonido, luces y DJ para eventos.",
        "quote": None,
        "event_request": None,
        "availability": None,
        "missing_fields": [],
        "reply_source": "static",
    },
}


def _example(code: str) -> dict[str, object]:
    return {"summary": code, "value": {"detail": code, "message": CHAT_ERRORS[code]}}


def _examples(*codes: str) -> dict[str, object]:
    return {"content": {"application/json": {"examples": {c: _example(c) for c in codes}}}}


RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "content": {
            "application/json": {
                "examples": {k: {"summary": k, "value": v} for k, v in RESPONSE_EXAMPLES.items()}
            }
        }
    },
    413: {"model": ChatErrorOut, "description": "The body is larger than 16 KiB."},
    422: {
        "model": ChatInvalidOut,
        "description": "Bad shape or length. Field paths and codes only, never the input.",
        "content": {
            "application/json": {
                "example": {
                    "detail": "invalid_request",
                    "message": CHAT_ERRORS["invalid_request"],
                    "errors": [{"field": "messages.0.content", "code": "string_too_long"}],
                }
            }
        },
    },
    429: {
        "model": ChatErrorOut,
        "description": "Too many requests from this client, or `temporarily_blocked` after "
        "several off-topic refusals in 10 minutes; the limit is 3 or 5 depending on the "
        "configured policy. Wait `Retry-After` seconds.",
        "headers": {"Retry-After": {"schema": {"type": "integer", "minimum": 1, "example": 37}}},
        **_examples("rate_limited", "temporarily_blocked"),
    },
    503: {
        "model": ChatErrorOut,
        "description": "The assistant is off, out of daily budget, or its provider is down.",
        **_examples(
            "chat_disabled", "daily_budget_exhausted", "llm_unavailable", "catalog_unavailable"
        ),
    },
    500: {"model": ChatErrorOut, "description": "Unexpected failure; no detail is exposed."},
}


def _error(code: str, status: int, request_id: str | None = None, **headers: str) -> JSONResponse:
    if request_id:
        headers["X-Request-ID"] = request_id
    return JSONResponse(
        {"detail": code, "message": CHAT_ERRORS[code]},
        status_code=status,
        headers={"Cache-Control": "no-store", **headers},
    )


def chat_refusal_handler(_: Request, exc: ChatRefusal) -> JSONResponse:
    return _error(exc.code, exc.status)


def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Field path and error code only: FastAPI's default 422 body echoes the user's text."""
    errors = [
        {"field": ".".join(str(p) for p in err["loc"][1:]), "code": str(err["type"])}
        for err in exc.errors()[:10]
    ]
    body = {
        "detail": "invalid_request",
        "message": CHAT_ERRORS["invalid_request"],
        "errors": errors,
    }
    headers = {"X-Request-ID": uuid.uuid4().hex, "Cache-Control": "no-store"}
    return JSONResponse(body, status_code=422, headers=headers)


@router.post(
    "/chat",
    response_model=ChatResponseOut,
    summary="Describe tu evento y recibe una cotizacion",
    description=(
        "Chat with the quote assistant. Send the conversation so far (up to 16 messages of 1,000 "
        "characters, the last one from the user) and receive either a quote, the questions still "
        "needed, or a polite refusal when the message is not about quoting an event. Prices come "
        "from the company's pricing rules, never from the AI. All data is synthetic. The server "
        "keeps no conversation."
    ),
    responses=RESPONSES,
)
def post_chat(body: ChatRequestIn, request: Request) -> JSONResponse:
    state = request.app.state
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    ip = client_ip(request, state.settings.trusted_proxy_hops)
    gate = state.abuse_gate
    if gate.is_blocked(ip):
        # Before the limiter, the budget and the model: a blocked client costs nothing. Not stored
        # (the _refuse log line below counts it), so a flood cannot grow the table.
        return _refuse(
            "temporarily_blocked", 429, request_id, **{"Retry-After": str(BLOCK_RETRY_SECONDS)}
        )
    try:
        result = quote_chat(
            [ChatTurn(m.role, m.content) for m in body.messages],
            ip,
            agent=state.chat_agent,
            budget=state.usage_budget,
            limiter=state.rate_limiter,
            clock=lambda: datetime.now(UTC),
            limits=state.chat_limits_source(),
            request_id=request_id,
        )
        # Serialized inside the try: a failure here is a safe 500 with the request id.
        payload = ChatResponseOut.from_outcome(request_id, result.outcome).model_dump(mode="json")
    except RateLimited as exc:
        retry = {"Retry-After": str(max(1, exc.retry_after_seconds))}
        return _refuse("rate_limited", 429, request_id, **retry)
    except BudgetExhausted:
        return _refuse("daily_budget_exhausted", 503, request_id)
    except InvalidChat:
        logger.info("chat refused request_id=%s outcome=invalid_chat", request_id)
        errors = [{"field": "messages", "code": "invalid_chat"}]
        return JSONResponse(
            {
                "detail": "invalid_request",
                "message": CHAT_ERRORS["invalid_request"],
                "errors": errors,
            },
            status_code=422,
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
    except LlmError as exc:
        # Only the class and a constant reason code (not_json, ...): never provider text.
        logger.warning(
            "chat llm error request_id=%s error=%s reason=%s",
            request_id,
            type(exc).__name__,
            getattr(exc, "reason", "-"),
        )
        return _refuse("llm_unavailable", 503, request_id)
    except (RepositoryUnavailable, InvalidStoredData):
        return _refuse("catalog_unavailable", 503, request_id)
    except Exception as exc:
        # Only the class is logged: the message may carry hosts or keys.
        logger.error("chat failed request_id=%s error=%s", request_id, type(exc).__name__)
        return _error("internal_error", 500, request_id)

    outcome, meter = result.outcome, result.meter
    if outcome.status is AgentStatus.REFUSED:
        gate.record(CHAT_REFUSED, ip)
    if outcome.status is AgentStatus.QUOTE and outcome.quote and outcome.event_request:
        try:
            who = optional_principal(request)
            event = outcome.event_request
            payload["quote_id"] = record_quote(
                state.quote_store,
                NewQuote(
                    user_id=who.user_id if who else None,
                    event_type=event.event_type.value,
                    event_start=event.start,
                    event_end=event.end,
                    guest_count=event.guest_count,
                    total_cop=payload["quote"]["total"],
                    available=None
                    if outcome.availability is None
                    else outcome.availability.is_available,
                    quote=payload["quote"],
                    event_request=payload["event_request"],
                ),
            )
        except Exception as exc:  # saving is best effort: the customer still gets the quote
            logger.warning("quote not saved request_id=%s error=%s", request_id, type(exc).__name__)
            payload["quote_id"] = None
    logger.info(
        "chat request_id=%s status=%s source=%s tokens=%d llm_calls=%d tools=%s degraded=%d ms=%d",
        request_id,
        outcome.status.value,
        outcome.reply_source,
        meter.total_tokens,
        meter.llm_calls,
        ",".join(meter.tools),
        len(outcome.degraded),
        int((time.monotonic() - started) * 1000),
    )
    return JSONResponse(payload, headers={"X-Request-ID": request_id, "Cache-Control": "no-store"})


def _refuse(code: str, status: int, request_id: str, **headers: str) -> JSONResponse:
    logger.info("chat refused request_id=%s outcome=%s", request_id, code)
    return _error(code, status, request_id, **headers)


@config_router.get(
    "/config",
    response_model=QuoteConfigOut,
    summary="Mensaje de bienvenida del asistente",
    description=(
        "Public, no login. The greeting the chat opens with, as configured by an admin (a "
        "default when none is stored). It exposes nothing else of the agent configuration. "
        "Served from a short in-memory cache, never a database read per request."
    ),
    responses={
        200: {
            "content": {"application/json": {"example": {"welcome_message": WELCOME}}},
            "headers": {"Cache-Control": {"schema": {"example": "public, max-age=30"}}},
        }
    },
)
def get_quote_config(request: Request) -> JSONResponse:
    try:
        message = request.app.state.agent_config.current().config.welcome_message
        if not isinstance(message, str) or not message:
            message = WELCOME
    except Exception as exc:  # public read: any failure serves the default
        logger.warning("welcome message unavailable: %s", type(exc).__name__)
        message = WELCOME
    return JSONResponse(
        {"welcome_message": message}, headers={"Cache-Control": "public, max-age=30"}
    )
