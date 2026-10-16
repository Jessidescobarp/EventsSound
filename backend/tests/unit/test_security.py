"""Abuse detection: hashed client keys and the refusal-count block (in-memory log, no database)."""

from datetime import UTC, datetime, timedelta

import pytest

from eventssound.application.security import (
    CHAT_REFUSED,
    LOGIN_FAILED,
    AbuseGate,
    client_key,
    derive_key,
)
from fakes import InMemorySecurityLog as MemoryLog

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
KEY = b"k" * 32


def gate(log: MemoryLog, now: datetime = NOW, enabled: bool = True) -> AbuseGate:
    return AbuseGate(log, KEY, lambda: now, enabled=enabled)


def test_client_key_is_stable_keyed_and_never_the_raw_address() -> None:
    key = client_key("203.0.113.7", KEY)

    assert key == client_key("203.0.113.7", KEY)
    assert key != client_key("203.0.113.8", KEY) and key != client_key("203.0.113.7", b"o" * 32)
    assert len(key) == 16 and int(key, 16) >= 0 and "203" not in key


def test_derived_key_is_purpose_bound_and_depends_on_the_secret() -> None:
    assert derive_key("secret-a") == derive_key("secret-a")
    assert derive_key("secret-a") != derive_key("secret-b")
    assert derive_key("secret-a") != b"secret-a" and len(derive_key("secret-a")) == 32


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
        log.add(CHAT_REFUSED, client_key("1.1.1.1", KEY), NOW - age)

    assert gate(log).is_blocked("1.1.1.1") is blocked


def test_other_kinds_and_other_clients_do_not_count() -> None:
    log = MemoryLog()
    for _ in range(6):
        log.add(LOGIN_FAILED, client_key("1.1.1.1", KEY), NOW)
        log.add(CHAT_REFUSED, client_key("2.2.2.2", KEY), NOW)

    assert gate(log).is_blocked("1.1.1.1") is False


def test_storage_errors_fail_open_and_record_never_raises() -> None:
    broken = gate(MemoryLog(broken=True))

    broken.record(CHAT_REFUSED, "1.1.1.1")

    assert broken.is_blocked("1.1.1.1") is False


def test_record_stores_the_hashed_key_only() -> None:
    log = MemoryLog()

    gate(log).record(LOGIN_FAILED, "9.9.9.9")

    assert log.rows == [(LOGIN_FAILED, client_key("9.9.9.9", KEY), NOW)]


def test_a_disabled_gate_never_blocks_and_skips_refusals_but_keeps_login_failures() -> None:
    log = MemoryLog()
    for _ in range(6):
        log.add(CHAT_REFUSED, client_key("1.1.1.1", KEY), NOW)
    off = gate(log, enabled=False)

    off.record(CHAT_REFUSED, "1.1.1.1")
    off.record(LOGIN_FAILED, "1.1.1.1")

    assert off.is_blocked("1.1.1.1") is False
    assert [k for k, _, _ in log.rows].count(CHAT_REFUSED) == 6 and log.rows[-1][0] == LOGIN_FAILED
