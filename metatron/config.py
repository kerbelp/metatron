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
    )
