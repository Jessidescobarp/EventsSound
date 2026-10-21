"""`GET /admin/agent-config` and `POST /admin/agent-config/preview` (fakes, no database)."""

import dataclasses
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_admin_catalog_api import ANA, ROOT, SECRET, Hasher, Users, as_user

from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.agent_config import defaults_from_settings
from eventssound.application.auth import AuthService
from eventssound.config import Settings
from eventssound.domain.user import Role, User
from eventssound.entrypoints.api.app import create_app
from eventssound.entrypoints.api.auth_kit import AuthKit
from fakes import InMemoryAgentConfigRepository, InMemorySecurityLog

JWT = "Zx9fLp2Qw7Rt5Yb3Nm8Vc4Hd6Jg1Ks0A"
API_KEY = "sk-sentinel-api-key"
SENTINEL = "sentinel-value-7"
PREVIEW = "/admin/agent-config/preview"
GET = "/admin/agent-config"


def settings_for(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x",
        "llm_model": "vendor/model-a",
        "llm_model_allowlist": "vendor/model-a,vendor/model-b",
        "jwt_secret": JWT,
        **over,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


ROOT2 = User("88888888-8888-4888-8888-888888888888", "root2@example.com", Role.ADMIN, "h:pw")


class UsersById(Users):
    def by_email(self, email: str) -> User | None:
        return {u.email: u for u in (ANA, ROOT, ROOT2)}.get(email)

    def by_id(self, user_id: str) -> User | None:
        return {u.id: u for u in (ANA, ROOT, ROOT2)}.get(user_id)


def build(
    repo: InMemoryAgentConfigRepository | None = None, *, login_limit: int = 100, **over: Any
) -> tuple[TestClient, InMemoryAgentConfigRepository, Settings]:
    repo = repo or InMemoryAgentConfigRepository()
    tokens = JwtTokenIssuer(SECRET, 60)
    kit = AuthKit(
        AuthService(UsersById(), Hasher(), tokens, dummy_hash="h:x"),
        tokens,
        InMemoryRateLimiter(100),
        InMemoryRateLimiter(login_limit),
    )
    settings = settings_for(**over)
    app = create_app(
        settings,
        auth_kit=kit,
        security_log=InMemorySecurityLog(),  # type: ignore[arg-type]
        agent_config_repository=repo,  # type: ignore[arg-type]
    )
    return TestClient(app), repo, settings


def preview(client: TestClient, changes: Any = None, base: Any = 0, **extra: Any):  # noqa: ANN201
    body: dict[str, Any] = {"base_version": base, **extra}
    if changes is not None:
        body["changes"] = changes
    return client.post(PREVIEW, json=body, headers=as_user(client, ROOT))


@pytest.mark.parametrize(("method", "path"), [("get", GET), ("post", PREVIEW)])
def test_only_an_admin_may_use_the_endpoints(method: str, path: str) -> None:
    client, _, _ = build()
    send = getattr(client, method)
    kwargs = (
        {"json": {"changes": {"tone": "formal"}, "base_version": 0}} if method == "post" else {}
    )

    assert send(path, **kwargs).status_code == 401
    assert send(path, headers=as_user(client, ANA), **kwargs).status_code == 403
    assert send(path, headers={"Authorization": "Bearer nope"}, **kwargs).status_code == 401


def test_get_shows_the_defaults_then_the_stored_version() -> None:
    client, repo, settings = build()
    admin = as_user(client, ROOT)

    first = client.get(GET, headers=admin).json()
    repo.put(dataclasses.replace(defaults_from_settings(settings), tone="formal"), ROOT.id)
    second = client.get(GET, headers=admin).json()

    assert first["version"] == 0 and first["updated_at"] is None and first["updated_by"] is None
    assert first["config"]["tone"] == "neutral" and first["config"]["llm_model"] == "vendor/model-a"
    assert first["ceilings"] == {
        "max_daily_tokens": 1_000_000,
        "max_daily_cost_micro_usd": 10_000_000,
        "max_rate_limit_per_minute": 60,
    }
    assert first["allowed_models"] == ["vendor/model-a", "vendor/model-b"]
    assert second["version"] == 1 and second["config"]["tone"] == "formal"
    assert second["updated_by"] == ROOT.id and second["updated_at"].startswith("2026-10-20")


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, ("replay", "replay", False)),
        ({"chat_enabled": False}, ("replay", "disabled", False)),
        ({"llm_provider": "openrouter"}, ("openrouter", "disabled", False)),  # no API key
        (
            {"llm_provider": "openrouter", "openrouter_api_key": API_KEY},
            ("openrouter", "active", False),  # free model: prices 0
        ),
        (
            {
                "llm_provider": "openrouter",
                "openrouter_api_key": API_KEY,
                "llm_input_price_micro_usd_per_mtok": 300_000,
            },
            ("openrouter", "active", True),
        ),
    ],
)
def test_the_model_in_use_card_and_it_never_leaks_keys(
    over: dict[str, Any], expected: tuple[str, str, bool]
) -> None:
    client, _, _ = build(**over)

    response = client.get(GET, headers=as_user(client, ROOT))

    card = response.json()["model_in_use"]
    assert (card["provider"], card["status"], card["cost_cap_applies"]) == expected
    assert card["model"] == "vendor/model-a"
    assert set(card) == {
        "provider",
        "model",
        "status",
        "input_price_per_mtok",
        "output_price_per_mtok",
        "cost_cap_applies",
    }
    assert API_KEY not in response.text and JWT not in response.text


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"tone": "casual"}, ["tone"]),
        ({"off_topic_policy": "lax"}, ["off_topic_policy"]),
        ({"welcome_message": f"Visita https://{SENTINEL}.example"}, ["welcome_message"]),
        ({"closing_message": SENTINEL * 30}, ["closing_message"]),
        ({"refusal_message": 5}, ["refusal_message"]),
        ({"llm_model": f"other/{SENTINEL}"}, ["llm_model"]),  # not in the allowlist
        ({"llm_model": f"bad model {SENTINEL}"}, ["llm_model"]),
        ({"daily_token_cap": 1_000_001}, ["daily_token_cap"]),
        ({"daily_cost_cap_micro_usd": 10_000_001}, ["daily_cost_cap_micro_usd"]),
        ({"chat_rate_limit_per_minute": 61}, ["chat_rate_limit_per_minute"]),
        ({"daily_token_cap": 0}, ["daily_token_cap"]),
        ({"daily_token_cap": True}, ["daily_token_cap"]),
        ({"daily_token_cap": "5"}, ["daily_token_cap"]),
        ({SENTINEL: 1}, []),  # unknown field: rejected without echoing its name
        ({}, []),
    ],
)
def test_invalid_changes_name_the_field_and_never_echo_the_value(
    changes: dict[str, Any], fields: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    client, _, _ = build()

    with caplog.at_level(logging.DEBUG):
        response = client.post(
            PREVIEW,
            json={"changes": changes, "base_version": 0},
            headers=as_user(client, ROOT),
        )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "invalid_config" and body["fields"] == fields
    assert SENTINEL not in response.text and SENTINEL not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {"base_version": 0},  # neither
        {"base_version": 0, "changes": {"tone": "formal"}, "rollback_to_version": 1},  # both
        {"base_version": "0", "changes": {"tone": "formal"}},
        {"base_version": -1, "changes": {"tone": "formal"}},
        {"base_version": 0, "changes": {"tone": "formal"}, "extra": 1},
    ],
)
def test_a_malformed_request_is_422_invalid_request(body: dict[str, Any]) -> None:
    client, _, _ = build()

    response = client.post(PREVIEW, json=body, headers=as_user(client, ROOT))

    assert response.status_code == 422 and response.json()["detail"] == "invalid_request"


def test_a_stale_base_version_is_409_and_no_change_is_422() -> None:
    client, repo, settings = build()
    repo.put(defaults_from_settings(settings))

    stale = preview(client, {"tone": "formal"}, base=0)
    same = preview(client, {"tone": "neutral"}, base=1)

    assert stale.status_code == 409 and stale.json()["detail"] == "version_conflict"
    assert same.status_code == 422 and same.json()["detail"] == "no_changes"


@pytest.mark.parametrize(
    ("changes", "codes", "password"),
    [
        ({"welcome_message": "Hola, bienvenido"}, {"texts_changed"}, False),
        ({"tone": "formal"}, {"behavior_changed"}, False),
        ({"daily_token_cap": 150_000}, {"cap_raised"}, True),
        ({"daily_cost_cap_micro_usd": 2_500_000}, {"cap_raised_2x"}, True),
        ({"daily_token_cap": 50_000}, set(), True),  # lowering is not a risk warning
        ({"llm_model": "vendor/model-b"}, {"model_changed"}, True),
        ({"chat_rate_limit_per_minute": 30}, {"rate_limit_raised"}, True),
        ({"chat_rate_limit_per_minute": 2}, set(), True),
    ],
)
def test_preview_returns_the_diff_the_risks_and_whether_a_password_is_needed(
    changes: dict[str, Any], codes: set[str], password: bool
) -> None:
    client, _, _ = build()

    response = preview(client, changes)

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["action"] == "save" and body["base_version"] == 0
    assert set(body["diff"]) == set(changes) and body["requires_password"] is password
    found = {w["code"] for w in body["warnings"]}
    assert codes <= found and found - codes == {"immediate_effect"}
    assert {w["severity"] for w in body["warnings"] if w["code"] == "cap_raised_2x"} <= {"danger"}
    assert all(w["message_es"] for w in body["warnings"]) and body["confirmation_token"]


def test_preview_flags_a_cost_cap_that_cannot_bind_and_estimates_the_worst_day() -> None:
    free, _, _ = build(llm_provider="openrouter", openrouter_api_key=API_KEY)
    paid, _, _ = build(
        llm_provider="openrouter",
        openrouter_api_key=API_KEY,
        llm_input_price_micro_usd_per_mtok=1_000_000,
        llm_output_price_micro_usd_per_mtok=2_000_000,
    )
    change = {"daily_token_cap": 150_000}

    free_body, paid_body = preview(free, change).json(), preview(paid, change).json()

    assert "cost_cap_not_binding" in {w["code"] for w in free_body["warnings"]}
    assert free_body["max_daily_cost_estimate_micro_usd"] is None  # unknown, never 0
    assert "cost_unknown" in {w["code"] for w in free_body["warnings"]}
    assert "cost_cap_not_binding" not in {w["code"] for w in paid_body["warnings"]}
    assert paid_body["max_daily_cost_estimate_micro_usd"] == 300_000  # 150k tokens at 2 USD/Mtok

    other = preview(paid, {"llm_model": "vendor/model-b"}).json()  # price belongs to model-a
    assert other["max_daily_cost_estimate_micro_usd"] is None
    assert {w["code"]: w["severity"] for w in other["warnings"]}["cost_unknown"] == "danger"


def test_success_bodies_are_not_cacheable_and_oversized_changes_are_refused() -> None:
    client, _, _ = build()
    headers = as_user(client, ROOT)

    ok = [client.get(GET, headers=headers), preview(client, {"tone": "formal"})]
    too_long = preview(client, {"welcome_message": "a" * 1001})
    too_many = preview(client, {f"k{i}": 1 for i in range(13)})

    assert [r.status_code for r in ok] == [200, 200]
    assert {r.headers["Cache-Control"] for r in ok} == {"no-store"}
    assert [r.json()["detail"] for r in (too_long, too_many)] == ["invalid_request"] * 2


def test_get_lists_the_default_fields_that_are_out_of_bounds() -> None:
    client, _, _ = build(llm_daily_token_cap=0, chat_rate_limit_per_minute=100)
    healthy, _, _ = build()

    body = client.get(GET, headers=as_user(client, ROOT)).json()

    assert body["defaults_out_of_bounds"] == ["daily_token_cap", "chat_rate_limit_per_minute"]
    assert healthy.get(GET, headers=as_user(healthy, ROOT)).json()["defaults_out_of_bounds"] == []


def test_a_rollback_previews_the_difference_to_that_version() -> None:
    client, repo, settings = build()
    base = defaults_from_settings(settings)
    repo.put(dataclasses.replace(base, tone="formal"))
    repo.put(dataclasses.replace(base, tone="cercano", llm_model="vendor/model-b"))

    body = preview(client, base=2, rollback_to_version=1).json()

    assert body["action"] == "rollback"
    assert body["diff"] == {
        "tone": ["cercano", "formal"],
        "llm_model": ["vendor/model-b", "vendor/model-a"],
    }
    assert body["requires_password"] is True
    assert preview(client, base=2, rollback_to_version=2).json()["detail"] == "no_changes"
    assert preview(client, base=2, rollback_to_version=9).json()["detail"] == "unknown_version"


def test_a_rollback_to_a_model_that_is_no_longer_allowed_is_refused() -> None:
    client, repo, settings = build()
    base = defaults_from_settings(settings)
    repo.put(dataclasses.replace(base, llm_model="gone/model"))
    repo.put(base)

    response = preview(client, base=2, rollback_to_version=1)

    assert response.status_code == 422 and response.json()["fields"] == ["llm_model"]


def test_without_a_jwt_secret_preview_fails_closed_but_the_read_works() -> None:
    client, _, _ = build(jwt_secret=None)

    assert preview(client, {"tone": "formal"}).status_code == 503
    assert client.get(GET, headers=as_user(client, ROOT)).status_code == 200


def test_a_storage_failure_is_503_without_details(caplog: pytest.LogCaptureFixture) -> None:
    client, repo, _ = build(InMemoryAgentConfigRepository(broken=True))

    with caplog.at_level(logging.WARNING):
        read = client.get(GET, headers=as_user(client, ROOT))
        write = preview(client, {"tone": "formal"})

    assert read.status_code == write.status_code == 503
    assert read.json()["detail"] == "storage_unavailable"


def test_preview_is_rate_limited_per_admin_user() -> None:
    client, _, _ = build()
    admin = as_user(client, ROOT)
    body = {"changes": {"tone": "formal"}, "base_version": 0}

    statuses = [client.post(PREVIEW, json=body, headers=admin).status_code for _ in range(11)]

    assert statuses == [200] * 10 + [429]
    assert int(client.post(PREVIEW, json=body, headers=admin).headers["Retry-After"]) >= 1
