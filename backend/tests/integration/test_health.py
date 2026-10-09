from fastapi.testclient import TestClient

from eventssound.config import Settings
from eventssound.entrypoints.api.app import create_app

UNREACHABLE_DB = "postgresql+psycopg://user:pass@127.0.0.1:1/nodb"
ALLOWED = "https://frontend.example"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "DATABASE_URL": UNREACHABLE_DB,
        "cors_allowed_origins": [ALLOWED],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_factory_builds_independent_apps() -> None:
    first = create_app(make_settings(app_env="local"))
    second = create_app(make_settings(app_env="ci"))

    assert first is not second
    assert first.state.settings.app_env == "local"
    assert second.state.settings.app_env == "ci"


def test_health_returns_exact_body() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_need_a_reachable_database() -> None:
    client = TestClient(create_app(make_settings(DATABASE_URL=UNREACHABLE_DB)))

    assert client.get("/health").status_code == 200


def test_allowed_origin_gets_cors_header() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health", headers={"Origin": ALLOWED})

    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_disallowed_origin_gets_no_cors_header() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_production_disables_debug() -> None:
    app = create_app(make_settings(app_env="production"))

    assert app.debug is False
