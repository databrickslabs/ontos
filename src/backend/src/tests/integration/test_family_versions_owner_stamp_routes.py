"""Family routes list published versions that still carry a draft owner (PRD #442).

``GET /api/data-{contracts,products}/{id}/versions`` and
``GET /api/data-{contracts,products}/families/{family_id}/latest`` hide another
user's personal draft (``draft`` status with a ``draft_owner_id``) and nothing
else by owner: an active or deprecated version stamped with another user's
``draft_owner_id`` is visible to a consumer.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.users import UserInfo

OWNER = "owner@example.com"
CONSUMER = "consumer@example.com"
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

KINDS = {
    "contract": ("/api/data-contracts", DataContractDb, {}),
    "product": ("/api/data-products", DataProductDb,
                {"api_version": "v1.0.0", "kind": "DataProduct"}),
}


@pytest.fixture
def as_consumer(client):
    """``client`` called by a Data Consumer (read-only on both features, not an admin)."""
    async def _override():
        return UserInfo(username=CONSUMER, email=CONSUMER, user=CONSUMER, ip="127.0.0.1",
                        groups=["data-consumers"])

    app.dependency_overrides[get_user_details_from_sdk] = _override
    return client


@pytest.fixture(params=sorted(KINDS))
def kind(request):
    return KINDS[request.param]


def _family(db_session, model, extra, statuses):
    """One family with a version per ``(status, draft_owner_id)``, oldest first."""
    family_id = str(uuid.uuid4())
    ids = []
    for day, (status, owner) in enumerate(statuses):
        row_id = str(uuid.uuid4())
        db_session.add(model(
            id=row_id, name=f"orders-{family_id[:8]}", version=f"{day + 1}.0.0",
            status=status, version_family_id=family_id, draft_owner_id=owner,
            created_at=BASE + timedelta(days=day), updated_at=BASE + timedelta(days=day),
            **extra,
        ))
        ids.append(row_id)
    db_session.commit()
    return family_id, ids


def test_versions_list_published_rows_stamped_by_another_user(db_session, as_consumer, kind):
    prefix, model, extra = kind
    _fid, (deprecated, active, draft) = _family(
        db_session, model, extra, [("deprecated", OWNER), ("active", OWNER), ("draft", OWNER)]
    )

    response = as_consumer.get(f"{prefix}/{active}/versions")

    assert response.status_code == 200, response.text
    assert [v["id"] for v in response.json()] == [active, deprecated]
    assert draft not in {v["id"] for v in response.json()}


def test_latest_returns_the_active_version_stamped_by_another_user(
    db_session, as_consumer, kind
):
    prefix, model, extra = kind
    family_id, (_deprecated, active, _draft) = _family(
        db_session, model, extra, [("deprecated", OWNER), ("active", OWNER), ("draft", OWNER)]
    )

    response = as_consumer.get(f"{prefix}/families/{family_id}/latest")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == active
    assert response.json()["status"] == "active"


def test_latest_returns_a_deprecated_version_stamped_by_another_user(
    db_session, as_consumer, kind
):
    prefix, model, extra = kind
    family_id, (deprecated, _draft) = _family(
        db_session, model, extra, [("deprecated", OWNER), ("draft", OWNER)]
    )

    response = as_consumer.get(f"{prefix}/families/{family_id}/latest")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == deprecated


def test_latest_still_hides_another_users_personal_draft(db_session, as_consumer, kind):
    prefix, model, extra = kind
    family_id, _ids = _family(db_session, model, extra, [("draft", OWNER)])

    response = as_consumer.get(f"{prefix}/families/{family_id}/latest")

    assert response.status_code == 404, response.text
