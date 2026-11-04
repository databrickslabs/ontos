"""Family version lists hide only personal drafts by owner (PRD #442, tier 1).

A personal draft is a row in ``draft`` status with a ``draft_owner_id``; only
its owner sees it. The owner stamp doesn't hide a row in any other status: an
active or deprecated version that still carries another user's
``draft_owner_id`` is published and listed for everyone.

Covers ``get_family_versions`` on both repositories and the managers'
``get_contract_versions`` / ``get_product_versions`` that serve
``GET /{id}/versions``.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.repositories.data_contracts_repository import data_contract_repo
from src.repositories.data_products_repository import data_product_repo

OWNER = "owner@example.com"
CONSUMER = "consumer@example.com"
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _contract(**kwargs):
    return DataContractDb(name="orders", **kwargs)


def _product(**kwargs):
    return DataProductDb(api_version="v1.0.0", kind="DataProduct", name="orders", **kwargs)


KINDS = {
    "contract": (_contract, data_contract_repo),
    "product": (_product, data_product_repo),
}


@pytest.fixture(params=sorted(KINDS))
def family(request, db_session: Session):
    """A deprecated v1, an active v2 and a personal draft v3, all stamped with OWNER.

    Also a stamped row in ``proposed`` status (``change-status`` draft -> proposed
    keeps the stamp; only the review request clears it) and an unstamped draft.
    """
    make, repo = KINDS[request.param]
    family_id = str(uuid.uuid4())
    spec = [
        ("deprecated", "1.0.0", OWNER),
        ("active", "2.0.0", OWNER),
        ("proposed", "2.1.0", OWNER),
        ("draft", "2.2.0", None),
        ("draft", "3.0.0", OWNER),
    ]
    ids = {}
    for day, (status, version, owner) in enumerate(spec):
        row_id = str(uuid.uuid4())
        db_session.add(make(
            id=row_id, version=version, status=status, version_family_id=family_id,
            draft_owner_id=owner,
            created_at=BASE + timedelta(days=day), updated_at=BASE + timedelta(days=day),
        ))
        ids[version] = row_id
    db_session.commit()
    return request.param, repo, family_id, ids


class TestGetFamilyVersions:

    def test_lists_published_versions_with_another_users_stamp(self, db_session, family):
        _kind, repo, family_id, ids = family
        rows = repo.get_family_versions(db_session, family_id=family_id, user_email=CONSUMER)
        listed = {r.id for r in rows}
        assert ids["1.0.0"] in listed  # deprecated
        assert ids["2.0.0"] in listed  # active

    def test_still_hides_another_users_personal_draft(self, db_session, family):
        _kind, repo, family_id, ids = family
        rows = repo.get_family_versions(db_session, family_id=family_id, user_email=CONSUMER)
        assert ids["3.0.0"] not in {r.id for r in rows}

    def test_lists_every_row_but_the_personal_draft(self, db_session, family):
        _kind, repo, family_id, ids = family
        rows = repo.get_family_versions(db_session, family_id=family_id, user_email=CONSUMER)
        assert [r.id for r in rows] == [ids[v] for v in ("2.2.0", "2.1.0", "2.0.0", "1.0.0")]

    def test_status_case_and_spaces_dont_unhide_a_personal_draft(self, db_session, family):
        _kind, repo, family_id, ids = family
        row = repo.get(db_session, id=ids["3.0.0"])
        row.status = " Draft "
        db_session.commit()
        rows = repo.get_family_versions(db_session, family_id=family_id, user_email=CONSUMER)
        assert ids["3.0.0"] not in {r.id for r in rows}

    def test_owner_and_admin_see_every_version(self, db_session, family):
        _kind, repo, family_id, ids = family
        for kwargs in ({"user_email": OWNER}, {"user_email": CONSUMER, "is_admin": True}):
            rows = repo.get_family_versions(db_session, family_id=family_id, **kwargs)
            assert {r.id for r in rows} == set(ids.values())

    def test_anonymous_caller_sees_published_stamped_versions(self, db_session, family):
        _kind, repo, family_id, ids = family
        rows = repo.get_family_versions(db_session, family_id=family_id, user_email=None)
        listed = {r.id for r in rows}
        assert {ids["1.0.0"], ids["2.0.0"]} <= listed
        assert ids["3.0.0"] not in listed


class TestManagerVersionLists:
    """The managers behind ``GET /{id}/versions`` pass the rule through."""

    def test_versions_of_a_published_row_include_it(self, db_session, family):
        kind, _repo, _family_id, ids = family
        if kind == "contract":
            from src.controller.data_contracts_manager import DataContractsManager

            manager = DataContractsManager(data_dir=Path("/tmp"))
            rows = manager.get_contract_versions(
                db=db_session, contract_id=ids["2.0.0"], user_email=CONSUMER, is_admin=False
            )
        else:
            from src.controller.data_products_manager import DataProductsManager

            manager = DataProductsManager(db=db_session, ws_client=MagicMock(spec=WorkspaceClient))
            rows = manager.get_product_versions(
                db=db_session, product_id=ids["2.0.0"], user_email=CONSUMER, is_admin=False
            )
        listed = {r.id for r in rows}
        assert {ids["1.0.0"], ids["2.0.0"]} <= listed
        assert ids["3.0.0"] not in listed
