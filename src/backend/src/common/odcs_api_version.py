"""The ODCS spelling of a contract's apiVersion."""
from typing import Optional


def normalized_api_version(value: Optional[str]) -> Optional[str]:
    """``value`` in the ODCS spelling ('3.0.2' -> 'v3.0.2'), not checked; ``None`` passes."""
    if value is None:
        return None
    version = str(value).strip().lower()
    return f"v{version}" if version[:1].isdigit() else version
