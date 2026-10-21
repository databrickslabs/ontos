"""Tests for manifest signing key providers."""

import base64
import os
import pytest
from unittest.mock import MagicMock, patch, Mock

from src.services.manifest_signing import (
    SigningKeyProvider,
    LocalFileKeyProvider,
    DatabricksSecretScopeKeyProvider,
    KeyProviderError,
)


# Test fixtures

@pytest.fixture
def valid_ed25519_key():
    """A valid 32-byte Ed25519 private key (all zeros for testing)."""
    return b'\x00' * 32


@pytest.fixture
def valid_ed25519_key_b64(valid_ed25519_key):
    """Base64-encoded Ed25519 key."""
    return base64.b64encode(valid_ed25519_key).decode('utf-8')


@pytest.fixture
def different_ed25519_key():
    """A different 32-byte Ed25519 private key."""
    return b'\xFF' * 32


@pytest.fixture
def different_ed25519_key_b64(different_ed25519_key):
    """Base64-encoded different key."""
    return base64.b64encode(different_ed25519_key).decode('utf-8')


# LocalFileKeyProvider Tests

class TestLocalFileKeyProvider:
    """Tests for LocalFileKeyProvider."""

    def test_initialization_success(self, valid_ed25519_key_b64, monkeypatch):
        """Provider initializes when MANIFEST_SIGNING_KEY is set."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        provider = LocalFileKeyProvider()
        assert provider is not None

    def test_get_signing_key(self, valid_ed25519_key_b64, valid_ed25519_key,
                             monkeypatch):
        """get_signing_key returns the key from environment."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        provider = LocalFileKeyProvider()
        assert provider.get_signing_key() == valid_ed25519_key

    def test_get_key_id_uses_env(self, valid_ed25519_key_b64, monkeypatch):
        """get_key_id returns MANIFEST_SIGNING_KEY_ID if set."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'my-key-2026-10-21')
        provider = LocalFileKeyProvider()
        assert provider.get_key_id() == 'my-key-2026-10-21'

    def test_get_key_id_default(self, valid_ed25519_key_b64, monkeypatch):
        """get_key_id uses default 'local-dev' if env var not set."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_ID', raising=False)
        provider = LocalFileKeyProvider()
        assert provider.get_key_id() == 'local-dev'

    def test_get_algorithm(self, valid_ed25519_key_b64, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        provider = LocalFileKeyProvider()
        assert provider.get_algorithm() == 'Ed25519'

    def test_missing_env_var_raises_error(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_KEY not set."""
        monkeypatch.delenv('MANIFEST_SIGNING_KEY', raising=False)
        with pytest.raises(KeyProviderError) as exc_info:
            LocalFileKeyProvider()
        assert exc_info.value.code == 'key_provider_error'
        assert 'MANIFEST_SIGNING_KEY' in str(exc_info.value)

    def test_invalid_base64_raises_error(self, monkeypatch):
        """Raises KeyProviderError if base64 decoding fails."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', 'not-valid-base64!!!')
        with pytest.raises(KeyProviderError) as exc_info:
            LocalFileKeyProvider()
        assert exc_info.value.code == 'key_provider_error'

    def test_wrong_key_length_raises_error(self, monkeypatch):
        """Raises KeyProviderError if decoded key is not 32 bytes."""
        # 16-byte key encoded as base64
        short_key = base64.b64encode(b'\x00' * 16).decode('utf-8')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', short_key)
        with pytest.raises(KeyProviderError) as exc_info:
            LocalFileKeyProvider()
        assert exc_info.value.code == 'key_provider_error'
        assert '32 bytes' in str(exc_info.value)

    def test_key_id_in_params(self, valid_ed25519_key_b64, monkeypatch):
        """KeyProviderError includes key_id in params."""
        invalid_b64 = 'bad!!!'
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', invalid_b64)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'test-key-id')
        with pytest.raises(KeyProviderError):
            LocalFileKeyProvider()

    def test_multiple_keys_different_instances(self, valid_ed25519_key_b64,
                                               different_ed25519_key_b64,
                                               monkeypatch):
        """Different provider instances can have different keys."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY', valid_ed25519_key_b64)
        provider1 = LocalFileKeyProvider()

        monkeypatch.setenv('MANIFEST_SIGNING_KEY', different_ed25519_key_b64)
        provider2 = LocalFileKeyProvider()

        assert provider1.get_signing_key() != provider2.get_signing_key()


# DatabricksSecretScopeKeyProvider Tests

class TestDatabricksSecretScopeKeyProvider:
    """Tests for DatabricksSecretScopeKeyProvider."""

    def test_initialization_missing_scope(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_SECRET_SCOPE not set."""
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_SCOPE', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_ID', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretScopeKeyProvider(ws_client)
        assert 'scope' in str(exc_info.value).lower()

    def test_initialization_missing_key(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_SECRET_KEY not set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_ID', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretScopeKeyProvider(ws_client)
        assert 'secret' in str(exc_info.value).lower()

    def test_initialization_missing_key_id(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_KEY_ID not set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_ID', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretScopeKeyProvider(ws_client)
        assert 'key id' in str(exc_info.value).lower()

    def test_initialization_success(self, monkeypatch):
        """Provider initializes when all env vars are set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key-2026-10-21')

        ws_client = MagicMock()
        provider = DatabricksSecretScopeKeyProvider(ws_client)
        assert provider is not None

    def test_get_key_id(self, monkeypatch):
        """get_key_id returns the configured key ID."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key-2026-10-21')

        ws_client = MagicMock()
        provider = DatabricksSecretScopeKeyProvider(ws_client)
        assert provider.get_key_id() == 'prod-key-2026-10-21'

    def test_get_algorithm(self, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        provider = DatabricksSecretScopeKeyProvider(ws_client)
        assert provider.get_algorithm() == 'Ed25519'

    def test_get_signing_key_success_bytes(self, valid_ed25519_key_b64,
                                           valid_ed25519_key, monkeypatch):
        """get_signing_key retrieves and decodes the key when API returns
        bytes."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = valid_ed25519_key_b64.encode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        key = provider.get_signing_key()

        assert key == valid_ed25519_key
        ws_client.secrets.get_secret.assert_called_once_with(
            scope='my-scope',
            key='my-key'
        )

    def test_get_signing_key_success_str(self, valid_ed25519_key_b64,
                                         valid_ed25519_key, monkeypatch):
        """get_signing_key handles when API returns string."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = valid_ed25519_key_b64  # String
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        key = provider.get_signing_key()

        assert key == valid_ed25519_key

    def test_get_signing_key_empty_secret(self, monkeypatch):
        """Raises KeyProviderError if secret value is empty."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = None
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_signing_key()
        assert 'empty' in str(exc_info.value).lower()

    def test_get_signing_key_invalid_base64(self, monkeypatch):
        """Raises KeyProviderError if secret is not valid base64."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = 'not-valid-base64!!!'
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_signing_key()
        assert 'base64' in str(exc_info.value).lower()

    def test_get_signing_key_wrong_length(self, monkeypatch):
        """Raises KeyProviderError if decoded key is not 32 bytes."""
        short_key = base64.b64encode(b'\x00' * 16).decode('utf-8')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = short_key
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_signing_key()
        assert '32 bytes' in str(exc_info.value)

    def test_get_signing_key_api_error(self, monkeypatch):
        """Raises KeyProviderError if secrets API call fails."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        ws_client.secrets.get_secret.side_effect = RuntimeError('API error')

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_signing_key()
        assert 'Failed to retrieve' in str(exc_info.value)

    def test_get_signing_key_whitespace_handling(self, valid_ed25519_key_b64,
                                                  valid_ed25519_key,
                                                  monkeypatch):
        """get_signing_key handles base64 with whitespace."""
        # Add newlines as might happen from multi-line secrets
        key_with_whitespace = f'  {valid_ed25519_key_b64}  \n'

        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_ID', 'prod-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = key_with_whitespace
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretScopeKeyProvider(ws_client)
        key = provider.get_signing_key()

        assert key == valid_ed25519_key


# Inheritance Tests

class TestSigningKeyProviderInterface:
    """Tests for SigningKeyProvider abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Cannot directly instantiate SigningKeyProvider."""
        with pytest.raises(TypeError):
            SigningKeyProvider()

    def test_local_provider_is_subclass(self):
        """LocalFileKeyProvider is a SigningKeyProvider."""
        assert issubclass(LocalFileKeyProvider, SigningKeyProvider)

    def test_databricks_provider_is_subclass(self):
        """DatabricksSecretScopeKeyProvider is a SigningKeyProvider."""
        assert issubclass(DatabricksSecretScopeKeyProvider, SigningKeyProvider)
