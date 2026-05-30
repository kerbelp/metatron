"""Tests for settings loading: defaults, file values, and env overrides."""

from metatron.config import load_settings
from metatron.extraction.provider import DEFAULT_MODEL


def test_defaults_when_no_file_and_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = load_settings(tmp_path / "absent.toml")

    assert settings.db_path == "metatron.db"
    assert settings.model == DEFAULT_MODEL
    assert settings.anthropic_api_key is None


def test_reads_values_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ndb_path = "/data/priors.db"\nmodel = "claude-y"\n')

    settings = load_settings(cfg)

    assert settings.db_path == "/data/priors.db"
    assert settings.model == "claude-y"


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ndb_path = "/from/file.db"\n')
    monkeypatch.setenv("METATRON_DB", "/from/env.db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")

    settings = load_settings(cfg)

    assert settings.db_path == "/from/env.db"
    assert settings.anthropic_api_key == "secret"
