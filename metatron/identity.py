"""The local employee identity that ``serve`` stamps onto events.

Metatron serves agents across an org; we want to know *whose* agent produced a query
or piece of feedback. Identity is **local metadata about the person running Metatron**
— not auth. It lives in ``<METATRON_HOME>/config.toml`` (default ``~/.metatron``),
seeded once from ``git config`` so there is no login step. It travels denormalized on
each event, so a handed-off / merged DB stays self-describing.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tomllib
from pathlib import Path

from pydantic import BaseModel


class Identity(BaseModel):
    actor_id: str = ""       # stable id; sha1(email)[:12], else "" (anonymous)
    email: str = ""
    display_name: str = ""


def _home() -> Path:
    # Separate from the catalog (db_path): identity is about the person, not the store.
    # METATRON_CONFIG_DIR overrides the default and is how tests isolate it from the
    # real ~/.metatron. (Distinct from METATRON_HOME, which the setup script uses for
    # the source checkout.)
    return Path(os.environ.get("METATRON_CONFIG_DIR", "~/.metatron")).expanduser()


def config_path() -> Path:
    return _home() / "config.toml"


def _actor_id_for(email: str) -> str:
    return hashlib.sha1(email.strip().lower().encode("utf-8")).hexdigest()[:12] if email else ""


def load_identity() -> Identity:
    """Read the persisted identity, or an empty (anonymous) one if none is set."""
    path = config_path()
    if not path.exists():
        return Identity()
    table = tomllib.loads(path.read_text()).get("identity", {})
    return Identity(
        actor_id=table.get("actor_id", ""),
        email=table.get("email", ""),
        display_name=table.get("display_name", ""),
    )


def set_identity(*, email: str | None = None, display_name: str | None = None) -> Identity:
    """Persist (merge) identity fields. Recomputes ``actor_id`` when email changes."""
    current = load_identity()
    new_email = email if email is not None else current.email
    ident = Identity(
        email=new_email,
        display_name=display_name if display_name is not None else current.display_name,
        actor_id=_actor_id_for(new_email) if new_email else current.actor_id,
    )
    _write(ident)
    return ident


def ensure_identity() -> Identity:
    """Return the identity, seeding it from ``git config`` on first use if unset."""
    current = load_identity()
    if current.actor_id or current.email:
        return current
    seeded = _from_git()
    if seeded is None:
        return current  # stay anonymous; nothing to seed from
    _write(seeded)
    return seeded


def _from_git() -> Identity | None:
    email = _git_config("user.email")
    if not email:
        return None
    return Identity(
        actor_id=_actor_id_for(email),
        email=email,
        display_name=_git_config("user.name"),
    )


def _git_config(key: str) -> str:
    result = subprocess.run(
        ["git", "config", key], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _write(ident: Identity) -> None:
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    lines = [
        "[identity]",
        f'actor_id = "{ident.actor_id}"',
        f'email = "{ident.email}"',
        f'display_name = "{_escape(ident.display_name)}"',
    ]
    config_path().write_text("\n".join(lines) + "\n")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
