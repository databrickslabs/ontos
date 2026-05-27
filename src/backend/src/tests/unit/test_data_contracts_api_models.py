"""Unit tests for ODCS Pydantic models in data_contracts_api."""

import pytest
from pydantic import ValidationError

from src.models.data_contracts_api import ColumnProperty, DataContractRead
from src.db_models.data_contracts import (
    DataContractDb,
    DataContractServerDb,
    DataContractTeamDb,
    DataContractRoleDb,
    DataContractSupportDb,
    DataContractPricingDb,
    DataContractSlaPropertyDb,
)


def test_column_property_transform_source_objects_accepts_list():
    """ODCS v3.1.0 defines transformSourceObjects as an array of strings.

    Regression test for issue #285: ODCS-compliant uploads with
    transformSourceObjects as a list previously failed Pydantic validation
    with HTTP 422 ("Input should be a valid string").
    """
    prop = ColumnProperty(
        name='col',
        logicalType='string',
        transformSourceObjects=['table_a', 'table_b'],
    )
    assert prop.transformSourceObjects == ['table_a', 'table_b']


def test_column_property_transform_source_objects_accepts_string_for_backcompat():
    """Plain-string input remains valid for backward compatibility."""
    prop = ColumnProperty(
        name='col',
        logicalType='string',
        transformSourceObjects='table_a',
    )
    assert prop.transformSourceObjects == 'table_a'


def test_column_property_transform_source_objects_optional():
    """Field is optional and may be omitted."""
    prop = ColumnProperty(name='col', logicalType='string')
    assert prop.transformSourceObjects is None


# ---------------------------------------------------------------------------
# Issue #455 regression: DataContractRead.model_validate against ORM rows
# ---------------------------------------------------------------------------
# Before the fix, POST /api/data-contracts/{id}/clone returned HTTP 400 even
# though the clone was committed: the response handler called
# ``DataContractRead.model_validate(new_contract).model_dump()`` and Pydantic v2
# rejected the nested ``DataContractServerDb`` rows because ``ServerConfig`` did
# not allow attribute-based validation. The fix passes ``from_attributes=True``
# at the call site so the flag propagates into nested model validation. These
# tests pin that behaviour at the model layer (no DB / no TestClient needed).


def _orm_contract_with_servers() -> DataContractDb:
    """Build a detached SQLAlchemy instance that mimics a freshly-loaded clone
    with one populated server row. We don't touch a Session — Pydantic only
    needs attribute access. Column defaults (``kind``, ``publication_scope``)
    are normally applied at flush time, so we set them explicitly here."""
    contract = DataContractDb(
        id='c-1',
        version_family_id='c-1',
        kind='DataContract',
        name='Sample',
        version='1.0.0',
        status='active',
        publication_scope='none',
    )
    contract.servers = [
        DataContractServerDb(
            id='s-1',
            contract_id='c-1',
            server='prod-db',
            type='postgresql',
            environment='prod',
        )
    ]
    return contract


def test_data_contract_read_validates_from_orm_with_nested_servers():
    """Regression: validating a DataContractDb with populated `servers` must
    succeed and round-trip the nested ServerConfig values. Without
    ``from_attributes=True`` propagating into ServerConfig, Pydantic v2 raised
    ``Input should be a valid dictionary or instance of ServerConfig``."""
    contract = _orm_contract_with_servers()

    read = DataContractRead.model_validate(contract, from_attributes=True)

    assert read.id == 'c-1'
    assert read.name == 'Sample'
    assert len(read.servers) == 1
    assert read.servers[0].server == 'prod-db'
    assert read.servers[0].type == 'postgresql'
    assert read.servers[0].environment == 'prod'


def test_data_contract_read_dumps_after_orm_validation():
    """The full validate-then-dump pipeline used by the clone route must
    produce a dict whose `servers` entry is JSON-serialisable (no leftover
    ORM instances)."""
    contract = _orm_contract_with_servers()

    payload = DataContractRead.model_validate(
        contract, from_attributes=True
    ).model_dump()

    assert isinstance(payload, dict)
    assert isinstance(payload['servers'], list)
    assert payload['servers'][0]['server'] == 'prod-db'
    # Make sure nothing leaked as an SQLAlchemy object.
    assert not isinstance(payload['servers'][0], DataContractServerDb)


def test_data_contract_read_validates_multiple_nested_orm_collections():
    """Several nested collections live alongside `servers` (team, roles,
    support, pricing, sla_properties). They share the same ORM-mapped
    pattern; the fix must work for all of them, not just servers."""
    contract = DataContractDb(
        id='c-2',
        version_family_id='c-2',
        kind='DataContract',
        name='Rich',
        version='2.0.0',
        status='active',
        publication_scope='none',
    )
    contract.servers = [
        DataContractServerDb(
            id='s-2', contract_id='c-2', server='db-a', type='bigquery'
        )
    ]
    contract.team = [
        DataContractTeamDb(
            id='t-1', contract_id='c-2', username='alice@example.com', role='Data Engineer'
        )
    ]
    contract.roles = [
        DataContractRoleDb(id='r-1', contract_id='c-2', role='reader', access='read')
    ]
    contract.support = [
        DataContractSupportDb(
            id='su-1', contract_id='c-2', channel='#help', url='https://example.com'
        )
    ]
    contract.pricing = DataContractPricingDb(
        id='p-1', contract_id='c-2', price_amount='10.00', price_currency='USD'
    )
    contract.sla_properties = [
        DataContractSlaPropertyDb(
            id='sla-1', contract_id='c-2', property='availability', value='99.9'
        )
    ]

    read = DataContractRead.model_validate(contract, from_attributes=True)
    payload = read.model_dump()

    assert payload['servers'][0]['server'] == 'db-a'
    assert payload['team'][0]['username'] == 'alice@example.com'
    assert payload['roles'][0]['role'] == 'reader'


def test_server_config_properties_validator_handles_orm_rows():
    """Direct unit test for the ``ServerConfig.properties`` coercion helper:
    a list of objects with ``.key``/``.value`` (the shape returned by the
    ``DataContractServerDb.properties`` relationship) must be flattened into
    a dict. This is the exact path the clone endpoint exercises."""
    from src.models.data_contracts_api import ServerConfig

    class _Row:
        def __init__(self, key, value):
            self.key = key
            self.value = value

    cfg = ServerConfig.model_validate(
        {
            'type': 'postgresql',
            'server': 'prod-db',
            'properties': [_Row('host', 'db.internal'), _Row('port', '5432')],
        }
    )

    assert cfg.properties == {'host': 'db.internal', 'port': '5432'}


def test_server_config_properties_validator_accepts_dict_input():
    """Plain-dict input (JSON payloads, ODCS YAML upload, etc.) must remain
    valid -- the coercion is additive, not a replacement."""
    from src.models.data_contracts_api import ServerConfig

    cfg = ServerConfig.model_validate(
        {'type': 'snowflake', 'properties': {'account': 'acme.us-east-1'}}
    )

    assert cfg.properties == {'account': 'acme.us-east-1'}


def test_server_config_properties_validator_accepts_dict_rows():
    """Some upstream paths build a list of ``{"key": ..., "value": ...}``
    dicts (e.g. ODCS import). That shape must be coerced as well."""
    from src.models.data_contracts_api import ServerConfig

    cfg = ServerConfig.model_validate(
        {
            'type': 'bigquery',
            'properties': [
                {'key': 'project', 'value': 'analytics-prod'},
                {'key': 'dataset', 'value': 'sales'},
            ],
        }
    )

    assert cfg.properties == {'project': 'analytics-prod', 'dataset': 'sales'}
