"""HTTP regressions for the compliance template routes, on the real managers and test database."""
import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.models.users import UserInfo

TEMPLATE_URL = "/api/compliance-templates"

NEW_TEMPLATE = {
    "name": "Governance",
    "entity_type": "data_product",
    "fields": [
        {"label": "Tier", "key": "tier", "reference_id": "tier", "value_type": "string"},
    ],
}


ADMIN_EMAIL = "admin@example.com"


@pytest.fixture(autouse=True)
def _as_admin(client, monkeypatch):
    """The caller is an admin: ADMIN on every feature. Other callers resolve as usual.

    The test roles don't grant ADMIN on the compliance features, so the admin persona
    is granted them here (the same as ``test_admins`` in production's Admin role).
    """
    from src.common import authorization
    from src.common.features import APP_FEATURES, FeatureAccessLevel

    original = authorization.resolve_effective_permissions

    async def _resolve(user_email, user_groups, request, *args, **kwargs):
        if user_email == ADMIN_EMAIL:
            return {feature: FeatureAccessLevel.ADMIN for feature in APP_FEATURES}
        return await original(user_email, user_groups, request, *args, **kwargs)

    monkeypatch.setattr(authorization, "resolve_effective_permissions", _resolve)

    async def _override():
        return UserInfo(username=ADMIN_EMAIL, email=ADMIN_EMAIL, user=ADMIN_EMAIL,
                        ip="127.0.0.1", groups=["admins"])

    app.dependency_overrides[get_user_details_from_sdk] = _override
    yield client


@pytest.fixture
def template(client, db_session):
    """A template with one field. A refused request rolls its session back, so the
    fixture's data sits in a SAVEPOINT that only the request's own rollback can reach."""
    db_session.connection().begin_nested()
    created = client.post(TEMPLATE_URL, json=NEW_TEMPLATE)
    assert created.status_code == 201, created.text
    return created.json()


def _stored_field(client, template_id, field_id):
    listed = client.get(TEMPLATE_URL, params={"entity_type": "data_product"})
    assert listed.status_code == 200, listed.text
    template = next(t for t in listed.json() if t["id"] == template_id)
    return next(f for f in template["fields"] if f["id"] == field_id)


@pytest.mark.parametrize("body", [
    {"possible_values": "abc"},
    {"possible_values": [1, 2]},
    {"possible_values": ["a", ""]},
    {"possible_values": ["a"]},  # a string field takes no vocabulary
    {"value_type": "bogus"},
    {"value_type": None},
    {"is_mandatory": "yes"},
    {"label": "   "},
    {"group_order": -1},
    {"bogus": 1},
])
def test_bad_field_update_answers_400_and_persists_nothing(client, template, body):
    field = template["fields"][0]
    before = _stored_field(client, template["id"], field["id"])

    response = client.put(f"{TEMPLATE_URL}/{template['id']}/fields/{field['id']}", json=body)

    assert response.status_code == 400, response.text
    after = _stored_field(client, template["id"], field["id"])
    assert after == before


def test_reads_still_work_after_a_refused_update(client, template):
    field = template["fields"][0]
    refused = client.put(f"{TEMPLATE_URL}/{template['id']}/fields/{field['id']}",
                         json={"possible_values": "abc"})
    assert refused.status_code == 400

    assert client.get(TEMPLATE_URL).status_code == 200
    assert client.get(TEMPLATE_URL, params={"entity_type": "data_product"}).status_code == 200

    # A valid edit still goes through after the refusal.
    accepted = client.put(f"{TEMPLATE_URL}/{template['id']}/fields/{field['id']}",
                          json={"label": "Business tier", "is_mandatory": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["label"] == "Business tier"
    assert accepted.json()["is_mandatory"] is True
