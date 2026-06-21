from __future__ import annotations

from dataclasses import dataclass, field

# Trailer keys a model emits per the usage-tracking contract. Lower-cased for
# case-insensitive matching.
_KEYS = {
    "decisions-applied": "applied",
    "decisions-considered": "considered",
    "decisions-violated": "violated",
}


@dataclass
class Trailers:
    applied: list[str] = field(default_factory=list)
    considered: list[str] = field(default_factory=list)
    violated: list[str] = field(default_factory=list)


def parse_trailers(text: str) -> Trailers:
    """Parse `Decisions-Applied/Considered/Violated` trailers from commit text."""
    out = Trailers()
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        attr = _KEYS.get(key.strip().lower())
        if attr is None:
            continue
        ids = [piece.strip() for piece in value.split(",") if piece.strip()]
        getattr(out, attr).extend(ids)
    return out
