"""Domain fields of a contract payload: which are sent, and which are refused.

A field counts as sent when its key is present and not ``None``, so ``[]`` and ``""``
are values, not absence.
"""
from typing import Optional

from src.common.api_errors import CodedValueError


class InvalidDomainIdentifierError(CodedValueError):
    """A domain field of a contract payload that is present but blank (``""``)."""

    code = 'invalid_domain_identifier'

    def __init__(self, field: str, message: Optional[str] = None):
        super().__init__(message or f"{field} must not be empty", field=field)


class PrimaryDomainNotAssignedError(CodedValueError):
    """A primary domain that isn't one of the contract's (new or stored) domains."""

    code = 'primary_domain_not_in_domains'

    def __init__(self, domain_id: str):
        super().__init__(
            f"Domain {domain_id} is not one of the contract's domains", primaryDomainId=domain_id,
        )


DOMAIN_IDS_KEYS = ('domainIds', 'domain_ids')
PRIMARY_DOMAIN_KEYS = ('primaryDomainId', 'primary_domain_id')
LEGACY_DOMAIN_ID_KEYS = ('domainId', 'domain_id')


def sent_domain_field(data_dict: dict, keys: tuple):
    """(field name, value) of the first of ``keys`` sent with a non-null value, else None.

    A key is "sent" when it is present and not ``None``: ``[]`` and ``""`` are values
    (``[]`` clears, ``""`` is refused), not absence. The camelCase name comes first.
    """
    for key in keys:
        if data_dict.get(key) is not None:
            return key, data_dict[key]
    return None


def domain_identifier(field: str, value) -> str:
    """A domain id sent by a client, stripped; blank or non-string is refused."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidDomainIdentifierError(field)
    return value.strip()


LEGACY_DOMAIN_NAME_KEYS = ('domain',)
