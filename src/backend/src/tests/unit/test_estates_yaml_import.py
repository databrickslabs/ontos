"""Estates YAML import on startup (#1128): one-time import with sample detection."""
import tempfile
from pathlib import Path
import pytest
import yaml

from src.controller.estate_manager import EstateManager
from src.models.estate import Estate, SharingPolicy, SharingRule
from src.repositories.app_settings_repository import app_settings_repo
from src.utils.startup_tasks import import_estates_from_yaml_once


@pytest.fixture
def clean_app_settings(db_session):
    """Clean the import flag and estates table before and after each test."""
    from src.db_models.estates import EstateDb

    # Clean before
    app_settings_repo.delete(db_session, 'estates_yaml_import_done')
    db_session.query(EstateDb).delete()
    db_session.commit()

    yield

    # Clean after
    app_settings_repo.delete(db_session, 'estates_yaml_import_done')
    db_session.query(EstateDb).delete()
    db_session.commit()


def test_path_is_injectable(db_session, clean_app_settings):
    """Item 2: Path parameter is injectable for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'custom.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Test Estate',
                'description': 'Test',
                'workspace_url': 'https://test.com',
                'cloud_type': 'aws',
                'metastore_name': 'test',
            }
        ]))

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        assert result is True
        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 1
        assert estates[0].name == 'Test Estate'


def test_shipped_sample_not_imported(db_session, clean_app_settings):
    """Item 1a: Exact shipped sample detected and not imported (3 estates)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        # Exact shipped sample (3 estates with all fields and timestamps)
        yaml_path.write_text(yaml.dump([
            {
                'id': '1',
                'name': 'US Production',
                'description': 'Primary production workspace in US West',
                'workspace_url': 'https://us-west.cloud.databricks.com',
                'cloud_type': 'aws',
                'metastore_name': 'us_prod_metastore',
                'connection_type': 'delta_share',
                'sharing_policies': [
                    {
                        'id': 'policy-us-prod-dp-active',
                        'name': 'Share Active US Data Products',
                        'description': 'Shares all active data products from the US Production estate.',
                        'resource_type': 'data_product',
                        'rules': [
                            {'filter_type': 'status', 'operator': 'equals', 'filter_value': 'Active'},
                            {'filter_type': 'domain', 'operator': 'equals', 'filter_value': 'US Operations'},
                        ],
                        'is_enabled': True,
                        'created_at': '2024-03-30T10:00:00Z',
                        'updated_at': '2024-03-30T10:00:00Z',
                    }
                ],
                'is_enabled': True,
                'sync_schedule': '0 0 * * *',
                'last_sync_time': '2024-03-29T10:00:00Z',
                'last_sync_status': 'success',
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-03-29T10:00:00Z',
            },
            {
                'id': '2',
                'name': 'EU Analytics',
                'description': 'Analytics workspace in EU Central',
                'workspace_url': 'https://europe-west.cloud.databricks.com',
                'cloud_type': 'azure',
                'metastore_name': 'eu_analytics_metastore',
                'connection_type': 'delta_share',
                'sharing_policies': [
                    {
                        'id': 'policy-eu-glossary-finance',
                        'name': 'Share Finance Glossary Terms from EU',
                        'description': 'Shares all business glossary terms related to Finance.',
                        'resource_type': 'business_glossary',
                        'rules': [
                            {'filter_type': 'tag', 'operator': 'contains', 'filter_value': 'finance'},
                            {'filter_type': 'domain', 'operator': 'equals', 'filter_value': 'EU Analytics'},
                        ],
                        'is_enabled': True,
                        'created_at': '2024-03-30T11:00:00Z',
                        'updated_at': '2024-03-30T11:00:00Z',
                    }
                ],
                'is_enabled': True,
                'sync_schedule': '0 12 * * *',
                'last_sync_time': '2024-03-29T12:00:00Z',
                'last_sync_status': 'success',
                'created_at': '2024-01-15T00:00:00Z',
                'updated_at': '2024-03-29T12:00:00Z',
            },
            {
                'id': '3',
                'name': 'APAC Development',
                'description': 'Development workspace in APAC',
                'workspace_url': 'https://asia-southeast.cloud.databricks.com',
                'cloud_type': 'gcp',
                'metastore_name': 'apac_dev_metastore',
                'connection_type': 'database',
                'sharing_policies': [],
                'is_enabled': False,
                'sync_schedule': '0 6 * * *',
                'last_sync_time': '2024-03-28T06:00:00Z',
                'last_sync_status': 'failed',
                'last_sync_error': 'Connection timeout',
                'created_at': '2024-02-01T00:00:00Z',
                'updated_at': '2024-03-28T06:00:00Z',
            },
        ]))

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        # Should return False (sample not imported)
        assert result is False
        # Flag should be set
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') == 'true'
        # DB should be empty
        manager = EstateManager()
        assert manager.list_estates(db_session) == []


def test_sample_with_one_rule_changed_is_imported(db_session, clean_app_settings):
    """Item 1b: Sample with one rule value changed is imported (not treated as sample)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        # Exact shipped sample EXCEPT one rule value changed
        yaml_path.write_text(yaml.dump([
            {
                'id': '1',
                'name': 'US Production',
                'description': 'Primary production workspace in US West',
                'workspace_url': 'https://us-west.cloud.databricks.com',
                'cloud_type': 'aws',
                'metastore_name': 'us_prod_metastore',
                'connection_type': 'delta_share',
                'sharing_policies': [
                    {
                        'id': 'policy-us-prod-dp-active',
                        'name': 'Share Active US Data Products',
                        'description': 'Shares all active data products from the US Production estate.',
                        'resource_type': 'data_product',
                        'rules': [
                            {'filter_type': 'status', 'operator': 'equals', 'filter_value': 'Active'},
                            {'filter_type': 'domain', 'operator': 'equals', 'filter_value': 'CUSTOMIZED OPS'},  # Changed!
                        ],
                        'is_enabled': True,
                        'created_at': '2024-03-30T10:00:00Z',
                        'updated_at': '2024-03-30T10:00:00Z',
                    }
                ],
                'is_enabled': True,
                'sync_schedule': '0 0 * * *',
                'last_sync_time': '2024-03-29T10:00:00Z',
                'last_sync_status': 'success',
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-03-29T10:00:00Z',
            },
            {
                'id': '2',
                'name': 'EU Analytics',
                'description': 'Analytics workspace in EU Central',
                'workspace_url': 'https://europe-west.cloud.databricks.com',
                'cloud_type': 'azure',
                'metastore_name': 'eu_analytics_metastore',
                'connection_type': 'delta_share',
                'sharing_policies': [
                    {
                        'id': 'policy-eu-glossary-finance',
                        'name': 'Share Finance Glossary Terms from EU',
                        'description': 'Shares all business glossary terms related to Finance.',
                        'resource_type': 'business_glossary',
                        'rules': [
                            {'filter_type': 'tag', 'operator': 'contains', 'filter_value': 'finance'},
                            {'filter_type': 'domain', 'operator': 'equals', 'filter_value': 'EU Analytics'},
                        ],
                        'is_enabled': True,
                        'created_at': '2024-03-30T11:00:00Z',
                        'updated_at': '2024-03-30T11:00:00Z',
                    }
                ],
                'is_enabled': True,
                'sync_schedule': '0 12 * * *',
                'last_sync_time': '2024-03-29T12:00:00Z',
                'last_sync_status': 'success',
                'created_at': '2024-01-15T00:00:00Z',
                'updated_at': '2024-03-29T12:00:00Z',
            },
            {
                'id': '3',
                'name': 'APAC Development',
                'description': 'Development workspace in APAC',
                'workspace_url': 'https://asia-southeast.cloud.databricks.com',
                'cloud_type': 'gcp',
                'metastore_name': 'apac_dev_metastore',
                'connection_type': 'database',
                'sharing_policies': [],
                'is_enabled': False,
                'sync_schedule': '0 6 * * *',
                'last_sync_time': '2024-03-28T06:00:00Z',
                'last_sync_status': 'failed',
                'last_sync_error': 'Connection timeout',
                'created_at': '2024-02-01T00:00:00Z',
                'updated_at': '2024-03-28T06:00:00Z',
            },
        ]))

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        # Should return True (configured, not sample)
        assert result is True
        # Flag should be set
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') == 'true'
        # DB should have 3 estates
        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 3
        # Verify the changed rule is in the database
        us_prod = next((e for e in estates if e.name == 'US Production'), None)
        assert us_prod is not None
        assert len(us_prod.export_policies) > 0
        domain_rules = [r for r in us_prod.export_policies[0].rules if r.filter_type == 'domain']
        assert len(domain_rules) > 0
        assert domain_rules[0].filter_value == 'CUSTOMIZED OPS'


def test_malformed_yaml_no_mark_done(db_session, clean_app_settings):
    """Item 4: Malformed YAML logs warning and does NOT mark done."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'bad.yaml'
        yaml_path.write_text('{ invalid: yaml: [')

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        # Should return False (not imported)
        assert result is False
        # Flag should NOT be set (allows retry)
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') is None


def test_transaction_atomicity_rollback_on_error(db_session, clean_app_settings):
    """Item 2b: Import is atomic - if 2nd estate is invalid, no estates imported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Good Estate',
                'description': 'Valid',
                'workspace_url': 'https://good.com',
                'cloud_type': 'aws',
                'metastore_name': 'good',
            },
            {
                'name': 'Bad Estate',
                'description': 'Missing required fields',
                # Missing workspace_url, cloud_type, metastore_name - will cause error
            },
        ]))

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        # Should return False (error during import)
        assert result is False
        # Flag should NOT be set (allows retry)
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') is None
        # DB should be empty (rolled back)
        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 0


def test_transaction_retry_after_fix(db_session, clean_app_settings):
    """Item 2c: After fixing invalid YAML, both estates import on next startup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Good Estate',
                'description': 'Valid',
                'workspace_url': 'https://good.com',
                'cloud_type': 'aws',
                'metastore_name': 'good',
            },
            {
                'name': 'Bad Estate',
                'description': 'Invalid',
                # Missing required fields
            },
        ]))

        # First attempt fails
        result1 = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result1 is False
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') is None

        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 0

        # Fix the YAML
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Good Estate',
                'description': 'Valid',
                'workspace_url': 'https://good.com',
                'cloud_type': 'aws',
                'metastore_name': 'good',
            },
            {
                'name': 'Fixed Estate',
                'description': 'Now valid',
                'workspace_url': 'https://fixed.com',
                'cloud_type': 'azure',
                'metastore_name': 'fixed',
            },
        ]))

        # Second attempt succeeds
        result2 = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result2 is True
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') == 'true'

        estates = manager.list_estates(db_session)
        assert len(estates) == 2
        names = {e.name for e in estates}
        assert names == {'Good Estate', 'Fixed Estate'}


def test_mark_as_done_prevents_reimport(db_session, clean_app_settings):
    """Import marks done; second startup skips."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Estate 1',
                'description': 'Test',
                'workspace_url': 'https://test.com',
                'cloud_type': 'aws',
                'metastore_name': 'test',
            }
        ]))

        # First import
        result1 = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result1 is True

        manager = EstateManager()
        count_after_first = len(manager.list_estates(db_session))
        assert count_after_first == 1

        # Second import (should skip)
        result2 = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result2 is False

        # No duplicates
        count_after_second = len(manager.list_estates(db_session))
        assert count_after_second == count_after_first


def test_upgrade_configured_estate_with_policies_and_rules(db_session, clean_app_settings):
    """Item 5: Upgrade test - configured estate with policies and rules imported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Configured Estate',
                'description': 'Has policies and rules',
                'workspace_url': 'https://configured.com',
                'cloud_type': 'gcp',
                'metastore_name': 'configured',
                'export_policies': [
                    {
                        'name': 'Policy 1',
                        'resource_type': 'data_product',
                        'is_enabled': True,
                        'rules': [
                            {'filter_type': 'domain', 'operator': 'equals', 'filter_value': 'Engineering'}
                        ],
                    }
                ],
                'import_policies': [
                    {
                        'name': 'Import Policy',
                        'resource_type': 'data_contract',
                        'is_enabled': True,
                        'rules': [
                            {'filter_type': 'tag', 'operator': 'contains', 'filter_value': 'shared'},
                            {'filter_type': 'status', 'operator': 'equals', 'filter_value': 'active'},
                        ],
                    }
                ],
            }
        ]))

        # First startup
        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result is True

        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 1

        estate = estates[0]
        assert estate.name == 'Configured Estate'
        assert len(estate.export_policies) == 1
        assert len(estate.import_policies) == 1
        assert len(estate.export_policies[0].rules) == 1
        assert len(estate.import_policies[0].rules) == 2

        # Second startup - no duplicates
        app_settings_repo.delete(db_session, 'estates_yaml_import_done')
        # Manually reset flag to simulate new DB but same YAML
        result2 = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result2 is False  # Already imported

        estates_after = manager.list_estates(db_session)
        assert len(estates_after) == 1  # Still one, no duplicates


def test_empty_file_marks_done(db_session, clean_app_settings):
    """Empty YAML file marks done to avoid retry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'empty.yaml'
        yaml_path.write_text('')

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)

        assert result is False
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') == 'true'


def test_missing_file_does_not_mark_done(db_session, clean_app_settings):
    """A missing file leaves the marker unset so a restored file is imported later."""
    from src.db_models.estates import EstateDb

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'estates.yaml'

        assert import_estates_from_yaml_once(db_session, yaml_path=yaml_path) is False
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') is None
        assert db_session.query(EstateDb).count() == 0

        # The file appears later (e.g. a customised copy is put back): next call imports it
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Restored Estate',
                'description': 'Put back after upgrade',
                'workspace_url': 'https://restored.com',
                'cloud_type': 'aws',
                'metastore_name': 'restored',
            }
        ]))

        assert import_estates_from_yaml_once(db_session, yaml_path=yaml_path) is True
        assert app_settings_repo.get_by_key(db_session, 'estates_yaml_import_done') == 'true'
        estates = EstateManager().list_estates(db_session)
        assert [e.name for e in estates] == ['Restored Estate']


def test_legacy_sharing_policies_converted(db_session, clean_app_settings):
    """Legacy sharing_policies and business_glossary converted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'legacy.yaml'
        yaml_path.write_text(yaml.dump([
            {
                'name': 'Legacy Estate',
                'description': 'Old format',
                'workspace_url': 'https://legacy.com',
                'cloud_type': 'azure',
                'metastore_name': 'legacy',
                'sharing_policies': [  # Old field name
                    {
                        'name': 'Finance Glossary',
                        'resource_type': 'business_glossary',  # Old type
                        'is_enabled': True,
                        'rules': [],
                    }
                ],
            }
        ]))

        result = import_estates_from_yaml_once(db_session, yaml_path=yaml_path)
        assert result is True

        manager = EstateManager()
        estates = manager.list_estates(db_session)
        assert len(estates) == 1
        assert len(estates[0].export_policies) == 1
        assert estates[0].export_policies[0].resource_type.value == 'business_term'
