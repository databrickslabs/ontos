"""ARF 1.2.0 batch 2, commit 4: version lifecycle, prerequisites by version and the migrations
(#859 review B7 prerequisites, B8, S1, S2, S6, N6).

Covers: a draft's prerequisite edit leaves the active version's resolve unchanged; New Version copies
the edges, domains (primary kept), tags with values, owners and metadata; a cycle is refused; deleting
a version with history is refused (409, retire instead); activating a version retires the family's
other active ones; version strings are validated and unique; the ak8 data move and ah1's SQL, run for real
on SQLite where SQLite can run them.
"""
import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.controller.authority_resolution_manager import (
    AuthorityDuplicateVersionError,
    AuthorityHasHistoryError,
    AuthorityInvalidError,
    AuthorityInvalidVersionError,
    AuthorityResolutionManager,
    AuthorityStatusError,
    STATUS_ACTIVE,
    STATUS_DRAFT,
    STATUS_RETIRED,
    VERDICT_APPROVED,
    VERDICT_DENIED,
)
from src.db_models.authority_resolution import AuthorityDecisionDb, AuthorityPrerequisiteDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.data_domains import DataDomain
from src.db_models.metadata import LinkMetadataDb, RichTextMetadataDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.authority_resolution import (
    AffirmationInput,
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    PrerequisiteInput,
)


def _user(email):
    return SimpleNamespace(email=email, username=email, user=email, groups=[])


def _pass():
    return [CriterionInput(name="Not blocked", rule="ASSERT obj.actor_identity != 'nobody'")]


def _gate(value_limit):
    return [CriterionInput(name="Cap", rule=f"ASSERT obj.value <= {value_limit}")]


def _ar(mgr, db, slug, *, criteria=None, prerequisites=None, caller_is_admin=True, **kwargs):
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug, criteria=criteria or _pass(),
        prerequisites=prerequisites, object_id="dp-1",
        justification_chain={"policy_id": "p"}, **kwargs,
    ), current_user="author@x.com", caller_is_admin=caller_is_admin)
    db.commit()
    return rel


def _activate_directly(db, rel):
    """Set a version active without the gates (for fixtures that aren't about the gates)."""
    rel.status = STATUS_ACTIVE
    db.commit()


# ------------------------------------------------ prerequisites by version (B7)

def test_a_draft_prerequisite_edit_does_not_change_the_active_version(db_session):
    """B7: v1 is active and approves. Adding a failing prerequisite on draft v2 must not change v1."""
    mgr = AuthorityResolutionManager()
    _activate_directly(db_session, _ar(mgr, db_session, "up-cap", criteria=_gate(1)))
    v1 = _ar(mgr, db_session, "main-ar")
    _activate_directly(db_session, v1)
    assert mgr.resolve(db_session, "main-ar", {"value": 5}, record=False)["verdict"] == VERDICT_APPROVED

    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()
    mgr.update_relation(db_session, v2.id, AuthorityRelationUpdate(
        prerequisites=[PrerequisiteInput(prerequisite_family_slug="up-cap", required=True)]))
    db_session.commit()

    still = mgr.resolve(db_session, "main-ar", {"value": 5}, record=False)
    assert still["verdict"] == VERDICT_APPROVED
    assert still["relation_version"] == "1.0.0"
    assert still["prerequisite_chain"] == []
    draft = mgr.resolve(db_session, v2.id, {"value": 5}, record=False, require_active=False)
    assert draft["verdict"] == VERDICT_DENIED
    assert "blocked by prerequisite ar:up-cap" in draft["reason"]


def test_new_version_copies_the_prerequisite_edges(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, "up-copy")
    v1 = _ar(mgr, db_session, "dn-copy", prerequisites=[PrerequisiteInput(prerequisite_family_slug="up-copy")])
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()
    edges_v1 = mgr.list_prerequisites(db_session, v1)
    edges_v2 = mgr.list_prerequisites(db_session, v2)
    assert [e["prerequisite_family_slug"] for e in edges_v1] == ["up-copy"]
    assert [e["prerequisite_family_slug"] for e in edges_v2] == ["up-copy"]
    rows = db_session.query(AuthorityPrerequisiteDb).filter(
        AuthorityPrerequisiteDb.relation_id.in_([v1.id, v2.id])).all()
    assert {r.relation_id for r in rows} == {v1.id, v2.id}  # one owned copy per version


def test_a_prerequisite_cycle_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, "cyc-a", prerequisites=[])
    _ar(mgr, db_session, "cyc-b", prerequisites=[PrerequisiteInput(prerequisite_family_slug="cyc-a")])
    with pytest.raises(AuthorityInvalidError, match="close a cycle"):
        mgr.update_relation(db_session, mgr.resolve_relation_ref(db_session, "cyc-a").id,
                            AuthorityRelationUpdate(prerequisites=[
                                PrerequisiteInput(prerequisite_family_slug="cyc-b")]))
    db_session.rollback()


def test_deleting_the_last_version_is_refused_while_another_family_requires_it(db_session):
    mgr = AuthorityResolutionManager()
    up = _ar(mgr, db_session, "del-up")
    _ar(mgr, db_session, "del-dn", prerequisites=[PrerequisiteInput(prerequisite_family_slug="del-up")])
    with pytest.raises(AuthorityInvalidError, match="prerequisite of del-dn"):
        mgr.delete_relation(db_session, up.id)
    db_session.rollback()


# -------------------------------------------------------- New Version copies (B8)

def _tag(db, name, namespace_name):
    ns = TagNamespaceDb(name=namespace_name)
    db.add(ns)
    db.flush()
    tag = TagDb(name=name, namespace_id=ns.id, status="active")
    db.add(tag)
    db.flush()
    return tag


def test_new_version_copies_domains_tags_owners_and_metadata(db_session):
    mgr = AuthorityResolutionManager()
    suffix = uuid.uuid4().hex[:8]
    primary = DataDomain(id=str(uuid.uuid4()), name=f"Primary {suffix}", created_by="setup@x.com")
    secondary = DataDomain(id=str(uuid.uuid4()), name=f"Secondary {suffix}", created_by="setup@x.com")
    db_session.add_all([primary, secondary])
    db_session.flush()
    role = BusinessRoleDb(id=uuid.uuid4(), name=f"Owner role {suffix}", category="governance")
    db_session.add(role)
    db_session.flush()
    src = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Carried AR", slug=f"carried-{suffix}", criteria=_pass(),
        domain_ids=[primary.id, secondary.id], primary_domain_id=primary.id,
    ), current_user="author@x.com")
    db_session.flush()
    tag = _tag(db_session, f"tier-{suffix}", f"carried-ns-{suffix}")
    db_session.add(EntityTagAssociationDb(tag_id=tag.id, entity_id=src.id,
                                          entity_type="authority_relation", assigned_value="gold"))
    db_session.add(BusinessOwnerDb(id=uuid.uuid4(), object_type="authority_relation", object_id=src.id,
                                   user_email="owner@x.com", user_name="Owner", role_id=role.id, is_active=True))
    db_session.add(RichTextMetadataDb(id=uuid.uuid4(), entity_id=src.id, entity_type="authority_relation",
                                      title="Note", content_markdown="Body"))
    db_session.add(LinkMetadataDb(id=uuid.uuid4(), entity_id=src.id, entity_type="authority_relation",
                                  title="Policy", url="https://example.com/policy"))
    db_session.commit()

    v2 = mgr.create_new_version(db_session, src.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()

    domains = {d["domain_id"]: d["is_primary"] for d in mgr.to_read_dict(db_session, v2)["domains"]}
    assert domains == {primary.id: True, secondary.id: False}
    tags = mgr.to_read_dict(db_session, v2)["tags"]
    assert [(t["fully_qualified_name"] is not None, t["assigned_value"]) for t in tags] == [(True, "gold")]
    owners = db_session.query(BusinessOwnerDb).filter_by(object_type="authority_relation", object_id=v2.id).all()
    assert [o.user_email for o in owners] == ["owner@x.com"]
    notes = db_session.query(RichTextMetadataDb).filter_by(entity_type="authority_relation", entity_id=v2.id).all()
    links = db_session.query(LinkMetadataDb).filter_by(entity_type="authority_relation", entity_id=v2.id).all()
    assert [n.title for n in notes] == ["Note"] and [k.url for k in links] == ["https://example.com/policy"]


def test_a_failed_tag_copy_fails_the_new_version(db_session, monkeypatch):
    from src.controller import tags_manager as tags_module
    mgr = AuthorityResolutionManager()
    src = _ar(mgr, db_session, "tag-fail")
    suffix = uuid.uuid4().hex[:6]
    tag = _tag(db_session, f"t-{suffix}", f"tagfail-ns-{suffix}")
    db_session.add(EntityTagAssociationDb(tag_id=tag.id, entity_id=src.id, entity_type="authority_relation"))
    db_session.commit()

    def broken(self, *args, **kwargs):
        raise RuntimeError("tag store unavailable")

    monkeypatch.setattr(tags_module.TagsManager, "set_tags_for_entity", broken)
    with pytest.raises(RuntimeError):
        mgr.create_new_version(db_session, src.id, "2.0.0", current_user="lars@x.com")
    db_session.rollback()


# ------------------------------------------------------------ version strings (N6)

def test_a_version_must_look_like_semver(db_session):
    mgr = AuthorityResolutionManager()
    src = _ar(mgr, db_session, "fmt")
    for bad in ("2", "2.0", "v2.0.0", "2.0.0-draft", ""):
        with pytest.raises(AuthorityInvalidVersionError) as exc:
            mgr.create_new_version(db_session, src.id, bad, current_user="x@x.com")
        assert exc.value.code == "authority_invalid_version"
    db_session.rollback()


def test_a_duplicate_version_in_the_family_is_refused_with_409(db_session):
    mgr = AuthorityResolutionManager()
    src = _ar(mgr, db_session, "dup")
    mgr.create_new_version(db_session, src.id, "2.0.0", current_user="x@x.com")
    db_session.commit()
    with pytest.raises(AuthorityDuplicateVersionError) as exc:
        mgr.create_new_version(db_session, src.id, "2.0.0", current_user="x@x.com")
    assert exc.value.http_status == 409
    assert exc.value.params == {"version": "2.0.0"}


def test_a_create_payload_version_is_format_checked(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidVersionError):
        mgr.create_relation(db_session, {"name": "Bad version", "version": "one"})
    db_session.rollback()


# ------------------------------------------------------------- delete with history (S1)

def test_delete_with_decisions_is_409_and_keeps_the_history(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, "hist-dec")
    _activate_directly(db_session, rel)
    mgr.resolve(db_session, "hist-dec", {"actor_identity": "a"}, record=True)
    db_session.commit()
    with pytest.raises(AuthorityHasHistoryError) as exc:
        mgr.delete_relation(db_session, rel.id)
    assert exc.value.http_status == 409
    assert exc.value.params["decisions"] == 1
    assert "Retire it instead" in str(exc.value)
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 1


def test_delete_with_dna_runs_is_refused_too(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, "hist-run")
    mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a"}])
    db_session.commit()
    with pytest.raises(AuthorityHasHistoryError) as exc:
        mgr.delete_relation(db_session, rel.id)
    assert exc.value.params["dna_runs"] == 1


def test_delete_of_a_draft_without_history_still_works(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, "hist-none")
    assert mgr.delete_relation(db_session, rel.id) is True


# --------------------------------------------- activating retires the others (S2)

def test_activating_a_version_retires_the_other_active_one_with_timeline_entries(db_session):
    from src.db_models.comments import CommentDb
    mgr = AuthorityResolutionManager()
    v1 = _ar(mgr, db_session, "s2-fam", caller_is_admin=True, affirmations=[
        AffirmationInput(role="Approver", principal="approver@x.com")])
    _activate_directly(db_session, v1)
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()
    aff = mgr.to_read_dict(db_session, v2)["affirmations"][0]
    mgr.affirm(db_session, aff["id"], affirmed_by="approver@x.com", user=_user("approver@x.com"))
    mgr.compute_dnaco(db_session, v2.id, rows=[{"actor_identity": "a"}])
    db_session.commit()

    mgr.set_status(db_session, v2.id, STATUS_ACTIVE, caller_is_admin=True)
    db_session.commit()
    db_session.refresh(v1)
    assert v1.status == STATUS_RETIRED
    timeline = [c.comment for c in db_session.query(CommentDb).filter(
        CommentDb.entity_type == "authority_relation", CommentDb.entity_id == v1.id)]
    assert any("activated in its place" in t for t in timeline)
    # The pinned UUID of the retired version no longer answers as active.
    assert mgr.resolve(db_session, v1.id, {"actor_identity": "a"}, record=False)["verdict"] == "no_authority"


def test_retiring_a_version_refuses_a_draft_transition_and_drafts_cannot_skip_the_gates(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, "gate-skip", affirmations=[])
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert exc.value.params["reason"] == "not_measured"
    assert STATUS_DRAFT == rel.status


# ------------------------------------------------ HTTP mapping of the new errors

def test_route_failure_uses_the_error_status_and_its_code():
    from src.routes.authority_resolution_routes import _failure
    dup = _failure("create_new_version", AuthorityDuplicateVersionError("dup", version="2.0.0"), coded_status=400)
    # A coded refusal keeps its message in detail; its code rides on the cause (the handler reads it).
    assert dup.status_code == 409 and dup.__cause__.code == "authority_duplicate_version"
    bad = _failure("create_new_version", AuthorityInvalidVersionError("bad", version="2"))
    assert bad.status_code == 400 and bad.__cause__.code == "authority_invalid_version"
    hist = _failure("delete_relation", AuthorityHasHistoryError("history"), coded_status=409)
    assert hist.status_code == 409 and hist.__cause__.code == "authority_has_history"


# ----------------------------------------------------------------- migrations

def _load(name):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ak8_chains_on_ak7_and_ah1_is_unchanged_in_its_chain():
    migration = _load("ak8_authority_prerequisites_by_version")
    assert migration.revision == "ak8_authority_prerequisites_by_version"
    assert migration.down_revision == "ak7_authority_activation_history"


def _old_prereq_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE authority_relations (
            id TEXT PRIMARY KEY, slug TEXT UNIQUE, version_family_id TEXT, version TEXT)"""))
        conn.execute(text("CREATE TABLE authority_decisions (id TEXT PRIMARY KEY, relation_version TEXT)"))
        conn.execute(text("""CREATE TABLE authority_prerequisites (
            id TEXT PRIMARY KEY, relation_family_slug TEXT NOT NULL, prerequisite_family_slug TEXT NOT NULL,
            required BOOLEAN NOT NULL, display_order INTEGER NOT NULL, notes TEXT, created_at TEXT)"""))
        # Family "fam": v1 (anchor, slug holder) and v2 (no slug). Upstream "up": one version.
        conn.execute(text("INSERT INTO authority_relations VALUES ('fam-v1', 'fam', 'fam-v1', '1')"))
        conn.execute(text("INSERT INTO authority_relations VALUES ('fam-v2', NULL, 'fam-v1', '2.0.0')"))
        conn.execute(text("INSERT INTO authority_relations VALUES ('up-v1', 'up', 'up-v1', '1.0.0')"))
        conn.execute(text("INSERT INTO authority_decisions VALUES ('d1', '3')"))
        conn.execute(text("INSERT INTO authority_prerequisites VALUES ('e1', 'fam', 'up', 1, 0, 'n', '2026-01-01')"))
        conn.execute(text("INSERT INTO authority_prerequisites VALUES ('e2', 'ghost', 'up', 1, 0, NULL, '2026-01-01')"))
    return engine


def _run(engine, module, step):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, step)()


def test_ak8_upgrade_copies_each_edge_to_every_version_and_drops_orphans():
    engine = _old_prereq_db()
    _run(engine, _load("ak8_authority_prerequisites_by_version"), "upgrade")
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT relation_id, prerequisite_family_slug, prerequisite_version_id, notes
            FROM authority_prerequisites ORDER BY relation_id""")).fetchall()
        version_strings = dict(conn.execute(text("SELECT id, version FROM authority_relations")).fetchall())
        decision_version = conn.execute(text("SELECT relation_version FROM authority_decisions")).scalar()
    assert rows == [("fam-v1", "up", "up-v1", "n"), ("fam-v2", "up", "up-v1", "n")]
    assert version_strings["fam-v1"] == "1.0.0"       # '1' gets '.0.0' (S6)
    assert version_strings["fam-v2"] == "2.0.0"       # already dotted, untouched
    assert decision_version == "3.0.0"


def test_ak8_downgrade_restores_one_family_edge_per_upstream():
    engine = _old_prereq_db()
    module = _load("ak8_authority_prerequisites_by_version")
    _run(engine, module, "upgrade")
    _run(engine, module, "downgrade")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT relation_family_slug, prerequisite_family_slug, notes FROM authority_prerequisites")).fetchall()
    assert rows == [("fam", "up", "n")]


def test_ah1_downgrade_drops_the_default_before_the_cast_and_casts_by_major_version():
    migration = _load("ah1_authority_versioning")
    fake_op = MagicMock()
    with patch.object(migration, "op", fake_op):
        migration.downgrade()
    calls = fake_op.alter_column.call_args_list
    versions = [c for c in calls if c.args[:2] == ("authority_relations", "version")]
    assert versions[0].kwargs.get("server_default") is None         # default dropped first
    cast = next(c for c in versions if "type_" in c.kwargs)
    assert cast.kwargs["postgresql_using"] == "split_part(version, '.', 1)::integer"
    assert versions[-1].kwargs.get("server_default") == "1"         # restored after the cast


def test_ah1_upgrade_appends_the_patch_and_minor_for_bare_integers():
    migration = _load("ah1_authority_versioning")
    fake_op = MagicMock()
    with patch.object(migration, "op", fake_op):
        migration.upgrade()
    casts = [c.kwargs for c in fake_op.alter_column.call_args_list if "type_" in c.kwargs]
    using = {c.kwargs.get("postgresql_using") for c in fake_op.alter_column.call_args_list}
    assert "version || '.0.0'" in using
    assert "relation_version || '.0.0'" in using
    assert all("::varchar" not in str(k.get("postgresql_using")) for k in casts)
