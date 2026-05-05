"""End-to-end test for the on_first_access trigger + per-user consent flow.

Replaces the legacy welcome-disclaimer browser-flag dialog. The flow:

1. Admin creates an `on_first_access` approval workflow with
   ``entity_types: ["user"]``, a ``legal_document`` step, and
   ``persist_agreement``.
2. ``GET /api/user/pending-approvals`` returns the workflow for the current
   user (no agreement yet at the current ``workflow.version``).
3. The user creates a wizard session against ``entity_type='user'`` /
   ``entity_id=<their email>`` and walks it to completion.
4. ``GET /api/user/pending-approvals`` returns an empty list (consent recorded
   in the ``agreements`` table at the current version).
5. Bumping the workflow version (admin edit) → endpoint surfaces it again.
6. Disabling the workflow → endpoint never returns it regardless of consent.

Run directly:
    python3 src/e2e/test_on_first_access_disclaimer.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


# ---------------------------------------------------------------------------
# Config + auth
# ---------------------------------------------------------------------------

BASE = os.environ.get(
    "ONTOS_E2E_BASE",
    "https://ontos-7474659920352264.aws.databricksapps.com",
).rstrip("/")
PROFILE = os.environ.get("ONTOS_E2E_PROFILE", "account-workspace")

RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
RUN_TAG = f"E2E-OnFirstAccess-{RUN_TS}-{uuid.uuid4().hex[:6]}"


def _databricks_token() -> str:
    out = subprocess.run(
        ["databricks", "auth", "token", "--profile", PROFILE],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)["access_token"]


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_databricks_token()}",
        "Content-Type": "application/json",
    }


def _get(path: str) -> requests.Response:
    return requests.get(f"{BASE}{path}", headers=_headers(), timeout=30)


def _post(path: str, body: Dict[str, Any]) -> requests.Response:
    return requests.post(f"{BASE}{path}", headers=_headers(), json=body, timeout=30)


def _put(path: str, body: Dict[str, Any]) -> requests.Response:
    return requests.put(f"{BASE}{path}", headers=_headers(), json=body, timeout=30)


def _delete(path: str) -> requests.Response:
    return requests.delete(f"{BASE}{path}", headers=_headers(), timeout=30)


# ---------------------------------------------------------------------------
# Pretty test runner — same shape as the other E2E scripts in this directory
# ---------------------------------------------------------------------------

class Results:
    def __init__(self) -> None:
        self.entries: List[Tuple[str, bool, str]] = []

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {name}" + (f"  — {detail}" if detail else ""))
        self.entries.append((name, passed, detail))

    def summary(self) -> int:
        passed = sum(1 for _, p, _ in self.entries if p)
        total = len(self.entries)
        print("\n" + "=" * 72)
        print(f"on_first_access E2E — {passed}/{total} scenarios passed")
        print("=" * 72)
        for name, p, _ in self.entries:
            print(f"  {'PASS' if p else 'FAIL':4}  {name}")
        return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Workflow + session helpers
# ---------------------------------------------------------------------------

def _build_workflow_body(name: str, *, is_active: bool, body_markdown: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": "E2E on_first_access test workflow",
        "workflow_type": "approval",
        "trigger": {"type": "on_first_access", "entity_types": ["user"]},
        "scope": {"type": "all"},
        "is_active": is_active,
        "is_default": False,
        "steps": [
            {
                "step_id": "tou",
                "name": "Terms of Use",
                "step_type": "legal_document",
                "config": {
                    "title": "E2E Terms of Use",
                    "description": "Test ToU",
                    "body_markdown": body_markdown,
                    "require_scroll_to_end": False,
                    "require_acknowledgement_checkbox": True,
                    "acknowledgement_label": "I accept",
                },
                "on_pass": "persist",
                "order": 0,
            },
            {
                "step_id": "persist",
                "name": "Record Acceptance",
                "step_type": "persist_agreement",
                "config": {},
                "on_pass": "done",
                "order": 1,
            },
            {
                "step_id": "done",
                "name": "Complete",
                "step_type": "pass",
                "config": {},
                "order": 2,
            },
        ],
    }


def _create_workflow(body: Dict[str, Any]) -> str:
    r = _post("/api/workflows", body)
    r.raise_for_status()
    return r.json()["id"]


def _update_workflow(workflow_id: str, body: Dict[str, Any]) -> None:
    r = _put(f"/api/workflows/{workflow_id}", body)
    r.raise_for_status()


def _delete_workflow(workflow_id: str) -> None:
    try:
        _delete(f"/api/workflows/{workflow_id}")
    except Exception:
        pass


def _user_email() -> str:
    r = _get("/api/user/details")
    r.raise_for_status()
    d = r.json()
    return d.get("email") or d.get("user") or ""


def _pending_workflow_ids() -> List[str]:
    r = _get("/api/user/pending-approvals")
    r.raise_for_status()
    return [w["workflow_id"] for w in r.json().get("workflows", [])]


def _walk_wizard(workflow_id: str, user_email: str) -> Optional[str]:
    """Create a session, submit the legal_document + persist + done steps,
    return the agreement_id."""
    create = _post(
        "/api/approvals/sessions",
        {
            "workflow_id": workflow_id,
            "entity_type": "user",
            "entity_id": user_email,
        },
    )
    create.raise_for_status()
    session = create.json()
    session_id = session["session_id"]
    current = session.get("current_step") or {}

    # Submit legal_document
    if current.get("step_type") == "legal_document":
        step_id = current.get("step_id") or "tou"
        sub = _post(
            f"/api/approvals/sessions/{session_id}/steps",
            {"step_id": step_id, "payload": {"acknowledged": True, "scrolled_to_end": True}},
        )
        sub.raise_for_status()
        result = sub.json()
        # persist_agreement is non-visual and auto-advances; the next response
        # should already be the completion summary.
        if result.get("complete"):
            return result.get("agreement_id")
        # If the wizard surfaces persist as its own step, submit it to advance.
        nxt = result.get("current_step") or {}
        if nxt.get("step_type") == "persist_agreement":
            sub2 = _post(
                f"/api/approvals/sessions/{session_id}/steps",
                {"step_id": nxt.get("step_id", "persist"), "payload": {}},
            )
            sub2.raise_for_status()
            r2 = sub2.json()
            if r2.get("complete"):
                return r2.get("agreement_id")
    return None


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"=== on_first_access E2E ({RUN_TAG}) ===")
    print(f"Target: {BASE}")
    print(f"Auth profile: {PROFILE}")

    health = _get("/api/health")
    if health.status_code not in (200, 401):
        print(f"FATAL: health check failed: {health.status_code} {health.text[:200]}")
        return 1

    user_email = _user_email()
    if not user_email:
        print("FATAL: could not resolve current user email")
        return 1
    print(f"Current user: {user_email}")

    results = Results()
    created_workflows: List[str] = []

    try:
        # ----- S1: fresh workflow → endpoint surfaces it -----
        wf_name = f"{RUN_TAG}-active"
        wf_id = _create_workflow(
            _build_workflow_body(wf_name, is_active=True, body_markdown="v1 text")
        )
        created_workflows.append(wf_id)
        pending = _pending_workflow_ids()
        results.add(
            "S1 fresh workflow appears in pending-approvals",
            wf_id in pending,
            f"pending={pending}",
        )

        # ----- S2: walk wizard → consent persists -----
        agreement_id = _walk_wizard(wf_id, user_email)
        results.add(
            "S2 wizard completes and creates agreement",
            bool(agreement_id),
            f"agreement_id={agreement_id}",
        )

        # ----- S3: re-fetch → workflow no longer pending -----
        pending_after = _pending_workflow_ids()
        results.add(
            "S3 workflow drops from pending after consent",
            wf_id not in pending_after,
            f"pending_after={pending_after}",
        )

        # ----- S4: bump workflow version → re-prompted -----
        # Updating the workflow body bumps the version on the backend.
        _update_workflow(
            wf_id,
            _build_workflow_body(wf_name, is_active=True, body_markdown="v2 — text changed"),
        )
        # Tiny pause so the version increment is durable
        time.sleep(0.5)
        pending_v2 = _pending_workflow_ids()
        results.add(
            "S4 version bump re-prompts the user",
            wf_id in pending_v2,
            f"pending_v2={pending_v2}",
        )

        # ----- S5: disabled workflow → never returned -----
        disabled_name = f"{RUN_TAG}-disabled"
        wf_disabled = _create_workflow(
            _build_workflow_body(disabled_name, is_active=False, body_markdown="disabled text")
        )
        created_workflows.append(wf_disabled)
        pending_dis = _pending_workflow_ids()
        results.add(
            "S5 disabled workflow not returned",
            wf_disabled not in pending_dis,
            f"pending_dis={pending_dis}",
        )

    finally:
        # Cleanup created workflows (agreements stay — no public DELETE)
        for wf in created_workflows:
            _delete_workflow(wf)

    return results.summary()


if __name__ == "__main__":
    sys.exit(main())
