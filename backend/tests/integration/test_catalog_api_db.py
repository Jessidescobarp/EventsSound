"""The catalog API through the real wiring: Settings -> container -> SQLAlchemy -> Postgres."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from conftest import SECRETS_IN_UNREACHABLE_URL, UNREACHABLE_URL
from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.config import Settings
from eventssound.entrypoints.api.app import create_app


def client_for(url: str) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, DATABASE_URL=url)))  # type: ignore[call-arg]


def test_seeded_database_is_served_through_the_real_wiring(
    session_factory: sessionmaker[Session], migrated_database: str
) -> None:
    seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)
    client = client_for(migrated_database)

    items = client.get("/catalog/items").json()["items"]
    packages = client.get("/catalog/packages").json()["packages"]

    assert len(items) == len(SEED_ITEMS) == 20
    assert [item["code"] for item in items] == sorted(item["code"] for item in items)
    assert all(type(item["unit_price_cop"]) is int for item in items)
    assert len(packages) == len(SEED_PACKAGES) == 4
    codes = {item["code"] for item in items}
    assert all(line["item_code"] in codes for package in packages for line in package["items"])
    assert all(type(package["base_price_cop"]) is int for package in packages)


def test_migrated_empty_database_returns_empty_lists(migrated_database: str) -> None:
    client = client_for(migrated_database)

    assert client.get("/catalog/items").json() == {"items": []}
    assert client.get("/catalog/packages").json() == {"packages": []}


def test_unreachable_database_returns_503_without_connection_details() -> None:
    client = client_for(UNREACHABLE_URL)

    for path in ("/catalog/items", "/catalog/packages"):
        response = client.get(path)

        assert response.status_code == 503
        assert response.json() == {"detail": "catalog_unavailable"}
        assert not any(secret in response.text for secret in SECRETS_IN_UNREACHABLE_URL)
