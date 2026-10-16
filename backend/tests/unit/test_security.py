"""Abuse detection: hashed client keys and the refusal-count block (in-memory log, no database)."""

from datetime import UTC, datetime, timedelta

import pytest

from eventssound.application.security import (
    CHAT_BLOCKED,
    CHAT_REFUSED,
    LOGIN_FAILED,
    AbuseGate,
    client_key,
)
from fakes import InMemorySecurityLog as MemoryLog

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def gate(log: MemoryLog, now: datetime = NOW) -> AbuseGate:
    return AbuseGate(log, "salt", lambda: now)


def test_client_key_is_stable_salted_and_never_the_raw_address() -> None:
    key = client_key("203.0.113.7", "salt")

    assert key == client_key("203.0.113.7", "salt")
    assert key != client_key("203.0.113.8", "salt") and key != client_key("203.0.113.7", "other")
    assert len(key) == 16 and int(key, 16) >= 0 and "203" not in key


@pytest.mark.parametrize(
    ("refusals", "age", "blocked"),
    [
        (4, timedelta(minutes=1), False),
        (5, timedelta(minutes=1), True),
        (5, timedelta(minutes=9, seconds=59), True),
        (5, timedelta(minutes=10, seconds=1), False),  # the window slid past them: block ends
    ],
    ids=["below-limit", "at-limit", "window-edge", "expired"],
)
def test_block_follows_refusals_inside_the_window(
    refusals: int, age: timedelta, blocked: bool
) -> None:
    log = MemoryLog()
    for _ in range(refusals):
        log.add(CHAT_REFUSED, client_key("1.1.1.1", "salt"), NOW - age)

    assert gate(log).is_blocked("1.1.1.1") is blocked


def test_other_kinds_and_other_clients_do_not_count() -> None:
    log = MemoryLog()
    for kind in (CHAT_BLOCKED, LOGIN_FAILED):
        for _ in range(6):
            log.add(kind, client_key("1.1.1.1", "salt"), NOW)
    for _ in range(6):
        log.add(CHAT_REFUSED, client_key("2.2.2.2", "salt"), NOW)

    assert gate(log).is_blocked("1.1.1.1") is False


def test_storage_errors_fail_open_and_record_never_raises() -> None:
    broken = gate(MemoryLog(broken=True))

    broken.record(CHAT_REFUSED, "1.1.1.1")

    assert broken.is_blocked("1.1.1.1") is False


def test_record_stores_the_hashed_key_only() -> None:
    log = MemoryLog()

    gate(log).record(LOGIN_FAILED, "9.9.9.9")

    assert log.rows == [(LOGIN_FAILED, client_key("9.9.9.9", "salt"), NOW)]
