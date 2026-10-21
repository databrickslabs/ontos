"""Tests for Ed25519 manifest signing key providers.

ADR: docs/decisions/manifest-canonicalization-hashing-signing.md
Decision 7: Keys and key providers.
"""

import hashlib
import os
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.common.manifest_signing import (
    SigningKeyProvider,
    LocalDevKeyProvider,
    DatabricksSecretKeyProvider,
    KeyProviderError,
)


# Test fixtures

@pytest.fixture
def test_ed25519_key():
    """Generate a valid Ed25519 private key for testing."""
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def test_ed25519_pem(test_ed25519_key):
    """PEM-encoded Ed25519 private key."""
    return test_ed25519_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')


@pytest.fixture
def different_ed25519_pem():
    """Generate a different PEM-encoded Ed25519 key."""
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')


# LocalDevKeyProvider Tests

class TestLocalDevKeyProvider:
    """Tests for LocalDevKeyProvider."""

    def test_initialization_from_env_var(self, test_ed25519_pem, monkeypatch):
        """Provider initializes when MANIFEST_SIGNING_KEY_PEM is set."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        assert provider is not None

    def test_get_private_key(self, test_ed25519_pem, monkeypatch):
        """get_private_key returns an Ed25519PrivateKey."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        key = provider.get_private_key()
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, test_ed25519_pem, monkeypatch):
        """get_public_key_bytes returns the correct 32-byte public key."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        pubkey1 = provider.get_public_key_bytes()
        pubkey2 = provider.get_public_key_bytes()
        assert len(pubkey1) == 32
        assert pubkey1 == pubkey2

    def test_get_key_id_format(self, test_ed25519_pem, monkeypatch):
        """get_key_id returns format 'ed25519:XXXXXXXXXXXXXXXX'."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        key_id = provider.get_key_id()
        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_get_key_id_deterministic(self, test_ed25519_pem, monkeypatch):
        """get_key_id is deterministic for the same key."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider1 = LocalDevKeyProvider()
        key_id1 = provider1.get_key_id()

        provider2 = LocalDevKeyProvider()
        key_id2 = provider2.get_key_id()

        assert key_id1 == key_id2

    def test_get_algorithm(self, test_ed25519_pem, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        assert provider.get_algorithm() == 'Ed25519'

    def test_missing_key_pem_raises_error(self, monkeypatch, tmp_path):
        """Raises KeyProviderError if key not found in env or file."""
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(tmp_path / 'nonexistent.pem'))
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider()
        assert exc_info.value.code == 'key_provider_error'

    def test_invalid_pem_raises_error(self, monkeypatch):
        """Raises KeyProviderError if PEM is invalid."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', 'not-a-valid-pem')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider()
        assert exc_info.value.code == 'key_provider_error'

    def test_wrong_key_type_raises_error(self, monkeypatch):
        """Raises KeyProviderError if PEM is not Ed25519."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', rsa_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider()
        assert 'not Ed25519' in str(exc_info.value)

    def test_initialization_from_file(self, test_ed25519_pem, monkeypatch):
        """Provider initializes from file when env var not set."""
        with TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / 'key.pem'
            key_file.write_text(test_ed25519_pem)
            monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
            monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_file))
            provider = LocalDevKeyProvider()
            assert provider is not None

    def test_different_keys_different_key_ids(self, test_ed25519_pem,
                                               different_ed25519_pem, monkeypatch):
        """Different keys produce different key_ids."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider1 = LocalDevKeyProvider()
        key_id1 = provider1.get_key_id()

        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', different_ed25519_pem)
        provider2 = LocalDevKeyProvider()
        key_id2 = provider2.get_key_id()

        assert key_id1 != key_id2


# DatabricksSecretKeyProvider Tests

class TestDatabricksSecretKeyProvider:
    """Tests for DatabricksSecretKeyProvider."""

    def test_initialization_missing_scope(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_SECRET_SCOPE not set."""
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_SCOPE', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretKeyProvider(ws_client)
        assert 'scope' in str(exc_info.value).lower()

    def test_initialization_missing_key(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_SECRET_KEY not set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretKeyProvider(ws_client)
        assert 'secret' in str(exc_info.value).lower()

    def test_initialization_success(self, monkeypatch):
        """Provider initializes when config is set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        provider = DatabricksSecretKeyProvider(ws_client)
        assert provider is not None

    def test_get_private_key_success(self, test_ed25519_pem, monkeypatch):
        """get_private_key retrieves and decodes the key."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = test_ed25519_pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)
        ws_client.secrets.get_secret.assert_called_once_with(
            scope='my-scope',
            key='my-key'
        )

    def test_get_private_key_bytes_response(self, test_ed25519_pem, monkeypatch):
        """get_private_key handles bytes response from API."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = test_ed25519_pem.encode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_private_key_base64_response(self, test_ed25519_pem, monkeypatch):
        """get_private_key auto-decodes base64 if not PEM."""
        import base64
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = base64.b64encode(test_ed25519_pem.encode('utf-8')).decode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, test_ed25519_pem, monkeypatch):
        """get_public_key_bytes returns 32 bytes."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = test_ed25519_pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        pubkey = provider.get_public_key_bytes()

        assert isinstance(pubkey, bytes)
        assert len(pubkey) == 32

    def test_get_key_id_format(self, test_ed25519_pem, monkeypatch):
        """get_key_id returns format 'ed25519:XXXXXXXXXXXXXXXX'."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = test_ed25519_pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key_id = provider.get_key_id()

        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_empty_secret_raises_error(self, monkeypatch):
        """Raises KeyProviderError if secret is empty."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = None
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'empty' in str(exc_info.value).lower()

    def test_invalid_pem_raises_error(self, monkeypatch):
        """Raises KeyProviderError if secret is not valid PEM."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = 'not-a-valid-pem'
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'valid Ed25519 PEM' in str(exc_info.value)

    def test_wrong_key_type_raises_error(self, monkeypatch):
        """Raises KeyProviderError if PEM is not Ed25519."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = rsa_pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'not Ed25519' in str(exc_info.value)

    def test_api_error_raises_error(self, monkeypatch):
        """Raises KeyProviderError if secrets API call fails."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        ws_client.secrets.get_secret.side_effect = RuntimeError('API error')

        provider = DatabricksSecretKeyProvider(ws_client)
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'Failed to retrieve' in str(exc_info.value)

    def test_whitespace_handling(self, test_ed25519_pem, monkeypatch):
        """get_private_key handles whitespace around PEM."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = f'  {test_ed25519_pem}  \n'
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)


# SigningKeyProvider Interface Tests

class TestSigningKeyProviderInterface:
    """Tests for SigningKeyProvider abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Cannot directly instantiate SigningKeyProvider."""
        with pytest.raises(TypeError):
            SigningKeyProvider()

    def test_local_provider_is_subclass(self):
        """LocalDevKeyProvider is a SigningKeyProvider."""
        assert issubclass(LocalDevKeyProvider, SigningKeyProvider)

    def test_databricks_provider_is_subclass(self):
        """DatabricksSecretKeyProvider is a SigningKeyProvider."""
        assert issubclass(DatabricksSecretKeyProvider, SigningKeyProvider)

    def test_algorithm_constant(self, test_ed25519_pem, monkeypatch):
        """All providers return 'Ed25519' for algorithm."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', test_ed25519_pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        assert provider.get_algorithm() == 'Ed25519'
