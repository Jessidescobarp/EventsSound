"""reset_schema drops tables, so it must refuse anything that is not a local database."""

import pytest

import conftest
from conftest import UnsafeResetTarget, reset_schema


class Connected(Exception):
    """Raised by the engine factory stand-in: proves the guard let the call through."""


@pytest.fixture(autouse=True)
def engine_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    def would_connect(*args: object, **kwargs: object) -> None:
        raise Connected

    monkeypatch.setattr(conftest, "create_engine", would_connect)
    for name in ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://sentinel_user:sentinel_pw@sentinel-host.example.com:5432/db",
        "postgresql+psycopg://sentinel_user:sentinel_pw@10.0.0.5/db",
        "postgresql+psycopg://sentinel_user:sentinel_pw@localhost.evil.example.com/db",
        "postgresql+psycopg:///db?host=sentinel-host.example.com",
        "postgresql+psycopg://sentinel_user:sentinel_pw@localhost:5432,sentinel-evil:5432/db",
        "not a url",
    ],
    ids=["named-host", "address", "lookalike", "query-host", "multi-host", "garbage"],
)
def test_a_non_local_or_unparsable_url_is_refused_before_any_connection(url: str) -> None:
    with pytest.raises(UnsafeResetTarget) as caught:
        reset_schema(url)

    assert "sentinel" not in str(caught.value)


def test_the_libpq_environment_can_make_a_hostless_url_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOST", "sentinel-host.example.com")

    with pytest.raises(UnsafeResetTarget):
        reset_schema("postgresql+psycopg:///db")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:55434/test",
        "postgresql+psycopg://u:p@localhost:5432/eventssound_test",
        "postgresql+psycopg://u:p@[::1]/db",
    ],
)
def test_a_local_url_reaches_the_connection(url: str) -> None:
    with pytest.raises(Connected):
        reset_schema(url)
