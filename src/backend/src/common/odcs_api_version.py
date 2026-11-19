"""The ODCS apiVersion values a contract may carry, and their spelling."""
import json
from functools import lru_cache
from typing import Any, FrozenSet, Optional

from pydantic_core import PydanticCustomError

from src.common import odcs_validation
from src.common.api_errors import CodedValueError

UNSUPPORTED_CODE = "odcs_api_version_unsupported"


class UnsupportedOdcsApiVersionError(CodedValueError):
    """An apiVersion outside the ODCS enum (or null)."""

    code = UNSUPPORTED_CODE

    def __init__(self, api_version: Any):
        super().__init__(
            f"apiVersion {api_version} is not an ODCS version", api_version=api_version,
        )


@lru_cache(maxsize=1)
def odcs_api_versions() -> FrozenSet[str]:
    """The apiVersion enum of the ODCS JSON schema contracts are validated against
    (``odcs_validation.ODCS_SCHEMA_PATH``), so a newer schema brings its versions."""
    schema = json.loads(odcs_validation.ODCS_SCHEMA_PATH.read_text(encoding="utf-8"))
    return frozenset(schema["properties"]["apiVersion"]["enum"])


def normalized_api_version(value: Optional[str]) -> Optional[str]:
    """``value`` in the ODCS spelling ('3.0.2' -> 'v3.0.2'), not checked; ``None`` passes."""
    if value is None:
        return None
    version = str(value).strip().lower()
    return f"v{version}" if version[:1].isdigit() else version


def checked_api_version(value: Any) -> str:
    """``value`` normalized; :class:`UnsupportedOdcsApiVersionError` when it is null or
    outside the enum. For a new contract on any create path."""
    version = normalized_api_version(value)
    if version is None or version not in odcs_api_versions():
        raise UnsupportedOdcsApiVersionError(value)
    return version


def normalize_odcs_api_version(value: Any) -> str:
    """Pydantic validator for a new contract: :func:`checked_api_version` as the
    coded validation error ``odcs_api_version_unsupported`` (param ``api_version``)."""
    try:
        return checked_api_version(value)
    except UnsupportedOdcsApiVersionError as e:
        raise PydanticCustomError(
            UNSUPPORTED_CODE, "apiVersion {api_version} is not an ODCS version", e.params,
        ) from None


def check_api_version_change(stored: Optional[str], requested: Optional[str]) -> None:
    """Refuse an update to an apiVersion outside the enum.

    Sending back the stored value is accepted even when it is not an ODCS version
    (a contract stored before the check stays editable). ``None`` keeps the stored one.
    """
    if requested is None or requested == normalized_api_version(stored):
        return
    if requested not in odcs_api_versions():
        raise UnsupportedOdcsApiVersionError(requested)
