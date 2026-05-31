"""
Tier 2 visibility matrix — httpx against a running backend (:8000).

Skipped when TEST_USER_TOKEN is unset or the API is unreachable. Seeds matrix
entities idempotently via admin_ws impersonation, then replays VISIBILITY_CASES.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
import pytest

from tests.matrix.visibility_cases import (
    MATRIX_PERSONAS,
    VisibilityCase,
    VISIBILITY_CASES,
)
from src.common.authorization import (
    TEST_TOKEN_HEADER,
    TEST_USER_EMAIL_HEADER,
    TEST_USER_GROUPS_HEADER,
)

BASE_URL = os.environ.get("VISIBILITY_MATRIX_BASE_URL", "http://localhost:8000")
TEST_TOKEN = os.environ.get("TEST_USER_TOKEN", "")


def _backend_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


if not TEST_TOKEN or not _backend_reachable():
    pytest.skip(
        "Tier 2 visibility matrix requires TEST_USER_TOKEN and backend on :8000",
        allow_module_level=True,
    )


# Live deployments use workspace ``admins`` (not pytest's ``test_admins``).
_LIVE_GROUP_OVERRIDES: Dict[str, List[str]] = {
    "admin_ws": ["admins"],
}

# Matches #462 / settings.yaml — applied to persisted roles when empty (existing DBs).
_ROLE_PERSONA_GROUP_BINDINGS: Dict[str, List[str]] = {
    "Data Governance Officer": ["data-governance-officers"],
    "Data Steward": ["data-stewards"],
    "Data Consumer": ["data-consumers"],
    "Data Producer": ["data-producers"],
    "Security Officer": ["security-officers"],
}


def _sync_persona_role_bindings(client: httpx.Client, admin_headers: Dict[str, str]) -> None:
    """Idempotently backfill assigned_groups on pre-#462 role rows via Settings API."""
    listed = client.get("/api/settings/roles", headers=admin_headers)
    if listed.status_code != 200:
        return
    for role in listed.json():
        expected_groups = _ROLE_PERSONA_GROUP_BINDINGS.get(role.get("name") or "")
        if not expected_groups:
            continue
        current_lower = {g.lower() for g in (role.get("assigned_groups") or [])}
        if all(g.lower() in current_lower for g in expected_groups):
            continue
        merged = list(role.get("assigned_groups") or [])
        for group in expected_groups:
            if group.lower() not in current_lower:
                merged.append(group)
        payload = dict(role)
        payload["assigned_groups"] = merged
        role_id = payload.get("id")
        if not role_id:
            continue
        client.put(
            f"/api/settings/roles/{role_id}",
            headers=admin_headers,
            json=payload,
        )


def _headers(persona_id: str) -> Dict[str, str]:
    p = MATRIX_PERSONAS[persona_id]
    groups = _LIVE_GROUP_OVERRIDES.get(persona_id, p.groups)
    return {
        TEST_TOKEN_HEADER: TEST_TOKEN,
        TEST_USER_EMAIL_HEADER: p.email,
        TEST_USER_GROUPS_HEADER: json.dumps(groups),
    }


def _feature_readable(client: httpx.Client, persona_id: str) -> bool:
    """Return False when PermissionChecker returns 403 for data-products list."""
    r = client.get("/api/data-products", headers=_headers(persona_id))
    return r.status_code == 200


@pytest.fixture(scope="module")
def seeded_entities() -> Dict[str, str]:
    """Idempotent seed via admin_ws; returns name -> id map for teardown."""
    created: List[str] = []
    keys: Dict[str, str] = {}
    admin_h = _headers("admin_ws")

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        _sync_persona_role_bindings(client, admin_h)

        # Teams
        for key, name in [("team_a", "matrix-team-a"), ("team_b", "matrix-team-b")]:
            existing = client.get("/api/teams", headers=admin_h)
            if existing.status_code == 200:
                for t in existing.json():
                    if t.get("name") == name:
                        keys[key] = t["id"]
                        break
            if key not in keys:
                r = client.post(
                    "/api/teams",
                    headers=admin_h,
                    json={"name": name, "title": name, "members": []},
                )
                if r.status_code in (200, 201):
                    keys[key] = r.json()["id"]
                    created.append(f"team:{keys[key]}")

        _TEAM_MEMBERS = {
            "team_a": ("matrix-producer-a@test.local", "user"),
            "team_b": ("matrix-consumer-b@test.local", "user"),
        }
        for team_key, (email, member_type) in _TEAM_MEMBERS.items():
            team_id = keys.get(team_key)
            if not team_id:
                continue
            members = client.get(f"/api/teams/{team_id}/members", headers=admin_h)
            if members.status_code == 200 and any(
                m.get("member_identifier") == email for m in members.json()
            ):
                continue
            client.post(
                f"/api/teams/{team_id}/members",
                headers=admin_h,
                json={"member_type": member_type, "member_identifier": email},
            )

        # Projects + assignments (best-effort; APIs vary by deployment)
        for pkey, pname, owner in [
            ("project_p1", "matrix-project-p1", "team_a"),
            ("project_p2", "matrix-project-p2", "team_b"),
        ]:
            r = client.get("/api/projects", headers=admin_h)
            if r.status_code == 200:
                for p in r.json():
                    if p.get("name") == pname:
                        keys[pkey] = p["id"]
                        break
            if pkey not in keys:
                pr = client.post(
                    "/api/projects",
                    headers=admin_h,
                    json={
                        "name": pname,
                        "project_type": "TEAM",
                        "owner_team_id": keys.get(owner),
                    },
                )
                if pr.status_code in (200, 201):
                    keys[pkey] = pr.json()["id"]
                    created.append(f"project:{keys[pkey]}")

        _PROJECT_TEAMS = {
            "project_p1": ["team_a"],
            "project_p2": ["team_a", "team_b"],
        }
        for project_key, team_keys in _PROJECT_TEAMS.items():
            project_id = keys.get(project_key)
            if not project_id:
                continue
            for team_key in team_keys:
                team_id = keys.get(team_key)
                if not team_id:
                    continue
                client.post(
                    f"/api/projects/{project_id}/teams",
                    headers=admin_h,
                    json={"team_id": team_id},
                )

        # Data products by deterministic name
        for dp_key, dp_name, extra in [
            ("dp_orphan", "matrix-dp-orphan", {}),
            ("dp_project_p1", "matrix-dp-p1", {"project_id": keys.get("project_p1")}),
            ("dp_team_a", "matrix-dp-team-a", {"owner_team_id": keys.get("team_a")}),
            (
                "dp_draft_producer",
                "matrix-dp-draft-producer",
                {"draft_owner_id": "matrix-producer-a@test.local", "status": "draft"},
            ),
        ]:
            lr = client.get("/api/data-products", headers=admin_h)
            if lr.status_code == 200:
                for row in lr.json():
                    if row.get("name") == dp_name:
                        keys[dp_key] = row["id"]
                        break
            if dp_key not in keys:
                payload = {
                    "name": dp_name,
                    "version": "1.0.0",
                    "status": extra.pop("status", "active"),
                    **extra,
                }
                cr = client.post("/api/data-products", headers=admin_h, json=payload)
                if cr.status_code in (200, 201):
                    keys[dp_key] = cr.json()["id"]
                    created.append(f"dp:{keys[dp_key]}")

    yield keys

    # Tear-down only rows we created (tracked in created list)
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        for item in created:
            kind, eid = item.split(":", 1)
            if kind == "dp":
                client.delete(f"/api/data-products/{eid}", headers=admin_h)


def _check_data_product_live(
    case: VisibilityCase, client: httpx.Client, seed: Dict[str, str]
) -> None:
    if not _feature_readable(client, case.viewer):
        pytest.skip(
            f"Persona {case.viewer} cannot READ data-products on this deployment "
            f"(PermissionChecker 403). Ensure #462 group bindings are on roles "
            f"(Settings → Roles, or re-seed role rows)."
        )
    r = client.get("/api/data-products", headers=_headers(case.viewer))
    assert r.status_code == 200
    entity_id = seed.get(case.seed_entity_key)
    if not entity_id:
        pytest.skip(f"Seed missing {case.seed_entity_key}")
    names = {row.get("id") for row in r.json()}
    visible = entity_id in names
    assert visible == case.expected.visible_in_list


def _run_live_case(case: VisibilityCase, seeded_entities: Dict[str, str]) -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        if case.entity == "data_product":
            _check_data_product_live(case, client, seeded_entities)
        else:
            pytest.skip(f"Tier 2 live harness only implements data_product (got {case.entity})")


_LIVE_CASES = [c for c in VISIBILITY_CASES if c.entity == "data_product"]
_DEVIATION_LIVE = [c for c in _LIVE_CASES if c.deviation_id]
_PASS_LIVE = [c for c in _LIVE_CASES if not c.deviation_id]


@pytest.mark.parametrize("case", _PASS_LIVE, ids=[c.param_id for c in _PASS_LIVE])
def test_visibility_matrix_live_pass(case: VisibilityCase, seeded_entities):
    _run_live_case(case, seeded_entities)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            c,
            marks=pytest.mark.xfail(strict=True, reason=c.xfail_reason or c.deviation_id or ""),
        )
        for c in _DEVIATION_LIVE
    ],
    ids=[c.param_id for c in _DEVIATION_LIVE],
)
def test_visibility_matrix_live_deviations(case: VisibilityCase, seeded_entities):
    _run_live_case(case, seeded_entities)
