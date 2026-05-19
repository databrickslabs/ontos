"""Pydantic API models for the Directory layer (external IdP lookups).

The Directory layer is the generic abstraction over identity providers.
v1 ships one concrete provider (Microsoft Entra ID via Microsoft Graph),
but the manager / routes / models are provider-agnostic so future
providers (Okta, Ping, ...) can be added without breaking changes.

See plans/directory-lookup-and-principal-picker.md.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PrincipalType(str, Enum):
    """Type of a directory principal.

    ``unknown`` is reserved for legacy values that no longer resolve in
    the directory but still need to render in the UI.
    Service principals are reserved for v2.
    """

    USER = "user"
    GROUP = "group"
    UNKNOWN = "unknown"


class Principal(BaseModel):
    """Normalised representation of an external directory principal.

    Every concrete ``DirectoryProvider`` maps its native fields onto
    this shape. The ``id`` field is the persisted identifier (UPN or
    email for users, displayName for groups -- NOT GUIDs), which keeps
    every existing storage column shape unchanged.
    """

    type: PrincipalType = Field(..., description="user | group | unknown")
    id: str = Field(
        ...,
        description=(
            "Persisted identifier. UPN/email for users, displayName for "
            "groups. Used as the value sent back from the picker."
        ),
    )
    display_name: str = Field(..., description="Friendly name shown in UI")
    sub_label: Optional[str] = Field(
        default=None,
        description=(
            "Secondary identifier shown on row two and as tooltip on "
            "selected badges. Email/UPN for users, GUID for groups."
        ),
    )


class DirectoryProviderType(str, Enum):
    """Supported directory provider plug-ins.

    Unknown values persisted in settings are treated as not-configured.
    """

    ENTRA = "entra"


class DirectoryStatus(BaseModel):
    """Reports whether the directory is wired up.

    ``configured`` is True iff both a recognised provider type and a UC
    HTTP connection name are persisted in settings.
    """

    configured: bool
    provider_type: Optional[str] = None
    connection_name: Optional[str] = None


class DirectoryTestResult(BaseModel):
    """Result of probing the configured provider for connectivity."""

    healthy: bool
    error: Optional[str] = None


class DirectorySearchResponse(BaseModel):
    """Envelope for ``GET /api/directory/search`` results."""

    results: List[Principal]


class DirectorySettingsUpdate(BaseModel):
    """Payload accepted by ``PUT /api/directory/settings``.

    Either field may be ``None`` to clear that setting.
    """

    provider_type: Optional[str] = None
    connection_name: Optional[str] = None


# Setting keys (single source of truth)
SETTING_KEY_PROVIDER_TYPE = "DIRECTORY_PROVIDER_TYPE"
SETTING_KEY_CONNECTION_NAME = "DIRECTORY_UC_HTTP_CONNECTION_NAME"
