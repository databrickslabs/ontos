"""Clearing demo data removes demo rows and their parts, never user data (#1044).

Rows added after the demo was loaded have ids that aren't in the demo packs.
The ones that are part of a demo row (runs and results of a demo policy, a
custom property of a demo product) go with it; user data that only refers to
demo data (an asset of a demo asset type, a product owned by a demo team)
blocks the clear and is left as is.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.db_models.assets import AssetDb, AssetRelationshipDb, AssetTypeDb
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import CustomPropertyDb, DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.db_models.teams import TeamDb
from src.utils.demo_data_cleanup import plan_demo_clear, run_demo_clear


def _id():
    return str(uuid.uuid4())


def _name(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _product(db, owner_team_id=None):
    product = DataProductDb(
        id=_id(), api_version='v1.0.0', kind='DataProduct', status='active',
        name=_name('p'), version='1.0.0', owner_team_id=owner_team_id,
    )
    db.add(product)
    db.flush()
    return product


def _team(db):
    team = TeamDb(id=_id(), name=_name('team'), created_by='system@demo', updated_by='system@demo')
    db.add(team)
    db.flush()
    return team


def _asset_type(db):
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=_name('type'))
    db.add(asset_type)
    db.flush()
    return asset_type


def _asset(db, asset_type):
    asset = AssetDb(id=uuid.uuid4(), name=_name('asset'), asset_type_id=asset_type.id)
    db.add(asset)
    db.flush()
    return asset


def _clear(db, demo):
    """Plan, and run only when nothing blocks (as the route does)."""
    plan = plan_demo_clear(db, demo)
    if plan.blocking:
        return plan, None
    return plan, run_demo_clear(db, plan)


def test_parts_of_demo_rows_are_deleted_with_them(db_session):
    demo, users = _product(db_session), _product(db_session)
    db_session.add_all([
        CustomPropertyDb(id=_id(), product_id=demo.id, property='costCenter', value='CC-1'),
        CustomPropertyDb(id=_id(), product_id=users.id, property='costCenter', value='CC-2'),
    ])
    db_session.flush()

    plan, deleted = _clear(db_session, [('data_products', 'id', [demo.id])])

    assert plan.blocking == {}
    assert deleted == {'data_product_custom_properties': 1, 'data_products': 1}
    assert db_session.get(DataProductDb, users.id) is not None
    assert [p.product_id for p in db_session.query(CustomPropertyDb).all()
            if p.product_id in (demo.id, users.id)] == [users.id]


def test_runs_and_results_of_a_demo_policy_are_deleted_first(db_session):
    policy = CompliancePolicyDb(
        id=_id(), name=_name('policy'), rule="MATCH (p:data_product) ASSERT p.status = 'active'",
        category='Governance', severity='low', is_active=True,
    )
    db_session.add(policy)
    db_session.flush()
    run = ComplianceRunDb(id=_id(), policy_id=policy.id, status='succeeded')
    db_session.add(run)
    db_session.flush()
    db_session.add_all([
        ComplianceResultDb(id=_id(), run_id=run.id, object_type='data_product',
                           object_id=_id(), passed=True)
        for _ in range(2)
    ])
    db_session.flush()

    plan, deleted = _clear(db_session, [('compliance_policies', 'id', [policy.id])])

    assert deleted == {'compliance_results': 2, 'compliance_runs': 1, 'compliance_policies': 1}
    assert db_session.query(ComplianceRunDb).filter_by(policy_id=policy.id).count() == 0


def test_a_users_asset_of_a_demo_asset_type_blocks_and_survives(db_session):
    demo_type = _asset_type(db_session)
    users_asset = _asset(db_session, demo_type)

    plan, deleted = _clear(db_session, [('asset_types', 'id', [str(demo_type.id)])])

    assert deleted is None
    assert plan.blocking_report() == [{
        'table': 'assets', 'column': 'asset_type_id', 'references': 'asset_types',
        'count': 1, 'ids': [str(users_asset.id)],
    }]
    assert db_session.get(AssetTypeDb, demo_type.id) is not None
    assert db_session.get(AssetDb, users_asset.id) is not None


def test_a_demo_asset_of_a_demo_type_does_not_block(db_session):
    demo_type = _asset_type(db_session)
    demo_asset = _asset(db_session, demo_type)

    plan, deleted = _clear(db_session, [
        ('assets', 'id', [str(demo_asset.id)]), ('asset_types', 'id', [str(demo_type.id)]),
    ])

    assert plan.blocking == {}
    assert deleted == {'assets': 1, 'asset_types': 1}


def test_a_product_owned_by_a_demo_team_blocks_and_keeps_its_owner(db_session):
    team = _team(db_session)
    users_product = _product(db_session, owner_team_id=team.id)

    plan, deleted = _clear(db_session, [('teams', 'id', [team.id])])

    assert deleted is None
    assert [(b['table'], b['column'], b['ids']) for b in plan.blocking_report()] == [
        ('data_products', 'owner_team_id', [users_product.id.lower()]),
    ]
    db_session.refresh(users_product)
    assert users_product.owner_team_id == team.id


def test_a_demo_tag_on_a_demo_entity_goes_on_a_users_entity_blocks(db_session):
    namespace = TagNamespaceDb(id=uuid.uuid4(), name=_name('ns'))
    db_session.add(namespace)
    db_session.flush()
    tag = TagDb(id=uuid.uuid4(), name=_name('tag'), namespace_id=namespace.id)
    db_session.add(tag)
    db_session.flush()
    demo_product, users_product = _product(db_session), _product(db_session)
    on_demo = EntityTagAssociationDb(id=uuid.uuid4(), tag_id=tag.id, entity_id=demo_product.id,
                                     entity_type='data_product')
    on_users = EntityTagAssociationDb(id=uuid.uuid4(), tag_id=tag.id, entity_id=users_product.id,
                                      entity_type='data_product')
    db_session.add_all([on_demo, on_users])
    db_session.flush()
    demo = [
        ('data_products', 'id', [demo_product.id]),
        ('tags', 'id', [str(tag.id)]),
        ('tag_namespaces', 'id', [str(namespace.id)]),
    ]

    plan = plan_demo_clear(db_session, demo)

    assert list(plan.dependents['entity_tag_associations']) == [(str(on_demo.id),)]
    assert [(b['table'], b['ids']) for b in plan.blocking_report()] == [
        ('entity_tag_associations', [str(on_users.id)]),
    ]


def test_a_users_tag_in_a_demo_namespace_blocks(db_session):
    namespace = TagNamespaceDb(id=uuid.uuid4(), name=_name('ns'))
    db_session.add(namespace)
    db_session.flush()
    users_tag = TagDb(id=uuid.uuid4(), name=_name('tag'), namespace_id=namespace.id)
    db_session.add(users_tag)
    db_session.flush()

    plan, deleted = _clear(db_session, [('tag_namespaces', 'id', [str(namespace.id)])])

    assert deleted is None
    assert [(b['table'], b['ids']) for b in plan.blocking_report()] == [
        ('tags', [str(users_tag.id)]),
    ]


def test_a_relationship_between_demo_assets_goes_one_to_a_users_asset_blocks(db_session):
    asset_type = _asset_type(db_session)
    demo_a, demo_b, users = (_asset(db_session, asset_type) for _ in range(3))
    between_demo = AssetRelationshipDb(id=uuid.uuid4(), source_asset_id=demo_a.id,
                                       target_asset_id=demo_b.id, relationship_type='feeds')
    to_users = AssetRelationshipDb(id=uuid.uuid4(), source_asset_id=demo_a.id,
                                   target_asset_id=users.id, relationship_type='feeds')
    db_session.add_all([between_demo, to_users])
    db_session.flush()

    plan = plan_demo_clear(db_session, [('assets', 'id', [str(demo_a.id), str(demo_b.id)])])

    assert list(plan.dependents['asset_relationships']) == [(str(between_demo.id),)]
    assert [(b['table'], b['ids']) for b in plan.blocking_report()] == [
        ('asset_relationships', [str(to_users.id)]),
    ]


def test_a_users_domain_under_a_demo_domain_blocks(db_session):
    parent = DataDomain(id=_id(), name=_name('d'), created_by='system@demo')
    db_session.add(parent)
    db_session.flush()
    demo_child = DataDomain(id=_id(), name=_name('d'), parent_id=parent.id,
                            created_by='system@demo')
    users_child = DataDomain(id=_id(), name=_name('d'), parent_id=parent.id,
                             created_by='user@example.com')
    db_session.add_all([demo_child, users_child])
    db_session.flush()

    plan = plan_demo_clear(db_session, [('data_domains', 'id', [parent.id, demo_child.id])])

    assert [(b['table'], b['column'], b['ids']) for b in plan.blocking_report()] == [
        ('data_domains', 'parent_id', [users_child.id.lower()]),
    ]


def test_the_report_lists_what_would_be_deleted(db_session):
    demo = _product(db_session)
    prop = CustomPropertyDb(id=_id(), product_id=demo.id, property='costCenter', value='CC-1')
    db_session.add(prop)
    db_session.flush()
    missing = _id()

    plan = plan_demo_clear(db_session, [('data_products', 'id', [demo.id, missing])])

    assert plan.deletes_report(db_session) == {
        'data_products': [demo.id],
        'data_product_custom_properties': [prop.id.lower()],
    }
    assert db_session.get(DataProductDb, demo.id) is not None  # nothing changed


def test_a_demo_row_with_a_composite_key_is_counted_once(db_session):
    # The packs identify project_teams rows by project_id; the same row is also
    # reached from the demo team, and must not be counted (or deleted) twice.
    from src.db_models.projects import ProjectDb
    from src.db_models.projects import project_team_association as project_teams

    team = _team(db_session)
    project = ProjectDb(id=_id(), name=_name('project'), created_by='system@demo',
                        updated_by='system@demo')
    db_session.add(project)
    db_session.flush()
    db_session.execute(project_teams.insert().values(
        project_id=project.id, team_id=team.id, assigned_by='system@demo',
    ))
    demo = [
        ('project_teams', 'project_id', [project.id]),
        ('projects', 'id', [project.id]),
        ('teams', 'id', [team.id]),
    ]

    plan = plan_demo_clear(db_session, demo)

    assert plan.blocking == {} and 'project_teams' not in plan.dependents
    assert plan.deletes_report(db_session)['project_teams'] == [f'{project.id}/{team.id}']
    assert run_demo_clear(db_session, plan) == {'project_teams': 1, 'projects': 1, 'teams': 1}


def test_demo_rows_are_deleted_children_first_whatever_the_pack_order(db_session):
    # With several presets loaded, a later pack's products can come before an
    # earlier pack's custom properties in the packs' reverse order
    product = _product(db_session)
    prop = CustomPropertyDb(id=_id(), product_id=product.id, property='costCenter', value='CC-1')
    db_session.add(prop)
    db_session.flush()

    plan = plan_demo_clear(db_session, [
        ('data_products', 'id', [product.id]),
        ('data_product_custom_properties', 'id', [prop.id]),
    ])

    assert [table for table, _, _ in plan.demo] == [
        'data_product_custom_properties', 'data_products',
    ]
    assert run_demo_clear(db_session, plan) == {
        'data_product_custom_properties': 1, 'data_products': 1,
    }


@pytest.mark.parametrize('schema_table', [
    'data_contract_schema_objects', 'data_contract_schema_properties',
])
def test_every_table_under_a_contract_schema_is_a_part_of_it(schema_table):
    # Rows that hang off a contract's schema objects or properties can't exist
    # without them. A new table there (e.g. #609's property custom properties)
    # must be listed in PART_OF, or editing a demo contract would block the clear.
    from src.utils.demo_data_cleanup import PART_OF, _referencing_foreign_keys

    children = {
        (child.name, column)
        for child, column, _ in _referencing_foreign_keys().get(schema_table, [])
    }

    assert children and children <= PART_OF


def test_nothing_to_clear(db_session):
    plan, deleted = _clear(db_session, [('data_products', 'id', [_id()])])
    assert plan.blocking == {} and plan.dependents == {}
    assert deleted == {}


# --- The route ---------------------------------------------------------------


@pytest.fixture
def route_db():
    """A session of its own: the route commits or rolls back, which would end
    the shared test transaction (and the rows the test set up) otherwise."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.common.database import Base

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _call_route(db, dry_run=False):
    from src.routes import settings_routes

    return asyncio.run(settings_routes.clear_demo_data(
        request=MagicMock(), background_tasks=MagicMock(), db=db,
        audit_manager=MagicMock(), current_user=MagicMock(username='admin'),
        manager=MagicMock(), dry_run=dry_run,
    ))


def _route_demo(asset_type):
    """Make the route's demo set this asset type only (instead of the packs)."""
    from src.utils.demo_data_sql import DemoInsert

    return patch(
        'src.utils.demo_data_sql.parse_demo_inserts',
        side_effect=lambda text: [DemoInsert('asset_types', 'id', [str(asset_type.id)])],
    )


def test_the_route_refuses_while_user_data_refers_to_demo_data(route_db):
    demo_type = _asset_type(route_db)
    users_asset = _asset(route_db, demo_type)
    route_db.commit()

    with _route_demo(demo_type), pytest.raises(HTTPException) as refused:
        _call_route(route_db)

    assert refused.value.status_code == 409
    assert refused.value.detail['code'] == 'demo_clear_blocked'
    assert refused.value.detail['params'] == {'blocking': 1}
    assert 'Nothing was deleted' in refused.value.detail['message']
    assert refused.value.detail['blocking'][0]['ids'] == [str(users_asset.id)]
    assert route_db.get(AssetTypeDb, demo_type.id) is not None


def test_the_dry_run_lists_without_deleting(route_db):
    demo_type = _asset_type(route_db)
    users_asset = _asset(route_db, demo_type)
    route_db.commit()

    with _route_demo(demo_type):
        result = _call_route(route_db, dry_run=True)

    assert result['status'] == 'dry_run'
    assert result['code'] == 'demo_clear_dry_run'
    assert result['params'] == {'would_delete': 1, 'blocking': 1}
    assert result['would_delete'] == {'asset_types': [str(demo_type.id)]}
    assert result['blocking'][0]['ids'] == [str(users_asset.id)]
    assert route_db.get(AssetTypeDb, demo_type.id) is not None


def test_the_clear_is_all_or_nothing(route_db):
    demo_type = _asset_type(route_db)
    route_db.commit()

    def delete_then_fail(db, plan):
        run_demo_clear(db, plan)
        raise RuntimeError('a later delete failed')

    with _route_demo(demo_type), \
            patch('src.utils.demo_data_cleanup.run_demo_clear', side_effect=delete_then_fail), \
            pytest.raises(HTTPException) as failed:
        _call_route(route_db)

    assert failed.value.status_code == 500
    assert failed.value.detail['code'] == 'demo_clear_failed'
    assert 'nothing was deleted' in failed.value.detail['message']
    assert route_db.get(AssetTypeDb, demo_type.id) is not None


def test_the_route_clears_when_nothing_blocks(route_db):
    demo_type = _asset_type(route_db)
    type_id = demo_type.id
    route_db.commit()

    with _route_demo(demo_type):
        result = _call_route(route_db)

    assert result == {
        'status': 'success', 'code': 'demo_clear_succeeded', 'params': {'deleted': 1},
        'message': 'Demo data cleared. Deleted 1 records.',
        'deleted_counts': {'asset_types': 1},
    }
    route_db.expire_all()
    assert route_db.get(AssetTypeDb, type_id) is None
