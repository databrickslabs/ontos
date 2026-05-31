"""
Canonical visibility scenario matrix for issue #400.

Pure data module — no pytest dependency. Imported by:
  - backend/tests/integration/test_visibility_matrix.py (Tier 1, in-process)
  - backend/tests/e2e/test_visibility_matrix_live.py (Tier 2, live httpx)
  - tests/e2e/playwright/visibility_matrix.spec.ts (Tier 3, mirrors entity rows)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MatrixPersona:
    id: str
    email: str
    groups: List[str]
    team_member_of: List[str]


MATRIX_PERSONAS: Dict[str, MatrixPersona] = {
    "admin_ws": MatrixPersona(
        id="admin_ws",
        email="matrix-admin-ws@test.local",
        # In-process tests use APP_ADMIN_DEFAULT_GROUPS=["test_admins"] (see tests/conftest.py).
        groups=["test_admins"],
        team_member_of=[],
    ),
    "admin_ontos": MatrixPersona(
        id="admin_ontos",
        email="matrix-admin-ontos@test.local",
        groups=["data-governance-officers"],
        team_member_of=[],
    ),
    "producer_a": MatrixPersona(
        id="producer_a",
        email="matrix-producer-a@test.local",
        groups=["data-producers"],
        team_member_of=["team_a"],
    ),
    "consumer_b": MatrixPersona(
        id="consumer_b",
        email="matrix-consumer-b@test.local",
        groups=["data-consumers"],
        team_member_of=["team_b"],
    ),
    "outsider": MatrixPersona(
        id="outsider",
        email="matrix-outsider@test.local",
        groups=[],
        team_member_of=[],
    ),
}


@dataclass(frozen=True)
class VisibilityExpectation:
    visible_in_list: bool
    can_get_by_id: bool
    can_update: bool


@dataclass(frozen=True)
class VisibilityCase:
    case_id: str
    entity: str
    row_state: str
    viewer: str
    seed_entity_key: str
    expected: VisibilityExpectation
    deviation_id: Optional[str] = None
    notes: str = ""

    @property
    def param_id(self) -> str:
        return self.case_id

    @property
    def xfail_reason(self) -> Optional[str]:
        if not self.deviation_id:
            return None
        return f"{self.deviation_id}: {self.notes or 'known deviation'}"


def _case(
    entity: str,
    row_state: str,
    viewer: str,
    seed_entity_key: str,
    visible: bool,
    get_ok: bool,
    update_ok: bool,
    *,
    deviation_id: Optional[str] = None,
    notes: str = "",
) -> VisibilityCase:
    cid = f"{entity}::{row_state}::{viewer}"
    return VisibilityCase(
        case_id=cid,
        entity=entity,
        row_state=row_state,
        viewer=viewer,
        seed_entity_key=seed_entity_key,
        expected=VisibilityExpectation(visible, get_ok, update_ok),
        deviation_id=deviation_id,
        notes=notes,
    )


_DP_CASES: List[VisibilityCase] = [
    _case("data_product", "orphan", "admin_ws", "dp_orphan", True, True, True),
    _case("data_product", "orphan", "producer_a", "dp_orphan", False, False, False),
    _case("data_product", "orphan", "consumer_b", "dp_orphan", False, False, False),
    _case("data_product", "orphan", "outsider", "dp_orphan", False, False, False),
    _case("data_product", "project_p1", "admin_ws", "dp_project_p1", True, True, True),
    _case("data_product", "project_p1", "admin_ontos", "dp_project_p1", True, True, False),
    _case("data_product", "project_p1", "producer_a", "dp_project_p1", True, True, True),
    _case("data_product", "project_p1", "consumer_b", "dp_project_p1", False, False, False),
    _case("data_product", "project_p1", "outsider", "dp_project_p1", False, False, False),
    _case("data_product", "team_owned_a", "producer_a", "dp_team_a", True, True, True),
    _case("data_product", "team_owned_a", "consumer_b", "dp_team_a", False, False, False),
    _case("data_product", "draft_owner", "producer_a", "dp_draft_producer", True, True, True),
    _case("data_product", "draft_owner", "consumer_b", "dp_draft_producer", False, False, False),
    _case("data_product", "orphan", "admin_ontos", "dp_orphan", True, True, False),
]

_DC_CASES: List[VisibilityCase] = [
    _case(
        "data_contract",
        "other_project",
        "producer_a",
        "dc_project_p2",
        False,
        False,
        False,
        deviation_id="DC1",
        notes="GET /data-contracts without project_id does not restrict to caller projects",
    ),
    _case(
        "data_contract",
        "null_project",
        "outsider",
        "dc_null_project",
        False,
        False,
        False,
        deviation_id="DC2",
        notes="project_id IS NULL treated as visible-to-all in list_family_representatives",
    ),
    _case("data_contract", "personal_draft", "producer_a", "dc_draft_producer", True, True, False),
    _case("data_contract", "personal_draft", "consumer_b", "dc_draft_producer", False, False, False),
    _case("data_contract", "published", "outsider", "dc_published", True, True, False),
]

_PR_CASES: List[VisibilityCase] = [
    _case("project", "member_p1", "producer_a", "project_p1", True, True, False),
    _case("project", "member_p1", "consumer_b", "project_p1", False, False, False),
    _case("project", "member_p2", "consumer_b", "project_p2", True, True, False),
    _case(
        "project",
        "forbidden_get",
        "outsider",
        "project_p1",
        False,
        False,
        False,
        deviation_id="PR3",
        notes="GET /api/projects/{id} has no per-user access check",
    ),
]

_AR_CASES: List[VisibilityCase] = [
    _case(
        "asset_review",
        "project_p2",
        "producer_a",
        "ar_project_p2",
        False,
        False,
        False,
        deviation_id="AR1",
        notes="list_review_requests ignores project_id filter",
    ),
]

_AS_CASES: List[VisibilityCase] = [
    _case(
        "asset",
        "linked_dp_p1",
        "producer_a",
        "asset_linked_p1",
        True,
        True,
        False,
        deviation_id="AS1",
        notes="resolve_accessible_asset_ids calls list_products(is_admin=False) without scope; today returns empty",
    ),
]

_GL_CASES: List[VisibilityCase] = [
    _case(
        "glossary",
        "collection",
        "outsider",
        "glossary_collection",
        False,
        False,
        False,
        deviation_id="GL1",
        notes="glossary collections have scope_level but no per-user filter",
    ),
]

_TEAM_CASES: List[VisibilityCase] = [
    _case("team", "member_a", "producer_a", "team_a", True, True, False),
    _case("team", "member_a", "outsider", "team_a", False, False, False),
]

_COMMENT_CASES: List[VisibilityCase] = [
    _case("comment", "on_dp_p1", "producer_a", "comment_dp_p1", True, True, False),
    # Comments without audience are visible to any caller who can open the entity
    _case("comment", "on_dp_p1", "outsider", "comment_dp_p1", True, True, False),
]

_MDM_CASES: List[VisibilityCase] = [
    _case(
        "mdm",
        "project_p2_unscoped",
        "producer_a",
        "mdm_p2",
        False,
        False,
        False,
        deviation_id="MD1",
        notes="MDM list only filters when ?project_id= is passed",
    ),
]

_CM_CASES: List[VisibilityCase] = [
    _case(
        "catalog_commander",
        "uc_only",
        "producer_a",
        "n/a",
        True,
        True,
        False,
        notes="Ontos project/team have zero effect; UC privileges only",
    ),
]

_WF_CASES: List[VisibilityCase] = [
    _case(
        "workflow",
        "project_scoped",
        "producer_a",
        "workflow_p1",
        False,
        False,
        False,
        deviation_id="WF1",
        notes="scope_config controls execution targets not list visibility",
    ),
]

VISIBILITY_CASES: List[VisibilityCase] = (
    _DP_CASES
    + _DC_CASES
    + _PR_CASES
    + _AR_CASES
    + _AS_CASES
    + _GL_CASES
    + _TEAM_CASES
    + _COMMENT_CASES
    + _MDM_CASES
    + _CM_CASES
    + _WF_CASES
)

PLAYWRIGHT_ENTITY_ORDER: List[str] = [
    "data_product",
    "data_contract",
    "asset_review",
    "asset",
    "glossary",
    "project",
    "team",
    "comment",
    "mdm",
    "catalog_commander",
]


def cases_for_entity(entity: str) -> List[VisibilityCase]:
    return [c for c in VISIBILITY_CASES if c.entity == entity]


def cases_for_tier1() -> List[VisibilityCase]:
    return [
        c
        for c in VISIBILITY_CASES
        if c.entity
        in {
            "data_product",
            "data_contract",
            "project",
            "asset_review",
            "asset",
            "team",
            "comment",
        }
    ]
