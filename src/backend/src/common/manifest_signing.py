"""Pluggable manifest signing key providers.

Supports multiple key storage backends for Ed25519 signing:
- LocalDevKeyProvider: For local development (ENV=LOCAL), reads PEM from settings or file
- DatabricksSecretKeyProvider: For deployments, reads PEM from UC Secrets

Keys are Ed25519 private keys in PEM format. Key material is never logged;
only key_id and algorithm are visible in logs.

A signing operation reads the key once with ``SigningKeyProvider.get_signing_key()``
and uses the returned ``SigningKey`` for the signature, the advertised ``key_id``
and the public key, so they always belong to the same key, even when the
provider rotates between two reads.

ADR: docs/decisions/manifest-canonicalization-hashing-signing.md
- Algorithm: Ed25519
- key_id = "ed25519:" + first 16 hex characters of sha256(raw public key)
- Private keys never in DB/logs/Git
- Public key exposed for verification (I-14)
"""

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.common.api_errors import CodedValueError
from src.common.config import Settings
from src.common.logging import get_logger

logger = get_logger(__name__)


class KeyProviderError(CodedValueError):
    """Error retrieving or validating signing key."""

    code = 'key_provider_error'

    def __init__(self, message: str, provider: str = '', **params):
        super().__init__(message, provider=provider, **params)


class SigningKeyNotConfiguredError(KeyProviderError):
    """No usable signing key configuration for this environment (fail closed).

    Raised when the Databricks secret isn't configured, and when the local
    provider is used outside local development, where it never falls back to a
    key file or creates a key.
    """

    code = 'signing_key_not_configured'


def is_local_env(settings: Settings) -> bool:
    """True for local development (``ENV`` starting with ``LOCAL``), as elsewhere in the app."""
    return str(settings.ENV or '').upper().startswith('LOCAL')


def public_key_bytes_of(private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """The raw 32-byte Ed25519 public key of a private key."""
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )


def key_id_for(public_key_bytes: bytes) -> str:
    """The ADR's key id: "ed25519:" + the first 16 hex characters of sha256(public key)."""
    return f"ed25519:{hashlib.sha256(public_key_bytes).hexdigest()[:16]}"


ALGORITHM = 'Ed25519'


@dataclass(frozen=True)
class SigningKey:
    """One Ed25519 key read from a provider, bound to its public key and ``key_id``.

    Built from a single read of the private key, so the signature made with
    ``sign`` and the advertised ``key_id`` / ``public_key_bytes`` can't come
    from different keys. Hold one instance for a whole signing operation.
    """

    private_key: ed25519.Ed25519PrivateKey = field(repr=False, compare=False)
    public_key_bytes: bytes
    key_id: str
    algorithm: str = ALGORITHM

    @classmethod
    def from_private_key(cls, private_key: ed25519.Ed25519PrivateKey) -> 'SigningKey':
        """Bind a private key to its raw public key and ADR ``key_id``."""
        public_key = public_key_bytes_of(private_key)
        return cls(private_key=private_key, public_key_bytes=public_key,
                   key_id=key_id_for(public_key))

    def sign(self, message: bytes) -> bytes:
        """The Ed25519 signature of ``message`` with this key."""
        return self.private_key.sign(message)


class SigningKeyProvider(ABC):
    """Abstract base for Ed25519 manifest signing key providers.

    Implementations load the private key (``get_private_key``); callers sign
    through ``get_signing_key``, which reads it once and binds it to its public
    key and ``key_id``. There is deliberately no separate ``key_id`` or public
    key getter: a second read could return another key when the provider is
    stateful or the secret was rotated in between. Key material is never
    logged; only key_id and algorithm are visible in logs.

    References:
    - ADR Decision 7: docs/decisions/manifest-canonicalization-hashing-signing.md
    """

    @abstractmethod
    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Load the Ed25519 private key (one read; may differ between calls).

        Callers that sign use ``get_signing_key`` instead.

        Returns:
            ed25519.Ed25519PrivateKey: The private key object.

        Raises:
            KeyProviderError: If key cannot be retrieved or is invalid.
        """
        pass

    def get_signing_key(self) -> SigningKey:
        """Read the key once and bind it to its public key and ``key_id``.

        ``key_id`` is "ed25519:" + the first 16 hex characters of
        sha256(raw public key) (ADR Decision 7). Use the returned value for the
        signature, the advertised ``key_id`` and the public key of one signing
        operation; call again for the next operation to pick up a rotation.

        Raises:
            KeyProviderError: If key cannot be retrieved or is invalid.
        """
        return SigningKey.from_private_key(self.get_private_key())

    def get_algorithm(self) -> str:
        """Get the signing algorithm name.

        Returns:
            str: Always 'Ed25519' per ADR Decision 7.
        """
        return ALGORITHM


class LocalDevKeyProvider(SigningKeyProvider):
    """Development-only key provider using a local PEM file or a PEM setting.

    Reads an Ed25519 private key in PEM format from the application settings
    (``Settings``, which merges the process environment and the ``.env`` file):
    1. ``MANIFEST_SIGNING_KEY_PEM`` (if set)
    2. The file at ``MANIFEST_LOCAL_KEY_PATH`` (default
       ``~/.ontos/manifest_signing_ed25519.pem``)

    If neither is present, a new key is generated and written to the file with
    mode 0600 (parent directories are created; an existing file is never
    overwritten).

    Only in local development (``ENV`` starting with ``LOCAL``, the check the
    app uses for its other dev-only behavior). In any other environment the
    provider fails closed with ``SigningKeyNotConfiguredError``: it reads no
    PEM or key file and creates no key, so a deployment without the Databricks
    secret configuration can't sign with a local key. This provider has no
    access controls and keeps the key in process memory.

    ADR Decision 7: local PEM provider ("for development and tests only").
    """

    def __init__(self, settings: Settings):
        """Initialize provider by loading or generating the key.

        Args:
            settings: Application settings carrying ``ENV``,
                ``MANIFEST_SIGNING_KEY_PEM`` and ``MANIFEST_LOCAL_KEY_PATH``.

        Raises:
            SigningKeyNotConfiguredError: If ``ENV`` isn't local development.
            KeyProviderError: If key cannot be loaded or generated.
        """
        if not is_local_env(settings):
            logger.error(
                'Manifest signing: the local key provider is disabled outside ENV=LOCAL '
                '(ENV=%s); configure MANIFEST_SECRET_SCOPE / MANIFEST_SECRET_KEY',
                settings.ENV,
            )
            raise SigningKeyNotConfiguredError(
                'The local manifest signing key is only available in local development '
                '(ENV=LOCAL). Configure the Databricks secret '
                '(MANIFEST_SECRET_SCOPE / MANIFEST_SECRET_KEY).',
                provider='LocalDevKeyProvider',
            )

        key_pem = settings.MANIFEST_SIGNING_KEY_PEM
        if not key_pem:
            key_path = Path(settings.MANIFEST_LOCAL_KEY_PATH).expanduser()
            try:
                if not key_path.exists():
                    self._create_key_file(key_path)
                key_pem = key_path.read_text(encoding='utf-8')
            except KeyProviderError:
                raise
            except Exception as e:
                raise KeyProviderError(
                    f'Failed to read key file {key_path}: {type(e).__name__}',
                    provider='LocalDevKeyProvider'
                ) from e

        # Load and validate the private key
        try:
            self._private_key = serialization.load_pem_private_key(
                key_pem.encode('utf-8'),
                password=None
            )
        except Exception as e:
            raise KeyProviderError(
                f'Failed to load Ed25519 private key from PEM: {type(e).__name__}',
                provider='LocalDevKeyProvider'
            ) from e

        if not isinstance(self._private_key, ed25519.Ed25519PrivateKey):
            raise KeyProviderError(
                f'Key is not Ed25519 (got {type(self._private_key).__name__})',
                provider='LocalDevKeyProvider'
            )
        self._signing_key = SigningKey.from_private_key(self._private_key)

        logger.info(
            'LocalDevKeyProvider initialized; key_id=%s',
            self._signing_key.key_id
        )

    @staticmethod
    def _create_key_file(key_path: Path) -> None:
        """Generate an Ed25519 key and write it to key_path with mode 0600.

        Never overwrites an existing file: if another process created it first,
        the existing file is kept.
        """
        pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(fd, 'wb') as f:
            f.write(pem)
        logger.info('Generated a new local manifest signing key at %s', key_path)

    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Return the loaded private key."""
        return self._private_key

    def get_signing_key(self) -> SigningKey:
        """The key loaded at start-up, bound to its ``key_id`` once."""
        return self._signing_key


class DatabricksSecretKeyProvider(SigningKeyProvider):
    """Production key provider using Databricks UC Secrets.

    Retrieves an Ed25519 private key in PEM format from a Databricks
    workspace secret:
    - Scope: MANIFEST_SECRET_SCOPE (required)
    - Key: MANIFEST_SECRET_KEY (required)

    The secret value must contain a PEM-encoded Ed25519 private key
    (optionally base64-encoded by the API; decoding is automatic).

    Access requires:
    - Workspace admin privileges or explicit secret scope access
    - Valid WorkspaceClient credential (injected at startup)

    ADR Decision 7: Databricks Secrets provider.
    """

    def __init__(self, workspace_client, settings: Settings):
        """Initialize the provider with a WorkspaceClient and the settings.

        Args:
            workspace_client: databricks.sdk.WorkspaceClient instance
            settings: Application settings carrying MANIFEST_SECRET_SCOPE and
                MANIFEST_SECRET_KEY

        Raises:
            SigningKeyNotConfiguredError: If the scope or the key name is missing.
        """
        self._ws_client = workspace_client

        scope = settings.MANIFEST_SECRET_SCOPE
        if not scope:
            raise SigningKeyNotConfiguredError(
                f'Databricks secret scope not configured. '
                f'Set MANIFEST_SECRET_SCOPE.',
                provider='DatabricksSecretKeyProvider'
            )

        key_name = settings.MANIFEST_SECRET_KEY
        if not key_name:
            raise SigningKeyNotConfiguredError(
                f'Databricks secret name not configured. '
                f'Set MANIFEST_SECRET_KEY.',
                provider='DatabricksSecretKeyProvider'
            )

        self._scope = scope
        self._key_name = key_name

        logger.info(
            'DatabricksSecretKeyProvider initialized; scope=%s',
            self._scope
        )

    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Retrieve the key from Databricks UC Secrets (one secret read per call).

        Not cached: a rotated secret is used from the next call on (ADR
        Decision 7, "a new key_id on first use"). ``get_signing_key`` binds the
        key of one read to its ``key_id``.

        Returns:
            ed25519.Ed25519PrivateKey: The loaded private key.

        Raises:
            KeyProviderError: If secret cannot be retrieved or is invalid.
        """
        try:
            resp = self._ws_client.secrets.get_secret(
                scope=self._scope,
                key=self._key_name
            )
        except Exception as e:
            logger.error(
                'Failed to retrieve secret from scope=%s key=%s: %s',
                self._scope,
                self._key_name,
                type(e).__name__
            )
            raise KeyProviderError(
                f'Failed to retrieve signing key from UC Secrets: '
                f'{type(e).__name__}',
                provider='DatabricksSecretKeyProvider'
            ) from e

        if not resp or not resp.value:
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} is empty',
                provider='DatabricksSecretKeyProvider'
            )

        # Normalize response (may be bytes or str)
        raw = resp.value
        if isinstance(raw, bytes):
            text = raw.decode('utf-8')
        else:
            text = str(raw)

        text = text.strip()

        # Try to decode base64 if it doesn't start with PEM header
        if not text.startswith('-----BEGIN'):
            import base64
            try:
                text = base64.b64decode(text).decode('utf-8')
            except Exception:
                # Not base64, try as-is
                pass

        # Load and validate
        try:
            private_key = serialization.load_pem_private_key(
                text.encode('utf-8'),
                password=None
            )
        except Exception as e:
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} is not valid Ed25519 PEM: '
                f'{type(e).__name__}',
                provider='DatabricksSecretKeyProvider'
            ) from e

        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} is not Ed25519 '
                f'(got {type(private_key).__name__})',
                provider='DatabricksSecretKeyProvider'
            )

        logger.debug(
            'Retrieved signing key from UC Secrets; key_id=%s',
            key_id_for(public_key_bytes_of(private_key))
        )
        return private_key


