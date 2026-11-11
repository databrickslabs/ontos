"""
Regression tests for #1295: list views silently truncated results at 100.

Covers:
- ``CRUDBase.get_multi`` returns every row by default.
- Teams, Data Domains and Projects list every row by default.
- ``list_products`` and ``list_contracts_from_db`` list every family by
  default, and products page *after* the family collapse so older versions
  can't use up the limit.
- ``get_published_products`` pages after the publication filter, so
  unpublished products can't push published ones off the first page.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.projects import ProjectDb
from src.db_models.teams import TeamDb

# Comfortably past the old default page size of 100.
COUNT = 130
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _products_manager(db_session: Session):
    from src.controller.data_products_manager import DataProductsManager
    return DataProductsManager(db=db_session, ws_client=MagicMock(spec=WorkspaceClient))


def _add_teams(db_session: Session, n: int = COUNT) -> None:
    for i in range(n):
        db_session.add(TeamDb(
            id=str(uuid.uuid4()), name=f"team-{i:03d}",
            created_by="admin@example.com", updated_by="admin@example.com",
        ))
    db_session.commit()


class TestBaseRepository:
    def test_get_multi_returns_all_rows_by_default(self, db_session: Session):
        from src.repositories.teams_repository import team_repo
        _add_teams(db_session)
        assert len(team_repo.get_multi(db_session)) == COUNT

    def test_get_multi_honours_explicit_limit(self, db_session: Session):
        from src.repositories.teams_repository import team_repo
        _add_teams(db_session)
        assert len(team_repo.get_multi(db_session, skip=10, limit=5)) == 5


class TestReferenceLists:
    def test_teams_list_all(self, db_session: Session):
        from src.controller.teams_manager import TeamsManager
        _add_teams(db_session)
        assert len(TeamsManager().get_all_teams(db_session)) == COUNT
        assert len(TeamsManager().get_teams_summary(db_session)) == COUNT

    def test_domains_list_all(self, db_session: Session):
        from src.controller.data_domains_manager import DataDomainManager
        from src.repositories.data_domain_repository import data_domain_repo
        for i in range(COUNT):
            db_session.add(DataDomain(
                id=str(uuid.uuid4()), name=f"domain-{i:03d}", created_by="admin@example.com",
            ))
        db_session.commit()
        manager = DataDomainManager(repository=data_domain_repo)
        assert len(manager.get_all_domains(db_session)) == COUNT

    def test_projects_list_all_for_admin(self, db_session: Session):
        from src.controller.projects_manager import ProjectsManager
        for i in range(COUNT):
            db_session.add(ProjectDb(
                id=str(uuid.uuid4()), name=f"project-{i:03d}", project_type="TEAM",
                created_by="admin@example.com", updated_by="admin@example.com",
            ))
        db_session.commit()
        manager = ProjectsManager()
        assert len(manager.get_all_projects(db_session, is_admin=True)) == COUNT
        assert len(manager.get_projects_summary(db_session)) == COUNT


class TestProductsList:
    def test_lists_every_product_by_default(self, db_session: Session):
        for i in range(COUNT):
            pid = str(uuid.uuid4())
            db_session.add(DataProductDb(
                id=pid, name=f"product-{i:03d}", version="1.0.0", status="active",
                version_family_id=pid, created_at=BASE, updated_at=BASE,
            ))
        db_session.commit()
        assert len(_products_manager(db_session).list_products(is_admin=True)) == COUNT

    def test_pages_after_family_collapse(self, db_session: Session):
        # One family with more versions than the old page size, plus two
        # single-version families. Before #1295 the old versions filled the
        # first 100 rows and the other families could vanish.
        fam = str(uuid.uuid4())
        for i in range(COUNT):
            db_session.add(DataProductDb(
                id=str(uuid.uuid4()), name="orders", version=f"{i + 1}.0.0", status="active",
                version_family_id=fam,
                created_at=BASE + timedelta(minutes=i), updated_at=BASE + timedelta(minutes=i),
            ))
        loose_ids = []
        for name in ("customers", "invoices"):
            pid = str(uuid.uuid4())
            loose_ids.append(pid)
            db_session.add(DataProductDb(
                id=pid, name=name, version="1.0.0", status="active",
                version_family_id=pid, created_at=BASE, updated_at=BASE,
            ))
        db_session.commit()

        manager = _products_manager(db_session)
        products = manager.list_products(is_admin=True)
        assert len(products) == 3
        assert set(loose_ids) <= {p.id for p in products}

        page = manager.list_products(is_admin=True, skip=1, limit=1)
        assert len(page) == 1
        assert page[0].id == products[1].id

    def test_published_products_page_after_publication_filter(self, db_session: Session):
        for i in range(COUNT):
            pid = str(uuid.uuid4())
            db_session.add(DataProductDb(
                id=pid, name=f"internal-{i:03d}", version="1.0.0", status="active",
                version_family_id=pid, publication_scope="none",
                created_at=BASE, updated_at=BASE,
            ))
        published = []
        for i in range(3):
            pid = str(uuid.uuid4())
            published.append(pid)
            db_session.add(DataProductDb(
                id=pid, name=f"published-{i}", version="1.0.0", status="active",
                version_family_id=pid, publication_scope="organization",
                created_at=BASE + timedelta(days=1), updated_at=BASE + timedelta(days=1),
            ))
        db_session.commit()

        manager = _products_manager(db_session)
        assert {p.id for p in manager.get_published_products()} == set(published)
        assert len(manager.get_published_products(limit=2)) == 2


class TestContractsList:
    def test_lists_every_contract_by_default(self, db_session: Session):
        from src.controller.data_contracts_manager import DataContractsManager
        for i in range(COUNT):
            cid = str(uuid.uuid4())
            db_session.add(DataContractDb(
                id=cid, name=f"contract-{i:03d}", version="1.0.0", status="active",
                version_family_id=cid, created_at=BASE, updated_at=BASE,
            ))
        db_session.commit()
        manager = DataContractsManager(data_dir=Path("/tmp"))
        assert len(manager.list_contracts_from_db(db_session, is_admin=True)) == COUNT
