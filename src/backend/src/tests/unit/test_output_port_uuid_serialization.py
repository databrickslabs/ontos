"""Tests for UUID/str serializer fix on OutputPort.deliveryMethodId.

The DB column `delivery_method_id` is `PG_UUID(as_uuid=True)`, so SQLAlchemy
returns `uuid.UUID` instances when models are loaded via `from_attributes`.
The Pydantic field is `Optional[str]`, which Pydantic v2 refuses to coerce
from `UUID` on the response side. We added a `@field_serializer` that
stringifies on serialize. These tests pin that behavior.
"""

import json
import uuid

import pytest

from src.models.data_products import OutputPort


SAMPLE_UUID_STR = "0f400005-0000-4000-8000-000000000005"


def _make_port(delivery_method_id):
    return OutputPort(
        name="port-a",
        version="1.0.0",
        deliveryMethodId=delivery_method_id,
    )


def test_uuid_instance_serializes_to_string_by_alias():
    """UUID instance -> string in model_dump(by_alias=True)."""
    port = _make_port(uuid.UUID(SAMPLE_UUID_STR))
    dumped = port.model_dump(by_alias=True)
    assert dumped["delivery_method_id"] == SAMPLE_UUID_STR
    assert isinstance(dumped["delivery_method_id"], str)


def test_uuid_instance_serializes_to_string_by_field_name():
    """UUID instance -> string in model_dump(by_alias=False)."""
    port = _make_port(uuid.UUID(SAMPLE_UUID_STR))
    dumped = port.model_dump(by_alias=False)
    assert dumped["deliveryMethodId"] == SAMPLE_UUID_STR
    assert isinstance(dumped["deliveryMethodId"], str)


def test_uuid_instance_serializes_to_quoted_string_in_json():
    """model_dump_json produces a JSON string (quoted), not a malformed UUID."""
    port = _make_port(uuid.UUID(SAMPLE_UUID_STR))
    payload = json.loads(port.model_dump_json(by_alias=True))
    assert payload["delivery_method_id"] == SAMPLE_UUID_STR
    # ensure it's a JSON string, not some object
    assert isinstance(payload["delivery_method_id"], str)


def test_none_serializes_as_none():
    """deliveryMethodId=None round-trips as None."""
    port = _make_port(None)
    dumped = port.model_dump(by_alias=True)
    assert dumped["delivery_method_id"] is None
    payload = json.loads(port.model_dump_json(by_alias=True))
    assert payload["delivery_method_id"] is None


def test_already_string_round_trips():
    """If the value is already a str (e.g. came from JSON body), it stays a str."""
    port = _make_port(SAMPLE_UUID_STR)
    dumped = port.model_dump(by_alias=True)
    assert dumped["delivery_method_id"] == SAMPLE_UUID_STR
    assert isinstance(dumped["delivery_method_id"], str)


def test_uuid_via_from_attributes_simulating_sqlalchemy_load():
    """Simulate SQLAlchemy's behavior: an attribute holding a UUID instance.

    This is the original bug shape — `from_attributes=True` + a source object
    whose `delivery_method_id` is a UUID. We want Pydantic to accept it and
    stringify on serialize.
    """

    class _FakeRow:
        # mimic the SQLAlchemy attribute names
        name = "port-a"
        version = "1.0.0"
        delivery_method_id = uuid.UUID(SAMPLE_UUID_STR)

    port = OutputPort.model_validate(_FakeRow(), from_attributes=True)
    dumped = port.model_dump(by_alias=True)
    assert dumped["delivery_method_id"] == SAMPLE_UUID_STR
    assert isinstance(dumped["delivery_method_id"], str)
