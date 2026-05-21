"""Abstract DirectoryProvider interface implemented by every concrete provider.

Providers receive a small ``DirectoryProviderContext`` so they can pull
in whatever transport they need (Databricks SDK workspace client for
Entra; SQLAlchemy engine for Lakebase; filesystem for File). They also
receive a typed ``DirectoryProviderConfig`` carrying every directory
setting -- each provider reads only the fields relevant to its type
and raises ``DirectoryError`` on missing required values.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from src.models.directory import Principal


class DirectoryError(Exception):
    """Raised when a provider fails to talk to its IdP.

    The string is surfaced to the UI via the ``/api/directory/test``
    endpoint and (one-shot) via the picker's graceful-degradation log
    line. It must not contain secrets.
    """


@dataclass
class DirectoryProviderContext:
    """Per-instance transport handles a provider may need.

    Populated by ``DirectoryManager`` at provider-build time. Adding a
    new context field requires only updating the manager that builds
    it -- providers ignore fields they do not need.
    """

    ws_client: Any = None
    db_engine: Any = None


@dataclass
class DirectoryProviderConfig:
    """All directory settings in one bag.

    Each provider reads only the fields relevant to its type. Unused
    fields are simply ignored. This keeps the registry signature
    stable as more providers come online.
    """

    connection_name: Optional[str] = None   # entra
    lakebase_table: Optional[str] = None    # lakebase
    file_path: Optional[str] = None         # file

    def signature(self) -> Tuple[Optional[str], ...]:
        """A hashable representation used for cache invalidation."""

        return (self.connection_name, self.lakebase_table, self.file_path)


class DirectoryProvider(ABC):
    """Provider plug-in contract.

    Every method must return normalised ``Principal`` instances and is
    responsible for safe escaping of the caller-supplied ``prefix`` /
    ``id`` against its own query syntax (OData for Graph, parameterised
    SQL for Lakebase, etc.). The manager does not sanitise these
    strings.
    """

    @abstractmethod
    def search_users(self, prefix: str, top: int) -> List[Principal]:
        """Search users whose display name or UPN starts with ``prefix``."""

    @abstractmethod
    def search_groups(self, prefix: str, top: int) -> List[Principal]:
        """Search groups whose display name starts with ``prefix``."""

    @abstractmethod
    def get_user(self, id: str) -> Principal:
        """Resolve a single user by ``id`` (UPN/email)."""

    @abstractmethod
    def get_group(self, id: str) -> Principal:
        """Resolve a single group by ``id`` (display name)."""

    @abstractmethod
    def test(self) -> None:
        """Probe the IdP. Raise ``DirectoryError`` on failure, return on success."""
