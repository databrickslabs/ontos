"""Rules whose MATCH type no entity loader supports are reported, not silently empty."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

from src.common.compliance_entities import (
    AppEntityLoader,
    EntityFilter,
    EntityIterator,
    EntityLoader,
    parse_entity_filter,
)
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb

LOGGER = 'src.common.compliance_entities'


class _TableLoader(EntityLoader):
    def get_supported_types(self):
        return ['table']

    def load_entities(self, entity_types, batch_size=100):
        yield {'type': 'table', 'id': 'main.sales.orders', 'name': 'orders'}


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if 'matches no entities' in r.getMessage()]


def test_unsupported_type_is_reported_with_its_source(caplog):
    iterator = EntityIterator([_TableLoader()])

    with caplog.at_level('WARNING', logger=LOGGER):
        entities = list(iterator.iterate(EntityFilter(entity_types=['dataset']), source='policy X'))

    assert entities == []
    [message] = _warnings(caplog)
    assert 'of policy X' in message
    assert "MATCH type 'dataset'" in message
    assert 'available types: table' in message


def test_supported_type_is_not_reported(caplog):
    iterator = EntityIterator([_TableLoader()])

    with caplog.at_level('WARNING', logger=LOGGER):
        entities = list(iterator.iterate(EntityFilter(entity_types=['table'])))

    assert [e['id'] for e in entities] == ['main.sales.orders']
    assert _warnings(caplog) == []


def test_object_rule_is_not_reported_when_some_types_are_supported(db_session, caplog):
    iterator = EntityIterator([AppEntityLoader(db_session)])
    entity_filter = parse_entity_filter("MATCH (obj:Object) ASSERT obj.name != ''")

    with caplog.at_level('WARNING', logger=LOGGER):
        list(iterator.iterate(entity_filter))

    assert _warnings(caplog) == []


def test_policy_run_names_the_policy(db_session, caplog):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()),
        name='Vehicle PII consent',
        rule="MATCH (d:Dataset) ASSERT d.consent_mechanism != ''",
        is_active=True,
    )
    db_session.add(policy)
    db_session.flush()

    with patch('src.controller.compliance_manager.create_entity_iterator',
               return_value=EntityIterator([AppEntityLoader(db_session)])), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()), \
            caplog.at_level('WARNING', logger=LOGGER):
        ComplianceManager().run_policy_inline(db_session, policy=policy)

    [message] = _warnings(caplog)
    assert f"policy 'Vehicle PII consent' ({policy.id})" in message
    assert "MATCH type 'Dataset'" in message


def test_glossary_term_rules_are_reported_until_glossary_terms_load(db_session, caplog):
    iterator = EntityIterator([AppEntityLoader(db_session)])
    entity_filter = parse_entity_filter("MATCH (g:glossary_term) ASSERT g.description != ''")

    with caplog.at_level('WARNING', logger=LOGGER):
        assert list(iterator.iterate(entity_filter)) == []

    [message] = _warnings(caplog)
    assert "MATCH type 'glossary_term'" in message


def test_rule_without_match_is_not_reported(caplog):
    # Maturity gates and workflow policy checks have no MATCH by design.
    iterator = EntityIterator([_TableLoader()])

    with caplog.at_level('WARNING', logger=LOGGER):
        list(iterator.iterate(parse_entity_filter("ASSERT obj.has_owner = True"), source='policy Y'))

    assert _warnings(caplog) == []
