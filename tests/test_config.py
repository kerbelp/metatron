"""Tests for settings loading: defaults, file values, and env overrides."""

from metatron.config import (
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT_LANGUAGE,
    get_output_language,
    load_settings,
    update_settings,
)
from metatron.extraction.provider import DEFAULT_MODEL


def test_defaults_when_no_file_and_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("METATRON_OUTPUT_LANGUAGE", raising=False)

    settings = load_settings(tmp_path / "absent.toml")

    # Defaults to the shared catalog data dir (~/.metatron), not a cwd file.
    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.model == DEFAULT_MODEL
    assert settings.anthropic_api_key is None
    assert settings.output_language == DEFAULT_OUTPUT_LANGUAGE


def test_reads_output_language_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_OUTPUT_LANGUAGE", raising=False)
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\noutput_language = "french"\n')

    assert load_settings(cfg).output_language == "french"
    assert get_output_language(cfg) == "french"


def test_env_overrides_output_language(tmp_path, monkeypatch):
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\noutput_language = "french"\n')
    monkeypatch.setenv("METATRON_OUTPUT_LANGUAGE", "german")

    assert load_settings(cfg).output_language == "german"
    assert get_output_language(cfg) == "german"


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


def test_context_dir_env_beats_toml(tmp_path, monkeypatch):
    cfg = tmp_path / "metatron.toml"
    cfg.write_text('[metatron]\ncontext_dir = "kb"\n')
    monkeypatch.setenv("METATRON_CONTEXT_DIR", "conventions")
    assert load_settings(cfg).context_dir == "conventions"
    monkeypatch.delenv("METATRON_CONTEXT_DIR")
    assert load_settings(cfg).context_dir == "kb"


def test_context_dir_unset_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("METATRON_CONTEXT_DIR", raising=False)
    assert load_settings(tmp_path / "metatron.toml").context_dir is None


def test_resolve_context_dir_prefers_default(tmp_path):
    from metatron.config import resolve_context_dir
    assert resolve_context_dir(tmp_path) == tmp_path / "context"


def test_resolve_context_dir_explicit_config_wins(tmp_path):
    from metatron.config import resolve_context_dir
    # Explicit config is used as-is even when a legacy bundle exists.
    (tmp_path / "metatron" / "decisions").mkdir(parents=True)
    assert resolve_context_dir(tmp_path, "kb") == tmp_path / "kb"


def test_resolve_context_dir_falls_back_to_legacy_bundle(tmp_path):
    from metatron.config import resolve_context_dir
    (tmp_path / "metatron" / "decisions").mkdir(parents=True)
    assert resolve_context_dir(tmp_path) == tmp_path / "metatron"
    # ...but only while context/ is absent: once it exists, it wins.
    (tmp_path / "context").mkdir()
    assert resolve_context_dir(tmp_path) == tmp_path / "context"


def test_resolve_context_dir_ignores_non_bundle_metatron_dir(tmp_path):
    from metatron.config import resolve_context_dir
    # A metatron/ dir without status subdirectories (e.g. a Python package)
    # is not a legacy bundle and must not hijack resolution.
    (tmp_path / "metatron").mkdir()
    (tmp_path / "metatron" / "__init__.py").touch()
    assert resolve_context_dir(tmp_path) == tmp_path / "context"
