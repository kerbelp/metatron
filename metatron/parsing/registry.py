"""Maps source files to the parser for their language.

This is the single place grammars are wired up. The language-agnostic core means
adding a language is registering one more ``LanguageParser`` here; nothing else
changes. Python is the reference grammar for the first milestone.
"""

from __future__ import annotations

import os

from metatron.parsing.base import LanguageParser
from metatron.parsing.python_parser import PythonParser

# Extension -> parser factory. Add new languages here.
_PARSERS_BY_EXTENSION: dict[str, type[LanguageParser]] = {
    ".py": PythonParser,
}


def get_parser_for_path(path: str) -> LanguageParser | None:
    """Return a parser for the file's extension, or ``None`` if unsupported."""
    _, ext = os.path.splitext(path)
    parser_cls = _PARSERS_BY_EXTENSION.get(ext.lower())
    return parser_cls() if parser_cls is not None else None
