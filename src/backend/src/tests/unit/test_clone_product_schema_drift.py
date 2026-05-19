"""Tests for ``clone_product_for_new_version`` schema-drift fix.

Earlier versions of the clone routine referenced columns/attributes that no
longer exist on the DB models. The function would raise ``AttributeError``
the moment it touched output ports — so any product with a non-trivial
shape (output ports, management ports, support channels, team members,
SBOMs) could not be cloned for editing.

These tests exercise each entity type and assert the clone is a faithful
copy. They use the in-memory SQLite database wired up by ``conftest.py``.

Background:
- ``OutputPortDb`` no longer has ``expectation`` / ``dataset_name``
- ``SBOMDb`` only has ``type`` / ``url`` (not spdx_version, spdx_id, etc.)
- ``ManagementPortDb`` requires ``content``; uses ``port_type`` / ``url``
- ``SupportDb`` requires ``channel``; uses ``tool`` / ``scope``
- ``DataProductTeamMemberDb`` requires ``username`` (not ``email``)
- The relationship on OutputPortDb is ``sbom`` singular, not ``sboms``
"""
import datetime
import uuid

import pytest
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import (
    DataProductDb,
    DataProductTeamDb,
    DataProductTeamMemberDb,
    InputContractDb,
    ManagementPortDb,
    OutputPortDb,
    SBOMDb,
    SupportDb,
)


def _make_active_source(db: Session, **overrides) -> DataProductDb:
    """Create an ``active`` DP suitable for cloning into a new version."""
    src = DataProductDb(
        id=str(uuid.uuid4()),
        api_version="v1.0.0",
        kind="DataProduct",
        status="active",
        name="source-product",
        version="1.0.0",
        domain="d1",
        tenant=None,
        owner_team_id=None,
        max_level_inheritance=99,
    )
    for k, v in overrides.items():
        setattr(src, k, v)
    db.add(src)
    db.flush()
    return src


class TestCloneOutputPorts:
    def test_clone_preserves_all_output_port_columns(self, db_session: Session):
        """Source product with a fully-populated OutputPort — all real
        columns must survive the clone (the dead refs are gone, the live
        ones round-trip)."""
        src = _make_active_source(db_session)
        port = OutputPortDb(
            product_id=src.id,
            name="sales_table",
            version="1.0.0",
            description="Sales fact table",
            port_type="table",
            contract_id="contract-abc",
            delivery_method_id=None,
            asset_type="table",
            asset_identifier="catalog.sales.fact",
            status="active",
            server='{"host":"x"}',
            contains_pii=True,
            auto_approve=False,
        )
        db_session.add(port)
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        new_port = (
            db_session.query(OutputPortDb).filter_by(product_id=cloned.id).one()
        )
        assert new_port.name == "sales_table"
        assert new_port.description == "Sales fact table"
        assert new_port.port_type == "table"
        assert new_port.contract_id == "contract-abc"
        assert new_port.asset_type == "table"
        assert new_port.asset_identifier == "catalog.sales.fact"
        assert new_port.status == "active"
        assert new_port.server == '{"host":"x"}'
        assert new_port.contains_pii is True
        assert new_port.auto_approve is False


class TestCloneSBOMs:
    def test_clone_carries_sboms_via_singular_relationship(
        self, db_session: Session
    ):
        """Earlier code referenced ``port.sboms`` (plural); the actual
        relationship is ``port.sbom``. The hasattr check silently no-op'd,
        so SBOMs were never cloned. Fix exercises the singular path."""
        src = _make_active_source(db_session)
        port = OutputPortDb(
            product_id=src.id, name="p", version="1.0.0"
        )
        db_session.add(port)
        db_session.flush()
        sbom = SBOMDb(output_port_id=port.id, type="external", url="https://x/sbom.json")
        db_session.add(sbom)
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        new_port = (
            db_session.query(OutputPortDb).filter_by(product_id=cloned.id).one()
        )
        new_sboms = (
            db_session.query(SBOMDb).filter_by(output_port_id=new_port.id).all()
        )
        assert len(new_sboms) == 1
        assert new_sboms[0].type == "external"
        assert new_sboms[0].url == "https://x/sbom.json"


class TestCloneManagementPorts:
    def test_clone_management_port_includes_required_content(
        self, db_session: Session
    ):
        """``content`` is nullable=False on ``ManagementPortDb``. The earlier
        code omitted it (and referenced ``port.endpoint`` which doesn't
        exist), so any product with a management port would IntegrityError
        if the AttributeError didn't fire first."""
        src = _make_active_source(db_session)
        mp = ManagementPortDb(
            product_id=src.id,
            name="discovery",
            content="discoverability",
            port_type="rest",
            url="https://api.example.com/discover",
            channel="ops",
            description="Discovery endpoint",
        )
        db_session.add(mp)
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        new_mp = (
            db_session.query(ManagementPortDb).filter_by(product_id=cloned.id).one()
        )
        assert new_mp.name == "discovery"
        assert new_mp.content == "discoverability"
        assert new_mp.port_type == "rest"
        assert new_mp.url == "https://api.example.com/discover"
        assert new_mp.channel == "ops"


class TestCloneSupportChannels:
    def test_clone_support_includes_required_channel(self, db_session: Session):
        """``channel`` is nullable=False on ``SupportDb``. Earlier code
        omitted it and referenced ``channel.type`` (which doesn't exist).
        Without this fix, any product with a support channel raises on
        clone."""
        src = _make_active_source(db_session)
        sup = SupportDb(
            product_id=src.id,
            channel="email",
            url="mailto:support@example.com",
            description="Email support",
            tool="email",
            scope="interactive",
            invitation_url=None,
        )
        db_session.add(sup)
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        new_sup = (
            db_session.query(SupportDb).filter_by(product_id=cloned.id).one()
        )
        assert new_sup.channel == "email"
        assert new_sup.url == "mailto:support@example.com"
        assert new_sup.tool == "email"
        assert new_sup.scope == "interactive"


class TestCloneTeamMembers:
    def test_clone_team_member_uses_username_not_email(self, db_session: Session):
        """``username`` is the required identity column on
        ``DataProductTeamMemberDb``. Earlier code wrote ``email=member.email``,
        which would AttributeError on read and IntegrityError on commit."""
        src = _make_active_source(db_session)
        team = DataProductTeamDb(
            product_id=src.id, name="data-eng", description="Data eng team"
        )
        db_session.add(team)
        db_session.flush()
        member = DataProductTeamMemberDb(
            team_id=team.id,
            username="alice@example.com",
            name="Alice",
            description="Lead",
            role="owner",
            date_in=datetime.date(2024, 1, 1),
        )
        db_session.add(member)
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        new_team = (
            db_session.query(DataProductTeamDb).filter_by(product_id=cloned.id).one()
        )
        new_member = (
            db_session.query(DataProductTeamMemberDb)
            .filter_by(team_id=new_team.id)
            .one()
        )
        assert new_member.username == "alice@example.com"
        assert new_member.name == "Alice"
        assert new_member.role == "owner"
        assert new_member.date_in == datetime.date(2024, 1, 1)


class TestCloneEverythingTogether:
    def test_clone_full_product_does_not_raise(self, db_session: Session):
        """End-to-end: a product with every entity type clones cleanly.

        Before this fix, this would raise on the first output port
        (AttributeError) or on the first management port
        (IntegrityError on missing ``content``).
        """
        src = _make_active_source(db_session)
        port = OutputPortDb(product_id=src.id, name="p", version="1.0.0", asset_type="table")
        db_session.add(port); db_session.flush()
        db_session.add(SBOMDb(output_port_id=port.id, type="external", url="https://x"))
        db_session.add(
            ManagementPortDb(
                product_id=src.id, name="m", content="discoverability", port_type="rest"
            )
        )
        db_session.add(
            SupportDb(product_id=src.id, channel="slack", url="https://slack/x")
        )
        team = DataProductTeamDb(product_id=src.id, name="t")
        db_session.add(team); db_session.flush()
        db_session.add(
            DataProductTeamMemberDb(team_id=team.id, username="u@example.com")
        )
        db_session.flush()

        mgr = DataProductsManager(db=db_session)
        cloned = mgr.clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0"
        )

        assert cloned.id != src.id
        assert cloned.version == "2.0.0"
        # Each entity type was carried over.
        assert (
            db_session.query(OutputPortDb).filter_by(product_id=cloned.id).count() == 1
        )
        assert (
            db_session.query(ManagementPortDb).filter_by(product_id=cloned.id).count()
            == 1
        )
        assert (
            db_session.query(SupportDb).filter_by(product_id=cloned.id).count() == 1
        )
        new_team_id = (
            db_session.query(DataProductTeamDb).filter_by(product_id=cloned.id).one().id
        )
        assert (
            db_session.query(DataProductTeamMemberDb)
            .filter_by(team_id=new_team_id)
            .count()
            == 1
        )
