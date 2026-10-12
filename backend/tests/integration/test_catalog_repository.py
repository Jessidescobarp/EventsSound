"""SqlAlchemyCatalogRepository against a real Postgres (DATABASE_URL_TEST)."""

import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from conftest import SECRETS_IN_UNREACHABLE_URL
from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.models import EquipmentItemModel, PackageItemModel, ServicePackageModel
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.ports import CatalogRepository
from eventssound.domain.catalog import EquipmentCategory
from eventssound.domain.money import Money


def item(code: str, price: int = 50000, **overrides) -> EquipmentItemModel:
    fields = {
        "code": code,
        "name": "Equipo",
        "category": "sound",
        "stock_quantity": 4,
        "unit_price_cop": price,
    }
    return EquipmentItemModel(**{**fields, **overrides})


def package(code: str, lines: list[tuple[EquipmentItemModel, int]], bps: int = 0):
    model = ServicePackageModel(code=code, name="Paquete", discount_bps=bps)
    model.lines = [PackageItemModel(item=it, quantity=qty) for it, qty in lines]
    return model


def seed(factory: sessionmaker[Session], *models: object) -> None:
    with factory.begin() as session:
        session.add_all(models)


def test_sqlalchemy_repository_satisfies_the_port(session_factory: sessionmaker[Session]) -> None:
    assert isinstance(SqlAlchemyCatalogRepository(session_factory), CatalogRepository)


def test_empty_database_gives_an_empty_catalog(session_factory: sessionmaker[Session]) -> None:
    catalog = SqlAlchemyCatalogRepository(session_factory).get_catalog()

    assert catalog.items == ()
    assert catalog.packages == ()


def test_round_trip_maps_items_money_and_package_members(
    session_factory: sessionmaker[Session],
) -> None:
    speaker = item("sound_speaker", 1_250_000, name="Parlante activo", stock_quantity=6)
    light = item("light_par", 30000, category="lighting", stock_quantity=0)
    seed(session_factory, package("pkg_party", [(speaker, 2), (light, 8)], bps=1000))

    catalog = SqlAlchemyCatalogRepository(session_factory).get_catalog()

    stored = catalog.item("sound_speaker")
    assert stored.name == "Parlante activo"
    assert stored.category is EquipmentCategory.SOUND
    assert stored.stock_quantity == 6
    assert stored.unit_price == Money(1_250_000)
    assert type(stored.unit_price.amount) is int
    assert catalog.item("light_par").stock_quantity == 0
    party = catalog.package("pkg_party")
    assert party.discount_bps == 1000
    assert [(line.item_code, line.quantity) for line in party.lines] == [
        ("light_par", 8),
        ("sound_speaker", 2),
    ]
    assert party.base_unit_price(catalog) == Money(1_250_000 * 2 + 30000 * 8)


def test_items_packages_and_lines_are_ordered_by_code(
    session_factory: sessionmaker[Session],
) -> None:
    zeta, alpha, mid = item("zeta_item"), item("alpha_item"), item("mid_item")
    seed(
        session_factory,
        package("pkg_b", [(zeta, 1), (alpha, 1), (mid, 1)]),
        package("pkg_a", [(mid, 2)]),
    )

    catalog = SqlAlchemyCatalogRepository(session_factory).get_catalog()

    assert [i.code for i in catalog.items] == ["alpha_item", "mid_item", "zeta_item"]
    assert [p.code for p in catalog.packages] == ["pkg_a", "pkg_b"]
    assert [line.item_code for line in catalog.package("pkg_b").lines] == [
        "alpha_item",
        "mid_item",
        "zeta_item",
    ]


def test_a_package_without_lines_is_rejected_as_stored_data(
    session_factory: sessionmaker[Session],
) -> None:
    seed(session_factory, ServicePackageModel(code="pkg_empty", name="Vacio"))

    with pytest.raises(InvalidStoredData):
        SqlAlchemyCatalogRepository(session_factory).get_catalog()


@pytest.mark.parametrize(
    ("overrides", "dropped_check"),
    [
        ({"category": "pyrotechnics"}, "category_valid"),
        ({"code": "Bad Code"}, None),
        ({"code": "ab"}, None),
        ({"name": "   "}, None),
        ({"unit_price_cop": 2_000_000_000}, None),
    ],
    ids=["unknown-category", "uppercase-code", "short-code", "blank-name", "absurd-price"],
)
def test_invalid_item_rows_raise_a_typed_error_not_a_raw_one(
    session_factory: sessionmaker[Session], overrides: dict, dropped_check: str | None
) -> None:
    if dropped_check:
        with session_factory.begin() as session:
            constraint = f"ck_equipment_items_{dropped_check}"
            session.execute(text(f"ALTER TABLE equipment_items DROP CONSTRAINT {constraint}"))
    seed(session_factory, item(**{"code": "sound_speaker", **overrides}))

    with pytest.raises(InvalidStoredData):
        SqlAlchemyCatalogRepository(session_factory).get_catalog()


def test_invalid_package_row_raises_a_typed_error(session_factory: sessionmaker[Session]) -> None:
    speaker = item("sound_speaker")
    seed(session_factory, package("Bad Package", [(speaker, 1)]))

    with pytest.raises(InvalidStoredData):
        SqlAlchemyCatalogRepository(session_factory).get_catalog()


def test_storage_failure_is_reported_without_connection_details(
    unreachable_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(RepositoryUnavailable) as caught:
        SqlAlchemyCatalogRepository(unreachable_session_factory).get_catalog()

    rendered = str(caught.value) + "".join(traceback.format_exception(caught.value))
    for secret in SECRETS_IN_UNREACHABLE_URL:
        assert secret not in rendered
