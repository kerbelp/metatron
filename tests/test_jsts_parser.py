"""Tests for the TypeScript/JavaScript parsers and their registry wiring."""

import pytest

from metatron.parsing.base import ClassDef
from metatron.parsing.jsts_parser import (
    JavaScriptParser,
    TsxParser,
    TypeScriptParser,
)
from metatron.parsing.registry import get_parser_for_path

TS_SAMPLE = '''\
import { component$ } from "@builder.io/qwik";
import Default from "./mod";
export { x } from "./re-export";

@Component()
class Foo extends Bar implements Baz {
  method() {}
}

function topFn() {}
const arrowFn = () => {};
'''

TSX_SAMPLE = '''\
import { component$ } from "@builder.io/qwik";

export const Counter = component$(() => {
  return <div class="counter">hi</div>;
});
'''

JS_SAMPLE = '''\
import { x } from "./mod";
class Widget extends Base {}
function run() {}
const handler = () => {};
'''


# --- TypeScript ---------------------------------------------------------

@pytest.fixture
def ts():
    return TypeScriptParser().parse(TS_SAMPLE, "thing.ts")


def test_typescript_language_name(ts):
    assert ts.language == "typescript"


def test_typescript_extracts_module_specifiers_without_quotes(ts):
    assert set(ts.imports) == {"@builder.io/qwik", "./mod", "./re-export"}


def test_typescript_extracts_functions_methods_and_arrow_consts(ts):
    assert {"topFn", "method", "arrowFn"} <= set(ts.functions)


def test_typescript_extracts_class_with_extends_and_implements(ts):
    assert ts.classes == [ClassDef(name="Foo", bases=["Bar", "Baz"])]


def test_typescript_extracts_decorator_name(ts):
    assert "Component" in ts.decorators


# --- TSX ----------------------------------------------------------------

def test_tsx_parses_jsx_and_extracts_imports():
    parsed = TsxParser().parse(TSX_SAMPLE, "counter.tsx")
    assert parsed.language == "tsx"
    assert "@builder.io/qwik" in parsed.imports


# --- JavaScript ---------------------------------------------------------

def test_javascript_extracts_imports_functions_and_classes():
    parsed = JavaScriptParser().parse(JS_SAMPLE, "thing.js")
    assert parsed.language == "javascript"
    assert parsed.imports == ["./mod"]
    assert {"run", "handler"} <= set(parsed.functions)
    assert parsed.classes == [ClassDef(name="Widget", bases=["Base"])]


# --- registry -----------------------------------------------------------

@pytest.mark.parametrize(
    "path,language",
    [
        ("a/b.ts", "typescript"),
        ("a/b.mts", "typescript"),
        ("a/b.tsx", "tsx"),
        ("a/b.js", "javascript"),
        ("a/b.mjs", "javascript"),
    ],
)
def test_registry_maps_extensions_to_parsers(path, language):
    parser = get_parser_for_path(path)
    assert parser is not None
    assert parser.language == language
