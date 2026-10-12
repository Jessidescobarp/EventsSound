"""The catalog is read from one snapshot, and the seed keeps `updated_at` honest."""

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES

LATE_ROWS = (
    "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
    " VALUES ('late_item', 'Tardio', 'sound', 1, 1000);"
    "INSERT INTO service_packages (code, name) VALUES ('pkg_late', 'Tardio');"
    "INSERT INTO package_items (package_id, equipment_item_id, quantity)"
    " SELECT p.id, i.id, 1 FROM service_packages p, equipment_items i"
    " WHERE p.code = 'pkg_late' AND i.code = 'late_item'"
)


def test_a_commit_between_the_two_selects_is_not_seen(
    session_factory: sessionmaker[Session],
) -> None:
    engine: Engine = session_factory.kw["bind"]
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
                " VALUES ('first_item', 'Primero', 'sound', 2, 5000)"
            )
        )
    other = create_engine(engine.url.render_as_string(hide_password=False))
    fired: list[bool] = []

    @event.listens_for(engine, "before_cursor_execute")
    def commit_elsewhere(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if "FROM service_packages" in statement and not fired:
            fired.append(True)
            with other.begin() as connection:
                for statement_text in LATE_ROWS.split(";"):
                    connection.execute(text(statement_text))

    try:
        catalog = SqlAlchemyCatalogRepository(session_factory).get_catalog()
    finally:
        event.remove(engine, "before_cursor_execute", commit_elsewhere)
        other.dispose()

    assert fired, "the concurrent commit never happened, so this test proves nothing"
    assert [i.code for i in catalog.items] == ["first_item"]
    assert catalog.packages == ()
    with session_factory() as session:
        assert session.execute(text("SELECT count(*) FROM service_packages")).scalar_one() == 1


def test_every_upsert_moves_updated_at_forward(session_factory: sessionmaker[Session]) -> None:
    seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)
    tables = ("equipment_items", "service_packages", "bookings")
    with session_factory.begin() as session:
        for table in tables:
            session.execute(text(f"UPDATE {table} SET updated_at = '2000-01-01T00:00:00+00'"))

    seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)

    with session_factory() as session:
        for table in tables:
            total, stale = session.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE updated_at < '2001-01-01')"
                    f" FROM {table}"
                )
            ).one()
            assert total > 0
            assert stale == 0, table
