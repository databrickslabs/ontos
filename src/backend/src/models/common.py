"""Shared Pydantic model mixins used across entity schemas."""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OptionalIdMixin(BaseModel):
    """Mixin for Create schemas that allow an optional caller-provided primary key.

    API-only: the UI never sends this. When ``id`` is omitted the server generates
    a UUID via the model's column default (``str(uuid4())``). When supplied, the
    caller-provided UUID is used verbatim, letting external systems keep their own
    stable identifiers across imports. Repositories/managers are responsible for
    rejecting collisions and stringifying the value for String primary keys.
    """
    id: Optional[UUID] = Field(
        default=None,
        description=(
            "Optional caller-provided UUID (API only). If omitted, a UUID is "
            "generated server-side. Must be unique; a collision is rejected."
        ),
    )
