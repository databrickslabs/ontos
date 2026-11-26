"""Reading a product's compliance values follows the product read rule.

The entity read and the completeness read answer 404, the same body as a missing
product, when the caller can't read the product (a draft or proposed product they
don't own). Published products read for everyone with the feature.
"""
import uuid

import pytest

from src.app import app
from src.common import authorization
from src.common.authorization import get_user_details_from_sdk
from src.common.features import APP_FEATURES, FeatureAccessLevel
from src.db_models.data_products import DataProductDb
from src.models.users import UserInfo

OWNER = "owner@example.com"
CONSUMER = "consumer@example.com"
ADMIN = "admin@example.com"

# email, groups (the default roles map these groups to the role in the comment)
PERSONAS = {
    "owner": (OWNER, ["data-producers"]),  # Data Producer, read/write compliance values
    "consumer": (CONSUMER, ["data-consumers"]),  # Data Consumer, read-only compliance values
    "admin": (ADMIN, ["admins"]),
}

ROUTES = [
    "/api/compliance-templates/entities/data_product/{pid}",
    "/api/compliance-templates/entities/data_product/{pid}/completeness",
]
MISSING = {"detail": "Data product not found"}

# (status, draft owner, persona, expected status)
CASES = [
    ("draft", OWNER, "owner", 200),
    ("draft", OWNER, "admin", 200),
    ("draft", OWNER, "consumer", 404),  # another user's draft
    ("draft", None, "owner", 404),  # a producer who doesn't own it
    ("proposed", OWNER, "consumer", 404),
    ("active", None, "consumer", 200),
    ("deprecated", None, "consumer", 200),
]


@pytest.fixture
def as_persona(client, monkeypatch):
    """Switch the caller of ``client``. The admin persona holds ADMIN on every feature."""
    original_permissions = authorization.resolve_effective_permissions
    original_request_permissions = authorization.effective_permissions_for_request

    async def _resolve(user_email, user_groups, request, *args, **kwargs):
        if user_email == ADMIN:
            return {feature: FeatureAccessLevel.ADMIN for feature in APP_FEATURES}
        return await original_permissions(user_email, user_groups, request, *args, **kwargs)

    def _request_permissions(request, user_email, user_groups, auth_manager, *args, **kwargs):
        if user_email == ADMIN:
            return {feature: FeatureAccessLevel.ADMIN for feature in APP_FEATURES}
        return original_request_permissions(request, user_email, user_groups, auth_manager, *args, **kwargs)

    monkeypatch.setattr(authorization, "resolve_effective_permissions", _resolve)
    monkeypatch.setattr(authorization, "effective_permissions_for_request", _request_permissions)

    def _switch(persona):
        email, groups = PERSONAS[persona]

        async def _override():
            return UserInfo(username=email, email=email, user=email, ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    return _switch


@pytest.fixture
def savepoint(db_session):
    """A refused read rolls its session back: data made before it sits in a SAVEPOINT."""
    db_session.connection().begin_nested()
    return db_session


@pytest.fixture
def make_product(savepoint):
    db_session = savepoint

    def _make(status, draft_owner=None):
        pid = str(uuid.uuid4())
        db_session.add(DataProductDb(
            id=pid, name=f"P {pid[:8]}", version="1.0.0", status=status,
            api_version="v1.0.0", kind="DataProduct", draft_owner_id=draft_owner,
        ))
        db_session.commit()
        return pid

    return _make


@pytest.mark.parametrize("status,draft_owner,persona,expected", CASES,
                         ids=[f"{s}-{p}" for s, _, p, _ in CASES])
def test_values_follow_the_product_read_rule(as_persona, make_product, status, draft_owner, persona, expected):
    pid = make_product(status, draft_owner)
    client = as_persona(persona)
    for route in ROUTES:
        response = client.get(route.format(pid=pid))
        assert response.status_code == expected, (route, response.text)
        if expected == 404:
            assert response.json() == MISSING


@pytest.mark.parametrize("persona", ["consumer", "owner", "admin"])
def test_a_missing_product_answers_the_same_404(as_persona, savepoint, persona):
    client = as_persona(persona)
    for route in ROUTES:
        response = client.get(route.format(pid=str(uuid.uuid4())))
        assert response.status_code == 404, (route, response.text)
        assert response.json() == MISSING


@pytest.mark.parametrize("persona", ["owner", "consumer"])
def test_only_an_admin_writes_the_values_of_another_entity_type(as_persona, persona):
    """No owner rule exists for tables and views yet, so a Producer (read/write) is refused."""
    client = as_persona(persona)
    response = client.put(
        "/api/compliance-templates/entities/table/some-table/values", json={"values": []},
    )
    assert response.status_code == 403, response.text
