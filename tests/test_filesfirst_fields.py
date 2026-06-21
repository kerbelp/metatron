"""Tests for field ownership guards on decision edits."""

from metatron.filesfirst.fields import changed_fields, ownership_violations


def test_changed_fields_detects_add_remove_modify():
    old = {"id": "d", "title": "A", "references": 1}
    new = {"id": "d", "title": "B", "references": 1, "keywords": ["x"]}
    assert changed_fields(old, new) == {"title", "keywords"}


def test_human_may_not_edit_machine_fields():
    v = ownership_violations({"references", "title"}, actor="human")
    assert v == {"references"}


def test_ci_may_not_edit_human_fields():
    v = ownership_violations({"references", "title"}, actor="ci")
    assert v == {"title"}


def test_unknown_fields_are_ignored():
    assert ownership_violations({"some-future-field"}, actor="human") == set()
