"""Unit tests for compliance templates on table and view assets.

Covers the asset host module (which assets a template applies to, the reconcile
call on an asset edit) and the route-level asset access check, with mocks.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.controller import compliance_template_assets as cta
from src.routes import compliance_templates_routes as routes


def _asset(type_name):
    return SimpleNamespace(
        id=uuid.uuid4(),
        asset_type=SimpleNamespace(name=type_name) if type_name else None,
    )


class TestResolveTemplateAsset:

    @pytest.mark.parametrize("type_name", ["Table", "View"])
    def test_tables_and_views_resolve(self, type_name):
        asset = _asset(type_name)
        with patch.object(cta, "asset_repo") as repo:
            repo.get.return_value = asset
            assert cta.resolve_template_asset(MagicMock(), str(asset.id)) is asset

    @pytest.mark.parametrize("type_name", ["Dashboard", "Dataset", "Column", None])
    def test_other_types_are_unsupported(self, type_name):
        with patch.object(cta, "asset_repo") as repo:
            repo.get.return_value = _asset(type_name)
            with pytest.raises(cta.ComplianceTemplateAssetError) as exc:
                cta.resolve_template_asset(MagicMock(), str(uuid.uuid4()))
        assert exc.value.code == "compliance_template_asset_type_unsupported"
        assert exc.value.status_code == 422
        assert exc.value.to_detail()["params"] == {"assetType": type_name}

    def test_missing_asset_is_not_found(self):
        with patch.object(cta, "asset_repo") as repo:
            repo.get.return_value = None
            with pytest.raises(cta.ComplianceTemplateAssetError) as exc:
                cta.resolve_template_asset(MagicMock(), str(uuid.uuid4()))
        assert exc.value.code == "compliance_template_asset_not_found"
        assert exc.value.status_code == 404

    def test_non_uuid_id_is_not_found_without_a_query(self):
        with patch.object(cta, "asset_repo") as repo:
            with pytest.raises(cta.ComplianceTemplateAssetError) as exc:
                cta.resolve_template_asset(MagicMock(), "main.sales.orders")
            repo.get.assert_not_called()
        assert exc.value.code == "compliance_template_asset_not_found"


class TestReconcileAsset:

    @pytest.mark.parametrize("type_name", ["Table", "View"])
    def test_reconciles_tables_and_views(self, type_name):
        db = MagicMock()
        with patch.object(cta, "compliance_templates_manager") as mgr:
            cta.reconcile_asset(db, asset_id="a1", asset_type_name=type_name, user_email="u@x")
        mgr.reconcile_entity.assert_called_once_with(
            db, entity_type="asset", entity_id="a1", user_email="u@x"
        )

    def test_skips_other_asset_types(self):
        with patch.object(cta, "compliance_templates_manager") as mgr:
            cta.reconcile_asset(
                MagicMock(), asset_id="a1", asset_type_name="Dashboard", user_email=None
            )
        mgr.reconcile_entity.assert_not_called()

    def test_never_raises(self):
        db = MagicMock()
        with patch.object(cta, "compliance_templates_manager") as mgr:
            mgr.reconcile_entity.side_effect = RuntimeError("boom")
            cta.reconcile_asset(db, asset_id="a1", asset_type_name="Table", user_email=None)
        # The edit's own transaction is left to the request session.
        db.rollback.assert_not_called()
        db.commit.assert_not_called()


def _run_access(*, entity_type="asset", write, has_asset_rw, linked=False, dpm=True,
                asset=None):
    asset = asset or _asset("Table")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            data_products_manager=MagicMock() if dpm else None,
        )),
    )

    async def _has_feature(*args, **kwargs):
        return has_asset_rw

    with patch.object(routes, "resolve_template_asset", return_value=asset) as resolve, \
            patch.object(routes, "_has_feature", side_effect=_has_feature) as has_feature, \
            patch.object(routes, "assets_manager") as am:
        am.is_asset_accessible.return_value = linked
        asyncio.run(routes._ensure_entity_access(
            request, MagicMock(), MagicMock(), MagicMock(),
            entity_type=entity_type, entity_id=str(asset.id), write=write,
        ))
        return resolve, has_feature, am


class TestEnsureEntityAccess:

    def test_non_asset_entity_types_are_untouched(self):
        resolve, has_feature, _ = _run_access(
            entity_type="data_product", write=True, has_asset_rw=False
        )
        resolve.assert_not_called()
        has_feature.assert_not_called()

    @pytest.mark.parametrize("write", [False, True])
    def test_asset_editor_can_read_and_write(self, write):
        _, has_feature, am = _run_access(write=write, has_asset_rw=True)
        assert has_feature.call_args.args[3:] == ("assets", routes.FeatureAccessLevel.READ_WRITE)
        am.is_asset_accessible.assert_not_called()

    def test_reader_of_a_linked_asset_can_read(self):
        _, _, am = _run_access(write=False, has_asset_rw=False, linked=True)
        assert am.is_asset_accessible.call_args.kwargs["is_admin"] is False

    def test_reader_of_an_unlinked_asset_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            _run_access(write=False, has_asset_rw=False, linked=False)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "compliance_template_asset_read_forbidden"

    def test_reader_is_refused_without_data_products_manager(self):
        with pytest.raises(HTTPException) as exc:
            _run_access(write=False, has_asset_rw=False, linked=True, dpm=False)
        assert exc.value.detail["code"] == "compliance_template_asset_read_forbidden"

    def test_write_without_asset_edit_rights_is_refused_even_if_linked(self):
        with pytest.raises(HTTPException) as exc:
            _run_access(write=True, has_asset_rw=False, linked=True)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "compliance_template_asset_write_forbidden"

    def test_unsupported_asset_maps_to_coded_http_error(self):
        err = cta.ComplianceTemplateAssetError(
            "compliance_template_asset_type_unsupported", "nope", 422, assetType="Dashboard"
        )
        with patch.object(routes, "resolve_template_asset", side_effect=err):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(routes._ensure_entity_access(
                    MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                    entity_type="asset", entity_id="x", write=False,
                ))
        assert exc.value.status_code == 422
        assert exc.value.detail == {
            "code": "compliance_template_asset_type_unsupported",
            "message": "nope",
            "params": {"assetType": "Dashboard"},
        }


class TestHasFeature:

    def test_forbidden_is_false_and_other_errors_propagate(self):
        async def _deny(*args):
            raise HTTPException(status_code=403, detail="no")

        async def _broken(*args):
            raise HTTPException(status_code=500, detail="err")

        level = routes.FeatureAccessLevel.READ_WRITE
        with patch.object(routes, "PermissionChecker") as pc:
            pc.return_value.side_effect = _deny
            assert asyncio.run(routes._has_feature(None, None, None, "assets", level)) is False
            pc.return_value.side_effect = _broken
            with pytest.raises(HTTPException):
                asyncio.run(routes._has_feature(None, None, None, "assets", level))
            pc.return_value.side_effect = None
            pc.return_value.return_value = asyncio.sleep(0)
            assert asyncio.run(routes._has_feature(None, None, None, "assets", level)) is True
