"""Tests for settings loading: defaults, file values, and env overrides."""

from metatron.config import DEFAULT_DB_PATH, load_settings, update_settings
from metatron.extraction.provider import DEFAULT_MODEL


def test_defaults_when_no_file_and_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = load_settings(tmp_path / "absent.toml")

    # Defaults to the shared catalog data dir (~/.metatron), not a cwd file.
    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.model == DEFAULT_MODEL
    assert settings.anthropic_api_key is None


def test_reads_values_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ndb_path = "/data/decisions.db"\nmodel = "claude-y"\n')

    settings = load_settings(cfg)

    assert settings.db_path == "/data/decisions.db"
    assert settings.model == "claude-y"


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ndb_path = "/from/file.db"\n')
    monkeypatch.setenv("METATRON_DB", "/from/env.db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")

    settings = load_settings(cfg)

    assert settings.db_path == "/from/env.db"
    assert settings.anthropic_api_key == "secret"


def test_update_settings_creates_file_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    cfg = tmp_path / "metatron.toml"

    update_settings({"default_repo": "github.com/acme/app"}, cfg)

    assert load_settings(cfg).default_repo == "github.com/acme/app"


def test_update_settings_preserves_other_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ndb_path = "/data/decisions.db"\nmodel = "claude-y"\n')

    update_settings({"default_repo": "github.com/acme/app"}, cfg)

    settings = load_settings(cfg)
    assert settings.default_repo == "github.com/acme/app"
    assert settings.db_path == "/data/decisions.db"
    assert settings.model == "claude-y"


def test_update_settings_none_removes_key(tmp_path):
    cfg = tmp_path / "metatron.toml"
    update_settings({"default_repo": "github.com/acme/app"}, cfg)
    update_settings({"default_repo": None}, cfg)
    assert load_settings(cfg).default_repo is None
