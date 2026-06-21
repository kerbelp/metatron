"""Loading and rendering the editable prompt templates.

Prompts live as plain-text files in ``prompts/`` so they are trivial to inspect
and edit. Substitution is plain ``str.format``-style ``{placeholder}`` — no
templating dependency.
"""

from __future__ import annotations

from pathlib import Path

from metatron.config import DEFAULT_OUTPUT_LANGUAGE, get_output_language

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str, language: str | None = None) -> str:
    """Return the template text for ``name`` (without the ``.txt`` suffix).

    When the configured output language is not the English default, a directive is
    appended so the LLM writes the natural-language field values in that language.
    ``language`` defaults to :func:`metatron.config.get_output_language`, keeping all
    call sites language-agnostic; pass it explicitly only to override resolution.
    """
    template = (_PROMPTS_DIR / f"{name}.txt").read_text()
    if language is None:
        language = get_output_language()
    return _with_language_directive(template, language)


def _with_language_directive(template: str, language: str) -> str:
    """Append the output-language directive unless the language is the English default.

    The directive carries no ``{placeholder}`` braces, so the appended text passes
    through :func:`render` (``str.format``) untouched. It closes by re-asserting the
    JSON-only output format: because the directive is appended after the template's own
    "no prose outside the JSON array" instruction, the format constraint must be
    restated so it remains the final line the model reads.
    """
    if language.strip().lower() == DEFAULT_OUTPUT_LANGUAGE:
        return template
    directive = (
        "\n\nOutput language: write all natural-language field values "
        f"(the \"pattern\" and \"rationale\" fields, and any human-readable text) in {language}. "
        "Keep code identifiers, file paths, library names, and JSON keys exactly as they "
        "appear in the source — never translate them. Keywords may be written in "
        f"{language} or English, whichever an engineer on this codebase would search with. "
        "Still return only the JSON array described above, with no prose outside it."
    )
    return template + directive


def render(template: str, **values: object) -> str:
    """Substitute ``{placeholder}`` values into a template."""
    return template.format(**values)
