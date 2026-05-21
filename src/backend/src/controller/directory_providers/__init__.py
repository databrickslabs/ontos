"""Directory provider plug-ins.

Concrete providers shipped with the app:

- ``EntraIdProvider``  — Microsoft Entra ID via Microsoft Graph (UC HTTP)
- ``LakebaseProvider`` — Postgres table backed (the app's own Lakebase DB)
- ``FileProvider``     — Local CSV file (primarily for tests / demos)

Each provider receives a typed ``DirectoryProviderContext`` (transport
handles: SDK workspace client, SQLAlchemy engine, ...) and a
``DirectoryProviderConfig`` (all directory settings in one bag). The
provider reads only the fields relevant to its type and raises
``DirectoryError`` on missing / invalid required values.

Field mapping lives entirely inside each provider; the manager and
routes only ever see normalised ``Principal`` instances.
"""

from src.controller.directory_providers.base import (
    DirectoryError,
    DirectoryProvider,
    DirectoryProviderConfig,
    DirectoryProviderContext,
)
from src.controller.directory_providers.entra_id_provider import (
    EntraIdProvider,
)
from src.controller.directory_providers.file_provider import FileProvider
from src.controller.directory_providers.lakebase_provider import (
    LakebaseProvider,
)

__all__ = [
    "DirectoryError",
    "DirectoryProvider",
    "DirectoryProviderConfig",
    "DirectoryProviderContext",
    "EntraIdProvider",
    "FileProvider",
    "LakebaseProvider",
]
