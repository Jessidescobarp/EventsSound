"""Admin API for the agent configuration: read, preview and (next) apply. Admin only."""

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
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
from eventssound.application.confirmation import ConfirmationTokens
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable, VersionConflict
from eventssound.application.messages_es_agent_config import CONFIG_ERRORS
from eventssound.application.messages_es_auth import AUTH_ERRORS
from eventssound.application.quote_chat import RateLimited
from eventssound.domain.errors import InvalidAgentConfig
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import require_role
from eventssound.entrypoints.api.schemas_agent_config import (
    AgentConfigViewOut,
    ChangeIn,
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


def plan_or_refusal(
    service: AgentConfigAdmin, body: ChangeIn
) -> tuple[Plan | None, JSONResponse | None]:
    """The validated plan, or the response that refuses the request (field names only)."""
    try:
        return service.plan(body.changes, body.rollback_to_version, body.base_version), None
    except VersionConflict:
        return None, refuse(409, "version_conflict")
    except NoChanges:
        return None, refuse(422, "no_changes")
    except UnknownVersion:
        return None, refuse(422, "unknown_version")
    except InvalidAgentConfig as error:
        field = failing_field(error)
        return None, refuse(422, "invalid_config", fields=[field] if field else [])
    except (RepositoryUnavailable, InvalidStoredData) as error:
        logger.warning("agent config unavailable error=%s", type(error).__name__)
        return None, refuse(503, "storage_unavailable")


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
    plan, refusal = plan_or_refusal(service, body)
    if plan is None:
        return refusal  # type: ignore[return-value]
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
