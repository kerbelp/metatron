"""Settings: non-secret config from ``metatron.toml``, secrets and overrides from env.

Resolution order (highest first): environment variables, then the ``[metatron]``
table of ``metatron.toml``, then built-in defaults. Secrets (the Anthropic API
key) come only from the environment and are never read from the file.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

from metatron.extraction.provider import DEFAULT_MODEL

# The catalog data directory (one self-contained DB file per repo lives here). A
# single shared location so sibling repos aggregate, rather than fragmenting per cwd.
# Overridable via METATRON_DB / metatron.toml; pointing it at a single *file* selects
# single-file mode (the recipient of a handed-off DB).
DEFAULT_DB_PATH = str(Path.home() / ".metatron")

# The natural language for LLM-generated output (the ``pattern`` and ``rationale``
# fields, keywords, etc.). The default keeps the historical English-only behaviour;
# code identifiers, file paths, and library names are never translated regardless.
# Overridable via METATRON_OUTPUT_LANGUAGE / metatron.toml so a codebase whose commits
# and comments are not in English does not get English decisions back over MCP.
DEFAULT_OUTPUT_LANGUAGE = "english"

# The knowledge-base directory inside a repo (the OKF bundle root, holding
# ``candidate/`` and ``decisions/``). "context" matches the Repository Context Layer
# framing and avoids colliding with a "metatron" package/dir; earlier bundles used
# ``metatron/``, which resolve_context_dir still recognizes.
DEFAULT_CONTEXT_DIR = "context"
LEGACY_CONTEXT_DIR = "metatron"


class Settings(BaseModel):
    db_path: str = DEFAULT_DB_PATH
    model: str = DEFAULT_MODEL
    anthropic_api_key: str | None = None
    # A persisted default repo (written by ``metatron repo set``). It sits below the
    # ``METATRON_REPO`` env var in precedence, so an env override still wins per-shell.
    default_repo: str | None = None
    # The language LLM output is written in. A global setting today; the
    # ``get_output_language`` helper is the single resolution point so a per-repo
    # override can layer on later without touching the prompt call sites.
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    # The repo's knowledge-base directory name. ``None`` means "not explicitly
    # configured", which lets ``resolve_context_dir`` fall back to a legacy
    # ``metatron/`` bundle; an explicit value is always used as-is.
    context_dir: str | None = None


def load_settings(path: str | Path = "metatron.toml") -> Settings:
    file_values: dict = {}
    path = Path(path)
    if path.exists():
        file_values = tomllib.loads(path.read_text()).get("metatron", {})

    return Settings(
        db_path=os.environ.get(
            "METATRON_DB", file_values.get("db_path", DEFAULT_DB_PATH)
        ),
        model=os.environ.get(
            "METATRON_MODEL", file_values.get("model", DEFAULT_MODEL)
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        default_repo=file_values.get("default_repo"),
        output_language=os.environ.get(
            "METATRON_OUTPUT_LANGUAGE",
            file_values.get("output_language", DEFAULT_OUTPUT_LANGUAGE),
        ),
        context_dir=os.environ.get(
            "METATRON_CONTEXT_DIR", file_values.get("context_dir")
        ),
    )


def resolve_context_dir(root: str | Path = ".", configured: str | None = None) -> Path:
    """The repo's knowledge-base directory under *root*.

    An explicitly *configured* name (CLI flag, ``METATRON_CONTEXT_DIR``,
    ``metatron.toml``) is always used as-is. Otherwise the default ``context/`` is
    chosen — unless it does not exist while a legacy ``metatron/`` bundle (one that
    actually has a ``candidate/`` or ``decisions/`` status directory) does, so repos
    onboarded before the rename keep working without configuration.
    """
    root = Path(root)
    if configured:
        return root / configured
    preferred = root / DEFAULT_CONTEXT_DIR
    legacy = root / LEGACY_CONTEXT_DIR
    if not preferred.exists() and (
        (legacy / "candidate").is_dir() or (legacy / "decisions").is_dir()
    ):
        return legacy
    return preferred


def get_output_language(path: str | Path = "metatron.toml") -> str:
    """Resolve the configured output language (env > ``metatron.toml`` > default).

    The single resolution point for output language, so prompt rendering never reads
    config directly and a per-repo override can layer on here later without changing
    any call site.
    """
    return load_settings(path).output_language


def update_settings(updates: dict, path: str | Path = "metatron.toml") -> None:
    """Merge ``updates`` into the ``[metatron]`` table of ``metatron.toml`` and rewrite it.

    A value of ``None`` removes that key. This is a deliberately small writer for the
    project's tiny config (one table of scalar values) — there is no TOML serializer in
    the stdlib, and the file holds only ``[metatron]`` scalars.
    """
    path = Path(path)
    doc = tomllib.loads(path.read_text()) if path.exists() else {}
    table = doc.setdefault("metatron", {})
    for key, value in updates.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    _write_toml(doc, path)


def _write_toml(doc: dict, path: Path) -> None:
    lines: list[str] = []
    for key, value in doc.items():
        if isinstance(value, dict):
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    for table, values in doc.items():
        if not isinstance(values, dict):
            continue
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
    path.write_text("\n".join(lines) + "\n")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
