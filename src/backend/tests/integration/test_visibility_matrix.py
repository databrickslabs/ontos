"""
Tier 1 visibility matrix — in-process SQLite + dependency overrides.

Pins today's visibility behavior for issue #400. Deviation rows use
pytest.mark.xfail(strict=True) so fixes surface as unexpected passes.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from tests.matrix.visibility_cases import (
    MATRIX_PERSONAS,
    VisibilityCase,
    cases_for_tier1,
)
from src.common.authorization import is_user_admin
from src.common.config import get_settings
from src.controller.assets_manager import AssetsManager
from src.controller.comments_manager import CommentsManager
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.projects_manager import projects_manager
from src.controller.teams_manager import teams_manager
from src.db_models.comments import CommentDb, CommentStatus, CommentType
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.projects import ProjectDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.repositories.data_contracts_repository import data_contract_repo
from src.repositories.data_products_repository import data_product_repo
from src.repositories.projects_repository import project_repo


# ---------------------------------------------------------------------------
# Deterministic seed (mirrors visibility_matrix_seed.yaml)
# ---------------------------------------------------------------------------

TEAM_A_ID = "matrix-seed-team-a"
TEAM_B_ID = "matrix-seed-team-b"
PROJECT_P1_ID = "matrix-seed-project-p1"
PROJECT_P2_ID = "matrix-seed-project-p2"


@pytest.fixture
def matrix_seed(db_session: Session) -> Dict[str, str]:
    """Insert teams, projects, and entities keyed for matrix cases."""
    keys: Dict[str, str] = {}

    for tid, name in [(TEAM_A_ID, "matrix-team-a"), (TEAM_B_ID, "matrix-team-b")]:
        db_session.add(
            TeamDb(
                id=tid,
                name=name,
                created_by="matrix-seed",
                updated_by="matrix-seed",
            )
        )
    db_session.flush()

    db_session.add(
        TeamMemberDb(
            team_id=TEAM_A_ID,
            member_type="user",
            member_identifier="matrix-producer-a@test.local",
            added_by="matrix-seed",
        )
    )
    db_session.add(
        TeamMemberDb(
            team_id=TEAM_B_ID,
            member_type="user",
            member_identifier="matrix-consumer-b@test.local",
            added_by="matrix-seed",
        )
    )

    db_session.add(
        ProjectDb(
            id=PROJECT_P1_ID,
            name="matrix-project-p1",
            project_type="TEAM",
            owner_team_id=TEAM_A_ID,
            created_by="matrix-seed",
            updated_by="matrix-seed",
        )
    )
    db_session.add(
        ProjectDb(
            id=PROJECT_P2_ID,
            name="matrix-project-p2",
            project_type="TEAM",
            owner_team_id=TEAM_B_ID,
            created_by="matrix-seed",
            updated_by="matrix-seed",
        )
    )
    db_session.flush()
    project_repo.assign_team(
        db_session, project_id=PROJECT_P1_ID, team_id=TEAM_A_ID, assigned_by="matrix-seed"
    )
    project_repo.assign_team(
        db_session, project_id=PROJECT_P2_ID, team_id=TEAM_A_ID, assigned_by="matrix-seed"
    )
    project_repo.assign_team(
        db_session, project_id=PROJECT_P2_ID, team_id=TEAM_B_ID, assigned_by="matrix-seed"
    )

    def _dp(key: str, name: str, **kwargs: Any) -> None:
        row = DataProductDb(
            id=str(uuid.uuid4()),
            api_version="v1.0.0",
            kind="DataProduct",
            status=kwargs.pop("status", "active"),
            name=name,
            version="1.0.0",
            **kwargs,
        )
        db_session.add(row)
        db_session.flush()
        keys[key] = row.id

    _dp("dp_orphan", "matrix-dp-orphan")
    _dp("dp_project_p1", "matrix-dp-p1", project_id=PROJECT_P1_ID)
    _dp("dp_team_a", "matrix-dp-team-a", owner_team_id=TEAM_A_ID)
    _dp(
        "dp_draft_producer",
        "matrix-dp-draft-producer",
        status="draft",
        draft_owner_id="matrix-producer-a@test.local",
    )

    def _dc(key: str, name: str, family: str, **kwargs: Any) -> None:
        row = DataContractDb(
            id=str(uuid.uuid4()),
            name=name,
            version="1.0.0",
            version_family_id=family,
            **kwargs,
        )
        db_session.add(row)
        db_session.flush()
        keys[key] = row.id

    _dc("dc_project_p2", "matrix-dc-p2", "matrix-dc-family-p2", project_id=PROJECT_P2_ID)
    _dc("dc_null_project", "matrix-dc-null", "matrix-dc-family-null", project_id=None)
    _dc(
        "dc_draft_producer",
        "matrix-dc-draft",
        "matrix-dc-family-draft",
        draft_owner_id="matrix-producer-a@test.local",
    )
    _dc(
        "dc_published",
        "matrix-dc-published",
        "matrix-dc-family-pub",
        publication_scope="domain",
    )

    ar = DataAssetReviewRequestDb(
        id=str(uuid.uuid4()),
        requester_email="matrix-consumer-b@test.local",
        reviewer_email="matrix-admin-ws@test.local",
        project_id=PROJECT_P2_ID,
    )
    db_session.add(ar)
    db_session.flush()
    keys["ar_project_p2"] = ar.id

    comment = CommentDb(
        entity_type="data_product",
        entity_id=keys["dp_project_p1"],
        comment="matrix visibility comment",
        created_by="matrix-producer-a@test.local",
        status=CommentStatus.ACTIVE,
        comment_type=CommentType.COMMENT,
        project_id=PROJECT_P1_ID,
    )
    db_session.add(comment)
    db_session.flush()
    keys["comment_dp_p1"] = str(comment.id)

    keys["project_p1"] = PROJECT_P1_ID
    keys["project_p2"] = PROJECT_P2_ID
    keys["team_a"] = TEAM_A_ID
    db_session.commit()
    return keys


@pytest.fixture
def dp_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session,
        ws_client=MagicMock(),
        notifications_manager=MagicMock(),
        tags_manager=MagicMock(),
    )


def _resolve_scope(
    db: Session, persona_id: str, settings
) -> tuple[bool, str, List[str], List[str]]:
    """Return (is_list_admin, email, team_ids, project_ids)."""
    persona = MATRIX_PERSONAS[persona_id]
    ws_admin = is_user_admin(persona.groups, settings)
    # Ontos data-products Admin (governance officer) bypasses list scope like routes do.
    is_list_admin = ws_admin or persona_id == "admin_ontos"

    teams = teams_manager.get_teams_for_user(db, persona.email, persona.groups)
    team_ids = [t.id for t in teams if getattr(t, "id", None)]
    access = projects_manager.get_user_projects(db, persona.email, persona.groups)
    project_ids = [p.id for p in access.projects if getattr(p, "id", None)]
    return is_list_admin, persona.email, team_ids, project_ids


def _assert_data_product(
    case: VisibilityCase,
    db: Session,
    seed: Dict[str, str],
    manager: DataProductsManager,
    settings,
) -> None:
    is_admin, email, team_ids, project_ids = _resolve_scope(db, case.viewer, settings)
    entity_id = seed[case.seed_entity_key]
    listed = manager.list_products(
        is_admin=is_admin,
        caller_email=email,
        caller_team_ids=team_ids,
        caller_project_ids=project_ids,
    )
    visible = any(str(p.id) == entity_id for p in listed)
    assert visible == case.expected.visible_in_list

    got = data_product_repo.get(db, id=entity_id)
    can_get = got is not None and visible
    assert can_get == case.expected.can_get_by_id

    can_update = False
    with patch("src.common.config.get_settings", return_value=settings):
        if case.expected.can_update:
            try:
                manager.update_product_with_auth(
                    product_id=entity_id,
                    product_data_dict={"title": "matrix-update-attempt"},
                    user_email=email,
                    user_groups=MATRIX_PERSONAS[case.viewer].groups,
                    db=db,
                    caller_team_ids=team_ids,
                )
                can_update = True
            except PermissionError:
                can_update = False
        else:
            with pytest.raises(PermissionError):
                manager.update_product_with_auth(
                    product_id=entity_id,
                    product_data_dict={"title": "matrix-update-denied"},
                    user_email=email,
                    user_groups=MATRIX_PERSONAS[case.viewer].groups,
                    db=db,
                    caller_team_ids=team_ids,
                )
            can_update = False
    assert can_update == case.expected.can_update


def _assert_data_contract(case: VisibilityCase, db: Session, seed: Dict[str, str], settings) -> None:
    persona = MATRIX_PERSONAS[case.viewer]
    is_admin = is_user_admin(persona.groups, settings)
    access = projects_manager.get_user_projects(db, persona.email, persona.groups)
    project_ids = [p.id for p in access.projects if getattr(p, "id", None)]

    rows = data_contract_repo.list_family_representatives(
        db,
        user_email=persona.email,
        is_admin=is_admin,
        project_id=None,
    )
    entity_id = seed[case.seed_entity_key]
    visible = any(r.id == entity_id for r in rows)
    assert visible == case.expected.visible_in_list

    if case.expected.can_get_by_id:
        assert data_contract_repo.get(db, id=entity_id) is not None
    else:
        if visible:
            pytest.fail("can_get_by_id False but row appeared in list")


def _assert_project(case: VisibilityCase, db: Session, seed: Dict[str, str]) -> None:
    persona = MATRIX_PERSONAS[case.viewer]
    access = projects_manager.get_user_projects(db, persona.email, persona.groups)
    project_ids = {p.id for p in access.projects}
    entity_id = seed[case.seed_entity_key]
    visible = entity_id in project_ids
    assert visible == case.expected.visible_in_list

    if case.deviation_id == "PR3":
        got = projects_manager.get_project_by_id(db, entity_id)
        can_get = got is not None
        assert can_get == case.expected.can_get_by_id
    else:
        assert visible == case.expected.can_get_by_id


def _assert_asset_review(case: VisibilityCase, db: Session, seed: Dict[str, str]) -> None:
    mgr = DataAssetReviewManager(
        db=db, ws_client=MagicMock(), notifications_manager=MagicMock()
    )
    entity_id = seed[case.seed_entity_key]
    rows = mgr.list_review_requests()
    visible = any(r.id == entity_id for r in rows)
    assert visible == case.expected.visible_in_list


def _assert_asset(
    case: VisibilityCase,
    db: Session,
    seed: Dict[str, str],
    manager: DataProductsManager,
    settings,
) -> None:
    is_list_admin, email, team_ids, project_ids = _resolve_scope(db, case.viewer, settings)
    assets_mgr = AssetsManager(db=db, ws_client=MagicMock())
    ids = assets_mgr.resolve_accessible_asset_ids(
        db,
        data_products_manager=manager,
        is_admin=is_list_admin,
    )
    # AS1: producer has scoped DPs but list_products is called without scope → empty
    if case.deviation_id == "AS1":
        products = manager.list_products(
            is_admin=False,
            caller_email=email,
            caller_team_ids=team_ids,
            caller_project_ids=project_ids,
        )
        visible = len(products) > 0
    else:
        visible = ids is not None and len(ids) > 0
    assert visible == case.expected.visible_in_list


def _assert_team(case: VisibilityCase, db: Session, seed: Dict[str, str]) -> None:
    persona = MATRIX_PERSONAS[case.viewer]
    teams = teams_manager.get_teams_for_user(db, persona.email, persona.groups)
    entity_id = seed[case.seed_entity_key]
    visible = any(t.id == entity_id for t in teams)
    assert visible == case.expected.visible_in_list


def _assert_comment(case: VisibilityCase, db: Session, seed: Dict[str, str]) -> None:
    persona = MATRIX_PERSONAS[case.viewer]
    dp_id = seed["dp_project_p1"]
    mgr = CommentsManager()
    teams = teams_manager.get_teams_for_user(db, persona.email, persona.groups)
    team_ids = [t.id for t in teams if getattr(t, "id", None)]
    resp = mgr.list_comments(
        db,
        entity_type="data_product",
        entity_id=dp_id,
        project_id=PROJECT_P1_ID,
        user_groups=persona.groups,
        user_teams=team_ids,
        user_email=persona.email,
    )
    comment_id = seed[case.seed_entity_key]
    visible = any(str(c.id) == comment_id for c in resp.comments)
    assert visible == case.expected.visible_in_list


def _run_case(
    case: VisibilityCase,
    db_session: Session,
    matrix_seed: Dict[str, str],
    dp_manager: DataProductsManager,
    test_settings,
) -> None:
    if case.entity == "data_product":
        _assert_data_product(case, db_session, matrix_seed, dp_manager, test_settings)
    elif case.entity == "data_contract":
        _assert_data_contract(case, db_session, matrix_seed, test_settings)
    elif case.entity == "project":
        _assert_project(case, db_session, matrix_seed)
    elif case.entity == "asset_review":
        _assert_asset_review(case, db_session, matrix_seed)
    elif case.entity == "asset":
        _assert_asset(case, db_session, matrix_seed, dp_manager, test_settings)
    elif case.entity == "team":
        _assert_team(case, db_session, matrix_seed)
    elif case.entity == "comment":
        _assert_comment(case, db_session, matrix_seed)
    else:
        pytest.skip(f"Tier 1 does not execute entity {case.entity}")


_TIER1 = cases_for_tier1()


_DEVIATION_CASES = [c for c in _TIER1 if c.deviation_id]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            c,
            marks=pytest.mark.xfail(strict=True, reason=c.xfail_reason or c.deviation_id or ""),
        )
        for c in _DEVIATION_CASES
    ],
    ids=[c.param_id for c in _DEVIATION_CASES],
)
def test_visibility_matrix_known_deviations(
    case: VisibilityCase, db_session, matrix_seed, dp_manager, test_settings
):
    _run_case(case, db_session, matrix_seed, dp_manager, test_settings)


@pytest.mark.parametrize(
    "case",
    [c for c in _TIER1 if not c.deviation_id],
    ids=[c.param_id for c in _TIER1 if not c.deviation_id],
)
def test_visibility_matrix_expected_pass(
    case: VisibilityCase, db_session, matrix_seed, dp_manager, test_settings
):
    _run_case(case, db_session, matrix_seed, dp_manager, test_settings)
