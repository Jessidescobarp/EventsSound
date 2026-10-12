"""Read-only catalog routes and the public OpenAPI schema, without a database."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eventssound.config import Settings
from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.money import Money
from eventssound.entrypoints.api.app import create_app
from fakes import BrokenCatalogRepository, InMemoryCatalogRepository

CATALOG = Catalog(
    items=(
        EquipmentItem("zeta_light", "Luz Zeta", EquipmentCategory.LIGHTING, 4, Money(25_000)),
        EquipmentItem("alpha_speaker", "Parlante Alfa", EquipmentCategory.SOUND, 2, Money(60_000)),
    ),
    packages=(
        ServicePackage(
            "pkg_b",
            "Paquete B",
            (PackageLine("zeta_light", 2), PackageLine("alpha_speaker", 1)),
            500,
        ),
        ServicePackage("pkg_a", "Paquete A", (PackageLine("alpha_speaker", 1),), 0),
    ),
)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x"}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def client_for(repository: Any, **settings: object) -> TestClient:
    app = create_app(make_settings(**settings), catalog_repository=repository)
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return client_for(InMemoryCatalogRepository(CATALOG))


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in all_keys(v)}
    return set()


def test_items_are_ordered_by_code_and_expose_the_public_fields(client: TestClient) -> None:
    response = client.get("/catalog/items")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "code": "alpha_speaker",
                "name": "Parlante Alfa",
                "category": "sound",
                "stock_quantity": 2,
                "unit_price_cop": 60_000,
            },
            {
                "code": "zeta_light",
                "name": "Luz Zeta",
                "category": "lighting",
                "stock_quantity": 4,
                "unit_price_cop": 25_000,
            },
        ]
    }


def test_packages_are_ordered_by_code_with_a_derived_base_price(client: TestClient) -> None:
    response = client.get("/catalog/packages")

    assert response.status_code == 200
    assert response.json() == {
        "packages": [
            {
                "code": "pkg_a",
                "name": "Paquete A",
                "discount_bps": 0,
                "base_price_cop": 60_000,
                "items": [{"item_code": "alpha_speaker", "quantity": 1}],
            },
            {
                "code": "pkg_b",
                "name": "Paquete B",
                "discount_bps": 500,
                "base_price_cop": 110_000,
                "items": [
                    {"item_code": "zeta_light", "quantity": 2},
                    {"item_code": "alpha_speaker", "quantity": 1},
                ],
            },
        ]
    }


def test_empty_catalog_returns_empty_lists() -> None:
    client = client_for(InMemoryCatalogRepository(Catalog((), ())))

    assert client.get("/catalog/items").json() == {"items": []}
    assert client.get("/catalog/packages").json() == {"packages": []}


def test_no_internal_keys_are_exposed(client: TestClient) -> None:
    keys = all_keys(client.get("/catalog/items").json()) | all_keys(
        client.get("/catalog/packages").json()
    )

    assert not {
        k for k in keys if k == "id" or k.endswith("_id") or "created" in k or "updated" in k
    }


@pytest.mark.parametrize("path", ["/catalog/items", "/catalog/packages"])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_rejected(client: TestClient, path: str, method: str) -> None:
    assert getattr(client, method)(path).status_code == 405


def test_there_is_no_availability_route(client: TestClient) -> None:
    assert client.get("/catalog/availability").status_code == 404


@pytest.mark.parametrize("path", ["/catalog/items", "/catalog/packages"])
def test_unavailable_storage_returns_503_without_details(path: str) -> None:
    client = client_for(BrokenCatalogRepository())

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": "catalog_unavailable"}


def test_the_fake_repository_is_used_without_any_database(client: TestClient) -> None:
    # make_settings points at an unreachable database: a 200 proves the fake served the request.
    assert client.get("/catalog/items").status_code == 200


# --- public OpenAPI -------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["local", "production"])
def test_swagger_and_schema_are_public_in_every_environment(env: str) -> None:
    client = client_for(InMemoryCatalogRepository(CATALOG), app_env=env)

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/redoc").status_code == 404


def test_schema_documents_both_catalog_routes_for_a_business_reader() -> None:
    client = client_for(InMemoryCatalogRepository(CATALOG), app_env="production")
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "EventSoundDR API"
    assert schema["info"]["description"].strip()
    assert any(tag["name"] == "Catalog" and tag["description"] for tag in schema["tags"])
    for path in ("/catalog/items", "/catalog/packages"):
        assert set(schema["paths"][path]) == {"get"}
        operation = schema["paths"][path]["get"]
        assert operation["tags"] == ["Catalog"]
        assert operation["summary"]
        assert operation["description"].strip()
        assert "503" in operation["responses"]
        ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in ok


def test_every_response_model_carries_an_example() -> None:
    client = client_for(InMemoryCatalogRepository(CATALOG))
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    for name in ("ItemsResponse", "PackagesResponse"):
        assert schemas[name]["examples"], name
        assert json.dumps(schemas[name]["examples"])
