"""Python implementation of :class:`LanguageParser` (the reference grammar)."""

from __future__ import annotations

import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from metatron.parsing.base import ClassDef, LanguageParser, ParsedFile

_LANGUAGE = Language(tsp.language())

_IMPORTS_QUERY = """
(import_statement name: (dotted_name) @mod)
(import_statement name: (aliased_import name: (dotted_name) @mod))
(import_from_statement module_name: (dotted_name) @mod)
"""
_FUNCTIONS_QUERY = "(function_definition name: (identifier) @fn)"
_CLASSES_QUERY = "(class_definition) @cls"
_DECORATORS_QUERY = "(decorator) @dec"


class PythonParser(LanguageParser):
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(_LANGUAGE)
        self._imports = Query(_LANGUAGE, _IMPORTS_QUERY)
        self._functions = Query(_LANGUAGE, _FUNCTIONS_QUERY)
        self._classes = Query(_LANGUAGE, _CLASSES_QUERY)
        self._decorators = Query(_LANGUAGE, _DECORATORS_QUERY)

    def parse(self, source: str, path: str) -> ParsedFile:
        root = self._parser.parse(source.encode()).root_node
        return ParsedFile(
            path=path,
            language=self.language,
            imports=[_text(n) for n in self._capture(self._imports, root, "mod")],
            functions=[_text(n) for n in self._capture(self._functions, root, "fn")],
            classes=[_class_def(n) for n in self._capture(self._classes, root, "cls")],
            decorators=[
                _decorator_name(n)
                for n in self._capture(self._decorators, root, "dec")
            ],
        )

    @staticmethod
    def _capture(query: Query, root: Node, name: str) -> list[Node]:
        return QueryCursor(query).captures(root).get(name, [])


def _text(node: Node) -> str:
    return node.text.decode()


def _class_def(node: Node) -> ClassDef:
    name = _text(node.child_by_field_name("name"))
    superclasses = node.child_by_field_name("superclasses")
    bases = [_text(child) for child in superclasses.named_children] if superclasses else []
    return ClassDef(name=name, bases=bases)


def _decorator_name(node: Node) -> str:
    """The dotted name a decorator references, e.g. ``app.route`` from ``@app.route(...)``."""
    target = node.named_children[0]
    if target.type == "call":
        target = target.child_by_field_name("function")
    return _text(target)
