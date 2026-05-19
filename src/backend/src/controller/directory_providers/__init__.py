"""Directory provider plug-ins.

Each concrete provider talks to its IdP exclusively via a Unity Catalog
HTTP Connection so UC owns OAuth2 client-credentials acquisition,
caching, and refresh. The app stores no client secret and no token
cache.

Field mapping (Graph ``userPrincipalName`` vs Okta ``profile.login`` vs
...) lives entirely inside each provider; the manager and routes only
ever see normalised ``Principal`` instances.
"""

from src.controller.directory_providers.base import (
    DirectoryError,
    DirectoryProvider,
)
from src.controller.directory_providers.entra_id_provider import (
    EntraIdProvider,
)

__all__ = [
    "DirectoryError",
    "DirectoryProvider",
    "EntraIdProvider",
]
