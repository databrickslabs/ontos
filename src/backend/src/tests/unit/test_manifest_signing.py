"""Tests for Ed25519 manifest signing key providers.

ADR: docs/decisions/manifest-canonicalization-hashing-signing.md
Decision 7: Keys and key providers.
"""

import base64
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
    key_id_for,
    public_key_bytes_of,
)


def _generate_ed25519_pem():
    """Generate a PEM-encoded Ed25519 private key."""
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')


# LocalDevKeyProvider Tests

class TestLocalDevKeyProvider:
    """Tests for LocalDevKeyProvider."""

    def test_initialization_from_env_var(self, monkeypatch):
        """Provider initializes when MANIFEST_SIGNING_KEY_PEM is set."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        assert provider is not None

    def test_get_private_key(self, monkeypatch):
        """get_private_key returns an Ed25519PrivateKey."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        key = provider.get_private_key()
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, monkeypatch):
        """get_public_key_bytes returns the correct 32-byte public key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        pubkey1 = provider.get_public_key_bytes()
        pubkey2 = provider.get_public_key_bytes()
        assert len(pubkey1) == 32
        assert pubkey1 == pubkey2

    def test_get_key_id_format(self, monkeypatch):
        """get_key_id returns format 'ed25519:XXXXXXXXXXXXXXXX'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        key_id = provider.get_key_id()
        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_get_algorithm(self, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
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

    def test_initialization_from_file(self, monkeypatch):
        """Provider initializes from file when env var not set."""
        pem = _generate_ed25519_pem()
        with TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / 'key.pem'
            key_file.write_text(pem)
            monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
            monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_file))
            provider = LocalDevKeyProvider()
            assert provider is not None


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

    def test_get_private_key_success(self, monkeypatch):
        """get_private_key retrieves and decodes the key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)
        ws_client.secrets.get_secret.assert_called_once_with(
            scope='my-scope',
            key='my-key'
        )

    def test_get_private_key_bytes_response(self, monkeypatch):
        """get_private_key handles bytes response from API."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem.encode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_private_key_base64_response(self, monkeypatch):
        """get_private_key auto-decodes base64 if not PEM."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = base64.b64encode(pem.encode('utf-8')).decode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, monkeypatch):
        """get_public_key_bytes returns 32 bytes."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client)
        pubkey = provider.get_public_key_bytes()

        assert isinstance(pubkey, bytes)
        assert len(pubkey) == 32

    def test_get_key_id_format(self, monkeypatch):
        """get_key_id returns format 'ed25519:XXXXXXXXXXXXXXXX'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem
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

    def test_whitespace_handling(self, monkeypatch):
        """get_private_key handles whitespace around PEM."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = f'  {pem}  \n'
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

    def test_algorithm_constant(self, monkeypatch):
        """All providers return 'Ed25519' for algorithm."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider()
        assert provider.get_algorithm() == 'Ed25519'


def test_secret_scope_key_id_matches_the_adr_format(monkeypatch):
    """get_key_id on the secret-scope provider reads the key once per call, without recursing."""
    pem = _generate_ed25519_pem()
    monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
    monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
    ws_client = MagicMock()
    ws_client.secrets.get_secret.return_value = MagicMock(value=pem)

    provider = DatabricksSecretKeyProvider(ws_client)
    expected = key_id_for(public_key_bytes_of(provider.get_private_key()))

    assert provider.get_key_id() == expected
    assert expected.startswith('ed25519:') and len(expected) == len('ed25519:') + 16
