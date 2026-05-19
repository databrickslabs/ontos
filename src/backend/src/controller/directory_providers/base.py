"""Abstract DirectoryProvider interface implemented by every concrete provider."""

from abc import ABC, abstractmethod
from typing import List

from src.models.directory import Principal


class DirectoryError(Exception):
    """Raised when a provider fails to talk to its IdP.

    The string is surfaced to the UI via the ``/api/directory/test``
    endpoint and (one-shot) via the picker's graceful-degradation log
    line. It must not contain secrets.
    """


class DirectoryProvider(ABC):
    """Provider plug-in contract.

    Every method must return normalised ``Principal`` instances and is
    responsible for safe escaping of the caller-supplied ``prefix`` /
    ``id`` against its own query syntax (OData for Graph, SCIM for
    Okta, etc.). The manager does not sanitise these strings.
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
