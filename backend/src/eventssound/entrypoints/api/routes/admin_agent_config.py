"""Admin API for the agent configuration: read, preview, apply and history. Admin only."""

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from eventssound.application.agent_config_admin import (
    CEILINGS,
    AgentConfigAdmin,
    NoChanges,
    Plan,
    UnknownVersion,
    failing_field,
    risk_warnings,
)
from eventssound.application.confirmation import ConfirmationError, ConfirmationTokens
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable, VersionConflict
from eventssound.application.messages_es_agent_config import CONFIG_ERRORS
from eventssound.application.messages_es_auth import AUTH_ERRORS
from eventssound.application.quote_chat import RateLimited
from eventssound.application.security import CONFIG_REAUTH_FAILED, CONFIG_REJECTED
from eventssound.domain.errors import InvalidAgentConfig
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import AuthKit, require_role
from eventssound.entrypoints.api.client_ip import client_ip
from eventssound.entrypoints.api.schemas_agent_config import (
    AgentConfigOut,
    AgentConfigViewOut,
    ApplyIn,
    ApplyOut,
    ChangeIn,
    HistoryItemOut,
    PreviewOut,
)

logger = logging.getLogger(__name__)


def no_store(response: Response) -> None:
    """Success bodies carry the config and, for a preview, the confirmation token."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/admin", tags=["Agent configuration"], dependencies=[Depends(no_store)])

AdminOnly = Annotated[Principal, Depends(require_role(Role.ADMIN))]
MESSAGES = {**AUTH_ERRORS, **CONFIG_ERRORS}
ERRORS = {
    401: {"description": "not_authenticated"},
    403: {"description": "forbidden"},
    503: {"description": "storage_unavailable or confirmation_unavailable"},
}


def refuse(status: int, code: str, **extra: object) -> JSONResponse:
    body = {"detail": code, "message": MESSAGES[code], **extra}
    headers = {"Cache-Control": "no-store"}
    if code == "rate_limited":
        headers["Retry-After"] = str(extra.get("retry_after", 60))
    return JSONResponse(body, status_code=status, headers=headers)


def admin_service(request: Request) -> AgentConfigAdmin:
    return request.app.state.agent_config_admin


def over_limit(request: Request, who: Principal) -> JSONResponse | None:
    """Per-admin burst control for preview and apply (in-process; fails closed)."""
    try:
        decision = request.app.state.agent_config_limiter.hit(who.user_id)
    except RateLimited as error:
        return refuse(429, "rate_limited", retry_after=error.retry_after_seconds)
    if not decision.allowed:
        return refuse(429, "rate_limited", retry_after=max(1, decision.retry_after_seconds))
    return None


@dataclass(frozen=True, slots=True)
class Refusal:
    status: int
    code: str
    extra: dict[str, object] = field(default_factory=dict)

    def response(self) -> JSONResponse:
        return refuse(self.status, self.code, **self.extra)


def plan_or_refusal(service: AgentConfigAdmin, body: ChangeIn) -> Plan | Refusal:
    """The validated plan, or why the request is refused (field names only, never values)."""
    try:
        note = body.note if isinstance(body, ApplyIn) else None
        return service.plan(body.changes, body.rollback_to_version, body.base_version, note)
    except VersionConflict:
        return Refusal(409, "version_conflict")
    except NoChanges:
        return Refusal(422, "no_changes")
    except UnknownVersion:
        return Refusal(422, "unknown_version")
    except InvalidAgentConfig as error:
        name = failing_field(error)
        return Refusal(422, "invalid_config", {"fields": [name] if name else []})
    except (RepositoryUnavailable, InvalidStoredData) as error:
        logger.warning("agent config unavailable error=%s", type(error).__name__)
        return Refusal(503, "storage_unavailable")


@router.get(
    "/agent-config",
    response_model=AgentConfigViewOut,
    summary="Configuracion actual del agente",
    description=(
        "The active agent configuration (version 0 means the environment defaults), the hard "
        "ceilings, the allowed models and a read-only view of the model in use. Never exposes "
        "the provider URL or any key. Admin only."
    ),
    responses=ERRORS,
)
def get_agent_config(request: Request, who: AdminOnly) -> AgentConfigViewOut | JSONResponse:
    service = admin_service(request)
    try:
        current = service.current()
    except (RepositoryUnavailable, InvalidStoredData) as error:
        logger.warning("agent config unavailable error=%s", type(error).__name__)
        return refuse(503, "storage_unavailable")
    return AgentConfigViewOut.model_validate(
        {
            "version": current.version,
            "config": current.config.to_dict(),
            "ceilings": CEILINGS,
            "allowed_models": list(service.allowed_models),
            "free_models": service.free_models,
            "paid_models": service.paid_models,
            "model_in_use": asdict(service.model_in_use(current.config)),
            "defaults_out_of_bounds": service.out_of_bounds(current.config),
            "updated_at": current.updated_at.isoformat() if current.updated_at else None,
            "updated_by": current.updated_by,
        }
    )


@router.post(
    "/agent-config/preview",
    response_model=PreviewOut,
    summary="Previsualizar un cambio del agente",
    description=(
        "Validates a partial change (or a rollback to an earlier version) against the current "
        "version, returns the field-by-field diff, the risks, whether a password will be needed "
        "and a single-use confirmation token (5 minutes) to send to apply. 409 when "
        "`base_version` is not the current version, 422 for invalid fields (names only) or no "
        "changes. Admin only; rate limited per user."
    ),
    responses={
        **ERRORS,
        409: {"description": "version_conflict"},
        422: {"description": "invalid_config, no_changes or unknown_version"},
        429: {"description": "rate_limited"},
    },
)
def preview_change(request: Request, who: AdminOnly, body: ChangeIn) -> PreviewOut | JSONResponse:
    tokens: ConfirmationTokens | None = request.app.state.confirmation_tokens
    if tokens is None:
        return refuse(503, "confirmation_unavailable")
    if (limited := over_limit(request, who)) is not None:
        return limited
    service = admin_service(request)
    plan = plan_or_refusal(service, body)
    if isinstance(plan, Refusal):
        return plan.response()
    estimate = service.max_daily_cost_estimate(plan.new)
    token, expires_at = tokens.issue(who.user_id, plan.base_version, plan.digest)
    return PreviewOut.model_validate(
        {
            "action": plan.action,
            "base_version": plan.base_version,
            "diff": plan.diff,
            "warnings": [
                asdict(w) for w in risk_warnings(plan, service.model_in_use(plan.new), estimate)
            ],
            "requires_password": plan.requires_password,
            "max_daily_cost_estimate_micro_usd": estimate,
            "confirmation_token": token,
            "expires_at": datetime.fromtimestamp(expires_at, UTC).isoformat(),
        }
    )


TYPED_CONFIRMATION = "APLICAR"


def reject(
    request: Request,
    who: Principal,
    status: int,
    code: str,
    event: str = CONFIG_REJECTED,
    **extra: object,
) -> JSONResponse:
    """Refuse an apply and leave a trace: a structured warning (code and user only, never a
    value) and a security event keyed by the caller's hashed address."""
    logger.warning("agent config change rejected code=%s user=%s", code, who.user_id)
    hops = request.app.state.settings.trusted_proxy_hops
    request.app.state.abuse_gate.record(event, client_ip(request, hops))
    return refuse(status, code, **extra)


def reauthenticate(request: Request, who: Principal, password: str | None) -> JSONResponse | None:
    """Re-check the admin's password, rate limited like login. None means it is verified."""
    kit: AuthKit = request.app.state.auth
    if not password:
        return reject(request, who, 422, "password_required")
    try:
        decision = kit.email_limiter.hit(f"reauth:{who.user_id}")
    except RateLimited as error:
        return refuse(429, "rate_limited", retry_after=error.retry_after_seconds)
    if not decision.allowed:
        return refuse(429, "rate_limited", retry_after=max(1, decision.retry_after_seconds))
    try:
        verified = kit.service.verify_password(who.user_id, password)
    except RepositoryUnavailable:
        return refuse(503, "auth_unavailable")
    if not verified:
        return reject(request, who, 403, "reauth_failed", CONFIG_REAUTH_FAILED)
    return None


@router.put(
    "/agent-config/apply",
    response_model=ApplyOut,
    summary="Aplicar un cambio del agente",
    description=(
        "Applies a change (or rollback) previewed before. The server recomputes the diff from "
        "the request and requires the confirmation token issued for exactly that change, the "
        'typed confirmation "APLICAR" and, when `requires_password` was true, the admin\'s '
        "password (403 `reauth_failed` otherwise). On success the new version is active for "
        "every new conversation. Rejected attempts are logged and recorded as security events. "
        "Admin only; rate limited per user."
    ),
    responses={
        **ERRORS,
        403: {"description": "forbidden, reauth_failed or token_invalid/expired/used/mismatch"},
        409: {"description": "version_conflict"},
        422: {
            "description": "invalid_config, no_changes, unknown_version, password_required, "
            "typed_confirmation_invalid or invalid_request"
        },
        429: {"description": "rate_limited"},
    },
)
def apply_change(request: Request, who: AdminOnly, body: ApplyIn) -> ApplyOut | JSONResponse:
    tokens: ConfirmationTokens | None = request.app.state.confirmation_tokens
    if tokens is None:
        return refuse(503, "confirmation_unavailable")
    if (limited := over_limit(request, who)) is not None:
        return limited
    kit: AuthKit = request.app.state.auth
    try:
        still_admin = kit.service.is_admin(who.user_id)
    except RepositoryUnavailable:
        return refuse(503, "auth_unavailable")
    if not still_admin:  # demoted or deleted since the token was issued
        return reject(request, who, 403, "reauth_failed")  # same answer as a wrong password
    if body.typed_confirmation != TYPED_CONFIRMATION:
        return reject(request, who, 422, "typed_confirmation_invalid")
    service = admin_service(request)
    plan = plan_or_refusal(service, body)
    if isinstance(plan, Refusal):
        if plan.status == 503:  # a storage outage is not an attempt worth recording
            return plan.response()
        return reject(request, who, plan.status, plan.code, **plan.extra)
    try:
        claims = tokens.check(body.confirmation_token, who.user_id, plan.base_version, plan.digest)
    except ConfirmationError as error:
        return reject(request, who, 403, error.code)
    if plan.requires_password:
        password = body.password.get_secret_value() if body.password else None
        if (failed := reauthenticate(request, who, password)) is not None:
            return failed
    try:
        tokens.consume(claims)  # atomic: two concurrent applies cannot both pass
    except ConfirmationError as error:
        return reject(request, who, 403, error.code)
    try:
        stored = service.apply(plan, who.user_id, body.note)
    except VersionConflict:
        return reject(request, who, 409, "version_conflict")
    except InvalidAgentConfig as error:
        field = failing_field(error)
        return refuse(422, "invalid_config", fields=[field] if field else [])
    except (RepositoryUnavailable, InvalidStoredData) as error:
        logger.warning("agent config save unavailable error=%s", type(error).__name__)
        return refuse(503, "storage_unavailable")
    request.app.state.agent_config.invalidate()
    logger.info(
        "agent config applied version=%s action=%s user=%s fields=%s",
        stored.version,
        plan.action,
        who.user_id,
        ",".join(plan.diff),
    )
    return ApplyOut(
        version=stored.version,
        config=AgentConfigOut.model_validate(stored.config.to_dict()),
        applied_at=stored.created_at.isoformat(),
    )


@router.get(
    "/agent-config/history",
    response_model=list[HistoryItemOut],
    summary="Historial de cambios del agente",
    description=(
        "Applied changes, newest first: version, editor, note, whether it was a rollback and the "
        "field-by-field diff. Admin only."
    ),
    responses=ERRORS,
)
def agent_config_history(
    request: Request,
    who: AdminOnly,
    limit: Annotated[int, Query(ge=1, le=100, description="Entries, 1 to 100.")] = 20,
) -> list[HistoryItemOut] | JSONResponse:
    try:
        entries = admin_service(request).history(limit)
    except RepositoryUnavailable as error:
        logger.warning("agent config history unavailable error=%s", type(error).__name__)
        return refuse(503, "storage_unavailable")
    return [
        HistoryItemOut(
            version=e.version,
            created_at=e.at.isoformat(),
            created_by=None if e.user_id is None else str(e.user_id),
            note=e.note,
            action=e.action,  # type: ignore[arg-type]
            diff=e.diff,
        )
        for e in entries
    ]
