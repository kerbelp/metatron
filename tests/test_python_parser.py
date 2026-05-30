"""Tests for the language-agnostic parsing layer and its Python implementation."""

import pytest

from metatron.parsing.base import ClassDef, LanguageParser, ParsedFile
from metatron.parsing.python_parser import PythonParser
from metatron.parsing.registry import get_parser_for_path

SAMPLE = '''\
import os
from typing import List
import numpy as np


@dataclass
class Config(BaseModel):
    def validate(self):
        return True


@app.route("/health")
def main():
    pass
'''


@pytest.fixture
def parsed() -> ParsedFile:
    return PythonParser().parse(SAMPLE, "sample.py")


def test_language_parser_is_abstract():
    with pytest.raises(TypeError):
        LanguageParser()  # type: ignore[abstract]


def test_python_parser_reports_its_language():
    assert PythonParser().language == "python"


def test_parsed_file_records_path_and_language(parsed):
    assert parsed.path == "sample.py"
    assert parsed.language == "python"


def test_extracts_imported_modules(parsed):
    assert set(parsed.imports) == {"os", "typing", "numpy"}


def test_extracts_function_and_method_names(parsed):
    assert set(parsed.functions) == {"validate", "main"}


def test_extracts_classes_with_base_classes(parsed):
    assert parsed.classes == [ClassDef(name="Config", bases=["BaseModel"])]


def test_extracts_decorator_names_including_dotted_and_calls(parsed):
    assert set(parsed.decorators) == {"dataclass", "app.route"}


def test_handles_empty_source():
    parsed = PythonParser().parse("", "empty.py")
    assert parsed.imports == []
    assert parsed.functions == []
    assert parsed.classes == []
    assert parsed.decorators == []


def test_registry_returns_python_parser_for_py_files():
    parser = get_parser_for_path("a/b/thing.py")
    assert isinstance(parser, PythonParser)


def test_registry_returns_none_for_unknown_extension():
    assert get_parser_for_path("a/b/thing.rs") is None
