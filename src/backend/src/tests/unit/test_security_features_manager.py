"""
Unit tests for SecurityFeaturesManager
"""
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, mock_open, patch
from src.controller.security_features_manager import SecurityFeaturesManager
from src.models.security_features import SecurityFeature, SecurityFeatureType


class TestSecurityFeaturesManager:
    """Test suite for SecurityFeaturesManager."""

    @pytest.fixture
    def manager(self):
        """Create SecurityFeaturesManager instance for testing."""
        return SecurityFeaturesManager()

    @pytest.fixture
    def sample_feature(self):
        """Sample security feature."""
        return SecurityFeature(
            id="feature-123",
            name="Differential Privacy",
            description="Add noise to queries",
            type=SecurityFeatureType.DIFFERENTIAL_PRIVACY,
            status="enabled",
            target="catalog.schema.table",
            conditions=["user_group = 'external'"],
            last_updated=datetime(2024, 1, 1, 0, 0, 0),
        )

    # Initialization Tests

    def test_manager_initialization(self):
        """Test manager initializes with empty features dict."""
        manager = SecurityFeaturesManager()
        assert isinstance(manager.features, dict)
        assert len(manager.features) == 0

    # Create Feature Tests

    def test_create_feature_success(self, manager, sample_feature):
        """Test creating a security feature."""
        result = manager.create_feature(sample_feature)

        assert result == sample_feature
        assert manager.features["feature-123"] == sample_feature

    def test_create_feature_replaces_existing(self, manager, sample_feature):
        """Test creating feature with existing ID replaces it."""
        manager.create_feature(sample_feature)

        updated_feature = SecurityFeature(
            id="feature-123",
            name="Updated Feature",
            description="Updated description",
            type=SecurityFeatureType.ROW_FILTERING,
            status="disabled",
        )
        result = manager.create_feature(updated_feature)

        assert result == updated_feature
        assert manager.features["feature-123"] == updated_feature

    # Get Feature Tests

    def test_get_feature_exists(self, manager, sample_feature):
        """Test getting an existing feature."""
        manager.create_feature(sample_feature)

        result = manager.get_feature("feature-123")

        assert result == sample_feature

    def test_get_feature_not_exists(self, manager):
        """Test getting a non-existent feature."""
        result = manager.get_feature("nonexistent")

        assert result is None

    # List Features Tests

    def test_list_features_empty(self, manager):
        """Test listing features when none exist."""
        result = manager.list_features()

        assert result == []

    def test_list_features_with_items(self, manager, sample_feature):
        """Test listing features with items."""
        feature2 = SecurityFeature(
            id="feature-456",
            name="Row-Level Security",
            description="Filter rows by user",
            type=SecurityFeatureType.ROW_FILTERING,
            status="enabled",
        )
        
        manager.create_feature(sample_feature)
        manager.create_feature(feature2)

        result = manager.list_features()

        assert len(result) == 2
        assert sample_feature in result
        assert feature2 in result

    def test_list_features_returns_values(self, manager, sample_feature):
        """Test that list_features returns values not keys."""
        manager.create_feature(sample_feature)

        result = manager.list_features()

        assert all(isinstance(f, SecurityFeature) for f in result)

    # Update Feature Tests

    def test_update_feature_success(self, manager, sample_feature):
        """Test updating an existing feature."""
        manager.create_feature(sample_feature)

        updated_feature = SecurityFeature(
            id="feature-123",
            name="Updated Name",
            description="Updated description",
            type=SecurityFeatureType.COLUMN_MASKING,
            status="disabled",
        )

        result = manager.update_feature("feature-123", updated_feature)

        assert result == updated_feature
        assert manager.features["feature-123"] == updated_feature

    def test_update_feature_not_found(self, manager):
        """Test updating a non-existent feature."""
        feature = SecurityFeature(
            id="nonexistent",
            name="Test",
            description="Test",
            type=SecurityFeatureType.TOKENIZATION,
            status="enabled",
        )

        result = manager.update_feature("nonexistent", feature)

        assert result is None
        assert "nonexistent" not in manager.features

    # Delete Feature Tests

    def test_delete_feature_success(self, manager, sample_feature):
        """Test deleting an existing feature."""
        manager.create_feature(sample_feature)

        result = manager.delete_feature("feature-123")

        assert result is True
        assert "feature-123" not in manager.features

    def test_delete_feature_not_found(self, manager):
        """Test deleting a non-existent feature."""
        result = manager.delete_feature("nonexistent")

        assert result is False

    # Load from YAML Tests

    @patch('pathlib.Path.exists')
    def test_load_from_yaml_file_not_found(self, mock_exists, manager):
        """Test loading from non-existent YAML file."""
        mock_exists.return_value = False

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is False

    @patch('builtins.open', new_callable=mock_open, read_data="")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_empty_file(self, mock_exists, mock_file, manager):
        """Test loading from empty YAML file."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is True
        assert len(manager.features) == 0

    @patch('builtins.open', new_callable=mock_open, read_data="features: []")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_empty_features_list(self, mock_exists, mock_file, manager):
        """Test loading from YAML with empty features list."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is True
        assert len(manager.features) == 0

    @patch('builtins.open', new_callable=mock_open, read_data="""
features:
  - id: feature-1
    name: Test Feature
    description: Test description
    enabled: true
    config: {}
""")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_valid_features(self, mock_exists, mock_file, manager):
        """Test loading valid features from YAML."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is True
        assert len(manager.features) == 1
        assert "feature-1" in manager.features
        assert manager.features["feature-1"].name == "Test Feature"

    @patch('builtins.open', new_callable=mock_open, read_data="invalid: yaml: :")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_invalid_syntax(self, mock_exists, mock_file, manager):
        """Test loading YAML with invalid syntax."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is False

    @patch('builtins.open', new_callable=mock_open, read_data="no_features_key: value")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_no_features_key(self, mock_exists, mock_file, manager):
        """Test loading YAML without features key."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is True  # Success but no features loaded

    @patch('builtins.open', new_callable=mock_open, read_data="features: not_a_list")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_features_not_list(self, mock_exists, mock_file, manager):
        """Test loading YAML where features is not a list."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        assert result is False

    @patch('builtins.open', new_callable=mock_open, read_data="""
features:
  - id: feature-1
    name: Valid Feature
    description: Valid
    enabled: true
    config: {}
  - invalid_feature_without_id
  - id: feature-2
    name: Another Valid Feature
    description: Also valid
    enabled: false
    config: {}
""")
    @patch('pathlib.Path.exists')
    def test_load_from_yaml_mixed_valid_invalid(self, mock_exists, mock_file, manager):
        """Test loading YAML with mix of valid and invalid features."""
        mock_exists.return_value = True

        result = manager.load_from_yaml(Path("/fake/path.yaml"))

        # Should return True (file processed) and load only valid features
        assert result is True
        assert len(manager.features) == 2  # Only valid features loaded
        assert "feature-1" in manager.features
        assert "feature-2" in manager.features

    # Save to YAML Tests

    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.dump')
    def test_save_to_yaml_success(self, mock_yaml_dump, mock_file, manager, sample_feature):
        """Test saving features to YAML."""
        manager.create_feature(sample_feature)

        manager.save_to_yaml(Path("/fake/path.yaml"))

        # Verify file was opened for writing
        mock_file.assert_called_once_with(Path("/fake/path.yaml"), 'w')
        # Verify yaml.dump was called
        mock_yaml_dump.assert_called_once()
        # Verify structure passed to yaml.dump
        call_args = mock_yaml_dump.call_args[0]
        assert 'features' in call_args[0]
        assert len(call_args[0]['features']) == 1

    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.dump')
    def test_save_to_yaml_empty_features(self, mock_yaml_dump, mock_file, manager):
        """Test saving empty features to YAML."""
        manager.save_to_yaml(Path("/fake/path.yaml"))

        # Verify empty list was saved
        call_args = mock_yaml_dump.call_args[0]
        assert 'features' in call_args[0]
        assert call_args[0]['features'] == []

    @patch('builtins.open', side_effect=IOError("Permission denied"))
    def test_save_to_yaml_io_error(self, mock_file, manager, sample_feature):
        """Test handling of IO errors when saving to YAML."""
        manager.create_feature(sample_feature)

        with pytest.raises(IOError, match="Permission denied"):
            manager.save_to_yaml(Path("/fake/path.yaml"))

    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.dump')
    def test_save_to_yaml_multiple_features(self, mock_yaml_dump, mock_file, manager):
        """Test saving multiple features to YAML."""
        feature1 = SecurityFeature(
            id="feature-1", 
            name="Feature 1", 
            description="Desc 1", 
            type=SecurityFeatureType.ROW_FILTERING,
            status="enabled"
        )
        feature2 = SecurityFeature(
            id="feature-2", 
            name="Feature 2", 
            description="Desc 2", 
            type=SecurityFeatureType.COLUMN_MASKING,
            status="disabled"
        )
        
        manager.create_feature(feature1)
        manager.create_feature(feature2)

        manager.save_to_yaml(Path("/fake/path.yaml"))

        call_args = mock_yaml_dump.call_args[0]
        assert len(call_args[0]['features']) == 2

