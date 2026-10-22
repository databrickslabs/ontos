"""One validator for the Ontos instance identity, whatever its source.

The id is stamped on exported entities and Git paths, so every source of the
effective value (environment, stored override from Settings, derived default)
goes through these functions. They raise coded errors (``instance_id_invalid`` /
``instance_name_invalid``) that the UI shows translated.
"""
import re
from typing import Tuple

from .api_errors import CodedValueError

INSTANCE_ID_SETTING_KEY = "ONTOS_INSTANCE_ID"
INSTANCE_NAME_SETTING_KEY = "ONTOS_INSTANCE_NAME"
# The id is stamped on exported entities, so keep it to a conservative,
# URL/filename-safe alphabet.
INSTANCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
INSTANCE_ID_MAX_LENGTH = 128
INSTANCE_NAME_MAX_LENGTH = 128


class InstanceIdInvalidError(CodedValueError):
    """The instance id is not 1-``max_length`` allowed characters (UI shows it translated)."""

    code = 'instance_id_invalid'


class InstanceNameInvalidError(CodedValueError):
    """The instance name is longer than ``max_length`` or has control characters."""

    code = 'instance_name_invalid'


def validate_instance_id(raw: object, source: str = 'settings') -> str:
    """Return the stripped instance id; '' (unset) is allowed and means "use the default".

    Args:
        raw: The candidate value.
        source: Where it came from (``settings``, ``env``, ``stored`` or ``default``), for the
            message.

    Raises:
        InstanceIdInvalidError: (a ``ValueError``) If a non-empty value has characters
            outside letters, digits, '.', '_', ':' and '-', does not start with a letter
            or digit, or is longer than 128 characters
    """
    value = raw.strip() if isinstance(raw, str) else ''
    if value and not INSTANCE_ID_PATTERN.fullmatch(value):
        raise InstanceIdInvalidError(
            f"{_where(INSTANCE_ID_SETTING_KEY, source)} must be 1-{INSTANCE_ID_MAX_LENGTH} "
            "characters: letters, digits, '.', '_', ':' or '-', starting with a letter or digit",
            max_length=INSTANCE_ID_MAX_LENGTH,
        )
    return value


def validate_instance_name(raw: object, source: str = 'settings') -> str:
    """Return the stripped instance name; '' (unset) is allowed and means "use the default".

    Raises:
        InstanceNameInvalidError: (a ``ValueError``) If the value is longer than 128
            characters or has control characters
    """
    value = raw.strip() if isinstance(raw, str) else ''
    if len(value) > INSTANCE_NAME_MAX_LENGTH or any(ord(c) < 32 for c in value):
        raise InstanceNameInvalidError(
            f"{_where(INSTANCE_NAME_SETTING_KEY, source)} must be at most "
            f"{INSTANCE_NAME_MAX_LENGTH} characters with no control characters",
            max_length=INSTANCE_NAME_MAX_LENGTH,
        )
    return value


def _where(key: str, source: str) -> str:
    if source == 'env':
        return f"{key} (environment variable)"
    if source == 'stored':
        return f"{key} (stored in the app settings)"
    if source == 'default':
        return f"{key} (derived from DATABRICKS_WORKSPACE_ID and DATABRICKS_APP_NAME)"
    return key.lower()


def resolve_instance_identity(
    env_id: object, env_name: object, workspace_id: object, app_name: object
) -> Tuple[str, str]:
    """Effective (id, name) before any stored override: the env value if set, else derived.

    Every candidate is validated, so an invalid environment value can't become the identity.
    """
    ws = (workspace_id or "").strip() if isinstance(workspace_id, str) else ""
    app = (app_name or "").strip() if isinstance(app_name, str) else ""
    app = app or "ontos"
    instance_id = validate_instance_id(env_id, 'env') or validate_instance_id(
        f"{ws}-{app}" if ws else app, 'default'
    )
    instance_name = (
        validate_instance_name(env_name, 'env') or validate_instance_name(app, 'default')
    )
    return instance_id, instance_name
