"""UTF-8 files must work independently of the host's default text encoding."""

import json
from pathlib import Path

import pytest

from metatron.config import load_settings, update_settings
from metatron.extraction import prompts
from metatron.identity import load_identity, set_identity
from metatron.mirror.okf import export_okf_bundle, validate_okf_bundle
from metatron.mirror.sync_import import import_bundle
from metatron.models import Decision, Origin, Status
from metatron.pipeline import _parse_tracked_files
from metatron.storage.sqlite import SQLiteDecisionStore
from metatron.version import upgrade_plan
from metatron.webui.files_mode import FilesMode


_TEXT = "日本語 — café"


@pytest.fixture(params=["cp932", "cp1252"])
def legacy_encoding(request, monkeypatch):
    # Changing locale.getpreferredencoding alone does not change the encoding
    # selected by Python's text I/O. Substitute the default at the Path.open
    # boundary instead, preserving explicit encodings and binary operations.
    original_open = Path.open

    def open_with_legacy_default(path, mode="r", buffering=-1, encoding=None,
                                 errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = request.param
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", open_with_legacy_default)


def test_mirror_utf8_round_trip(tmp_path, legacy_encoding):
    store = SQLiteDecisionStore(":memory:")
    decision = store.add(Decision(
        repo="r", pattern=_TEXT, scope="app", rationale=_TEXT,
        origin=Origin.HUMAN, status=Status.CANDIDATE,
    ))
    export_okf_bundle(store, repo="r", root=tmp_path, events=[])
    assert validate_okf_bundle(tmp_path) == []

    path = next((tmp_path / "context" / "candidate").glob("*.md"))
    text = path.read_text(encoding="utf-8")
    assert _TEXT in text
    assert import_bundle(store, repo="r", root=tmp_path).updated == []

    edited = _TEXT + " updated"
    path.write_text(text.replace(_TEXT, edited), encoding="utf-8")
    result = import_bundle(store, repo="r", root=tmp_path)
    assert result.conflicts == []
    assert result.updated == [decision.id]
    assert store.get(decision.id).pattern == edited
    assert store.get(decision.id).rationale == edited


def test_files_ui_creates_maps_and_edits_utf8(tmp_path, legacy_encoding):
    store = SQLiteDecisionStore(":memory:")
    decision = store.add(Decision(
        repo="r", pattern=_TEXT, scope="app", rationale=_TEXT,
        origin=Origin.HUMAN, status=Status.CANDIDATE,
    ))
    files = FilesMode(store, tmp_path, repo="r")
    files.write_new(decision.id)
    files.refresh()
    assert files.has_file(decision.id)
    assert store.get(decision.id).pattern == _TEXT

    edited = _TEXT + " updated"
    store.update_fields(decision.id, pattern=edited)
    files.write_back(decision.id)
    text = files.paths[decision.id].read_text(encoding="utf-8")
    assert edited in text


def test_settings_and_identity_preserve_utf8(tmp_path, legacy_encoding):
    path = tmp_path / "metatron.toml"
    update_settings({"default_repo": _TEXT}, path)
    assert load_settings(path).default_repo == _TEXT
    update_settings({"output_language": "日本語"}, path)
    settings = load_settings(path)
    assert settings.default_repo == _TEXT
    assert settings.output_language == "日本語"

    identity = set_identity(email="dev@example.com", display_name=_TEXT)
    assert load_identity() == identity
    updated = set_identity(email="updated@example.com")
    assert updated.display_name == _TEXT
    assert load_identity() == updated


def test_prompt_template_preserves_utf8(tmp_path, monkeypatch, legacy_encoding):
    (tmp_path / "example.txt").write_text(_TEXT, encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", tmp_path)
    assert prompts.load_prompt("example", language="english") == _TEXT


def test_ingest_does_not_skip_utf8_source(tmp_path, monkeypatch, legacy_encoding):
    (tmp_path / "example.py").write_text(
        f'# {_TEXT}\nimport os\ndef 日本語():\n    pass\n', encoding="utf-8")
    monkeypatch.setattr("metatron.pipeline._tracked_files", lambda *args: ["example.py"])
    parsed = _parse_tracked_files(tmp_path)
    assert len(parsed) == 1
    assert parsed[0].imports == ["os"]
    assert parsed[0].functions == ["日本語"]


def test_user_edited_install_state_preserves_utf8(monkeypatch, legacy_encoding):
    from metatron.identity import config_path

    monkeypatch.delenv("METATRON_INSTALL_CMD", raising=False)
    path = config_path().parent / "install.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    command = f"uv tool upgrade getmetatron --index https://example.com/{_TEXT}"
    path.write_text(json.dumps({"upgrade_command": command}, ensure_ascii=False),
                    encoding="utf-8")
    assert upgrade_plan().command == command
