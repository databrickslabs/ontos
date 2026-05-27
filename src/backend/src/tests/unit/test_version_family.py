"""
Unit tests for the unified version family (PRD #442).

Covers:
- Initial create on data_contracts sets version_family_id = self.id (root).
- Initial create on data_products sets version_family_id = self.id (root).
- ContractCloner propagates version_family_id and keeps the human-readable
  name stable across the family (no _v<version> suffix mutation anymore).
- DataProductsManager.clone_product_for_new_version propagates
  version_family_id to the clone.
- Repository helpers return the full family in newest-first order and
  hide other users' personal drafts.
- ``list_family_representatives`` collapses families to one row each, but
  returns the full set when include_history is True.
"""
import uuid
import pytest
from sqlalchemy.orm import Session

from src.repositories.data_contracts_repository import data_contract_repo
from src.repositories.data_products_repository import data_product_repo
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.data_products import DataProductCreate
from src.utils.contract_cloner import ContractCloner


# ---------------------------------------------------------------------------
# Initial-create defaults
# ---------------------------------------------------------------------------

class TestInitialCreateDefaults:
    """First-version rows must seed version_family_id with their own id."""

    def test_contract_create_via_orm_seeds_family_to_self(self, db_session: Session):
        cid = str(uuid.uuid4())
        row = DataContractDb(
            id=cid, name="initial", version="1.0.0", status="draft"
        )
        created = data_contract_repo.create(db=db_session, obj_in=row)

        assert created.id == cid
        assert created.version_family_id == cid, (
            "first version of a family should be its own family root"
        )
        assert created.parent_contract_id is None

    def test_contract_create_via_dict_seeds_family_to_self(self, db_session: Session):
        cid = str(uuid.uuid4())
        created = data_contract_repo.create(
            db=db_session,
            obj_in={"id": cid, "name": "initial-dict", "version": "1.0.0", "status": "draft"},
        )
        assert created.version_family_id == cid

    def test_contract_create_without_id_generates_and_seeds_family(self, db_session: Session):
        created = data_contract_repo.create(
            db=db_session,
            obj_in={"name": "no-id", "version": "1.0.0", "status": "draft"},
        )
        assert created.id is not None
        assert created.version_family_id == created.id

    def test_product_create_seeds_family_to_self(self, db_session: Session):
        pid = str(uuid.uuid4())
        created = data_product_repo.create(
            db=db_session,
            obj_in=DataProductCreate(
                id=pid,
                apiVersion="v1.0.0",
                kind="DataProduct",
                name="initial-product",
                version="1.0.0",
                status="draft",
            ),
        )
        db_session.commit()
        assert created.version_family_id == pid

    def test_product_create_honors_supplied_family_id(self, db_session: Session):
        # A manager cloning a new version explicitly passes the existing
        # family id; the repo must use it instead of defaulting to self.id.
        pid = str(uuid.uuid4())
        fam = str(uuid.uuid4())
        created = data_product_repo.create(
            db=db_session,
            obj_in=DataProductCreate(
                id=pid,
                apiVersion="v1.0.0",
                kind="DataProduct",
                name="clone-with-family",
                version="2.0.0",
                status="draft",
                versionFamilyId=fam,
            ),
        )
        db_session.commit()
        assert created.version_family_id == fam


# ---------------------------------------------------------------------------
# Clone-path propagation
# ---------------------------------------------------------------------------

class TestClonePathPropagation:
    """Every clone path inherits the source's family id."""

    def test_contract_cloner_propagates_family_and_keeps_name(self, db_session: Session):
        root_id = str(uuid.uuid4())
        root = DataContractDb(id=root_id, name="customers", version="1.0.0", status="active")
        data_contract_repo.create(db=db_session, obj_in=root)
        db_session.commit()

        cloner = ContractCloner()
        cloned = cloner.clone_for_new_version(
            source_contract_db=root,
            new_version="2.0.0",
            change_summary="major bump",
        )

        # New row id is fresh, version reflects the request, but the
        # human-readable name stays stable (PRD #442 explicitly drops
        # the legacy _v<version> name mutation).
        assert cloned["id"] != root_id
        assert cloned["name"] == "customers"
        assert cloned["version"] == "2.0.0"
        # Lineage edge + family id come through to the new row.
        assert cloned["parent_contract_id"] == root_id
        assert cloned["version_family_id"] == root_id

    def test_data_products_manager_clone_propagates_family(
        self, db_session: Session, monkeypatch
    ):
        from src.controller import data_products_manager as dpm_module
        from src.controller.data_products_manager import DataProductsManager
        from databricks.sdk import WorkspaceClient
        from unittest.mock import MagicMock

        # The manager constructor wants a workspace client; for a clone
        # operation that only touches the local DB we can hand it a mock.
        ws = MagicMock(spec=WorkspaceClient)
        manager = DataProductsManager(db=db_session, ws_client=ws)

        # Seed root product.
        root_id = str(uuid.uuid4())
        root = data_product_repo.create(
            db=db_session,
            obj_in=DataProductCreate(
                id=root_id,
                apiVersion="v1.0.0",
                kind="DataProduct",
                name="orders",
                version="1.0.0",
                status="active",
            ),
        )
        db_session.commit()

        clone_api = manager.clone_product_for_new_version(
            db=db_session,
            product_id=root_id,
            new_version="2.0.0",
            change_summary="schema overhaul",
            current_user="tester@example.com",
        )
        db_session.commit()

        # Re-fetch the clone from DB to assert family id directly.
        clone_row = db_session.query(DataProductDb).filter_by(id=clone_api.id).first()
        assert clone_row is not None
        assert clone_row.parent_product_id == root_id
        assert clone_row.version_family_id == root_id


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

class TestGetFamilyVersions:
    """``get_family_versions`` returns the whole family newest-first and
    enforces personal-draft visibility."""

    @pytest.fixture
    def contract_family(self, db_session: Session):
        # 3-version family: root (active), v2 (active), v3 (personal draft
        # owned by alice). A separate single-version family lives alongside.
        # We pin explicit created_at so the newest-first ordering assertion
        # is deterministic on fast SQLite test runs (same-microsecond inserts
        # otherwise tie).
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        family_id = str(uuid.uuid4())
        ids = [str(uuid.uuid4()) for _ in range(3)]

        rows = [
            DataContractDb(
                id=ids[0], name="customers", version="1.0.0", status="active",
                version_family_id=family_id, parent_contract_id=None,
                created_at=base, updated_at=base,
            ),
            DataContractDb(
                id=ids[1], name="customers", version="2.0.0", status="active",
                version_family_id=family_id, parent_contract_id=ids[0],
                created_at=base + timedelta(days=1), updated_at=base + timedelta(days=1),
            ),
            DataContractDb(
                id=ids[2], name="customers", version="3.0.0-draft", status="draft",
                version_family_id=family_id, parent_contract_id=ids[1],
                draft_owner_id="alice@example.com",
                created_at=base + timedelta(days=2), updated_at=base + timedelta(days=2),
            ),
            DataContractDb(
                id=str(uuid.uuid4()), name="orders", version="1.0.0", status="active",
                version_family_id=str(uuid.uuid4()),
                created_at=base, updated_at=base,
            ),
        ]
        for r in rows:
            db_session.add(r)
        db_session.commit()
        return family_id, ids

    def test_returns_all_versions_newest_first_for_admin(
        self, db_session: Session, contract_family
    ):
        family_id, ids = contract_family
        versions = data_contract_repo.get_family_versions(
            db_session, family_id=family_id, is_admin=True
        )
        assert [v.id for v in versions] == list(reversed(ids))

    def test_hides_other_users_personal_drafts(
        self, db_session: Session, contract_family
    ):
        family_id, ids = contract_family
        # bob is not the draft owner — alice's personal draft must be hidden.
        visible = data_contract_repo.get_family_versions(
            db_session, family_id=family_id, user_email="bob@example.com"
        )
        assert ids[2] not in {v.id for v in visible}
        assert {v.id for v in visible} == set(ids[:2])

    def test_personal_draft_owner_sees_their_own_draft(
        self, db_session: Session, contract_family
    ):
        family_id, ids = contract_family
        visible = data_contract_repo.get_family_versions(
            db_session, family_id=family_id, user_email="alice@example.com"
        )
        assert ids[2] in {v.id for v in visible}


class TestListFamilyRepresentatives:
    """The list-view collapse helper returns one row per family by default,
    and the full set when include_history=True."""

    @pytest.fixture
    def two_families(self, db_session: Session):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fam_a = str(uuid.uuid4())
        fam_b = str(uuid.uuid4())
        a_root = str(uuid.uuid4())
        b_root = str(uuid.uuid4())

        # Family A: two versions.
        db_session.add(DataContractDb(
            id=a_root, name="A", version="1.0.0", status="active",
            version_family_id=fam_a,
            created_at=base, updated_at=base,
        ))
        a_v2 = str(uuid.uuid4())
        db_session.add(DataContractDb(
            id=a_v2, name="A", version="2.0.0", status="active",
            version_family_id=fam_a, parent_contract_id=a_root,
            created_at=base + timedelta(days=1), updated_at=base + timedelta(days=1),
        ))
        # Family B: one version.
        db_session.add(DataContractDb(
            id=b_root, name="B", version="1.0.0", status="active",
            version_family_id=fam_b,
            created_at=base, updated_at=base,
        ))
        db_session.commit()
        return {"a_root": a_root, "a_v2": a_v2, "b_root": b_root, "fam_a": fam_a, "fam_b": fam_b}

    def test_default_returns_one_row_per_family(
        self, db_session: Session, two_families
    ):
        reps = data_contract_repo.list_family_representatives(
            db_session, is_admin=True
        )
        ids = {r.id for r in reps}
        # Family A's representative is the newest version (v2), not the root.
        assert two_families["a_v2"] in ids
        assert two_families["a_root"] not in ids
        assert two_families["b_root"] in ids
        assert len(reps) == 2

    def test_include_history_returns_all_rows(
        self, db_session: Session, two_families
    ):
        rows = data_contract_repo.list_family_representatives(
            db_session, is_admin=True, include_history=True
        )
        assert len(rows) == 3
        # Sorted by family id then created_at DESC — both A rows grouped together.
        # We don't pin the family order (DB-implementation-dependent), just
        # that within family A v2 precedes v1.
        a_rows = [r for r in rows if r.version_family_id == two_families["fam_a"]]
        assert [r.id for r in a_rows] == [two_families["a_v2"], two_families["a_root"]]


# ---------------------------------------------------------------------------
# Manager-level list collapse (Phase 2)
# ---------------------------------------------------------------------------

class TestContractsListCollapse:
    """``list_contracts_from_db`` collapses families and emits versionCount."""

    @pytest.fixture
    def family_with_loose_row(self, db_session: Session):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fam = str(uuid.uuid4())
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())
        v3 = str(uuid.uuid4())
        loose = str(uuid.uuid4())
        # 3-version family A
        db_session.add(DataContractDb(
            id=v1, name="A", version="1.0.0", status="active",
            version_family_id=fam,
            created_at=base, updated_at=base,
        ))
        db_session.add(DataContractDb(
            id=v2, name="A", version="2.0.0", status="active",
            version_family_id=fam, parent_contract_id=v1,
            created_at=base + timedelta(days=1), updated_at=base + timedelta(days=1),
        ))
        db_session.add(DataContractDb(
            id=v3, name="A", version="3.0.0", status="draft",
            version_family_id=fam, parent_contract_id=v2,
            created_at=base + timedelta(days=2), updated_at=base + timedelta(days=2),
        ))
        # Single-version family B (loose row)
        db_session.add(DataContractDb(
            id=loose, name="B", version="1.0.0", status="active",
            version_family_id=str(uuid.uuid4()),
            created_at=base, updated_at=base,
        ))
        db_session.commit()
        return {"fam": fam, "v1": v1, "v2": v2, "v3": v3, "loose": loose}

    def _manager(self, db_session):
        from pathlib import Path
        from src.controller.data_contracts_manager import DataContractsManager
        # The contracts manager keeps its DB session out of __init__ and takes
        # it as a method arg; data_dir is only used for legacy YAML loading
        # paths we don't exercise here.
        return DataContractsManager(data_dir=Path("/tmp"))

    def test_collapses_to_one_row_per_family_by_default(
        self, db_session: Session, family_with_loose_row
    ):
        manager = self._manager(db_session)
        summaries = manager.list_contracts_from_db(db_session, is_admin=True)
        ids = {s.id for s in summaries}
        # Family A is represented by its newest version (v3); loose row B
        # passes through as its own family.
        assert family_with_loose_row["v3"] in ids
        assert family_with_loose_row["v1"] not in ids
        assert family_with_loose_row["v2"] not in ids
        assert family_with_loose_row["loose"] in ids
        assert len(summaries) == 2

    def test_emits_version_count_on_collapse(
        self, db_session: Session, family_with_loose_row
    ):
        manager = self._manager(db_session)
        summaries = manager.list_contracts_from_db(db_session, is_admin=True)
        by_id = {s.id: s for s in summaries}
        # Family A had 3 versions, loose row B is a family of one.
        assert by_id[family_with_loose_row["v3"]].versionCount == 3
        assert by_id[family_with_loose_row["loose"]].versionCount == 1

    def test_include_history_returns_every_row_without_count(
        self, db_session: Session, family_with_loose_row
    ):
        manager = self._manager(db_session)
        summaries = manager.list_contracts_from_db(
            db_session, is_admin=True, include_history=True
        )
        ids = {s.id for s in summaries}
        # All 4 rows are present.
        assert ids == {
            family_with_loose_row["v1"],
            family_with_loose_row["v2"],
            family_with_loose_row["v3"],
            family_with_loose_row["loose"],
        }
        # versionCount is intentionally omitted on the expanded view.
        assert all(s.versionCount is None for s in summaries)


class TestProductsListCollapse:
    """``list_products`` collapses by version_family_id and attaches counts."""

    def test_default_collapses_to_latest_version_per_family(
        self, db_session: Session
    ):
        from datetime import datetime, timedelta, timezone
        from src.controller.data_products_manager import DataProductsManager
        from databricks.sdk import WorkspaceClient
        from unittest.mock import MagicMock

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fam = str(uuid.uuid4())
        p1 = str(uuid.uuid4())
        p2 = str(uuid.uuid4())
        # Family with two versions.
        db_session.add(DataProductDb(
            id=p1, name="orders", version="1.0.0", status="active",
            version_family_id=fam,
            created_at=base, updated_at=base,
        ))
        db_session.add(DataProductDb(
            id=p2, name="orders", version="2.0.0", status="active",
            version_family_id=fam, parent_product_id=p1,
            created_at=base + timedelta(days=1), updated_at=base + timedelta(days=1),
        ))
        db_session.commit()

        ws = MagicMock(spec=WorkspaceClient)
        manager = DataProductsManager(db=db_session, ws_client=ws)

        products = manager.list_products(is_admin=True)
        ids = {p.id for p in products}
        # Newest version wins.
        assert p2 in ids
        assert p1 not in ids
        # Family of two surfaces as versionCount=2.
        assert {p.version_count for p in products if p.id == p2} == {2}

    def test_include_history_returns_all_versions(self, db_session: Session):
        from datetime import datetime, timedelta, timezone
        from src.controller.data_products_manager import DataProductsManager
        from databricks.sdk import WorkspaceClient
        from unittest.mock import MagicMock

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fam = str(uuid.uuid4())
        p1 = str(uuid.uuid4())
        p2 = str(uuid.uuid4())
        db_session.add(DataProductDb(
            id=p1, name="orders", version="1.0.0", status="active",
            version_family_id=fam,
            created_at=base, updated_at=base,
        ))
        db_session.add(DataProductDb(
            id=p2, name="orders", version="2.0.0", status="active",
            version_family_id=fam, parent_product_id=p1,
            created_at=base + timedelta(days=1), updated_at=base + timedelta(days=1),
        ))
        db_session.commit()

        ws = MagicMock(spec=WorkspaceClient)
        manager = DataProductsManager(db=db_session, ws_client=ws)

        products = manager.list_products(is_admin=True, include_history=True)
        ids = {p.id for p in products}
        assert ids == {p1, p2}
        # version_count is suppressed on the expanded view.
        assert all(p.version_count is None for p in products)
