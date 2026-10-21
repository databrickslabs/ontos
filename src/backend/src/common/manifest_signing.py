"""Pluggable manifest signing key providers.

Supports multiple key storage backends for Ed25519 signing:
- LocalDevKeyProvider: For local development, reads PEM from environment or file
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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger

logger = get_logger(__name__)


class KeyProviderError(CodedValueError):
    """Error retrieving or validating signing key."""

    code = 'key_provider_error'

    def __init__(self, message: str, provider: str = '', **params):
        super().__init__(message, provider=provider, **params)


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
        public_key_bytes = self.get_public_key_bytes()
        digest = hashlib.sha256(public_key_bytes).hexdigest()
        return f"ed25519:{digest[:16]}"

    def get_public_key_bytes(self) -> bytes:
        """Get the raw 32-byte Ed25519 public key.

        Derived from the private key. Used for key_id computation and
        exposed for verification (I-14: manifest verification API).

        Returns:
            bytes: The raw public key (32 bytes).
        """
        private_key = self.get_private_key()
        public_key = private_key.public_key()
        return public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

    def get_algorithm(self) -> str:
        """Get the signing algorithm name.

        Returns:
            str: Always 'Ed25519' per ADR Decision 7.
        """
        return 'Ed25519'


class LocalDevKeyProvider(SigningKeyProvider):
    """Development-only key provider using local PEM file or environment.

    Reads an Ed25519 private key in PEM format from:
    1. Environment variable MANIFEST_SIGNING_KEY_PEM (if set)
    2. File at MANIFEST_SIGNING_KEY_PATH (default ~/.ontos/manifest_signing_ed25519.pem)

    If the file doesn't exist and environment variable is not set, raises
    KeyProviderError. File is created with mode 0600 if needed (outside scope
    of this provider).

    Use only in local development (ENV=LOCAL). This provider has no access
    controls and stores keys in process memory.

    ADR Decision 7: local PEM provider.
    """

    def __init__(self):
        """Initialize provider by loading or generating the key.

        Raises:
            KeyProviderError: If key cannot be loaded or generated.
        """
        import os
        # Try environment variable first
        key_pem = os.environ.get('MANIFEST_SIGNING_KEY_PEM')
        if not key_pem:
            # Fall back to file path from environment or default
            key_path_str = os.environ.get(
                'MANIFEST_SIGNING_KEY_PATH',
                '~/.ontos/manifest_signing_ed25519.pem'
            )
            key_path = Path(key_path_str).expanduser()
            if key_path.exists():
                try:
                    key_pem = key_path.read_text(encoding='utf-8')
                except Exception as e:
                    raise KeyProviderError(
                        f'Failed to read key file {key_path}: {type(e).__name__}',
                        provider='LocalDevKeyProvider'
                    ) from e
            else:
                raise KeyProviderError(
                    f'Manifest signing key not found. Set MANIFEST_SIGNING_KEY_PEM '
                    f'or create {key_path} with an Ed25519 private key in PEM format.',
                    provider='LocalDevKeyProvider'
                )

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

    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Return the loaded private key."""
        return self._private_key


class DatabricksSecretKeyProvider(SigningKeyProvider):
    """Production key provider using Databricks UC Secrets.

    Retrieves an Ed25519 private key in PEM format from a Databricks
    workspace secret:
    - Scope: MANIFEST_SIGNING_SECRET_SCOPE (required)
    - Key: MANIFEST_SIGNING_SECRET_KEY (required)

    The secret value must contain a PEM-encoded Ed25519 private key
    (optionally base64-encoded by the API; decoding is automatic).

    Access requires:
    - Workspace admin privileges or explicit secret scope access
    - Valid WorkspaceClient credential (injected at startup)

    ADR Decision 7: Databricks Secrets provider.
    """

    def __init__(self, workspace_client):
        """Initialize the provider with a WorkspaceClient.

        Args:
            workspace_client: databricks.sdk.WorkspaceClient instance

        Raises:
            KeyProviderError: If configuration is missing or invalid.
        """
        import os
        self._ws_client = workspace_client

        scope = os.environ.get('MANIFEST_SIGNING_SECRET_SCOPE')
        if not scope:
            raise KeyProviderError(
                f'Databricks secret scope not configured. '
                f'Set MANIFEST_SIGNING_SECRET_SCOPE.',
                provider='DatabricksSecretKeyProvider'
            )

        key_name = os.environ.get('MANIFEST_SIGNING_SECRET_KEY')
        if not key_name:
            raise KeyProviderError(
                f'Databricks secret name not configured. '
                f'Set MANIFEST_SIGNING_SECRET_KEY.',
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
            self.get_key_id()
        )
        return private_key


