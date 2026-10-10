from pathlib import Path

import pytest

from eventssound import config
from eventssound.config import Settings, root_env_file

FILE_URL = "postgresql+psycopg://file:file@127.0.0.1:5432/from_file"
ENV_URL = "postgresql+psycopg://env:env@127.0.0.1:5432/from_env"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "DATABASE_URL", "CORS_ALLOWED_ORIGINS", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_root_env_file_points_at_the_repo_root() -> None:
    module = Path("/repo/backend/src/eventssound/config.py")

    assert root_env_file(module) == Path("/repo/.env").resolve()


def test_root_env_file_does_not_raise_on_shallow_install_paths() -> None:
    assert root_env_file(Path("/config.py")) is None
    assert root_env_file(Path("/app/src/eventssound/config.py")) is None


def test_settings_load_the_root_env_file_from_any_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    module = root / "backend" / "src" / "eventssound" / "config.py"
    module.parent.mkdir(parents=True)
    (root / ".env").write_text(f"DATABASE_URL={FILE_URL}\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    settings = Settings(_env_file=root_env_file(module))

    assert settings.database_url.get_secret_value() == FILE_URL
    assert settings.log_level == "DEBUG"


def test_environment_variables_override_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={FILE_URL}\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", ENV_URL)

    settings = Settings(_env_file=env_file)

    assert settings.database_url.get_secret_value() == ENV_URL


def test_missing_root_env_file_is_harmless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", ENV_URL)

    settings = Settings(_env_file=tmp_path / "does-not-exist" / ".env")

    assert settings.database_url.get_secret_value() == ENV_URL


def test_settings_default_env_file_is_the_resolved_root_env() -> None:
    assert Settings.model_config.get("env_file") == config.root_env_file()
