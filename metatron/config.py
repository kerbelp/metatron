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

DEFAULT_DB_PATH = "metatron.db"


class Settings(BaseModel):
    db_path: str = DEFAULT_DB_PATH
    model: str = DEFAULT_MODEL
    anthropic_api_key: str | None = None
    # A persisted default repo (written by ``metatron repo set``). It sits below the
    # ``METATRON_REPO`` env var in precedence, so an env override still wins per-shell.
    default_repo: str | None = None


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
    )


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
