"""Tests for Ed25519 manifest signing key providers.

ADR: docs/decisions/manifest-canonicalization-hashing-signing.md
Decision 7: Keys and key providers.
"""

import base64
import os
import stat
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.common.config import Settings
from src.common.manifest_signing import (
    SigningKeyProvider,
    LocalDevKeyProvider,
    DatabricksSecretKeyProvider,
    KeyProviderError,
    key_id_for,
    public_key_bytes_of,
)


def _settings(env_file=None):
    """Settings built fresh from the process environment (and an optional env file)."""
    return Settings(_env_file=env_file)


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
        provider = LocalDevKeyProvider(_settings())
        assert provider is not None

    def test_get_private_key(self, monkeypatch):
        """get_private_key returns an Ed25519PrivateKey."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        key = provider.get_private_key()
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, monkeypatch):
        """get_public_key_bytes returns the correct 32-byte public key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        pubkey1 = provider.get_public_key_bytes()
        pubkey2 = provider.get_public_key_bytes()
        assert len(pubkey1) == 32
        assert pubkey1 == pubkey2

    def test_get_key_id_format(self, monkeypatch):
        """get_key_id returns format 'ed25519:XXXXXXXXXXXXXXXX'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        key_id = provider.get_key_id()
        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_get_algorithm(self, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        assert provider.get_algorithm() == 'Ed25519'

    def test_missing_key_file_is_created_with_mode_0600(self, monkeypatch, tmp_path):
        """ADR Decision 7: the local key is created with mode 0600 if missing."""
        key_path = tmp_path / 'nested' / 'dir' / 'key.pem'
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_path))
        provider = LocalDevKeyProvider(_settings())
        assert key_path.is_file()
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        # A second provider loads the same key from the file it created.
        again = LocalDevKeyProvider(_settings())
        assert again.get_key_id() == provider.get_key_id()

    def test_existing_key_file_is_never_overwritten(self, monkeypatch, tmp_path):
        """An existing key file is read as is, not regenerated."""
        pem = _generate_ed25519_pem()
        key_path = tmp_path / 'key.pem'
        key_path.write_text(pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_path))
        LocalDevKeyProvider(_settings())
        assert key_path.read_text() == pem

    def test_invalid_existing_key_file_is_not_replaced(self, monkeypatch, tmp_path):
        """A corrupt existing file raises and stays untouched."""
        key_path = tmp_path / 'key.pem'
        key_path.write_text('garbage')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_path))
        with pytest.raises(KeyProviderError):
            LocalDevKeyProvider(_settings())
        assert key_path.read_text() == 'garbage'

    def test_unwritable_key_location_raises_error(self, monkeypatch, tmp_path):
        """Raises KeyProviderError (not a raw OSError) when the key cannot be created."""
        blocker = tmp_path / 'file'
        blocker.write_text('x')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(blocker / 'key.pem'))
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider(_settings())
        assert exc_info.value.code == 'key_provider_error'

    def test_values_from_env_file_reach_the_local_provider(self, monkeypatch, tmp_path):
        """A key set only in the .env file used by Settings reaches the provider."""
        pem = _generate_ed25519_pem()
        env_file = tmp_path / 'test.env'
        env_file.write_text('MANIFEST_SIGNING_KEY_PEM="%s"\n' % pem.replace('\n', '\\n'))
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(tmp_path / 'unused.pem'))
        provider = LocalDevKeyProvider(_settings(env_file))
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        assert provider.get_public_key_bytes() == public_key_bytes_of(loaded)
        assert not (tmp_path / 'unused.pem').exists()

    def test_key_path_from_env_file_reaches_the_local_provider(self, monkeypatch, tmp_path):
        """MANIFEST_SIGNING_KEY_PATH set only in the .env file is honoured."""
        pem = _generate_ed25519_pem()
        key_file = tmp_path / 'from-env-file.pem'
        key_file.write_text(pem)
        env_file = tmp_path / 'test.env'
        env_file.write_text(f'MANIFEST_SIGNING_KEY_PATH={key_file}\n')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings(env_file))
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        assert provider.get_public_key_bytes() == public_key_bytes_of(loaded)

    def test_invalid_pem_raises_error(self, monkeypatch):
        """Raises KeyProviderError if PEM is invalid."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', 'not-a-valid-pem')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PATH', raising=False)
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider(_settings())
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
            LocalDevKeyProvider(_settings())
        assert 'not Ed25519' in str(exc_info.value)

    def test_initialization_from_file(self, monkeypatch):
        """Provider initializes from file when env var not set."""
        pem = _generate_ed25519_pem()
        with TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / 'key.pem'
            key_file.write_text(pem)
            monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
            monkeypatch.setenv('MANIFEST_SIGNING_KEY_PATH', str(key_file))
            provider = LocalDevKeyProvider(_settings())
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
            DatabricksSecretKeyProvider(ws_client, _settings())
        assert 'scope' in str(exc_info.value).lower()

    def test_initialization_missing_key(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SIGNING_SECRET_KEY not set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretKeyProvider(ws_client, _settings())
        assert 'secret' in str(exc_info.value).lower()

    def test_initialization_success(self, monkeypatch):
        """Provider initializes when config is set."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'not Ed25519' in str(exc_info.value)

    def test_api_error_raises_error(self, monkeypatch):
        """Raises KeyProviderError if secrets API call fails."""
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        ws_client.secrets.get_secret.side_effect = RuntimeError('API error')

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
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
        provider = LocalDevKeyProvider(_settings())
        assert provider.get_algorithm() == 'Ed25519'


def test_secret_scope_key_id_matches_the_adr_format(monkeypatch):
    """get_key_id on the secret-scope provider reads the key once per call, without recursing."""
    pem = _generate_ed25519_pem()
    monkeypatch.setenv('MANIFEST_SIGNING_SECRET_SCOPE', 'my-scope')
    monkeypatch.setenv('MANIFEST_SIGNING_SECRET_KEY', 'my-key')
    ws_client = MagicMock()
    ws_client.secrets.get_secret.return_value = MagicMock(value=pem)

    provider = DatabricksSecretKeyProvider(ws_client, _settings())
    expected = key_id_for(public_key_bytes_of(provider.get_private_key()))

    assert provider.get_key_id() == expected
    assert expected.startswith('ed25519:') and len(expected) == len('ed25519:') + 16


def test_secret_scope_values_from_env_file_reach_the_databricks_provider(monkeypatch, tmp_path):
    """Scope and key name set only in the .env file used by Settings reach the provider."""
    pem = _generate_ed25519_pem()
    env_file = tmp_path / 'test.env'
    env_file.write_text(
        'MANIFEST_SIGNING_SECRET_SCOPE=file-scope\nMANIFEST_SIGNING_SECRET_KEY=file-key\n'
    )
    monkeypatch.delenv('MANIFEST_SIGNING_SECRET_SCOPE', raising=False)
    monkeypatch.delenv('MANIFEST_SIGNING_SECRET_KEY', raising=False)
    ws_client = MagicMock()
    ws_client.secrets.get_secret.return_value = MagicMock(value=pem)

    provider = DatabricksSecretKeyProvider(ws_client, _settings(env_file))
    provider.get_private_key()

    ws_client.secrets.get_secret.assert_called_once_with(scope='file-scope', key='file-key')
