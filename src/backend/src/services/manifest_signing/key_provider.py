"""Pluggable manifest signing key providers.

Supports multiple key storage backends:
- LocalFileKeyProvider: For local development only, reads from environment
- DatabricksSecretScopeKeyProvider: For production, reads from UC Secrets

Keys are Ed25519 private keys encoded as base64. Key material is never
logged; only key_id and algorithm are logged.
"""

import base64
import os
from abc import ABC, abstractmethod
from typing import Optional

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger

logger = get_logger(__name__)


class KeyProviderError(CodedValueError):
    """Error retrieving signing key from provider."""

    code = 'key_provider_error'

    def __init__(self, message: str, provider: str = '', **params):
        super().__init__(message, provider=provider, **params)


class SigningKeyProvider(ABC):
    """Abstract base for manifest signing key providers.

    Implementations must provide an Ed25519 private key for signing
    manifests. Key material must never be logged; only key_id and
    algorithm may be logged.
    """

    @abstractmethod
    def get_signing_key(self) -> bytes:
        """Get the Ed25519 private key for signing.

        Returns:
            bytes: The 32-byte Ed25519 private key.

        Raises:
            KeyProviderError: If key cannot be retrieved.
        """
        pass

    @abstractmethod
    def get_key_id(self) -> str:
        """Get the unique identifier for this key (for rotation tracking).

        Returns:
            str: A stable key ID (e.g., ISO datetime when key was created).
        """
        pass

    def get_algorithm(self) -> str:
        """Get the signing algorithm name.

        Returns:
            str: Always 'Ed25519' for current implementations.
        """
        return 'Ed25519'


class LocalFileKeyProvider(SigningKeyProvider):
    """Development-only key provider that reads from environment.

    The key is provided as a base64-encoded Ed25519 private key in the
    MANIFEST_SIGNING_KEY environment variable. The key_id is read from
    MANIFEST_SIGNING_KEY_ID (defaults to "local-dev" if not set).

    Use only in local development (ENV=LOCAL). This provider has no
    access checks and stores keys in process memory.
    """

    ENV_KEY = 'MANIFEST_SIGNING_KEY'
    ENV_KEY_ID = 'MANIFEST_SIGNING_KEY_ID'
    DEFAULT_KEY_ID = 'local-dev'

    def __init__(self):
        """Initialize the provider.

        Raises:
            KeyProviderError: If MANIFEST_SIGNING_KEY is not set.
        """
        key_b64 = os.environ.get(self.ENV_KEY)
        if not key_b64:
            raise KeyProviderError(
                f'Manifest signing key not found. Set {self.ENV_KEY} '
                f'to a base64-encoded Ed25519 private key.',
                provider='LocalFileKeyProvider'
            )

        try:
            self._key = base64.b64decode(key_b64)
        except Exception as e:
            raise KeyProviderError(
                f'Failed to decode {self.ENV_KEY}: {type(e).__name__}',
                provider='LocalFileKeyProvider'
            ) from e

        if len(self._key) != 32:
            raise KeyProviderError(
                f'{self.ENV_KEY} must be 32 bytes when decoded (got {len(self._key)})',
                provider='LocalFileKeyProvider'
            )

        self._key_id = os.environ.get(self.ENV_KEY_ID, self.DEFAULT_KEY_ID)
        logger.info(
            'LocalFileKeyProvider initialized; key_id=%s',
            self._key_id
        )

    def get_signing_key(self) -> bytes:
        """Get the key from environment."""
        return self._key

    def get_key_id(self) -> str:
        """Get the key ID from environment or default."""
        return self._key_id


class DatabricksSecretScopeKeyProvider(SigningKeyProvider):
    """Production key provider using Databricks UC Secrets.

    The key is stored in a Databricks workspace secret scope:
    - Scope: MANIFEST_SIGNING_SECRET_SCOPE env var (required)
    - Key: MANIFEST_SIGNING_SECRET_KEY env var (required)
    - Key ID: MANIFEST_SIGNING_KEY_ID env var (required for rotation tracking)

    The secret value must be a base64-encoded Ed25519 private key (32 bytes).

    Access to the secret scope requires:
    - Workspace admin privileges or explicit secret scope access
    - Valid WorkspaceClient credential
    """

    ENV_SCOPE = 'MANIFEST_SIGNING_SECRET_SCOPE'
    ENV_KEY = 'MANIFEST_SIGNING_SECRET_KEY'
    ENV_KEY_ID = 'MANIFEST_SIGNING_KEY_ID'

    def __init__(self, workspace_client):
        """Initialize the provider with a WorkspaceClient.

        Args:
            workspace_client: databricks.sdk.WorkspaceClient instance

        Raises:
            KeyProviderError: If configuration is missing or invalid.
        """
        self._ws_client = workspace_client

        scope = os.environ.get(self.ENV_SCOPE)
        if not scope:
            raise KeyProviderError(
                f'Databricks secret scope not configured. '
                f'Set {self.ENV_SCOPE}.',
                provider='DatabricksSecretScopeKeyProvider'
            )

        key_name = os.environ.get(self.ENV_KEY)
        if not key_name:
            raise KeyProviderError(
                f'Databricks secret name not configured. '
                f'Set {self.ENV_KEY}.',
                provider='DatabricksSecretScopeKeyProvider'
            )

        key_id = os.environ.get(self.ENV_KEY_ID)
        if not key_id:
            raise KeyProviderError(
                f'Key ID not configured for rotation tracking. '
                f'Set {self.ENV_KEY_ID}.',
                provider='DatabricksSecretScopeKeyProvider'
            )

        self._scope = scope
        self._key_name = key_name
        self._key_id = key_id

        logger.info(
            'DatabricksSecretScopeKeyProvider initialized; '
            'scope=%s key_id=%s',
            self._scope,
            self._key_id
        )

    def get_signing_key(self) -> bytes:
        """Retrieve the key from Databricks UC Secrets.

        Returns:
            bytes: The 32-byte Ed25519 private key.

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
                f'Failed to retrieve signing key from UC Secrets: {type(e).__name__}',
                provider='DatabricksSecretScopeKeyProvider'
            ) from e

        if not resp or not resp.value:
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} is empty',
                provider='DatabricksSecretScopeKeyProvider'
            )

        # Normalize response (may be bytes or str)
        raw = resp.value
        if isinstance(raw, bytes):
            text = raw.decode('utf-8')
        else:
            text = str(raw)

        try:
            key_bytes = base64.b64decode(text.strip())
        except Exception as e:
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} is not valid base64: '
                f'{type(e).__name__}',
                provider='DatabricksSecretScopeKeyProvider'
            ) from e

        if len(key_bytes) != 32:
            raise KeyProviderError(
                f'Secret {self._scope}/{self._key_name} must be 32 bytes '
                f'when decoded (got {len(key_bytes)})',
                provider='DatabricksSecretScopeKeyProvider'
            )

        logger.debug(
            'Retrieved signing key from UC Secrets; key_id=%s',
            self._key_id
        )
        return key_bytes

    def get_key_id(self) -> str:
        """Get the configured key ID for rotation tracking."""
        return self._key_id
