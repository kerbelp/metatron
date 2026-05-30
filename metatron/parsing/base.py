"""The parsing interface and its structural-fact data types.

Parsing produces deterministic *structural facts* about a file — imports,
defined functions/methods, classes and their bases, decorators used. These feed
the signal-collection step; they are intentionally language-agnostic so other
grammars can implement the same ``ParsedFile`` shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ClassDef(BaseModel):
    name: str
    bases: list[str] = Field(default_factory=list)


class ParsedFile(BaseModel):
    path: str
    language: str
    imports: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    classes: list[ClassDef] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)


class LanguageParser(ABC):
    """Parses one language's source into a :class:`ParsedFile`."""

    language: str

    @abstractmethod
    def parse(self, source: str, path: str) -> ParsedFile:
        """Parse ``source`` (the contents of ``path``) into structural facts."""
