"""ARF 1.2.0 batch 2, commit 1: separation of duties and the input bounds (#859 review B4).

Covers: no affirmation by the AR's creator or last definition editor; the DNA
ceiling is a fraction in [0, 1]; a participant's Business Role must exist; the
ak5 migration chains on ak4.
"""
import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.controller.authority_resolution_manager import (
    AuthorityInvalidError,
    AuthorityPermissionError,
    AuthorityResolutionManager,
    AuthoritySelfAffirmationError,
)
from src.db_models.business_roles import BusinessRoleDb
from src.models.authority_resolution import AffirmationInput, AuthorityRelationCreate


def _user(email):
    return SimpleNamespace(email=email, username=email, user=email, groups=[])


def _ar_with_approver(mgr, db, *, author, approver="approver@x.com", **kwargs):
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name="SoD AR", affirmations=[AffirmationInput(role="Approver", principal=approver)], **kwargs,
    ), current_user=author)
    db.commit()
    return rel


def _approver_id(mgr, db, rel):
    return mgr.to_read_dict(db, rel)["affirmations"][0]["id"]


def test_creator_cannot_affirm_their_own_definition(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="approver@x.com")
    with pytest.raises(AuthoritySelfAffirmationError) as exc:
        mgr.affirm(db_session, _approver_id(mgr, db_session, rel), affirmed_by="approver@x.com",
                   user=_user("approver@x.com"))
    assert exc.value.code == "authority_self_affirmation"
    assert isinstance(exc.value, AuthorityPermissionError)
    db_session.refresh(rel)
    assert all(not a.affirmed for a in rel.affirmations)


def test_author_match_ignores_case(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="Approver@X.com")
    with pytest.raises(AuthoritySelfAffirmationError):
        mgr.affirm(db_session, _approver_id(mgr, db_session, rel), affirmed_by="approver@x.com",
                   user=_user("approver@x.com"))


def test_last_definition_editor_cannot_affirm(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="author@x.com")
    rel.definition_edited_by = "editor@x.com"
    db_session.commit()
    with pytest.raises(AuthoritySelfAffirmationError):
        mgr.affirm(db_session, _approver_id(mgr, db_session, rel), affirmed_by="editor@x.com",
                   user=_user("approver@x.com"))


def test_another_user_can_affirm(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="author@x.com")
    aff = mgr.affirm(db_session, _approver_id(mgr, db_session, rel), affirmed_by="approver@x.com",
                     user=_user("approver@x.com"))
    assert aff.affirmed is True


def test_editing_a_definition_moves_the_last_editor(db_session):
    from src.models.authority_resolution import AuthorityRelationUpdate
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="author@x.com")
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(object_id="dp-9"),
                        current_user="editor@x.com")
    db_session.commit()
    db_session.refresh(rel)
    assert rel.created_by == "author@x.com"
    assert rel.definition_edited_by == "editor@x.com"


def test_metadata_only_edit_keeps_the_last_definition_editor(db_session):
    from src.models.authority_resolution import AuthorityRelationUpdate
    mgr = AuthorityResolutionManager()
    rel = _ar_with_approver(mgr, db_session, author="author@x.com")
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(description="just a note"),
                        current_user="someone@x.com")
    db_session.commit()
    db_session.refresh(rel)
    assert rel.definition_edited_by == "author@x.com"


@pytest.mark.parametrize("value", [1.5, 5, -0.1, float("nan"), float("inf")])
def test_ceiling_outside_the_unit_interval_is_refused_by_the_model(value):
    with pytest.raises(ValidationError):
        AuthorityRelationCreate(name="Ceiling", dna_max_threshold=value)


@pytest.mark.parametrize("value", [1.5, -0.1, float("nan")])
def test_ceiling_is_refused_by_the_manager_too(db_session, value):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError):
        mgr._validate_ceiling(value)
    with pytest.raises(AuthorityInvalidError):
        mgr.create_relation(db_session, {"name": "Dict payload", "dna_max_threshold": value},
                            caller_is_admin=True)


def test_ceiling_bounds_are_inclusive(db_session):
    mgr = AuthorityResolutionManager()
    for value in (0.0, 1.0):
        rel = mgr.create_relation(db_session, AuthorityRelationCreate(
            name=f"Bound {value}", dna_max_threshold=value), caller_is_admin=True)
        assert rel.dna_max_threshold == value


def _role(db, name):
    role = BusinessRoleDb(id=uuid.uuid4(), name=name, category="governance")
    db.add(role)
    db.commit()
    return role


def test_unknown_business_role_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError) as exc:
        mgr.create_relation(db_session, AuthorityRelationCreate(
            name="Roles", affirmations=[AffirmationInput(
                role="Ghost", business_role_id=str(uuid.uuid4()), principal="p@x.com")],
        ), current_user="author@x.com")
    assert exc.value.code == "authority_invalid"
    db_session.rollback()


def test_malformed_business_role_id_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError):
        mgr.create_relation(db_session, AuthorityRelationCreate(
            name="Roles", affirmations=[AffirmationInput(
                role="Bad", business_role_id="not-a-uuid", principal="p@x.com")],
        ))
    db_session.rollback()


def test_known_business_role_is_accepted(db_session):
    mgr = AuthorityResolutionManager()
    role = _role(db_session, f"Governance Lead {uuid.uuid4().hex[:6]}")
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Roles ok", affirmations=[AffirmationInput(
            role="Governance Lead", business_role_id=str(role.id), principal="g@x.com")],
    ))
    db_session.commit()
    assert rel.id


def _load_migration(name):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_definition_tracking_migration_chains_on_the_grants_head():
    migration = _load_migration("ak5_authority_definition_tracking")
    assert migration.revision == "ak5_authority_definition_tracking"
    assert migration.down_revision == "ak4_authority_resolution_grants"
