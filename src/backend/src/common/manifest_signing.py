"""Pluggable manifest signing key providers.

Supports multiple key storage backends for Ed25519 signing:
- LocalDevKeyProvider: For local development, reads PEM from settings or file
- DatabricksSecretKeyProvider: For production, reads PEM from UC Secrets

Keys are Ed25519 private keys in PEM format. Key material is never logged;
only key_id and algorithm are visible in logs.

ADR: docs/decisions/manifest-canonicalization-hashing-signing.md
- Algorithm: Ed25519
- key_id = "ed25519:" + first 16 hex characters of sha256(raw public key)
- Private keys never in DB/logs/Git
- Public key exposed for verification (I-14)
"""

import hashlib
import os
from abc import ABC, abstractmethod
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


def public_key_bytes_of(private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """The raw 32-byte Ed25519 public key of a private key."""
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )


def key_id_for(public_key_bytes: bytes) -> str:
    """The ADR's key id: "ed25519:" + the first 16 hex characters of sha256(public key)."""
    return f"ed25519:{hashlib.sha256(public_key_bytes).hexdigest()[:16]}"


class SigningKeyProvider(ABC):
    """Abstract base for Ed25519 manifest signing key providers.

    Implementations provide a private key for signing and expose the
    corresponding public key for verification. Key material is never logged;
    only key_id and algorithm are visible in logs.

    References:
    - ADR Decision 7: docs/decisions/manifest-canonicalization-hashing-signing.md
    """

    @abstractmethod
    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Get the Ed25519 private key for signing.

        Returns:
            ed25519.Ed25519PrivateKey: The private key object.

        Raises:
            KeyProviderError: If key cannot be retrieved or is invalid.
        """
        pass

    def get_key_id(self) -> str:
        """Get the unique identifier for this key (for rotation tracking).

        Computed as "ed25519:" + first 16 hex characters of sha256(public_key).
        This ensures key_id is stable for a given public key and follows
        ADR Decision 7.

        Returns:
            str: Key identifier in format "ed25519:XXXXXXXXXXXXXXXX".
        """
        return key_id_for(self.get_public_key_bytes())

    def get_public_key_bytes(self) -> bytes:
        """Get the raw 32-byte Ed25519 public key.

        Derived from the private key. Used for key_id computation and
        exposed for verification (I-14: manifest verification API).

        Returns:
            bytes: The raw public key (32 bytes).
        """
        return public_key_bytes_of(self.get_private_key())

    def get_algorithm(self) -> str:
        """Get the signing algorithm name.

        Returns:
            str: Always 'Ed25519' per ADR Decision 7.
        """
        return 'Ed25519'


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

    Use only in local development (ENV=LOCAL). This provider has no access
    controls and stores keys in process memory.

    ADR Decision 7: local PEM provider.
    """

    def __init__(self, settings: Settings):
        """Initialize provider by loading or generating the key.

        Args:
            settings: Application settings carrying the MANIFEST_SIGNING_KEY_* values.

        Raises:
            KeyProviderError: If key cannot be loaded or generated.
        """
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

        logger.info(
            'LocalDevKeyProvider initialized; key_id=%s',
            self.get_key_id()
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
            settings: Application settings carrying MANIFEST_SIGNING_SECRET_*

        Raises:
            KeyProviderError: If configuration is missing or invalid.
        """
        self._ws_client = workspace_client

        scope = settings.MANIFEST_SECRET_SCOPE
        if not scope:
            raise KeyProviderError(
                f'Databricks secret scope not configured. '
                f'Set MANIFEST_SECRET_SCOPE.',
                provider='DatabricksSecretKeyProvider'
            )

        key_name = settings.MANIFEST_SECRET_KEY
        if not key_name:
            raise KeyProviderError(
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
        """Retrieve the key from Databricks UC Secrets.

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


