"""The ODCS apiVersion values a contract may carry."""
import json
from functools import lru_cache
from typing import FrozenSet, Optional

from pydantic_core import PydanticCustomError

from src.common.odcs_validation import ODCS_SCHEMA_PATH


@lru_cache(maxsize=1)
def odcs_api_versions() -> FrozenSet[str]:
    """The apiVersion enum of the ODCS JSON schema contracts are validated against."""
    schema = json.loads(ODCS_SCHEMA_PATH.read_text(encoding="utf-8"))
    return frozenset(schema["properties"]["apiVersion"]["enum"])


def normalize_odcs_api_version(value: Optional[str]) -> Optional[str]:
    """``value`` as an ODCS apiVersion: '3.0.2' -> 'v3.0.2'.

    Raises the coded error ``odcs_api_version_unsupported`` (param
    ``api_version``) for a value outside the ODCS enum; ``None`` passes.
    """
    if value is None:
        return None
    version = str(value).strip().lower()
    if version[:1].isdigit():
        version = f"v{version}"
    if version not in odcs_api_versions():
        raise PydanticCustomError(
            "odcs_api_version_unsupported",
            "apiVersion {api_version} is not an ODCS version",
            {"api_version": value},
        )
    return version
