from fastapi.testclient import TestClient

from eventssound.config import Settings
from eventssound.entrypoints.api.app import create_app


class FailingDatabase:
    def ping(self) -> None:
        raise ConnectionError("postgresql://user:secret@host/db refused")


class HealthyDatabase:
    def ping(self) -> None:
        return None


def make_settings(url: str = "postgresql+psycopg://u:p@127.0.0.1:1/x") -> Settings:
    return Settings(_env_file=None, DATABASE_URL=url)  # type: ignore[arg-type]


def test_health_db_returns_503_without_leaking_details() -> None:
    client = TestClient(create_app(make_settings(), database_health=FailingDatabase()))

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "secret" not in response.text


def test_health_db_returns_200_with_healthy_port() -> None:
    client = TestClient(create_app(make_settings(), database_health=HealthyDatabase()))

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_db_against_real_postgres(database_url: str) -> None:
    client = TestClient(create_app(make_settings(database_url)))

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
