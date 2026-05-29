"""
Unit tests for Features module

Tests feature configuration and access levels including:
- Feature access levels
- Feature configuration
- Access level ordering
"""
import pytest

from src.common.features import (
    FeatureAccessLevel,
    ACCESS_LEVEL_ORDER,
    APP_FEATURES,
    get_feature_config,
    get_all_access_levels,
)


class TestFeatures:
    """Test suite for features module"""

    def test_feature_access_level_enum(self):
        """Test FeatureAccessLevel enum values."""
        assert FeatureAccessLevel.NONE == "None"
        assert FeatureAccessLevel.READ_ONLY == "Read-only"
        assert FeatureAccessLevel.READ_WRITE == "Read/Write"
        assert FeatureAccessLevel.FILTERED == "Filtered"
        assert FeatureAccessLevel.FULL == "Full"
        assert FeatureAccessLevel.ADMIN == "Admin"

    def test_access_level_order(self):
        """Test access level ordering."""
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.NONE] == 0
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY] == 1
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.FILTERED] == 2
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_WRITE] == 3
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.FULL] == 4
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.ADMIN] == 5

    def test_access_level_ordering_comparison(self):
        """Test that higher access levels have higher order values."""
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.ADMIN] > ACCESS_LEVEL_ORDER[FeatureAccessLevel.FULL]
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.FULL] > ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_WRITE]
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_WRITE] > ACCESS_LEVEL_ORDER[FeatureAccessLevel.FILTERED]
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.FILTERED] > ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY]
        assert ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY] > ACCESS_LEVEL_ORDER[FeatureAccessLevel.NONE]

    def test_get_feature_config(self):
        """Test get_feature_config returns configuration."""
        config = get_feature_config()
        assert config is not None
        assert isinstance(config, dict)
        assert len(config) > 0

    def test_get_all_access_levels(self):
        """Test get_all_access_levels returns all levels."""
        levels = get_all_access_levels()
        assert levels is not None
        assert isinstance(levels, list)
        assert len(levels) == 6
        assert FeatureAccessLevel.NONE in levels
        assert FeatureAccessLevel.ADMIN in levels

    def test_app_features_structure(self):
        """Test APP_FEATURES has correct structure."""
        assert 'data-domains' in APP_FEATURES
        assert 'data-products' in APP_FEATURES
        assert 'data-contracts' in APP_FEATURES
        assert 'settings' in APP_FEATURES

        # Check structure of a feature
        data_domains = APP_FEATURES['data-domains']
        assert 'name' in data_domains
        assert 'allowed_levels' in data_domains
        assert data_domains['name'] == 'Data Domains'
        assert isinstance(data_domains['allowed_levels'], list)

    def test_data_domains_feature(self):
        """Test data-domains feature configuration."""
        feature = APP_FEATURES['data-domains']
        assert feature['name'] == 'Data Domains'
        assert FeatureAccessLevel.READ_ONLY in feature['allowed_levels']
        assert FeatureAccessLevel.READ_WRITE in feature['allowed_levels']
        assert FeatureAccessLevel.ADMIN in feature['allowed_levels']

    def test_settings_feature_layout_gate(self):
        """Settings is the parent layout gate; allows None/RO/RW/Admin.

        Per the Settings permissions refactor (PR #430 / issue #427), the
        top-level `settings` permission acts as a layout gate for the
        Settings area while individual sub-pages get their own
        `settings-<name>` permissions.
        """
        feature = APP_FEATURES['settings']
        assert feature['name'] == 'Settings'
        allowed = feature['allowed_levels']
        assert FeatureAccessLevel.NONE in allowed
        assert FeatureAccessLevel.READ_ONLY in allowed
        assert FeatureAccessLevel.READ_WRITE in allowed
        assert FeatureAccessLevel.ADMIN in allowed

    def test_data_products_filtered_access(self):
        """Test data-products supports filtered access."""
        feature = APP_FEATURES['data-products']
        allowed = feature['allowed_levels']
        assert FeatureAccessLevel.FILTERED in allowed

    def test_compliance_feature(self):
        """Test compliance feature configuration."""
        feature = APP_FEATURES['compliance']
        assert feature['name'] == 'Compliance'
        allowed = feature['allowed_levels']
        assert FeatureAccessLevel.READ_ONLY in allowed
        assert FeatureAccessLevel.READ_WRITE in allowed
        assert FeatureAccessLevel.ADMIN in allowed

    def test_all_features_have_name(self):
        """Test all features have a name."""
        for feature_id, config in APP_FEATURES.items():
            assert 'name' in config
            assert isinstance(config['name'], str)
            assert len(config['name']) > 0

    def test_all_features_have_allowed_levels(self):
        """Test all features have allowed_levels."""
        for feature_id, config in APP_FEATURES.items():
            assert 'allowed_levels' in config
            assert isinstance(config['allowed_levels'], list)
            assert len(config['allowed_levels']) > 0

