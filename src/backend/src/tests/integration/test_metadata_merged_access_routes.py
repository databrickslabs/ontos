"""Integration tests: /metadata/merged inherits only from sources the caller may open."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestMergedMetadataSourceAccess:
    """/metadata/merged only inherits from contracts and assets the caller may open."""

    @pytest.fixture
    def product(self, db_session: Session):
        from uuid import uuid4
        from src.db_models.assets import AssetDb, AssetTypeDb
        from src.db_models.data_contracts import DataContractDb
        from src.db_models.data_products import DataProductDb, OutputPortDb
        from src.db_models.metadata import RichTextMetadataDb

        product = DataProductDb(
            id=str(uuid4()), name="Orders", status="active", max_level_inheritance=99,
        )
        draft = DataContractDb(
            id=str(uuid4()), name="team-b-draft", version="0.1.0", status="draft",
            version_family_id=str(uuid4()), owner_team_id="team-b",
        )
        db_session.add_all([product, draft])
        dashboard_type = (
            db_session.query(AssetTypeDb).filter(AssetTypeDb.name == "Dashboard").first()
        )
        if dashboard_type is None:  # seeded at startup; create it if the seed is absent
            dashboard_type = AssetTypeDb(id=uuid4(), name="Dashboard")
            db_session.add(dashboard_type)
        db_session.flush()
        dashboard = AssetDb(
            id=uuid4(), name="Overview", asset_type_id=dashboard_type.id,
            location="https://bi/overview",
        )
        db_session.add(dashboard)
        db_session.flush()
        db_session.add_all([
            OutputPortDb(
                id=str(uuid4()), product_id=product.id, name="p", version="1.0.0",
                contract_id=draft.id,
            ),
            OutputPortDb(
                id=str(uuid4()), product_id=product.id, name="d", version="1.0.0",
                asset_identifier="https://bi/overview",
            ),
            RichTextMetadataDb(
                id=uuid4(), entity_type="data_contract", entity_id=draft.id, title="Draft terms",
                content_markdown="x", level=50, inheritable=True,
            ),
            RichTextMetadataDb(
                id=uuid4(), entity_type="asset", entity_id=str(dashboard.id),
                title="Dashboard notes",
                content_markdown="x", level=50, inheritable=True,
            ),
        ])
        db_session.flush()
        return product

    @pytest.fixture
    def access(self, monkeypatch):
        """Set the caller's contracts-admin and assets READ_WRITE rights."""
        from src.app import app
        from src.controller import teams_manager as tm
        from src.routes import assets_routes
        from src.routes.business_lineage_routes import contracts_feature_admin

        monkeypatch.setattr(tm.teams_manager, "get_teams_for_user", lambda db, email, groups: [])

        def set_access(*, contracts_admin: bool, assets_rw: bool):
            async def admin_override():
                return contracts_admin
            app.dependency_overrides[contracts_feature_admin] = admin_override
            monkeypatch.setattr(
                assets_routes, "_user_has_assets_feature", lambda request, user, level: assets_rw,
            )

        yield set_access
        app.dependency_overrides.pop(contracts_feature_admin, None)

    def _titles(self, client: TestClient, product) -> list:
        response = client.get(
            "/api/entities/data_product/metadata/merged", params={"entity_id": product.id},
        )
        assert response.status_code == 200, response.text
        return [rt["title"] for rt in response.json()["rich_texts"]]

    def test_consumer_does_not_inherit_unreadable_sources(
        self, client: TestClient, product, access, monkeypatch,
    ):
        from src.controller.assets_manager import AssetsManager

        access(contracts_admin=False, assets_rw=False)
        # The dashboard is not linked to any product the caller can access
        monkeypatch.setattr(
            AssetsManager, "resolve_accessible_asset_ids", lambda self, db, **kw: [],
        )
        assert self._titles(client, product) == []

    def test_privileged_caller_inherits_all_sources(self, client: TestClient, product, access):
        access(contracts_admin=True, assets_rw=True)
        assert sorted(self._titles(client, product)) == ["Dashboard notes", "Draft terms"]

    def test_explicit_contract_ids_go_through_the_read_check(
        self, client: TestClient, db_session: Session, product, access,
    ):
        from src.db_models.data_contracts import DataContractDb

        draft = db_session.query(DataContractDb).filter(DataContractDb.name == "team-b-draft").one()
        access(contracts_admin=False, assets_rw=False)
        response = client.get(
            "/api/entities/data_domain/metadata/merged",
            params={"entity_id": "d-1", "contract_ids": draft.id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rich_texts"] == []
