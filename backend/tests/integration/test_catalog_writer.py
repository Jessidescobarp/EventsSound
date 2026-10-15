"""The Postgres catalog writer: create and edit items and packages (needs DATABASE_URL_TEST)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.catalog_writer import SqlAlchemyCatalogWriter
from eventssound.application.errors import CodeTaken, NotFound
from eventssound.domain.catalog import EquipmentCategory, EquipmentItem, PackageLine, ServicePackage
from eventssound.domain.errors import UnknownCatalogEntry
from eventssound.domain.money import Money


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE package_items, service_packages, equipment_items CASCADE")
        )
    yield engine
    engine.dispose()


def item(
    code: str = "sound_new", name: str = "Parlante nuevo", stock: int = 4, price: int = 90_000
):
    return EquipmentItem(code, name, EquipmentCategory.SOUND, stock, Money(price))


def package(code: str, *lines: tuple[str, int], name: str = "Paquete", bps: int = 500):
    return ServicePackage(code, name, tuple(PackageLine(c, q) for c, q in lines), bps)


def test_a_created_item_is_in_the_catalog_and_its_edit_replaces_the_fields(engine: Engine) -> None:
    factory = sessionmaker(engine)
    writer, repository = SqlAlchemyCatalogWriter(factory), SqlAlchemyCatalogRepository(factory)

    writer.create_item(item())
    writer.update_item(item(name="Parlante renovado", stock=0, price=120_000))

    saved = repository.get_catalog().item("sound_new")
    assert (saved.name, saved.stock_quantity, saved.unit_price.amount) == (
        "Parlante renovado",
        0,
        120_000,
    )


def test_duplicate_codes_and_missing_targets_are_refused_without_side_effects(
    engine: Engine,
) -> None:
    writer = SqlAlchemyCatalogWriter(sessionmaker(engine))
    writer.create_item(item())

    with pytest.raises(CodeTaken):
        writer.create_item(item(name="Otro"))
    with pytest.raises(NotFound):
        writer.update_item(item("sound_ghost"))
    with pytest.raises(NotFound):
        writer.update_package(package("pack_ghost", ("sound_new", 1)))

    writer.create_package(package("pack_one", ("sound_new", 2)))
    with pytest.raises(CodeTaken):
        writer.create_package(package("pack_one", ("sound_new", 1)))


def test_a_package_with_an_unknown_item_is_refused_and_nothing_is_stored(engine: Engine) -> None:
    factory = sessionmaker(engine)
    writer = SqlAlchemyCatalogWriter(factory)
    writer.create_item(item())

    with pytest.raises(UnknownCatalogEntry):
        writer.create_package(package("pack_bad", ("sound_new", 1), ("sound_nope", 1)))

    assert SqlAlchemyCatalogRepository(factory).get_catalog().packages == ()


def test_editing_a_package_replaces_its_lines_even_when_it_keeps_an_item(engine: Engine) -> None:
    factory = sessionmaker(engine)
    writer, repository = SqlAlchemyCatalogWriter(factory), SqlAlchemyCatalogRepository(factory)
    writer.create_item(item("sound_a"))
    writer.create_item(item("sound_b"))
    writer.create_package(package("pack_x", ("sound_a", 1), ("sound_b", 1)))

    writer.update_package(package("pack_x", ("sound_a", 3), name="Renombrado", bps=1000))

    saved = repository.get_catalog().package("pack_x")
    assert saved.name == "Renombrado" and saved.discount_bps == 1000
    assert saved.lines == (PackageLine("sound_a", 3),)
