from sqlalchemy import text

from eventssound.config import Settings
from eventssound.entrypoints.api.app import create_app


def test_session_is_bound_to_the_configured_url_and_closed_after_use(database_url: str) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=database_url)  # type: ignore[arg-type]
    app = create_app(settings)

    provider = app.state.session_provider
    generator = provider()
    session = next(generator)

    assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert session.get_bind().url.render_as_string(hide_password=False) == database_url
    assert session.in_transaction()

    generator.close()

    assert not session.in_transaction()


def test_session_provider_can_be_overridden() -> None:
    def fake_provider():  # noqa: ANN202
        yield "fake-session"

    settings = Settings(_env_file=None, DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x")  # type: ignore[arg-type]
    app = create_app(settings, session_provider=fake_provider)

    assert next(app.state.session_provider()) == "fake-session"
