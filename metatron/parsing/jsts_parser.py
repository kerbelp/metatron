"""TypeScript / TSX / JavaScript parsers.

TypeScript is a superset of JavaScript and the three tree-sitter grammars share
the node types we care about (imports, functions, classes, decorators), so one
parametrized base handles all three; the concrete classes only supply the grammar
and a language label.
"""

from __future__ import annotations

import tree_sitter_javascript as tsj
import tree_sitter_typescript as tst
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from metatron.parsing.base import ClassDef, LanguageParser, ParsedFile

# Module specifiers from `import ... from "x"` and `export ... from "x"`.
_IMPORTS_QUERY = """
(import_statement source: (string) @mod)
(export_statement source: (string) @mod)
"""
# Named functions, methods, and arrow functions bound to a const/let/var.
_FUNCTIONS_QUERY = """
(function_declaration name: (identifier) @fn)
(method_definition name: (property_identifier) @fn)
(variable_declarator name: (identifier) @fn value: (arrow_function))
"""
_CLASSES_QUERY = "(class_declaration) @cls"
_DECORATORS_QUERY = "(decorator) @dec"

_HERITAGE_NAME_TYPES = {"identifier", "type_identifier"}


class _JsTsParser(LanguageParser):
    """Shared logic; subclasses set ``language`` and ``_ts_language``."""

    _ts_language: Language

    def __init__(self) -> None:
        self._parser = Parser(self._ts_language)
        self._imports = Query(self._ts_language, _IMPORTS_QUERY)
        self._functions = Query(self._ts_language, _FUNCTIONS_QUERY)
        self._classes = Query(self._ts_language, _CLASSES_QUERY)
        self._decorators = Query(self._ts_language, _DECORATORS_QUERY)

    def parse(self, source: str, path: str) -> ParsedFile:
        root = self._parser.parse(source.encode()).root_node
        return ParsedFile(
            path=path,
            language=self.language,
            imports=[_strip_quotes(_text(n)) for n in self._cap(self._imports, root, "mod")],
            functions=[_text(n) for n in self._cap(self._functions, root, "fn")],
            classes=[_class_def(n) for n in self._cap(self._classes, root, "cls")],
            decorators=[
                _decorator_name(n) for n in self._cap(self._decorators, root, "dec")
            ],
        )

    @staticmethod
    def _cap(query: Query, root: Node, name: str) -> list[Node]:
        return QueryCursor(query).captures(root).get(name, [])


class TypeScriptParser(_JsTsParser):
    language = "typescript"
    _ts_language = Language(tst.language_typescript())


class TsxParser(_JsTsParser):
    language = "tsx"
    _ts_language = Language(tst.language_tsx())


class JavaScriptParser(_JsTsParser):
    language = "javascript"
    _ts_language = Language(tsj.language())


def _text(node: Node) -> str:
    return node.text.decode()


def _strip_quotes(text: str) -> str:
    return text.strip("\"'`")


def _class_def(node: Node) -> ClassDef:
    name = _text(node.child_by_field_name("name"))
    bases: list[str] = []
    for child in node.named_children:
        if child.type != "class_heritage":
            continue
        for h in child.named_children:
            if h.type in _HERITAGE_NAME_TYPES:
                # JavaScript: the base is a direct child of class_heritage.
                bases.append(_text(h))
            else:
                # TypeScript: wrapped in extends_clause / implements_clause.
                bases.extend(
                    _text(sub)
                    for sub in h.named_children
                    if sub.type in _HERITAGE_NAME_TYPES
                )
    return ClassDef(name=name, bases=bases)


def _decorator_name(node: Node) -> str:
    target = node.named_children[0]
    if target.type == "call_expression":
        target = target.child_by_field_name("function")
    return _text(target)
