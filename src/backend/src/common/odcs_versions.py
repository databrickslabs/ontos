"""The ODCS apiVersion values a contract may carry."""
import json
from functools import lru_cache
from typing import FrozenSet, Optional

from pydantic_core import PydanticCustomError

from src.common.api_errors import CodedValueError
from src.common.odcs_validation import ODCS_SCHEMA_PATH

UNSUPPORTED_CODE = "odcs_api_version_unsupported"


class UnsupportedOdcsApiVersionError(CodedValueError):
    """An apiVersion outside the ODCS enum."""

    code = UNSUPPORTED_CODE

    def __init__(self, api_version: str):
        super().__init__(
            f"apiVersion {api_version} is not an ODCS version", api_version=api_version,
        )


@lru_cache(maxsize=1)
def odcs_api_versions() -> FrozenSet[str]:
    """The apiVersion enum of the ODCS JSON schema contracts are validated against."""
    schema = json.loads(ODCS_SCHEMA_PATH.read_text(encoding="utf-8"))
    return frozenset(schema["properties"]["apiVersion"]["enum"])


def normalized_api_version(value: Optional[str]) -> Optional[str]:
    """``value`` in the ODCS spelling ('3.0.2' -> 'v3.0.2'), not checked; ``None`` passes."""
    if value is None:
        return None
    version = str(value).strip().lower()
    return f"v{version}" if version[:1].isdigit() else version


def normalize_odcs_api_version(value: Optional[str]) -> Optional[str]:
    """Pydantic validator for a new contract: normalized, and refused outside the enum
    with the coded error ``odcs_api_version_unsupported`` (param ``api_version``)."""
    version = normalized_api_version(value)
    if version is not None and version not in odcs_api_versions():
        raise PydanticCustomError(
            UNSUPPORTED_CODE, "apiVersion {api_version} is not an ODCS version",
            {"api_version": value},
        )
    return version


def check_api_version_change(stored: Optional[str], requested: Optional[str]) -> None:
    """Refuse an update to an apiVersion outside the enum.

    Sending back the stored value is accepted even when it is not an ODCS version
    (a contract stored before the check stays editable).
    """
    if requested is None or requested == normalized_api_version(stored):
        return
    if requested not in odcs_api_versions():
        raise UnsupportedOdcsApiVersionError(requested)
