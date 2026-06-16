"""Shared factory for creating OpenAI clients pointed at Databricks serving endpoints.

Every LLM consumer in the codebase (LLMService, LLMSearchManager,
OntologyGeneratorManager) should use ``create_openai_client`` instead of
duplicating the authentication + base-URL logic.
"""

import os
from typing import Optional

from openai import OpenAI

from src.common.config import Settings
from src.common.logging import get_logger

logger = get_logger(__name__)


def create_openai_client(
    settings: Settings,
    *,
    user_token: Optional[str] = None,
):
    """Create an OpenAI client authenticated against a Databricks serving endpoint.

    Token resolution order:
      1. ``user_token`` (OBO / per-request token in Databricks Apps)
      2. ``settings.DATABRICKS_TOKEN`` or ``DATABRICKS_TOKEN`` env var (local dev PAT)
      3. Databricks SDK default config (``~/.databrickscfg`` / service-principal)

    Args:
        settings: Application settings carrying host/token/LLM config.
        user_token: Per-user OBO token from the ``x-forwarded-access-token``
            request header.  When supplied this takes priority over all
            other token sources.

    Returns:
        A configured ``openai.OpenAI`` client instance.

    Raises:
        RuntimeError: If no token can be resolved or no base URL is available.
    """

    token = user_token

    if not token:
        token = settings.DATABRICKS_TOKEN or os.environ.get("DATABRICKS_TOKEN")
        if token:
            logger.info("Using token from settings/environment (PAT)")

    if not token:
        try:
            from databricks.sdk.core import Config

            config_kwargs = {}
            if settings.DATABRICKS_CONFIG_PROFILE:
                # pydantic doesn't push .env values to os.environ; pass profile explicitly
                config_kwargs["profile"] = settings.DATABRICKS_CONFIG_PROFILE
            config = Config(**config_kwargs)
            headers = config.authenticate()
            if headers and "Authorization" in headers:
                auth_header = headers["Authorization"]
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    logger.info(
                        "Using token from Databricks SDK (%s)",
                        f"profile={settings.DATABRICKS_CONFIG_PROFILE}"
                        if settings.DATABRICKS_CONFIG_PROFILE
                        else "default config",
                    )
        except Exception as sdk_err:
            logger.debug("Could not get token from SDK config: %s", sdk_err)

    if not token:
        raise RuntimeError(
            "No authentication token available. "
            "Pass a user_token, set DATABRICKS_TOKEN, or configure the Databricks SDK."
        )

    base_url = settings.LLM_BASE_URL
    if not base_url and settings.DATABRICKS_HOST:
        host = settings.DATABRICKS_HOST.rstrip("/")
        if not host.startswith("http://") and not host.startswith("https://"):
            host = f"https://{host}"
        base_url = f"{host}/serving-endpoints"

    if not base_url:
        raise RuntimeError(
            "LLM_BASE_URL not configured and cannot be derived from DATABRICKS_HOST."
        )

    token_source = "user_token" if user_token else "settings/env"
    logger.info("Creating OpenAI client — base_url=%s, auth=%s", base_url, token_source)

    return OpenAI(api_key=token, base_url=base_url)
