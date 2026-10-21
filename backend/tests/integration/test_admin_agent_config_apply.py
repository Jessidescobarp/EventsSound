"""`PUT /admin/agent-config/apply` and `GET /admin/agent-config/history` (fakes, no database)."""

import dataclasses
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_admin_agent_config_api import (
    GET,
    JWT,
    PREVIEW,
    ROOT2,
    SENTINEL,
    build,
    preview,
)
from test_admin_catalog_api import ANA, ROOT, SECRET, as_user

from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.application.agent_config import defaults_from_settings
from eventssound.application.confirmation import ConfirmationTokens, derive_confirmation_key
from eventssound.application.errors import RepositoryUnavailable, VersionConflict
from eventssound.application.security import CONFIG_REAUTH_FAILED, CONFIG_REJECTED
from eventssound.domain.user import Role, User

APPLY = "/admin/agent-config/apply"
HISTORY = "/admin/agent-config/history"
GHOST = User("99999999-9999-4999-8999-999999999999", "ghost@example.com", Role.ADMIN, "h:pw")
TEXT = f"Bienvenido {SENTINEL.replace('-', '')} amigo"


def sign_off(
    client: TestClient,
    changes: Any = None,
    base: int = 0,
    who: User = ROOT,
    note: str | None = None,
    **change: Any,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Log in, preview and return the headers and a complete apply body."""
    headers = as_user(client, who)
    request: dict[str, Any] = {"base_version": base, **change}
    if changes is not None:
        request["changes"] = changes
    token = client.post(PREVIEW, json=request, headers=headers).json()["confirmation_token"]
    return headers, {
        **request,
        "confirmation_token": token,
        "typed_confirmation": "APLICAR",
        "password": "pw",
        **({"note": note} if note else {}),
    }


def apply(client: TestClient, headers: dict[str, str], body: dict[str, Any]):  # noqa: ANN201
    return client.put(APPLY, json=body, headers=headers)


def events(client: TestClient) -> list[str]:
    return [kind for kind, _, _ in client.app.state.security_log.rows]  # type: ignore[attr-defined]


@pytest.mark.parametrize(("method", "path"), [("put", APPLY), ("get", HISTORY)])
def test_only_an_admin_may_apply_or_read_history(method: str, path: str) -> None:
    client, repo, _ = build()
    send = getattr(client, method)
    kwargs = {"json": {"changes": {"tone": "formal"}, "base_version": 0}} if method == "put" else {}

    assert send(path, **kwargs).status_code == 401
    assert send(path, headers=as_user(client, ANA), **kwargs).status_code == 403
    assert repo.saves == []


def test_a_non_technical_change_applies_without_a_password_and_takes_effect_at_once() -> None:
    client, repo, _ = build()
    active = client.app.state.agent_config  # type: ignore[attr-defined]
    assert active.current().config.tone == "neutral"  # primes the 15 s cache
    headers, body = sign_off(client, {"tone": "formal", "welcome_message": TEXT}, note="why")
    body.pop("password")

    response = apply(client, headers, body)

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1 and response.json()["config"]["tone"] == "formal"
    config, base, user, note, action = repo.saves[0]
    assert (base, user, note, action) == (0, UUID(ROOT.id), "why", "save")
    assert active.current().config.tone == "formal"  # invalidated, not waiting for the TTL
    assert client.get(GET, headers=headers).json()["version"] == 1


def test_a_technical_change_needs_the_password_and_a_wrong_one_is_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"daily_token_cap": 50_000})

    with caplog.at_level(logging.DEBUG):
        missing = apply(client, headers, {k: v for k, v in body.items() if k != "password"})
        wrong = apply(client, headers, {**body, "password": f"bad-{SENTINEL}"})
        right = apply(client, headers, body)  # the token survived the failed attempts

    assert (missing.status_code, missing.json()["detail"]) == (422, "password_required")
    assert (wrong.status_code, wrong.json()["detail"]) == (403, "reauth_failed")
    assert right.status_code == 200 and repo.saves[0][0].daily_token_cap == 50_000
    assert events(client) == [CONFIG_REJECTED, CONFIG_REAUTH_FAILED]
    assert SENTINEL not in caplog.text and SENTINEL not in wrong.text


def test_an_unknown_user_gets_the_same_reauth_failure_as_a_wrong_password() -> None:
    client, repo, _ = build()
    ghost = User("99999999-9999-4999-8999-999999999999", "ghost@example.com", Role.ADMIN, "h:pw")
    headers = {"Authorization": f"Bearer {JwtTokenIssuer(SECRET, 60).issue(ghost).token}"}
    admin_headers, admin_body = sign_off(client, {"daily_token_cap": 50_000})
    request = {"changes": {"daily_token_cap": 50_000}, "base_version": 0}
    token = client.post(PREVIEW, json=request, headers=headers).json()["confirmation_token"]
    ghost_body = {**request, "confirmation_token": token, "typed_confirmation": "APLICAR"}

    ghost_response = apply(client, headers, {**ghost_body, "password": "pw"})  # right password
    wrong_response = apply(client, admin_headers, {**admin_body, "password": "nope"})

    assert ghost_response.status_code == wrong_response.status_code == 403
    assert ghost_response.json() == wrong_response.json() and repo.saves == []


def test_password_attempts_are_rate_limited_like_login() -> None:
    client, _, _ = build(login_limit=3)
    headers, body = sign_off(client, {"daily_token_cap": 50_000}, who=ROOT2)

    statuses = [apply(client, headers, {**body, "password": "nope"}).status_code for _ in range(4)]

    assert statuses == [403, 403, 403, 429]


@pytest.mark.parametrize("typed", ["aplicar", "APLICAR ", "", "APPLY"])
def test_the_typed_confirmation_must_be_exact(typed: str) -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})

    response = apply(client, headers, {**body, "typed_confirmation": typed})

    assert response.status_code == 422 and response.json()["detail"] in (
        "typed_confirmation_invalid",
        "invalid_request",
    )
    assert repo.saves == []


def test_a_token_is_bound_to_the_exact_change_user_and_signature() -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})
    other_headers, _ = sign_off(client, {"tone": "formal"}, who=ROOT2)
    tampered = body["confirmation_token"][:-3] + "AAA"

    cases = {
        "different change": {**body, "changes": {"tone": "cercano"}},
        "tampered": {**body, "confirmation_token": tampered},
        "garbage": {**body, "confirmation_token": "x.y"},
    }
    codes = {n: apply(client, headers, b).json()["detail"] for n, b in cases.items()}
    stolen = apply(client, other_headers, body)  # an admin sending another admin's token

    assert codes == {
        "different change": "token_mismatch",
        "tampered": "token_invalid",
        "garbage": "token_invalid",
    }
    assert stolen.status_code == 403 and stolen.json()["detail"] == "token_mismatch"
    assert repo.saves == [] and events(client) == [CONFIG_REJECTED] * 4


def test_an_expired_token_is_refused() -> None:
    client, repo, _ = build()
    now = [1_000_000.0]
    client.app.state.confirmation_tokens = ConfirmationTokens(  # type: ignore[attr-defined]
        derive_confirmation_key(JWT), clock=lambda: now[0]
    )
    headers, body = sign_off(client, {"tone": "formal"})
    now[0] += 301

    response = apply(client, headers, body)

    assert response.status_code == 403 and response.json()["detail"] == "token_expired"
    assert repo.saves == []


def test_a_token_is_spent_even_when_the_save_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})
    monkeypatch.setattr(repo, "save", _fail(RepositoryUnavailable()))

    first = apply(client, headers, body)
    monkeypatch.undo()
    retry = apply(client, headers, body)

    assert first.status_code == 503 and first.json()["detail"] == "storage_unavailable"
    assert retry.status_code == 403 and retry.json()["detail"] == "token_used"


def _fail(error: Exception):  # noqa: ANN202
    def save(*args: object, **kwargs: object) -> None:
        raise error

    return save


def test_a_version_that_moved_is_409_before_and_during_the_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, repo, settings = build()
    headers, body = sign_off(client, {"tone": "formal"})
    repo.put(dataclasses.replace(defaults_from_settings(settings), tone="cercano"))  # concurrent
    moved = apply(client, headers, body)

    headers, fresh = sign_off(client, {"tone": "formal"}, base=1)
    monkeypatch.setattr(repo, "save", _fail(VersionConflict()))  # lost the race at the database
    raced = apply(client, headers, fresh)

    assert moved.status_code == raced.status_code == 409
    assert moved.json()["detail"] == raced.json()["detail"] == "version_conflict"
    assert events(client) == [CONFIG_REJECTED] * 2


def test_a_rollback_applies_the_old_version_as_a_new_one_and_shows_in_history() -> None:
    client, repo, settings = build()
    base = defaults_from_settings(settings)
    repo.put(dataclasses.replace(base, tone="formal"))
    repo.put(dataclasses.replace(base, tone="cercano", llm_model="vendor/model-b:free"))
    headers, body = sign_off(client, base=2, rollback_to_version=1)

    response = apply(client, headers, body)

    assert response.status_code == 200 and response.json()["version"] == 3
    saved, _, _, _, action = repo.saves[0]
    assert action == "rollback" and (saved.tone, saved.llm_model) == ("formal", "vendor/model-a")
    top = client.get(HISTORY, headers=headers).json()[0]
    assert (top["version"], top["action"], top["created_by"]) == (3, "rollback", ROOT.id)
    assert top["diff"]["tone"] == ["cercano", "formal"]


def test_history_lists_applied_changes_newest_first_and_validates_the_limit() -> None:
    client, _, _ = build()
    for version, tone in enumerate(("formal", "cercano")):
        headers, body = sign_off(client, {"tone": tone}, base=version, note=f"n{version}")
        assert apply(client, headers, body).status_code == 200

    everything = client.get(HISTORY, headers=headers).json()
    one = client.get(HISTORY, params={"limit": 1}, headers=headers).json()

    assert [(e["version"], e["note"], e["action"]) for e in everything] == [
        (2, "n1", "save"),
        (1, "n0", "save"),
    ]
    assert set(everything[0]) == {"version", "created_at", "created_by", "note", "action", "diff"}
    assert everything[0]["diff"] == {"tone": ["formal", "cercano"]} and len(one) == 1
    for bad in (0, 101):
        assert client.get(HISTORY, params={"limit": bad}, headers=headers).status_code == 422


@pytest.mark.parametrize(
    ("extra", "status", "detail"),
    [
        ({"note": "x" * 201}, 422, "invalid_request"),
        ({"note": "line\nbreak"}, 422, "invalid_config"),
        ({"confirmation_token": ""}, 422, "invalid_request"),
    ],
)
def test_bad_apply_fields_are_422(extra: dict[str, Any], status: int, detail: str) -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})

    response = apply(client, headers, {**body, **extra})

    assert (response.status_code, response.json()["detail"]) == (status, detail)
    assert repo.saves == []


def test_without_a_secret_apply_fails_closed_and_apply_is_rate_limited_with_preview() -> None:
    closed, _, _ = build(jwt_secret=None)
    body = {
        "changes": {"tone": "formal"},
        "base_version": 0,
        "confirmation_token": "x.y",
        "typed_confirmation": "APLICAR",
    }
    assert closed.put(APPLY, json=body, headers=as_user(closed, ROOT)).status_code == 503

    client, _, _ = build()
    headers = as_user(client, ROOT)
    statuses = [preview(client, {"tone": "formal"}).status_code for _ in range(10)]
    limited = client.put(APPLY, json={**body, "confirmation_token": "x.y"}, headers=headers)

    assert statuses == [200] * 10 and limited.status_code == 429


def test_applied_values_never_reach_the_logs_or_the_security_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _, _ = build()

    with caplog.at_level(logging.DEBUG):
        headers, body = sign_off(client, {"welcome_message": TEXT}, note=f"note {SENTINEL}")
        assert apply(client, headers, body).status_code == 200

    sentinel = SENTINEL.replace("-", "")
    assert sentinel not in caplog.text and SENTINEL not in caplog.text
    assert "agent config applied version=1 action=save" in caplog.text
    assert sentinel not in repr(client.app.state.security_log.rows)  # type: ignore[attr-defined]


@pytest.mark.parametrize("who", [ANA, GHOST], ids=["demoted", "deleted"])
@pytest.mark.parametrize(
    "changes", [{"daily_token_cap": 50_000}, {"tone": "formal"}], ids=["technical", "texts-only"]
)
def test_a_token_whose_account_is_no_longer_an_admin_cannot_apply(
    who: User, changes: dict[str, Any]
) -> None:
    client, repo, _ = build()
    stale = dataclasses.replace(who, role=Role.ADMIN)  # the role claim a still-valid JWT carries
    headers = {"Authorization": f"Bearer {JwtTokenIssuer(SECRET, 60).issue(stale).token}"}
    request = {"changes": changes, "base_version": 0}
    token = client.post(PREVIEW, json=request, headers=headers).json()["confirmation_token"]
    body = {
        **request,
        "confirmation_token": token,
        "typed_confirmation": "APLICAR",
        "password": "pw",
    }

    response = apply(client, headers, body)

    assert response.status_code == 403 and response.json()["detail"] == "reauth_failed"
    assert repo.saves == [] and events(client) == [CONFIG_REJECTED]


def test_a_bad_note_is_refused_without_spending_the_token_and_history_is_not_cached() -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})

    bad = apply(client, headers, {**body, "note": "line\nbreak"})
    good = apply(client, headers, {**body, "note": "fine"})

    assert (bad.status_code, bad.json()["fields"]) == (422, ["note"])
    assert good.status_code == 200 and len(repo.saves) == 1
    assert good.headers["Cache-Control"] == "no-store"
    assert client.get(HISTORY, headers=headers).headers["Cache-Control"] == "no-store"


def test_two_simultaneous_applies_with_one_token_save_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, repo, _ = build()
    headers, body = sign_off(client, {"tone": "formal"})
    barrier = threading.Barrier(2, timeout=10)
    read = repo.get_active

    def meet_after_reading():  # noqa: ANN202  (both requests have planned before either goes on)
        stored = read()
        barrier.wait()
        return stored

    monkeypatch.setattr(repo, "get_active", meet_after_reading)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: apply(client, headers, body), range(2)))

    assert sorted(r.status_code for r in results) == [200, 403]
    assert {r.json()["detail"] for r in results if r.status_code == 403} == {"token_used"}
    assert len(repo.saves) == 1
