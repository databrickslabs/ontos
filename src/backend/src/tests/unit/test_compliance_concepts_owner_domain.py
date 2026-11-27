"""Compliance runs and workflow rules see products and contracts the same way (#1424, slice 1).

Both read ``entity_dict_builder``: a run through ``AppEntityLoader`` and a workflow
rule through ``_rule_object`` must agree on every key they share (``has_owner``,
counts, ``tags``, ``domain``, ``concepts``...). Semantic links are read in one query
per entity type, and ``HAS_CONCEPT`` matches a concept by IRI or by label.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest
from sqlalchemy import event

from src.common.compliance_dsl import evaluate_rule_on_object
from src.common.compliance_entities import AppEntityLoader
from src.controller.entity_dict_builder import (
    CONCEPT_LINK_TYPES,
    build_data_contract_dict,
    build_data_product_dict,
    build_data_product_dicts,
)
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.db_models.teams import TeamDb, TeamMemberDb

CUSTOMER_IRI = 'https://example.com/ontology#Customer'


def _suffix():
    return uuid.uuid4().hex[:8]


def _product(db, owner_team_id=None):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'p-{_suffix()}', version='1.0.0', owner_team_id=owner_team_id,
    )
    db.add(product)
    db.flush()
    return product


def _contract(db, owner_team_id=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{_suffix()}', version='1.0.0', status='draft',
        created_by='user@example.com', owner_team_id=owner_team_id,
    )
    db.add(contract)
    db.flush()
    return contract


def _team(db, members=()):
    team = TeamDb(id=str(uuid.uuid4()), name=f'team-{_suffix()}', created_by='x', updated_by='x')
    db.add(team)
    db.flush()
    for email in members:
        db.add(TeamMemberDb(
            id=str(uuid.uuid4()), team_id=team.id, member_type='user',
            member_identifier=email, added_by='x',
        ))
    db.flush()
    return team


def _domain(db, entity_id, entity_type):
    domain = DataDomain(id=str(uuid.uuid4()), name=f'domain-{_suffix()}', created_by='x')
    db.add(domain)
    db.flush()
    db.add(EntityDomainAssociationDb(
        domain_id=domain.id, entity_id=entity_id, entity_type=entity_type, is_primary=True,
    ))
    db.flush()
    return domain


def _link(db, entity_id, entity_type, iri, label=None):
    db.add(EntitySemanticLinkDb(entity_id=entity_id, entity_type=entity_type, iri=iri, label=label))
    db.flush()


@pytest.fixture
def statements(db_session):
    """The SQL statements the session runs while the test body runs."""
    seen = []
    connection = db_session.connection()

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(connection, 'before_cursor_execute', record)
    yield seen
    event.remove(connection, 'before_cursor_execute', record)


# ---------------------------------------------------------------- DSL

@pytest.mark.parametrize('rule', [
    f"ASSERT HAS_CONCEPT('{CUSTOMER_IRI}')",
    "ASSERT HAS_CONCEPT('Customer')",
    "ASSERT obj.concept_count > 0",
    "ASSERT 'Customer' IN obj.concept_labels",
    f"ASSERT '{CUSTOMER_IRI}' IN obj.concept_iris",
    "ASSERT obj.has_concepts = True",
])
def test_has_concept_and_concept_fields_match_a_linked_entity(rule):
    obj = {'concepts': [{'iri': CUSTOMER_IRI, 'label': 'Customer'}],
           'concept_iris': [CUSTOMER_IRI], 'concept_labels': ['Customer'],
           'concept_count': 1, 'has_concepts': True}

    passed, message = evaluate_rule_on_object(rule, obj)

    assert passed, message


@pytest.mark.parametrize('rule', [
    "ASSERT NOT HAS_CONCEPT('https://example.com/ontology#Supplier')",
    "ASSERT NOT HAS_CONCEPT('Supplier')",
    "ASSERT obj.concept_count = 0",
    "ASSERT HAS_CONCEPT('Customer') = False",
])
def test_has_concept_is_false_for_an_unlinked_entity(rule):
    obj = {'concepts': [], 'concept_iris': [], 'concept_labels': [],
           'concept_count': 0, 'has_concepts': False}

    passed, _ = evaluate_rule_on_object(rule, obj)

    assert passed, rule


def test_has_concept_is_false_on_an_entity_without_concepts():
    passed, _ = evaluate_rule_on_object("ASSERT HAS_CONCEPT('Customer')", {'name': 'orders'})

    assert passed is False


# ---------------------------------------------------------------- link type mapping

def test_every_loader_type_is_mapped_to_its_link_type_or_not_linkable():
    loader_types = set(AppEntityLoader.SUPPORTED_TYPES)

    assert set(CONCEPT_LINK_TYPES) == loader_types - {'review'}
    assert CONCEPT_LINK_TYPES['data_product'] == 'data_product'
    assert CONCEPT_LINK_TYPES['data_contract'] == 'data_contract'
    assert CONCEPT_LINK_TYPES['domain'] == 'data_domain'


def test_domain_run_entity_reads_its_concepts(db_session):
    domain = DataDomain(id=str(uuid.uuid4()), name=f'domain-{_suffix()}', created_by='x')
    db_session.add(domain)
    db_session.flush()
    _link(db_session, domain.id, 'data_domain', CUSTOMER_IRI, 'Customer')

    loaded = AppEntityLoader(db_session).load_entity('domain', domain.id)

    assert loaded['concept_iris'] == [CUSTOMER_IRI]
    assert loaded['concept_labels'] == ['Customer']
    assert loaded['concept_count'] == 1
    assert loaded['has_concepts'] is True


def test_review_run_entity_has_no_concept_fields(db_session):
    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb

    review = DataAssetReviewRequestDb(requester_email='a@example.com', reviewer_email='b@example.com')
    db_session.add(review)
    db_session.flush()

    loaded = AppEntityLoader(db_session).load_entity('review', review.id)

    assert 'concepts' not in loaded
    assert 'concept_count' not in loaded


# ---------------------------------------------------------------- run path == workflow path

def test_run_and_workflow_dicts_agree_on_every_shared_key(db_session):
    team = _team(db_session, members=['alice@example.com', 'bob@example.com'])
    product = _product(db_session, owner_team_id=team.id)
    _domain(db_session, product.id, 'data_product')
    _link(db_session, product.id, 'data_product', CUSTOMER_IRI, 'Customer')

    run = AppEntityLoader(db_session).load_entity('data_product', product.id)
    workflow = build_data_product_dict(db_session, product.id)

    shared = (set(run) & set(workflow)) - {'type', 'entity_type'}
    mismatches = {k: (run[k], workflow[k]) for k in shared if run[k] != workflow[k]}
    assert mismatches == {}
    assert run['has_owner'] is True
    assert run['concept_count'] == 1
    assert run['type'] == 'data_product'


def test_run_dict_has_the_slice_fields_for_products_and_contracts(db_session):
    team = _team(db_session, members=['alice@example.com'])
    product = _product(db_session, owner_team_id=team.id)
    contract = _contract(db_session, owner_team_id=team.id)

    for entity_type, entity_id in (('data_product', product.id), ('data_contract', contract.id)):
        loaded = AppEntityLoader(db_session).load_entity(entity_type, entity_id)
        assert {
            'owner', 'owner_team_id', 'owner_team_name', 'owner_emails', 'has_owner',
            'domain', 'domain_name', 'domain_id',
            'concepts', 'concept_iris', 'concept_labels', 'concept_count', 'has_concepts',
            'tags', 'tag_count', 'has_tags', 'relationship_count', 'quality_check_count',
            'maturity_level_order', 'status', 'description',
        } <= set(loaded), entity_type


def test_owner_fields_name_the_team_and_list_its_user_emails(db_session):
    team = _team(db_session, members=['alice@example.com', 'bob@example.com'])
    product = _product(db_session, owner_team_id=team.id)
    db_session.add(TeamMemberDb(
        id=str(uuid.uuid4()), team_id=team.id, member_type='group',
        member_identifier='data-stewards', added_by='x',
    ))
    db_session.flush()

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    # ``owner`` keeps the team id, as existing rules compare it
    assert loaded['owner'] == team.id
    assert loaded['owner_team_name'] == team.name
    assert loaded['owner_emails'] == ['alice@example.com', 'bob@example.com']


def test_no_owner_gives_empty_owner_fields(db_session):
    product = _product(db_session)

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    assert loaded['has_owner'] is False
    assert loaded['owner_team_name'] is None
    assert loaded['owner_emails'] == []


def test_contract_domain_is_its_primary_domain_name_and_id(db_session):
    contract = _contract(db_session)
    domain = _domain(db_session, contract.id, 'data_contract')

    loaded = AppEntityLoader(db_session).load_entity('data_contract', contract.id)
    workflow = build_data_contract_dict(db_session, contract.id)

    assert loaded['domain'] == domain.name
    assert loaded['domain_name'] == domain.name
    assert loaded['domain_id'] == domain.id
    assert workflow['domain'] == domain.name


def test_product_domain_is_its_primary_domain_name_and_id(db_session):
    product = _product(db_session)
    domain = _domain(db_session, product.id, 'data_product')

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    assert loaded['domain'] == domain.name
    assert loaded['domain_id'] == domain.id


def test_unlinked_product_has_no_concepts(db_session):
    product = _product(db_session)

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    assert loaded['concepts'] == []
    assert loaded['concept_iris'] == []
    assert loaded['concept_count'] == 0
    assert loaded['has_concepts'] is False


def test_concept_without_label_is_listed_by_iri_only(db_session):
    product = _product(db_session)
    _link(db_session, product.id, 'data_product', CUSTOMER_IRI, None)

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    assert loaded['concepts'] == [{'iri': CUSTOMER_IRI, 'label': None}]
    assert loaded['concept_labels'] == []
    assert loaded['concept_count'] == 1


def test_tags_stay_as_before_on_the_run_dict(db_session):
    namespace = TagNamespaceDb(name=f'gov-{_suffix()}')
    db_session.add(namespace)
    db_session.flush()
    tag = TagDb(name='pii', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.flush()
    product = _product(db_session)
    db_session.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=product.id, entity_type='data_product', assigned_value='yes',
    ))
    db_session.flush()

    loaded = AppEntityLoader(db_session).load_entity('data_product', product.id)

    assert loaded['tags']['pii'] == 'yes'
    assert loaded['tags'][f'{namespace.name}/pii'] == 'yes'
    assert loaded['tag_count'] == 1


# ---------------------------------------------------------------- one query per type per run

def test_semantic_links_are_read_in_one_query_for_many_products(db_session, statements):
    products = [_product(db_session) for _ in range(5)]
    for index, product in enumerate(products):
        _link(db_session, product.id, 'data_product', f'{CUSTOMER_IRI}{index}', f'Concept {index}')

    statements.clear()
    built = build_data_product_dicts(db_session, [p.id for p in products])

    assert len(built) == 5
    assert all(built[p.id]['concept_count'] == 1 for p in products)
    link_queries = [s for s in statements if 'entity_semantic_links' in s]
    assert len(link_queries) == 1


def test_run_loads_semantic_links_in_one_query_per_type(db_session, statements):
    for _ in range(3):
        product = _product(db_session)
        _link(db_session, product.id, 'data_product', CUSTOMER_IRI + str(uuid.uuid4()))
        contract = _contract(db_session)
        _link(db_session, contract.id, 'data_contract', CUSTOMER_IRI + str(uuid.uuid4()))

    statements.clear()
    loaded = list(AppEntityLoader(db_session).load_entities(['data_product', 'data_contract']))

    assert len(loaded) >= 6
    link_queries = [s for s in statements if 'entity_semantic_links' in s]
    assert len(link_queries) == 2  # one per entity type
