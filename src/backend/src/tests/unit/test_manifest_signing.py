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

from src.common.api_errors import CodedValueError
from src.common.config import Settings
from src.common.manifest_signing import (
    SigningKey,
    SigningKeyProvider,
    LocalDevKeyProvider,
    DatabricksSecretKeyProvider,
    KeyProviderError,
    SigningKeyNotConfiguredError,
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


def _load(pem):
    return serialization.load_pem_private_key(pem.encode(), password=None)


@pytest.fixture
def local_env(monkeypatch):
    """Local development (ENV=LOCAL), the only environment the local provider runs in."""
    monkeypatch.setenv('ENV', 'LOCAL')


# LocalDevKeyProvider Tests

@pytest.mark.usefixtures('local_env')
class TestLocalDevKeyProvider:
    """Tests for LocalDevKeyProvider."""

    def test_initialization_from_env_var(self, monkeypatch):
        """Provider initializes when MANIFEST_SIGNING_KEY_PEM is set."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        assert provider is not None

    def test_get_private_key(self, monkeypatch):
        """get_private_key returns an Ed25519PrivateKey."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        key = provider.get_private_key()
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, monkeypatch):
        """The signing key carries the correct 32-byte public key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        pubkey1 = provider.get_signing_key().public_key_bytes
        pubkey2 = provider.get_signing_key().public_key_bytes
        assert len(pubkey1) == 32
        assert pubkey1 == pubkey2 == public_key_bytes_of(_load(pem))

    def test_get_key_id_format(self, monkeypatch):
        """The signing key's key_id has the format 'ed25519:XXXXXXXXXXXXXXXX'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        key_id = provider.get_signing_key().key_id
        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_get_algorithm(self, monkeypatch):
        """get_algorithm returns 'Ed25519'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        assert provider.get_algorithm() == 'Ed25519'

    def test_missing_key_file_is_created_with_mode_0600(self, monkeypatch, tmp_path):
        """ADR Decision 7: the local key is created with mode 0600 if missing."""
        key_path = tmp_path / 'nested' / 'dir' / 'key.pem'
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))
        provider = LocalDevKeyProvider(_settings())
        assert key_path.is_file()
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        # A second provider loads the same key from the file it created.
        again = LocalDevKeyProvider(_settings())
        assert again.get_signing_key().key_id == provider.get_signing_key().key_id

    def test_existing_key_file_is_never_overwritten(self, monkeypatch, tmp_path):
        """An existing key file is read as is, not regenerated."""
        pem = _generate_ed25519_pem()
        key_path = tmp_path / 'key.pem'
        key_path.write_text(pem)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))
        LocalDevKeyProvider(_settings())
        assert key_path.read_text() == pem

    def test_invalid_existing_key_file_is_not_replaced(self, monkeypatch, tmp_path):
        """A corrupt existing file raises and stays untouched."""
        key_path = tmp_path / 'key.pem'
        key_path.write_text('garbage')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))
        with pytest.raises(KeyProviderError):
            LocalDevKeyProvider(_settings())
        assert key_path.read_text() == 'garbage'

    def test_unwritable_key_location_raises_error(self, monkeypatch, tmp_path):
        """Raises KeyProviderError (not a raw OSError) when the key cannot be created."""
        blocker = tmp_path / 'file'
        blocker.write_text('x')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(blocker / 'key.pem'))
        with pytest.raises(KeyProviderError) as exc_info:
            LocalDevKeyProvider(_settings())
        assert exc_info.value.code == 'key_provider_error'

    def test_values_from_env_file_reach_the_local_provider(self, monkeypatch, tmp_path):
        """A key set only in the .env file used by Settings reaches the provider."""
        pem = _generate_ed25519_pem()
        env_file = tmp_path / 'test.env'
        env_file.write_text('MANIFEST_SIGNING_KEY_PEM="%s"\n' % pem.replace('\n', '\\n'))
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(tmp_path / 'unused.pem'))
        provider = LocalDevKeyProvider(_settings(env_file))
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        assert provider.get_signing_key().public_key_bytes == public_key_bytes_of(loaded)
        assert not (tmp_path / 'unused.pem').exists()

    def test_key_path_from_env_file_reaches_the_local_provider(self, monkeypatch, tmp_path):
        """MANIFEST_LOCAL_KEY_PATH set only in the .env file is honoured."""
        pem = _generate_ed25519_pem()
        key_file = tmp_path / 'from-env-file.pem'
        key_file.write_text(pem)
        env_file = tmp_path / 'test.env'
        env_file.write_text(f'MANIFEST_LOCAL_KEY_PATH={key_file}\n')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings(env_file))
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        assert provider.get_signing_key().public_key_bytes == public_key_bytes_of(loaded)

    def test_invalid_pem_raises_error(self, monkeypatch):
        """Raises KeyProviderError if PEM is invalid."""
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', 'not-a-valid-pem')
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
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
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
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
            monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_file))
            provider = LocalDevKeyProvider(_settings())
            assert provider is not None


# DatabricksSecretKeyProvider Tests

class TestDatabricksSecretKeyProvider:
    """Tests for DatabricksSecretKeyProvider."""

    def test_initialization_missing_scope(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SECRET_SCOPE not set."""
        monkeypatch.delenv('MANIFEST_SECRET_SCOPE', raising=False)
        monkeypatch.delenv('MANIFEST_SECRET_KEY', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretKeyProvider(ws_client, _settings())
        assert 'scope' in str(exc_info.value).lower()

    def test_initialization_missing_key(self, monkeypatch):
        """Raises KeyProviderError if MANIFEST_SECRET_KEY not set."""
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.delenv('MANIFEST_SECRET_KEY', raising=False)

        ws_client = MagicMock()
        with pytest.raises(KeyProviderError) as exc_info:
            DatabricksSecretKeyProvider(ws_client, _settings())
        assert 'secret' in str(exc_info.value).lower()

    def test_initialization_success(self, monkeypatch):
        """Provider initializes when config is set."""
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        assert provider is not None

    def test_get_private_key_success(self, monkeypatch):
        """get_private_key retrieves and decodes the key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = base64.b64encode(pem.encode('utf-8')).decode('utf-8')
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        key = provider.get_private_key()

        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_get_public_key_bytes(self, monkeypatch):
        """The signing key carries a 32-byte public key."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        pubkey = provider.get_signing_key().public_key_bytes

        assert isinstance(pubkey, bytes)
        assert len(pubkey) == 32

    def test_get_key_id_format(self, monkeypatch):
        """The signing key's key_id has the format 'ed25519:XXXXXXXXXXXXXXXX'."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        resp = MagicMock()
        resp.value = pem
        ws_client.secrets.get_secret.return_value = resp

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        key_id = provider.get_signing_key().key_id

        assert key_id.startswith('ed25519:')
        assert len(key_id) == len('ed25519:') + 16

    def test_empty_secret_raises_error(self, monkeypatch):
        """Raises KeyProviderError if secret is empty."""
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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

        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

        ws_client = MagicMock()
        ws_client.secrets.get_secret.side_effect = RuntimeError('API error')

        provider = DatabricksSecretKeyProvider(ws_client, _settings())
        with pytest.raises(KeyProviderError) as exc_info:
            provider.get_private_key()
        assert 'Failed to retrieve' in str(exc_info.value)

    def test_whitespace_handling(self, monkeypatch):
        """get_private_key handles whitespace around PEM."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')

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

    def test_algorithm_constant(self, monkeypatch, local_env):
        """All providers return 'Ed25519' for algorithm."""
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        monkeypatch.delenv('MANIFEST_LOCAL_KEY_PATH', raising=False)
        provider = LocalDevKeyProvider(_settings())
        assert provider.get_algorithm() == 'Ed25519'


def test_secret_scope_key_id_matches_the_adr_format(monkeypatch):
    """The secret-scope provider's key_id follows the ADR, from one secret read."""
    pem = _generate_ed25519_pem()
    monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
    monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')
    ws_client = MagicMock()
    ws_client.secrets.get_secret.return_value = MagicMock(value=pem)

    provider = DatabricksSecretKeyProvider(ws_client, _settings())
    expected = key_id_for(public_key_bytes_of(_load(pem)))

    assert provider.get_signing_key().key_id == expected
    assert ws_client.secrets.get_secret.call_count == 1
    assert expected.startswith('ed25519:') and len(expected) == len('ed25519:') + 16


def test_secret_scope_values_from_env_file_reach_the_databricks_provider(monkeypatch, tmp_path):
    """Scope and key name set only in the .env file used by Settings reach the provider."""
    pem = _generate_ed25519_pem()
    env_file = tmp_path / 'test.env'
    env_file.write_text(
        'MANIFEST_SECRET_SCOPE=file-scope\nMANIFEST_SECRET_KEY=file-key\n'
    )
    monkeypatch.delenv('MANIFEST_SECRET_SCOPE', raising=False)
    monkeypatch.delenv('MANIFEST_SECRET_KEY', raising=False)
    ws_client = MagicMock()
    ws_client.secrets.get_secret.return_value = MagicMock(value=pem)

    provider = DatabricksSecretKeyProvider(ws_client, _settings(env_file))
    provider.get_private_key()

    ws_client.secrets.get_secret.assert_called_once_with(scope='file-scope', key='file-key')


# One read binds the key to its key_id (review: stateful / rotating providers)

class _RotatingProvider(SigningKeyProvider):
    """A stateful provider that returns the next key on every read, as a rotation would."""

    def __init__(self, count=3):
        self.keys = [ed25519.Ed25519PrivateKey.generate() for _ in range(count)]
        self.reads = 0

    def get_private_key(self):
        key = self.keys[self.reads % len(self.keys)]
        self.reads += 1
        return key


def _verifies(public_key_bytes, signature, message):
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, message)
        return True
    except Exception:
        return False


class TestSigningKeyBinding:
    """The signature, key_id and public key of one operation come from the same key."""

    MESSAGE = b'ontos-manifest-v1:f1220abc'

    def test_rotating_provider_signature_and_key_id_come_from_one_read(self):
        provider = _RotatingProvider()

        key = provider.get_signing_key()
        signature = key.sign(self.MESSAGE)

        assert provider.reads == 1
        assert key.key_id == key_id_for(public_key_bytes_of(provider.keys[0]))
        assert key.public_key_bytes == public_key_bytes_of(provider.keys[0])
        assert _verifies(key.public_key_bytes, signature, self.MESSAGE)
        # The provider has moved on; the bound value has not.
        assert key.key_id == key_id_for(key.public_key_bytes)
        assert provider.reads == 1

    def test_rotating_provider_next_operation_uses_the_new_key(self):
        provider = _RotatingProvider()

        first = provider.get_signing_key()
        second = provider.get_signing_key()

        assert first.key_id != second.key_id
        assert second.key_id == key_id_for(public_key_bytes_of(provider.keys[1]))
        signature = second.sign(self.MESSAGE)
        assert _verifies(second.public_key_bytes, signature, self.MESSAGE)
        assert not _verifies(first.public_key_bytes, signature, self.MESSAGE)

    def test_provider_has_no_separate_key_id_or_public_key_getter(self):
        """A second, independent read is what let the signature and key_id diverge."""
        assert not hasattr(SigningKeyProvider, 'get_key_id')
        assert not hasattr(SigningKeyProvider, 'get_public_key_bytes')

    def test_rotated_secret_binds_each_read(self, monkeypatch):
        """A secret replaced between two reads: each signing key matches its own read."""
        old_pem, new_pem = _generate_ed25519_pem(), _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')
        ws_client = MagicMock()
        ws_client.secrets.get_secret.side_effect = [
            MagicMock(value=old_pem), MagicMock(value=new_pem),
        ]
        provider = DatabricksSecretKeyProvider(ws_client, _settings())

        key = provider.get_signing_key()
        signature = key.sign(self.MESSAGE)

        assert ws_client.secrets.get_secret.call_count == 1
        assert key.key_id == key_id_for(public_key_bytes_of(_load(old_pem)))
        assert _verifies(key.public_key_bytes, signature, self.MESSAGE)

        rotated = provider.get_signing_key()
        assert ws_client.secrets.get_secret.call_count == 2
        assert rotated.key_id == key_id_for(public_key_bytes_of(_load(new_pem)))
        assert _verifies(rotated.public_key_bytes, rotated.sign(self.MESSAGE), self.MESSAGE)

    def test_local_provider_binds_its_key_once(self, monkeypatch, local_env):
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)
        provider = LocalDevKeyProvider(_settings())

        key = provider.get_signing_key()

        assert provider.get_signing_key() is key
        assert key.private_key is provider.get_private_key()
        assert key.key_id == key_id_for(public_key_bytes_of(_load(pem)))
        assert _verifies(key.public_key_bytes, key.sign(self.MESSAGE), self.MESSAGE)

    def test_signing_key_repr_hides_the_private_key(self):
        key = SigningKey.from_private_key(ed25519.Ed25519PrivateKey.generate())
        assert 'private_key' not in repr(key)
        assert key.algorithm == 'Ed25519'


# Fail closed outside local development (review: no local-key fallback in production)

NON_LOCAL_ENVS = ['PROD', 'DEV', 'TEST']


def _assert_not_configured(exc_info):
    error = exc_info.value
    assert isinstance(error, CodedValueError)
    assert error.code == 'signing_key_not_configured'
    assert error.__cause__ is None  # no exception text carried along


class TestFailClosedOutsideLocalDev:
    """Without ENV=LOCAL there is no local key: no generation, no PEM, no key file."""

    @pytest.mark.parametrize('env', NON_LOCAL_ENVS)
    def test_missing_configuration_fails_closed_and_creates_no_key(
        self, monkeypatch, tmp_path, env
    ):
        key_path = tmp_path / 'nested' / 'key.pem'
        monkeypatch.setenv('ENV', env)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))

        with pytest.raises(SigningKeyNotConfiguredError) as exc_info:
            LocalDevKeyProvider(_settings())

        _assert_not_configured(exc_info)
        assert not key_path.exists()
        assert not key_path.parent.exists()

    def test_default_env_is_production_and_fails_closed(self, monkeypatch, tmp_path):
        """ENV unset means PROD (Settings default), so it fails closed too."""
        key_path = tmp_path / 'key.pem'
        monkeypatch.delenv('ENV', raising=False)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))

        with pytest.raises(SigningKeyNotConfiguredError) as exc_info:
            LocalDevKeyProvider(Settings(_env_file=None))

        _assert_not_configured(exc_info)
        assert not key_path.exists()

    def test_pem_setting_is_not_used_outside_local_dev(self, monkeypatch):
        pem = _generate_ed25519_pem()
        monkeypatch.setenv('ENV', 'PROD')
        monkeypatch.setenv('MANIFEST_SIGNING_KEY_PEM', pem)

        with pytest.raises(SigningKeyNotConfiguredError) as exc_info:
            LocalDevKeyProvider(_settings())

        _assert_not_configured(exc_info)
        assert 'BEGIN' not in str(exc_info.value)

    def test_existing_key_file_is_not_used_outside_local_dev(self, monkeypatch, tmp_path):
        key_path = tmp_path / 'key.pem'
        key_path.write_text(_generate_ed25519_pem())
        monkeypatch.setenv('ENV', 'PROD')
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))

        with pytest.raises(SigningKeyNotConfiguredError) as exc_info:
            LocalDevKeyProvider(_settings())

        _assert_not_configured(exc_info)

    @pytest.mark.parametrize('unset', ['MANIFEST_SECRET_SCOPE', 'MANIFEST_SECRET_KEY'])
    def test_missing_secret_configuration_fails_closed(self, monkeypatch, unset):
        monkeypatch.setenv('ENV', 'PROD')
        monkeypatch.setenv('MANIFEST_SECRET_SCOPE', 'my-scope')
        monkeypatch.setenv('MANIFEST_SECRET_KEY', 'my-key')
        monkeypatch.delenv(unset)
        ws_client = MagicMock()

        with pytest.raises(SigningKeyNotConfiguredError) as exc_info:
            DatabricksSecretKeyProvider(ws_client, _settings())

        _assert_not_configured(exc_info)
        ws_client.secrets.get_secret.assert_not_called()

    @pytest.mark.parametrize('env', ['LOCAL', 'local'])
    def test_local_dev_still_creates_the_missing_key(self, monkeypatch, tmp_path, env):
        """Local development keeps its behavior: a missing key file is created (0600)."""
        key_path = tmp_path / 'nested' / 'key.pem'
        monkeypatch.setenv('ENV', env)
        monkeypatch.delenv('MANIFEST_SIGNING_KEY_PEM', raising=False)
        monkeypatch.setenv('MANIFEST_LOCAL_KEY_PATH', str(key_path))

        provider = LocalDevKeyProvider(_settings())

        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        assert provider.get_signing_key().key_id == key_id_for(
            public_key_bytes_of(_load(key_path.read_text()))
        )
