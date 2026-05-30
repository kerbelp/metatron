"""Loading and rendering the editable prompt templates.

Prompts live as plain-text files in ``prompts/`` so they are trivial to inspect
and edit. Substitution is plain ``str.format``-style ``{placeholder}`` — no
templating dependency.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Return the raw template text for ``name`` (without the ``.txt`` suffix)."""
    return (_PROMPTS_DIR / f"{name}.txt").read_text()


def render(template: str, **values: object) -> str:
    """Substitute ``{placeholder}`` values into a template."""
    return template.format(**values)
