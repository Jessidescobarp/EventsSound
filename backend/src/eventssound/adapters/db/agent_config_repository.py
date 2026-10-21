"""Versioned agent configuration in Postgres behind the `AgentConfigRepository` port."""

import logging
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable, VersionConflict
from eventssound.domain.agent_config import (
    AgentConfig,
    AuditEntry,
    StoredAgentConfig,
    validate_config,
    validate_note,
)
from eventssound.domain.errors import InvalidAgentConfig

from .models import AgentSettingsAuditModel as Audit
from .models import AgentSettingsModel as Settings

_UNIQUE_VIOLATION = "23505"
logger = logging.getLogger("eventssound.agent_config")


def _to_stored(row: Settings) -> StoredAgentConfig:
    try:
        # Structure, types and ceilings only; the model allowlist is checked by the caller.
        config = AgentConfig.from_mapping(row.config, None)
    except InvalidAgentConfig as error:
        raise InvalidStoredData from error
    return StoredAgentConfig(config, row.version, row.created_at, row.created_by_user_id, row.note)


def _diff(old: dict | None, new: dict) -> dict[str, list]:
    previous = old or {}
    return {k: [previous.get(k), v] for k, v in new.items() if previous.get(k) != v}


class SqlAlchemyAgentConfigRepository:
    def __init__(self, factory: sessionmaker[Session], allowed_models: Collection[str]) -> None:
        self._allowed_models = allowed_models
        self._factory = factory

    def get_active(self) -> StoredAgentConfig | None:
        try:
            with self._factory() as session:
                row = session.scalars(select(Settings).order_by(Settings.version.desc())).first()
                return None if row is None else _to_stored(row)
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def history(self, limit: int) -> list[StoredAgentConfig]:
        try:
            with self._factory() as session:
                rows = session.scalars(
                    select(Settings).order_by(Settings.version.desc()).limit(limit)
                ).all()
                stored = []
                for row in rows:
                    try:
                        stored.append(_to_stored(row))
                    except InvalidStoredData:
                        # One bad row must not hide the rest; the warning names no values.
                        logger.warning("agent config version %s no longer parses", row.version)
                return stored
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def audit(self, limit: int) -> list[AuditEntry]:
        try:
            with self._factory() as session:
                rows = session.execute(
                    select(Audit, Settings.note)
                    .join(Settings, Settings.version == Audit.version)
                    .order_by(Audit.version.desc())
                    .limit(limit)
                ).all()
                return [
                    AuditEntry(a.version, a.at, a.user_id, a.action, a.diff, note)
                    for a, note in rows
                ]
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def save(
        self,
        config: AgentConfig,
        *,
        base_version: int,
        user_id: UUID | None,
        note: str | None,
        action: str = "save",
    ) -> StoredAgentConfig:
        config = validate_config(config, self._allowed_models)  # before touching the database
        note = validate_note(note)
        if action not in ("save", "rollback"):
            raise InvalidAgentConfig("action must be save or rollback")
        try:
            with self._factory.begin() as session:
                current = session.scalars(
                    select(Settings).order_by(Settings.version.desc()).limit(1)
                ).first()
                if (current.version if current else 0) != base_version:
                    raise VersionConflict
                row = Settings(
                    version=base_version + 1,
                    config=config.to_dict(),
                    created_by_user_id=user_id,
                    note=note,
                )
                session.add(row)
                session.flush()
                session.add(
                    Audit(
                        version=row.version,
                        user_id=user_id,
                        action=action,
                        diff=_diff(current.config if current else None, row.config),
                    )
                )
                session.flush()
                session.refresh(row)
                return StoredAgentConfig(
                    config, row.version, row.created_at, row.created_by_user_id, row.note
                )
        except IntegrityError as error:
            # Two writers read the same base: the loser hits the primary key on `version`.
            if getattr(error.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
                raise VersionConflict from error
            raise RepositoryUnavailable from error
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
