"""The storage interface.

All access to priors goes through ``PriorStore`` so the backing store stays
swappable. SQLite backs it now; the same contract is meant to hold for Postgres
later, so implementations must not leak storage-specific details to callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from metatron.events import Event
from metatron.models import Prior, Status


class PriorStore(ABC):
    @abstractmethod
    def add(self, prior: Prior) -> Prior:
        """Persist a new prior and return it."""

    @abstractmethod
    def get(self, prior_id: str) -> Prior | None:
        """Return the prior with this id, or ``None`` if there is none."""

    @abstractmethod
    def list(
        self,
        *,
        repo: str | None = None,
        status: Status | None = None,
        scope: str | None = None,
        model: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Prior]:
        """Return priors newest-first, optionally filtered and paginated.

        Filters by exact ``repo``, ``status``, ``scope`` and ``model``;
        ``limit``/``offset`` paginate.
        """

    @abstractmethod
    def count(
        self,
        *,
        repo: str | None = None,
        status: Status | None = None,
        scope: str | None = None,
        model: str | None = None,
    ) -> int:
        """Count priors matching the (optional) ``repo``/``status``/``scope``/``model`` filters."""

    @abstractmethod
    def list_repos(self) -> list[str]:
        """Return the distinct repo identities present in the store."""

    @abstractmethod
    def set_status(self, prior_id: str, status: Status) -> Prior:
        """Set a prior's status (the curation primitive) and return it.

        Raises ``KeyError`` if no prior has this id.
        """


class EventStore(ABC):
    """Stores usage events. Separate from priors so reporting stays decoupled."""

    @abstractmethod
    def record(self, event: Event) -> Event:
        """Persist a usage event and return it."""

    @abstractmethod
    def list_events(
        self,
        *,
        repo: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Event]:
        """Return events newest-first, optionally filtered by repo and paginated."""

    @abstractmethod
    def count_events(self, *, repo: str | None = None) -> int:
        """Total number of recorded events (optionally for one repo)."""
