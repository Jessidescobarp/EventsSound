"""Migration 0010 and the Postgres agent config repository (needs DATABASE_URL_TEST)."""

import logging
from collections.abc import Iterator
from dataclasses import replace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.db.agent_config_repository import SqlAlchemyAgentConfigRepository
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable, VersionConflict
from eventssound.domain.agent_config import AgentConfig
from eventssound.domain.errors import InvalidAgentConfig

CONFIG = AgentConfig("cercano", "strict", "No.", "Gracias.", "Hola.", "v/m", 10, 20, 3)
ALLOWED = ("v/m", "v/other")


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


@pytest.fixture
def repo(engine: Engine) -> SqlAlchemyAgentConfigRepository:
    return SqlAlchemyAgentConfigRepository(sessionmaker(engine), ALLOWED)


def count(engine: Engine, table: str) -> int:
    with engine.connect() as c:
        return c.scalar(text(f"SELECT count(*) FROM {table}")) or 0


def test_migration_creates_and_drops_both_tables(alembic_config: Config, database_url: str) -> None:
    tables = {"agent_settings", "agent_settings_audit"}
    command.upgrade(alembic_config, "0010")
    engine = create_engine(database_url)
    try:
        assert tables <= set(inspect(engine).get_table_names())
        command.downgrade(alembic_config, "0009")
        assert not tables & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_empty_then_save_get_history(repo: SqlAlchemyAgentConfigRepository) -> None:
    assert repo.get_active() is None
    first = repo.save(CONFIG, base_version=0, user_id=None, note="first")
    second = repo.save(replace(CONFIG, tone="formal"), base_version=1, user_id=None, note=None)

    assert (first.version, second.version) == (1, 2)
    active = repo.get_active()
    assert active is not None and active.version == 2 and active.config.tone == "formal"
    assert [s.version for s in repo.history(10)] == [2, 1]
    assert [s.version for s in repo.history(1)] == [2]
    assert repo.history(10)[1].note == "first"


@pytest.mark.parametrize("base", [0, 2, 5])
def test_stale_or_future_base_version_conflicts(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine, base: int
) -> None:
    repo.save(CONFIG, base_version=0, user_id=None, note=None)

    with pytest.raises(VersionConflict):
        repo.save(CONFIG, base_version=base, user_id=None, note=None)

    assert (count(engine, "agent_settings"), count(engine, "agent_settings_audit")) == (1, 1)


@pytest.mark.parametrize(
    ("config", "note"),
    [
        (replace(CONFIG, daily_token_cap=0), None),
        (replace(CONFIG, llm_model="v/not-allowed"), None),
        (replace(CONFIG, welcome_message="mira http://x.co"), None),
        (CONFIG, "n" * 201),
    ],
)
def test_invalid_input_is_rejected_before_writing(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine, config: AgentConfig, note: str | None
) -> None:
    with pytest.raises(InvalidAgentConfig):
        repo.save(config, base_version=0, user_id=None, note=note)

    assert (count(engine, "agent_settings"), count(engine, "agent_settings_audit")) == (0, 0)


def test_database_refuses_a_note_over_200_chars(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text("INSERT INTO agent_settings (version, config, note) VALUES (1, '{}', :n)"),
            {"n": "n" * 201},
        )


def test_audit_row_holds_the_diff_and_user(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine
) -> None:
    with engine.begin() as c:
        user_id = c.scalar(
            text(
                "INSERT INTO users (email, role, password_hash) "
                "VALUES ('a@x.co', 'admin', 'h') RETURNING id"
            )
        )
    repo.save(CONFIG, base_version=0, user_id=user_id, note=None)
    changed = replace(CONFIG, tone="formal", daily_token_cap=11)
    repo.save(changed, base_version=1, user_id=None, note=None)

    with engine.connect() as c:
        rows = c.execute(
            text("SELECT user_id, action, diff FROM agent_settings_audit ORDER BY version")
        ).all()
    assert rows[0].user_id == user_id and rows[0].action == "save"
    assert rows[1].diff == {"tone": ["cercano", "formal"], "daily_token_cap": [10, 11]}


def test_audit_failure_rolls_back_the_settings_row(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine
) -> None:
    with engine.begin() as c:
        c.execute(text("ALTER TABLE agent_settings_audit ADD CONSTRAINT boom CHECK (false)"))

    with pytest.raises(RepositoryUnavailable):
        repo.save(CONFIG, base_version=0, user_id=None, note=None)

    assert count(engine, "agent_settings") == 0


def corrupt(engine: Engine, version: int) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                'UPDATE agent_settings SET config = \'{"tone": "SECRETVALUE"}\' WHERE version = :v'
            ),
            {"v": version},
        )


def test_corrupt_latest_row_raises_invalid_stored_data(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine
) -> None:
    repo.save(CONFIG, base_version=0, user_id=None, note=None)
    corrupt(engine, 1)

    with pytest.raises(InvalidStoredData):
        repo.get_active()


def test_history_skips_a_corrupt_row_without_logging_values(
    repo: SqlAlchemyAgentConfigRepository, engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    repo.save(CONFIG, base_version=0, user_id=None, note=None)
    repo.save(CONFIG, base_version=1, user_id=None, note=None)
    corrupt(engine, 1)

    with caplog.at_level(logging.WARNING):
        assert [s.version for s in repo.history(10)] == [2]
    assert "SECRETVALUE" not in caplog.text and "version 1" in caplog.text


def test_unreachable_database_maps_to_repository_unavailable(unreachable_session_factory) -> None:
    repo = SqlAlchemyAgentConfigRepository(unreachable_session_factory, ALLOWED)
    with pytest.raises(RepositoryUnavailable) as raised:
        repo.get_active()
    assert "S3cr3t" not in str(raised.value)


def test_concurrent_writer_losing_the_race_gets_a_conflict(engine: Engine) -> None:
    factory = sessionmaker(engine)
    inserted = []

    @event.listens_for(factory, "before_flush")
    def _rival_commits_first(session, flush_context, instances) -> None:  # noqa: ANN001
        if not inserted:
            inserted.append(True)
            with engine.begin() as other:
                other.execute(
                    text("INSERT INTO agent_settings (version, config) VALUES (1, '{}'::jsonb)")
                )

    with pytest.raises(VersionConflict):
        SqlAlchemyAgentConfigRepository(factory, ALLOWED).save(
            CONFIG, base_version=0, user_id=None, note=None
        )
