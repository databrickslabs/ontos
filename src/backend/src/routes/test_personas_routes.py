"""Test-persona discovery endpoint.

Exposes the canned personas defined in ``src/backend/src/data/test_personas.yaml``
to the frontend so the UI can offer a persona picker.

The endpoint is enabled only when ``TEST_USER_TOKEN`` is configured server-side
(otherwise the entire header-override mechanism is dormant and the frontend
should not show any persona UI). When disabled, the endpoint returns 404 so
clients can probe without learning that the feature exists.

Security:
- The endpoint does NOT echo back the ``TEST_USER_TOKEN`` itself. The token
  is provisioned to the dev/test client out-of-band (e.g. a frontend
  ``VITE_TEST_USER_TOKEN`` env var or a curl flag). This prevents an
  accidental information leak via a misconfigured prod deployment.
- The persona list itself is harmless metadata, but we still gate it on the
  token being configured to avoid surfacing the feature in production.
"""

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.authorization import (
    TEST_TOKEN_HEADER,
    TEST_USER_EMAIL_HEADER,
    TEST_USER_GROUPS_HEADER,
    TEST_USER_IP_HEADER,
    TEST_USER_NAME_HEADER,
    TEST_USER_USERNAME_HEADER,
)
from src.common.config import Settings, get_settings
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/test", tags=["Test"])

PERSONAS_YAML_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "test_personas.yaml"
)


class TestPersona(BaseModel):
    id: str
    label: str
    email: str
    # Groups are optional: when omitted, the backend falls back to a SCIM
    # lookup so the persona reflects real workspace state.
    groups: Optional[List[str]] = None
    description: Optional[str] = None


class TestPersonasResponse(BaseModel):
    personas: List[TestPersona]
    # Names of the headers the frontend must send. Surfacing them here keeps
    # the client and server agreed on the wire format.
    headers: Dict[str, str] = Field(
        default_factory=lambda: {
            "token": TEST_TOKEN_HEADER,
            "email": TEST_USER_EMAIL_HEADER,
            "groups": TEST_USER_GROUPS_HEADER,
            "username": TEST_USER_USERNAME_HEADER,
            "name": TEST_USER_NAME_HEADER,
            "ip": TEST_USER_IP_HEADER,
        }
    )


_cached_personas: Optional[List[TestPersona]] = None


def _load_personas() -> List[TestPersona]:
    """Load and cache the persona list from disk."""
    global _cached_personas
    if _cached_personas is not None:
        return _cached_personas

    if not PERSONAS_YAML_PATH.is_file():
        logger.warning(
            "test_personas.yaml not found at %s; returning empty persona list",
            PERSONAS_YAML_PATH,
        )
        _cached_personas = []
        return _cached_personas

    try:
        with PERSONAS_YAML_PATH.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse test_personas.yaml: %s", e)
        _cached_personas = []
        return _cached_personas

    items = raw.get("personas") or []
    personas: List[TestPersona] = []
    for item in items:
        try:
            personas.append(TestPersona(**item))
        except Exception as e:
            logger.warning("Skipping malformed test persona %r: %s", item, e)
    _cached_personas = personas
    return _cached_personas


@router.get("/personas", response_model=TestPersonasResponse)
def list_test_personas(settings: Settings = Depends(get_settings)) -> TestPersonasResponse:
    """List the canned test personas.

    Returns 404 when ``TEST_USER_TOKEN`` is unset (feature disabled).
    """
    if not settings.TEST_USER_TOKEN:
        raise HTTPException(status_code=404, detail="Test mode not enabled")

    return TestPersonasResponse(personas=_load_personas())


def register_routes(app):
    """Register the test-personas router with the FastAPI app."""
    app.include_router(router)
    logger.info("Test-personas routes registered")
