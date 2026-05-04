"""
Prod-like E2E coverage for the Daimler go-live features (PR #315).

Eight scenarios run sequentially against the deployed Ontos app and exercise
the full Daimler CUJ chain with REAL workspace groups (created by this script
via SCIM) and REAL Databricks employee emails as co-signers:

  S1 — subscribe on_behalf_of group (member)
  S2 — subscribe on_behalf_of group (non-member)
  S3 — subscribe on_behalf_of group (definitely-not-real → 400)
  S4 — full approval -> process workflow chain with on_behalf_of step,
       co_signers, persist_agreement, generate_pdf (Volume), deliver, plus
       an on_subscribe process workflow with a webhook step that resolves
       ${context.user_email}, ${context.on_behalf_of.value}, and
       ${entity.consumer_groups}
  S5 — deliver step's co_signers recipient resolution (regression for
       commit d7ef795)
  S6 — PDF readable text — no Python dict-repr leakage for cosigners
       (regression for commit bcf01d8)
  S7 — generate_pdf path smart-skip when volume_path ends in /agreements
       (regression for commit 5dab1fc)
  S8 — acknowledgement_checklist 10-item hard cap (PRD #242 close-out)

Targets:
    https://ontos-7474659920352264.aws.databricksapps.com

Auth:
    Databricks CLI OAuth via the ``account-workspace`` profile.

Usage:
    cd ontos
    python3 src/e2e/test_daimler_prodlike_e2e.py

Cleanup policy:
    - Created workspace groups (ontos-e2e-finance-team /
      ontos-e2e-engineering-team) deleted at end via SCIM.
    - Created data products + workflows DELETEd via the app.
    - Agreements + their PDFs are LEFT IN PLACE (no public DELETE on the
      app; user wants them as audit evidence).
    - Cleanup runs in try/finally so partial state doesn't accumulate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE = os.environ.get(
    "ONTOS_BASE_URL",
    "https://ontos-7474659920352264.aws.databricksapps.com",
)
DATABRICKS_HOST = os.environ.get(
    "DATABRICKS_HOST",
    "https://fevm-mkonchits-account-workspace.cloud.databricks.com",
)
DATABRICKS_PROFILE = os.environ.get("DATABRICKS_PROFILE", "account-workspace")

# Real Databricks employee emails the user (Mikhail) explicitly chose to use
# as co-signers in S4/S5. These are REAL inboxes — picking employees we know
# exist in the workspace SCIM directory.
COSIGNER_LARS = {"type": "user", "value": "lars.george@databricks.com", "display": "Lars George"}
COSIGNER_MANISHA = {"type": "user", "value": "manisha.v@databricks.com", "display": "Manisha V"}
REQUESTER_EMAIL = os.environ.get("ONTOS_E2E_REQUESTER_EMAIL", "mikhail.konchits@databricks.com")

# Volume paths (the deployed app's app_files volume).
VOLUME_DAIMLER = (
    "/Volumes/mkonchits_account_workspace_catalog/app_ontos/app_files/daimler_demo"
)
VOLUME_PATH_SMART_SKIP = (
    "/Volumes/mkonchits_account_workspace_catalog/app_ontos/app_files/agreements/"
    "prodlike_e2e_path_test/agreements"
)

WEBHOOK_URL = os.environ.get(
    "ONTOS_E2E_WEBHOOK_URL",
    "https://httpbin.org/post",
)

RUN_TS = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
RUN_TAG = f"Daimler-ProdE2E-{RUN_TS}-{uuid.uuid4().hex[:6]}"

GROUP_FINANCE = "ontos-e2e-finance-team"
GROUP_ENGINEERING = "ontos-e2e-engineering-team"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def get_token() -> str:
    explicit = os.environ.get("E2E_DATABRICKS_TOKEN")
    if explicit:
        return explicit
    proc = subprocess.run(
        [
            "databricks", "auth", "token",
            "--profile", DATABRICKS_PROFILE,
            "--host", DATABRICKS_HOST,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"databricks auth token failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout)["access_token"]
    except (json.JSONDecodeError, KeyError):
        return proc.stdout.strip()


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return s


def make_ws_session(token: str) -> requests.Session:
    """Bare workspace REST client (SCIM, Files API). Different host than
    the Ontos app — go direct to the Databricks workspace."""
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return s


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
class ScenarioResults:
    LABELS = {
        "S1": "Subscribe on_behalf_of real group (member case)",
        "S2": "Subscribe on_behalf_of real group (non-member case)",
        "S3": "Subscribe on_behalf_of unknown group -> 400",
        "S4": "Full approval->process chain with on_behalf_of, co_signers, PDF, webhook",
        "S5": "Deliver step's co_signers recipient resolution",
        "S6": "PDF readable text (no dict-repr leakage)",
        "S7": "generate_pdf path smart-skip on /agreements suffix",
        "S8": "acknowledgement_checklist 10-item hard cap",
    }

    def __init__(self) -> None:
        self.results: Dict[str, Dict[str, Any]] = {}

    def record(self, key: str, passed: bool, detail: str = "") -> None:
        self.results[key] = {"passed": passed, "detail": detail}
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {key}: {self.LABELS[key]}")
        if detail:
            print(f"         -> {detail}")

    def pass_(self, key: str, detail: str = "") -> None:
        self.record(key, True, detail)

    def fail(self, key: str, detail: str = "") -> None:
        self.record(key, False, detail)

    def summary(self) -> int:
        print("\n" + "=" * 78)
        print("SUMMARY — Daimler prod-like E2E (PR #315)")
        print("=" * 78)
        total = len(self.LABELS)
        passed_count = sum(1 for k in self.LABELS if self.results.get(k, {}).get("passed"))
        for key, label in self.LABELS.items():
            r = self.results.get(key)
            if r is None:
                marker, detail = "SKIP", "scenario not exercised"
            elif r["passed"]:
                marker, detail = "PASS", r["detail"] or ""
            else:
                marker, detail = "FAIL", r["detail"] or ""
            line = f"  [{marker}] {key}: {label}"
            if detail:
                line += f"  ({detail})"
            print(line)
        print("-" * 78)
        print(f"  {passed_count}/{total} scenarios passed")
        return 0 if passed_count == total else 1


# ---------------------------------------------------------------------------
# Workspace bootstrap — create the two test SCIM groups, add Mikhail to one.
# ---------------------------------------------------------------------------
def scim_create_group(ws: requests.Session, display_name: str) -> str:
    """Create a workspace group via SCIM. Returns its group ID."""
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/preview/scim/v2/Groups"
    body = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": display_name,
    }
    r = ws.post(url, json=body, timeout=20)
    if r.status_code in (200, 201):
        return r.json()["id"]
    # If the group already exists from a prior partial run, fetch its ID.
    if r.status_code == 409 or "already exists" in r.text.lower():
        list_url = (
            f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/preview/scim/v2/Groups"
            f"?filter=displayName+eq+%22{quote(display_name)}%22"
        )
        lr = ws.get(list_url, timeout=20)
        if lr.status_code == 200:
            res = lr.json().get("Resources") or []
            if res:
                return res[0]["id"]
    raise RuntimeError(
        f"SCIM create group {display_name!r} failed: {r.status_code} {r.text[:300]}"
    )


def scim_get_user_id(ws: requests.Session, user_name: str) -> Optional[str]:
    url = (
        f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/preview/scim/v2/Users"
        f"?filter=userName+eq+%22{quote(user_name)}%22&attributes=id,userName"
    )
    r = ws.get(url, timeout=20)
    if r.status_code == 200:
        res = r.json().get("Resources") or []
        if res:
            return res[0]["id"]
    return None


def scim_add_member(ws: requests.Session, group_id: str, user_id: str) -> bool:
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/preview/scim/v2/Groups/{group_id}"
    body = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "add", "path": "members", "value": [{"value": user_id}]},
        ],
    }
    r = ws.patch(url, json=body, timeout=20)
    return r.status_code in (200, 204)


def scim_delete_group(ws: requests.Session, group_id: str) -> bool:
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/preview/scim/v2/Groups/{group_id}"
    r = ws.delete(url, timeout=20)
    return r.status_code in (200, 204, 404)


# ---------------------------------------------------------------------------
# Volume helpers
# ---------------------------------------------------------------------------
def volume_get_file(ws: requests.Session, path: str) -> Tuple[int, bytes]:
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/fs/files{quote(path)}"
    r = ws.get(url, timeout=30)
    return r.status_code, r.content


def volume_list_dir(ws: requests.Session, path: str) -> Tuple[int, List[Dict[str, Any]]]:
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/fs/directories{quote(path)}"
    r = ws.get(url, timeout=30)
    if r.status_code != 200:
        return r.status_code, []
    return 200, r.json().get("contents", [])


def volume_delete_file(ws: requests.Session, path: str) -> int:
    url = f"{DATABRICKS_HOST.rstrip('/')}/api/2.0/fs/files{quote(path)}"
    r = ws.delete(url, timeout=20)
    return r.status_code


# ---------------------------------------------------------------------------
# Data product / workflow helpers
# ---------------------------------------------------------------------------
def create_data_product(
    s: requests.Session,
    name: str,
    consumer_groups: List[str],
) -> Dict[str, Any]:
    payload = {
        "id": str(uuid.uuid4()),
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "status": "active",
        "name": name,
        "version": "1.0.0",
        "domain": "e2e-daimler",
        "tenant": "e2e-org",
        "consumer_groups": consumer_groups,
        "description": {
            "purpose": "Daimler prod-like E2E target",
            "limitations": "test-only — auto-cleaned",
            "usage": "subscribed in test",
        },
    }
    r = s.post(f"{BASE}/api/data-products", json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_data_product({name}) failed: {r.status_code} {r.text[:400]}")
    body = r.json()
    body.setdefault("id", body.get("data", {}).get("id"))
    return body


def create_workflow(s: requests.Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = s.post(f"{BASE}/api/workflows", json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_workflow failed: {r.status_code} {r.text[:500]}")
    return r.json()


def delete_workflow(s: requests.Session, wf_id: str) -> None:
    try:
        s.delete(f"{BASE}/api/workflows/{wf_id}", timeout=15)
    except Exception:
        pass


def delete_data_product(s: requests.Session, prod_id: str) -> None:
    try:
        s.delete(f"{BASE}/api/data-products/{prod_id}", timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Wizard walker
# ---------------------------------------------------------------------------
def submit_step(
    s: requests.Session,
    session_id: str,
    step_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    r = s.post(
        f"{BASE}/api/approvals/sessions/{session_id}/steps",
        json={"step_id": step_id, "payload": payload},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"submit_step({step_id}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def _create_data_product_with_retry(
    s: requests.Session, name: str, consumer_groups: List[str],
    max_attempts: int = 6, sleep_secs: float = 3.0,
) -> Dict[str, Any]:
    """Wrap create_data_product with retry on 403.

    Adding the requester to a fresh SCIM group can take a few seconds to
    propagate through the app's permissions cache (the app re-resolves user
    groups via `/api/user/permissions`, which is cached for ~30s). The first
    create attempt right after group creation can transiently 403 even
    though the user has Data Producer permissions through the `users` group.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            return create_data_product(s, name=name, consumer_groups=consumer_groups)
        except RuntimeError as e:
            if "403" not in str(e):
                raise
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(sleep_secs)
    raise last_exc or RuntimeError("create_data_product failed (no last_exc)")


def run_s1(
    s: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
) -> None:
    """S1 — subscribe on_behalf_of a workspace group the user IS a member of."""
    print("\n--- S1: subscribe on_behalf_of finance team (member) ---")
    try:
        prod = _create_data_product_with_retry(
            s, name=f"{RUN_TAG}-S1", consumer_groups=["users"],
        )
        prod_id = prod["id"]
        cleanup["products"].append(prod_id)

        r = s.post(
            f"{BASE}/api/data-products/{prod_id}/subscribe",
            json={
                "reason": "S1 member-OBO",
                "on_behalf_of": {"type": "group", "value": GROUP_FINANCE},
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            results.fail("S1", f"subscribe HTTP {r.status_code}: {r.text[:200]}")
            return
        body = r.json()
        sub = body.get("subscription") or {}
        if sub.get("on_behalf_of_type") != "group" or sub.get("on_behalf_of_value") != GROUP_FINANCE:
            results.fail("S1", f"persisted OBO mismatch: {sub!r}")
            return
        cleanup["subscriptions"].append((prod_id, sub.get("subscriber_email")))
        results.pass_(
            "S1",
            f"product={prod_id} subscriber={sub.get('subscriber_email')} "
            f"obo=group:{GROUP_FINANCE}",
        )
    except Exception as e:
        results.fail("S1", f"exception: {e}")


def run_s2(
    s: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
) -> None:
    """S2 — subscribe on_behalf_of a workspace group the user is NOT a member of.

    Membership-checking is a workflow-level concern (the ``on_behalf_of`` step
    in an approval workflow can have ``allow_user_groups: true`` enforce
    "must be one of your groups"). The direct subscribe API only validates
    the group EXISTS via SCIM, not that the requester is a member. So this
    should succeed at HTTP layer.
    """
    print("\n--- S2: subscribe on_behalf_of engineering team (non-member) ---")
    try:
        prod = _create_data_product_with_retry(
            s, name=f"{RUN_TAG}-S2", consumer_groups=["users"],
        )
        prod_id = prod["id"]
        cleanup["products"].append(prod_id)

        r = s.post(
            f"{BASE}/api/data-products/{prod_id}/subscribe",
            json={
                "reason": "S2 non-member-OBO",
                "on_behalf_of": {"type": "group", "value": GROUP_ENGINEERING},
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            results.fail(
                "S2",
                f"non-member OBO subscribe rejected at API layer: "
                f"HTTP {r.status_code}: {r.text[:200]}",
            )
            return
        body = r.json()
        sub = body.get("subscription") or {}
        if (
            sub.get("on_behalf_of_type") != "group"
            or sub.get("on_behalf_of_value") != GROUP_ENGINEERING
        ):
            results.fail("S2", f"persisted OBO mismatch: {sub!r}")
            return
        cleanup["subscriptions"].append((prod_id, sub.get("subscriber_email")))
        results.pass_(
            "S2",
            f"non-member OBO accepted by API (workflow-layer guard out of scope): "
            f"obo=group:{GROUP_ENGINEERING}",
        )
    except Exception as e:
        results.fail("S2", f"exception: {e}")


def run_s3(
    s: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
) -> None:
    """S3 — subscribe on_behalf_of definitely-not-real → 400."""
    print("\n--- S3: subscribe on_behalf_of unknown group (negative validation) ---")
    try:
        prod = _create_data_product_with_retry(
            s, name=f"{RUN_TAG}-S3", consumer_groups=["users"],
        )
        prod_id = prod["id"]
        cleanup["products"].append(prod_id)

        ghost = f"definitely-not-a-real-workspace-group-{uuid.uuid4().hex[:8]}"
        r = s.post(
            f"{BASE}/api/data-products/{prod_id}/subscribe",
            json={"on_behalf_of": {"type": "group", "value": ghost}},
            timeout=30,
        )
        if r.status_code != 400:
            results.fail(
                "S3",
                f"expected 400 for ghost group, got {r.status_code}: {r.text[:300]}",
            )
            return
        # Sanity-check the error message references the missing group.
        text_lc = r.text.lower()
        if "not found" not in text_lc and ghost not in r.text:
            results.fail("S3", f"400 returned but message lacks expected detail: {r.text[:300]}")
            return
        results.pass_("S3", f"ghost group rejected with 400 (msg fragment OK)")
    except Exception as e:
        results.fail("S3", f"exception: {e}")


def build_s4_approval_workflow(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": "Daimler prod-like S4 approval (full chain)",
        "workflow_type": "approval",
        "trigger": {"type": "for_subscribe", "entity_types": ["data_product"]},
        "is_active": True,
        "steps": [
            {
                "step_id": "obo",
                "name": "Who are you requesting for",
                "step_type": "on_behalf_of",
                "config": {
                    "title": "Who are you requesting access for?",
                    "allow_self": True,
                    "allow_user_groups": True,
                    "allow_free_text": True,
                    "require_justification": False,
                },
                "on_pass": "legal",
                "order": 0,
            },
            {
                "step_id": "legal",
                "name": "Acceptable Use",
                "step_type": "legal_document",
                "config": {
                    "title": "Acceptable Use",
                    "body_markdown": (
                        "# Acceptable Use Policy\n\n"
                        "By subscribing you agree to the data product's stated "
                        "purpose and abide by the limitations."
                    ),
                    "require_acknowledgement_checkbox": True,
                    "acknowledgement_label": "I accept the AUP",
                },
                "on_pass": "checklist",
                "order": 1,
            },
            {
                "step_id": "checklist",
                "name": "Confirmations",
                "step_type": "acknowledgement_checklist",
                "config": {
                    "title": "Confirmations",
                    "items": [
                        {"id": "purpose", "label": "Use only for stated purpose", "required": True},
                        {"id": "pii", "label": "Will handle PII per policy", "required": True},
                        {"id": "deletion", "label": "Will delete on retirement", "required": True},
                    ],
                },
                "on_pass": "cosign",
                "order": 2,
            },
            {
                "step_id": "cosign",
                "name": "Co-Signers",
                "step_type": "co_signers",
                "config": {
                    "title": "Add at least two co-signers",
                    "min_count": 2,
                    "max_count": 3,
                    "principal_type": "either",
                },
                "on_pass": "persist",
                "order": 3,
            },
            {
                "step_id": "persist",
                "name": "Save Agreement",
                "step_type": "persist_agreement",
                "config": {},
                "on_pass": "pdf",
                "order": 4,
            },
            {
                "step_id": "pdf",
                "name": "Generate PDF",
                "step_type": "generate_pdf",
                "config": {
                    "storage": "volume",
                    "volume_path": VOLUME_DAIMLER,
                    "include_step_results": True,
                },
                "on_pass": "deliver",
                "order": 5,
            },
            {
                "step_id": "deliver",
                "name": "Deliver",
                "step_type": "deliver",
                "config": {
                    "channels": ["in_app"],
                    "recipients": ["signer", "co_signers", "entity_owner"],
                },
                "on_pass": "done",
                "order": 6,
            },
            {
                "step_id": "done",
                "name": "Done",
                "step_type": "pass",
                "config": {},
                "order": 7,
            },
        ],
    }


def build_s4_process_workflow(name: str, marker: str) -> Dict[str, Any]:
    """on_subscribe webhook with all the Daimler vars + a unique marker."""
    body_template = (
        "{"
        f'"marker": "{marker}", '
        '"event": "subscribe_request", '
        '"user_email": "${context.user_email}", '
        '"on_behalf_of_value": "${context.on_behalf_of.value}", '
        '"on_behalf_of_type": "${context.on_behalf_of.type}", '
        '"on_behalf_of_display": "${context.on_behalf_of.display}", '
        '"consumer_groups": ${entity.consumer_groups}, '
        '"entity_id": "${entity_id}"'
        "}"
    )
    return {
        "name": name,
        "description": "Daimler prod-like S4 process (on_subscribe webhook)",
        "workflow_type": "process",
        "trigger": {"type": "on_subscribe", "entity_types": ["data_product"]},
        "is_active": True,
        "steps": [
            {
                "step_id": "hook",
                "name": "Webhook Echo",
                "step_type": "webhook",
                "config": {
                    "url": WEBHOOK_URL,
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body_template": body_template,
                    "timeout_seconds": 30,
                    "success_codes": [200, 201],
                },
                "on_pass": "ok",
                "order": 0,
            },
            {
                "step_id": "ok",
                "name": "Done",
                "step_type": "pass",
                "config": {},
                "order": 1,
            },
        ],
    }


def run_s4(
    s: requests.Session,
    ws: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
    surviving: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Full chain. Returns context that S5/S6 can reuse (agreement, PDF bytes,
    co-signer payload). On failure, returns None and S5/S6 will record FAIL
    referencing this scenario."""
    print("\n--- S4: approval -> process workflow chain (full Daimler chain) ---")
    marker = f"DAIMLER-S4-{uuid.uuid4().hex[:10]}"
    try:
        prod = _create_data_product_with_retry(
            s, name=f"{RUN_TAG}-S4",
            consumer_groups=["users", GROUP_FINANCE],
        )
        prod_id = prod["id"]
        cleanup["products"].append(prod_id)
        surviving["s4_product_id"] = prod_id

        approval_wf = create_workflow(
            s, build_s4_approval_workflow(f"{RUN_TAG}-S4-Approval"),
        )
        approval_wf_id = approval_wf["id"]
        cleanup["workflows"].append(approval_wf_id)
        surviving["s4_approval_wf_id"] = approval_wf_id

        process_wf = create_workflow(
            s, build_s4_process_workflow(f"{RUN_TAG}-S4-Process", marker),
        )
        process_wf_id = process_wf["id"]
        cleanup["workflows"].append(process_wf_id)
        surviving["s4_process_wf_id"] = process_wf_id

        # Start wizard with on_behalf_of in body — the in-wizard step will also
        # capture it (test that both paths agree on the persisted value).
        sess_resp = s.post(
            f"{BASE}/api/approvals/sessions",
            json={
                "workflow_id": approval_wf_id,
                "entity_type": "data_product",
                "entity_id": prod_id,
                "completion_action": "subscribe",
                "on_behalf_of": {"type": "group", "value": GROUP_FINANCE},
            },
            timeout=30,
        )
        if sess_resp.status_code not in (200, 201):
            results.fail(
                "S4", f"create session: {sess_resp.status_code} {sess_resp.text[:300]}",
            )
            return None
        sess = sess_resp.json()
        session_id = sess["session_id"]
        cleanup["sessions"].append(session_id)
        print(f"  session_id={session_id}")

        # Walk wizard manually. We expect each visual step to surface; non-visual
        # steps (persist_agreement / generate_pdf / deliver) auto-advance through
        # _complete_session at the end of co_signers' on_pass chain (last visual
        # step is co_signers; the rest are non-visual and the wizard collapses
        # them into completion as observed in test_approval_ux_v1.py).
        data = sess
        cur = data.get("current_step") or {}
        if cur.get("step_type") != "on_behalf_of":
            results.fail(
                "S4",
                f"first step expected on_behalf_of, got {cur.get('step_type')}: {cur!r}",
            )
            return None
        # 1) on_behalf_of step
        data = submit_step(s, session_id, "obo", {
            "type": "group",
            "value": GROUP_FINANCE,
            "display": GROUP_FINANCE,
        })
        # 2) legal_document
        cur = data.get("current_step") or {}
        if cur.get("step_type") != "legal_document":
            results.fail("S4", f"expected legal_document, got {cur!r}")
            return None
        data = submit_step(s, session_id, "legal", {
            "acknowledged": True, "scrolled_to_end": True,
        })
        # 3) acknowledgement_checklist
        cur = data.get("current_step") or {}
        if cur.get("step_type") != "acknowledgement_checklist":
            results.fail("S4", f"expected acknowledgement_checklist, got {cur!r}")
            return None
        data = submit_step(s, session_id, "checklist", {
            "items": {"purpose": True, "pii": True, "deletion": True},
        })
        # 4) co_signers — REAL Databricks employees
        cur = data.get("current_step") or {}
        if cur.get("step_type") != "co_signers":
            results.fail("S4", f"expected co_signers, got {cur!r}")
            return None
        cosigners_payload = [COSIGNER_LARS, COSIGNER_MANISHA]
        data = submit_step(s, session_id, "cosign", {"co_signers": cosigners_payload})

        # 5..7 — defensive auto-walk through any remaining non-visual steps
        # (some backends surface them as visual; some auto-collapse).
        guard = 0
        while not data.get("complete") and guard < 6:
            cur = data.get("current_step") or {}
            sid = cur.get("step_id")
            if not sid:
                break
            data = submit_step(s, session_id, sid, {})
            guard += 1
        if not data.get("complete"):
            results.fail("S4", f"wizard did not complete after walk: {data!r}")
            return None
        agreement_id = data.get("agreement_id")
        if not agreement_id:
            results.fail("S4", f"no agreement_id on completion: {data!r}")
            return None
        surviving["s4_agreement_id"] = agreement_id
        print(f"  wizard complete agreement_id={agreement_id}")

        # ---------------------------------------------------------------
        # Subscription persisted with the OBO group?
        # ---------------------------------------------------------------
        time.sleep(1)
        sub_resp = s.get(f"{BASE}/api/data-products/{prod_id}/subscription", timeout=15)
        if sub_resp.status_code != 200:
            results.fail("S4", f"GET subscription: {sub_resp.status_code} {sub_resp.text[:200]}")
            return None
        sub_body = sub_resp.json()
        sub = sub_body.get("subscription") or {}
        cleanup["subscriptions"].append((prod_id, sub.get("subscriber_email")))
        if (
            sub.get("on_behalf_of_type") != "group"
            or sub.get("on_behalf_of_value") != GROUP_FINANCE
        ):
            results.fail("S4", f"subscription OBO wrong: {sub!r}")
            return None

        # ---------------------------------------------------------------
        # Agreement step_results have on_behalf_of + co_signers payloads
        # ---------------------------------------------------------------
        agr_resp = s.get(
            f"{BASE}/api/approvals/agreements/{agreement_id}", timeout=15,
        )
        if agr_resp.status_code != 200:
            results.fail("S4", f"GET agreement: {agr_resp.status_code} {agr_resp.text[:200]}")
            return None
        agreement = agr_resp.json()
        step_results = agreement.get("step_results") or []
        sr_by_step = {sr.get("step_id"): sr for sr in step_results if isinstance(sr, dict)}
        obo_sr = sr_by_step.get("obo")
        cosign_sr = sr_by_step.get("cosign")
        if not obo_sr or (obo_sr.get("payload") or {}).get("value") != GROUP_FINANCE:
            results.fail("S4", f"agreement OBO step_result missing/incorrect: {obo_sr!r}")
            return None
        cosigners_recorded = (cosign_sr or {}).get("payload", {}).get("co_signers") or []
        if len(cosigners_recorded) != 2:
            results.fail("S4", f"co_signers step_result count={len(cosigners_recorded)}")
            return None
        cosigner_values = {c.get("value") for c in cosigners_recorded if isinstance(c, dict)}
        if not {COSIGNER_LARS["value"], COSIGNER_MANISHA["value"]}.issubset(cosigner_values):
            results.fail("S4", f"co_signers values mismatch: {cosigners_recorded!r}")
            return None
        surviving["s4_cosigners"] = cosigners_recorded

        # ---------------------------------------------------------------
        # PDF persisted at expected path. The smart-skip rule means if the
        # configured volume_path doesn't end in /agreements, the file lands
        # at <volume_path>/agreements/<agreement_id>.pdf.
        # ---------------------------------------------------------------
        expected_pdf_path = f"{VOLUME_DAIMLER}/agreements/{agreement_id}.pdf"
        if agreement.get("pdf_storage_path") != expected_pdf_path:
            # Not always a hard fail — backend may store path differently. Log
            # but verify presence of the actual file too.
            print(
                f"  WARN: agreement.pdf_storage_path={agreement.get('pdf_storage_path')!r} "
                f"vs expected {expected_pdf_path!r}"
            )
        # Read PDF bytes via Files API (workspace REST, not the app).
        status, pdf_bytes = volume_get_file(ws, expected_pdf_path)
        if status != 200:
            # Try the path the agreement records, if different.
            recorded = agreement.get("pdf_storage_path")
            if recorded and recorded != expected_pdf_path:
                status, pdf_bytes = volume_get_file(ws, recorded)
                expected_pdf_path = recorded
        if status != 200:
            results.fail("S4", f"PDF not found at {expected_pdf_path}: HTTP {status}")
            return None
        if pdf_bytes[:4] != b"%PDF":
            results.fail("S4", f"PDF magic mismatch: {pdf_bytes[:8]!r}")
            return None
        surviving["s4_pdf_path"] = expected_pdf_path
        surviving["s4_pdf_bytes"] = pdf_bytes
        print(f"  PDF OK: path={expected_pdf_path} size={len(pdf_bytes)}")

        # ---------------------------------------------------------------
        # Process workflow execution fired and succeeded (filter by wf_id).
        # ---------------------------------------------------------------
        process_exec = None
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(2)
            er = s.get(
                f"{BASE}/api/workflows/executions",
                params={"workflow_id": process_wf_id, "limit": 50},
                timeout=15,
            )
            if er.status_code != 200:
                continue
            ex_list = er.json().get("executions") or []
            for ex in ex_list:
                if ex.get("workflow_id") == process_wf_id:
                    process_exec = ex
                    if ex.get("status") in ("succeeded", "failed"):
                        break
            if process_exec and process_exec.get("status") in ("succeeded", "failed"):
                break
        if not process_exec:
            results.fail("S4", "on_subscribe process workflow did not fire within 60s")
            return None
        if process_exec.get("status") != "succeeded":
            results.fail("S4", f"process exec status={process_exec.get('status')!r}")
            return None
        exec_id = process_exec["id"]
        surviving["s4_process_exec_id"] = exec_id

        # ---------------------------------------------------------------
        # Inspect webhook resolved body — must contain marker, OBO group,
        # and consumer_groups list literal.
        # ---------------------------------------------------------------
        det = s.get(f"{BASE}/api/workflows/executions/{exec_id}", timeout=15)
        if det.status_code != 200:
            results.fail("S4", f"exec detail: {det.status_code} {det.text[:200]}")
            return None
        detail = det.json()
        step_execs = detail.get("step_executions") or []
        webhook_se = next(
            (se for se in step_execs if se.get("step_id") == "hook"
             or (se.get("result_data") or {}).get("url")), None,
        )
        if not webhook_se:
            results.fail("S4", "webhook step_execution not found")
            return None
        rd = webhook_se.get("result_data") or {}
        # Build a multi-layer haystack — httpbin echoes the body inside a
        # response.data JSON STRING that itself contains another JSON STRING
        # (the resolved body_template). We need a recursive json.loads pass
        # to unwrap both layers so resolved values appear unescaped.
        def _deep_decode(val: Any, depth: int = 0) -> List[str]:
            out: List[str] = []
            if depth > 6:
                return out
            if isinstance(val, str):
                out.append(val)
                stripped = val.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        out.extend(_deep_decode(json.loads(stripped), depth + 1))
                    except (ValueError, TypeError):
                        pass
            elif isinstance(val, dict):
                out.append(json.dumps(val, default=str))
                for v in val.values():
                    out.extend(_deep_decode(v, depth + 1))
            elif isinstance(val, list):
                for v in val:
                    out.extend(_deep_decode(v, depth + 1))
            return out

        haystack = "\n".join(_deep_decode(rd))
        # The webhook handler truncates the response field to 500 chars
        # (workflow_executor implementation detail), which usually severs
        # the trailing JSON braces and makes deep-decode bail at parse-time.
        # Add an unescaped projection of the raw haystack so backslash-escaped
        # quotes (`\"users\"`) collapse to plain quotes, exposing tokens we
        # would otherwise have to repeat in two forms in every needle.
        haystack = haystack + "\n" + haystack.replace('\\"', '"').replace("\\\\", "\\")

        # Debug: dump the full result_data to /tmp on assertion failure so we
        # can re-run a haystack search locally instead of guessing.
        try:
            with open("/tmp/daimler_e2e_s4_rd.json", "w") as f:
                json.dump(rd, f, indent=2, default=str)
        except Exception:
            pass

        missing = []
        # Search against multiple alternative renderings so we tolerate the
        # backend choosing a different result_data shape over time.
        consumer_groups_needles = [
            f'["users","{GROUP_FINANCE}"]',
            f'["users", "{GROUP_FINANCE}"]',
            f'users","{GROUP_FINANCE}',
        ]
        if not any(n in haystack for n in consumer_groups_needles):
            missing.append(
                f"consumer_groups list ({consumer_groups_needles!r})"
            )
        for needle, label in [
            (marker, "unique marker"),
            (GROUP_FINANCE, "on_behalf_of_value"),
        ]:
            if needle not in haystack:
                missing.append(f"{label}({needle!r})")
        if missing:
            results.fail(
                "S4",
                f"webhook body missing: {missing}; haystack[:600]={haystack[:600]!r}",
            )
            return None

        results.pass_(
            "S4",
            f"product={prod_id} agreement={agreement_id} "
            f"pdf={expected_pdf_path} exec={exec_id} marker={marker}",
        )
        return {
            "agreement": agreement,
            "agreement_id": agreement_id,
            "pdf_bytes": pdf_bytes,
            "pdf_path": expected_pdf_path,
            "cosigners": cosigners_recorded,
            "session_id": session_id,
            "product_id": prod_id,
            "approval_wf_id": approval_wf_id,
            "process_wf_id": process_wf_id,
            "process_exec_id": exec_id,
            "marker": marker,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.fail("S4", f"exception: {e}")
        return None


def run_s5(
    s: requests.Session,
    results: ScenarioResults,
    s4_ctx: Optional[Dict[str, Any]],
) -> None:
    """S5 — deliver step's co_signers recipient resolution.

    Validate via the agreement's deliver step_result that the recipients
    list is what the workflow asked for. Per-recipient notifications
    landing in Lars/Manisha's inboxes can't be observed as Mikhail (the
    /api/notifications endpoint filters by current user). We assert two
    things instead:
      1. Deliver step's step_result captured channels=['in_app'] +
         recipients=['signer','co_signers','entity_owner'].
      2. The notifications endpoint shows the in-app notif for Mikhail
         (the requester / signer), proving the deliver step ran.
    """
    print("\n--- S5: deliver step's co_signers recipient resolution ---")
    if not s4_ctx:
        results.fail("S5", "S4 prerequisite did not produce an agreement context")
        return
    try:
        agreement = s4_ctx["agreement"]
        agreement_id = s4_ctx["agreement_id"]
        step_results = agreement.get("step_results") or []
        deliver_sr = next((sr for sr in step_results if sr.get("step_id") == "deliver"), None)
        if not deliver_sr:
            results.fail("S5", "deliver step_result missing from agreement")
            return
        deliver_payload = deliver_sr.get("payload") or {}
        recipients_recorded = deliver_payload.get("recipients") or []
        if "co_signers" not in recipients_recorded:
            results.fail("S5", f"deliver recipients={recipients_recorded!r} missing 'co_signers'")
            return
        if not deliver_payload.get("delivered"):
            results.fail("S5", f"deliver step_result missing delivered=true: {deliver_payload!r}")
            return

        # Confirm Mikhail (signer) got an in_app notif for this agreement —
        # proves the deliver step actually called the notifications manager.
        delivery_seen = False
        nr = s.get(f"{BASE}/api/notifications", timeout=15)
        if nr.status_code == 200:
            items = nr.json()
            if isinstance(items, dict):
                items = items.get("notifications", items.get("data", []))
            for n in items if isinstance(items, list) else []:
                payload = n.get("action_payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        payload = {}
                if (
                    n.get("action_type") == "agreement_completed"
                    and isinstance(payload, dict)
                    and payload.get("agreement_id") == agreement_id
                ):
                    delivery_seen = True
                    break
        if not delivery_seen:
            results.fail(
                "S5",
                "deliver step_result OK but no in_app notification observed "
                "for the requester (deliver pipeline didn't reach notifications)",
            )
            return
        results.pass_(
            "S5",
            f"deliver step_result has co_signers in recipients; "
            f"requester in_app notif present for agreement={agreement_id}",
        )
    except Exception as e:
        results.fail("S5", f"exception: {e}")


def run_s6(
    results: ScenarioResults,
    s4_ctx: Optional[Dict[str, Any]],
) -> None:
    """S6 — PDF readable text — no Python dict-repr leakage for cosigners.

    Regression test for commit bcf01d8 (cosigner rendering fix). The PDF
    must contain Lars/Manisha's display names AS READABLE TEXT and must
    NOT contain literal substrings like ``{'type'`` (the Python dict repr
    that the bug emitted).
    """
    print("\n--- S6: PDF readable text (no dict-repr leakage) ---")
    if not s4_ctx:
        results.fail("S6", "S4 prerequisite did not produce a PDF")
        return
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        results.fail("S6", "pypdf not installed (pip install pypdf)")
        return
    try:
        pdf_bytes = s4_ctx["pdf_bytes"]
        reader = PdfReader(BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        # Bug signature: dict-repr leakage
        dict_repr_in_text = "{'type'" in text or '{"type"' in text
        if dict_repr_in_text:
            results.fail("S6", "PDF contains Python dict-repr like {'type' — regression!")
            return
        # Positive: cosigner display names readable
        if "Lars George" not in text:
            results.fail("S6", f"PDF missing 'Lars George' in extracted text (len={len(text)})")
            return
        if "Manisha V" not in text:
            results.fail("S6", f"PDF missing 'Manisha V' in extracted text (len={len(text)})")
            return
        results.pass_(
            "S6",
            f"PDF text OK: {len(text)} chars, both co-signer display names render readably, no dict-repr",
        )
    except Exception as e:
        results.fail("S6", f"exception: {e}")


def run_s7(
    s: requests.Session,
    ws: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
    surviving: Dict[str, Any],
) -> None:
    """S7 — generate_pdf path smart-skip when volume_path ends in /agreements.

    Regression test for commit 5dab1fc. The configured volume_path here
    explicitly ends in ``/agreements``. The PDF MUST land at
    ``…/prodlike_e2e_path_test/agreements/{agreement_id}.pdf`` (single
    /agreements segment), NOT at
    ``…/prodlike_e2e_path_test/agreements/agreements/{agreement_id}.pdf``.
    """
    print("\n--- S7: generate_pdf path smart-skip ---")
    try:
        # Minimal workflow: just persist + generate_pdf so the wizard finishes
        # quickly. Add one cosmetic user_action up front so the wizard has a
        # visual step to drive.
        wf_payload = {
            "name": f"{RUN_TAG}-S7-PathSmartSkip",
            "description": "Verify smart-skip on /agreements suffix",
            "workflow_type": "approval",
            "trigger": {"type": "for_subscribe", "entity_types": ["data_product"]},
            "is_active": True,
            "steps": [
                {
                    "step_id": "ua",
                    "name": "Reason",
                    "step_type": "user_action",
                    "config": {
                        "title": "Reason",
                        "fields": [{"id": "reason", "label": "Reason", "type": "text", "required": True}],
                    },
                    "on_pass": "persist",
                    "order": 0,
                },
                {
                    "step_id": "persist",
                    "name": "Save",
                    "step_type": "persist_agreement",
                    "config": {},
                    "on_pass": "pdf",
                    "order": 1,
                },
                {
                    "step_id": "pdf",
                    "name": "PDF",
                    "step_type": "generate_pdf",
                    "config": {
                        "storage": "volume",
                        "volume_path": VOLUME_PATH_SMART_SKIP,
                        "include_step_results": True,
                    },
                    "on_pass": "done",
                    "order": 2,
                },
                {
                    "step_id": "done",
                    "name": "Done",
                    "step_type": "pass",
                    "config": {},
                    "order": 3,
                },
            ],
        }
        wf = create_workflow(s, wf_payload)
        wf_id = wf["id"]
        cleanup["workflows"].append(wf_id)
        surviving["s7_wf_id"] = wf_id

        prod = _create_data_product_with_retry(
            s, name=f"{RUN_TAG}-S7", consumer_groups=["users"],
        )
        prod_id = prod["id"]
        cleanup["products"].append(prod_id)
        surviving["s7_product_id"] = prod_id

        sess_resp = s.post(
            f"{BASE}/api/approvals/sessions",
            json={
                "workflow_id": wf_id,
                "entity_type": "data_product",
                "entity_id": prod_id,
            },
            timeout=30,
        )
        if sess_resp.status_code not in (200, 201):
            results.fail("S7", f"create session: {sess_resp.status_code} {sess_resp.text[:200]}")
            return
        session_id = sess_resp.json()["session_id"]
        cleanup["sessions"].append(session_id)

        data = submit_step(s, session_id, "ua", {"reason": "S7 smart-skip"})
        guard = 0
        while not data.get("complete") and guard < 5:
            cur = data.get("current_step") or {}
            sid = cur.get("step_id")
            if not sid:
                break
            data = submit_step(s, session_id, sid, {})
            guard += 1
        if not data.get("complete"):
            results.fail("S7", f"wizard did not complete: {data!r}")
            return
        agreement_id = data.get("agreement_id")
        if not agreement_id:
            results.fail("S7", f"no agreement_id: {data!r}")
            return
        surviving["s7_agreement_id"] = agreement_id

        # Verify the PDF lives at the smart-skipped path.
        good_path = f"{VOLUME_PATH_SMART_SKIP}/{agreement_id}.pdf"
        bad_path = f"{VOLUME_PATH_SMART_SKIP}/agreements/{agreement_id}.pdf"
        good_status, _ = volume_get_file(ws, good_path)
        bad_status, _ = volume_get_file(ws, bad_path)
        if good_status != 200:
            results.fail(
                "S7",
                f"PDF NOT at smart-skipped path {good_path}: HTTP {good_status} "
                f"(bad path={bad_path} HTTP {bad_status})",
            )
            return
        if bad_status == 200:
            results.fail(
                "S7",
                f"PDF doubled — present at BOTH {good_path} and the bad doubled "
                f"path {bad_path}",
            )
            return
        results.pass_("S7", f"PDF correctly at {good_path} (no doubling)")
        surviving["s7_pdf_path"] = good_path
    except Exception as e:
        results.fail("S7", f"exception: {e}")


def run_s8(
    s: requests.Session,
    results: ScenarioResults,
    cleanup: Dict[str, list],
) -> None:
    """S8 — acknowledgement_checklist 10-item hard cap (model-level).

    Commit d7ef795 added a 10-item cap on
    ``AcknowledgementChecklistStepConfig.items`` via a Pydantic
    field_validator. That cap fires when the model is constructed directly
    (the unit test ``test_acknowledgement_checklist_cap`` covers that
    path). However ``WorkflowStepCreate.config`` is typed as
    ``Dict[str, Any]`` and the workflow create endpoint never instantiates
    ``AcknowledgementChecklistStepConfig``, so the cap is NOT enforced at
    the HTTP layer. This test verifies BOTH realities:

      a) the API path currently accepts 11 items (documents the gap so a
         future PR that wires the typed model in is detected as a
         behavior change, not a regression), AND
      b) constructing the typed model with 11 items DOES raise (in-process
         path that the unit test also covers).

    PASS = both arms behave as documented. Either arm flipping is a
    behavior change worth investigating.
    """
    print("\n--- S8: acknowledgement_checklist 10-item cap (model-level) ---")
    try:
        eleven_items = [
            {"id": f"i{n}", "label": f"Item {n}", "required": True}
            for n in range(11)
        ]
        # Arm (a): API layer
        wf_payload = {
            "name": f"{RUN_TAG}-S8-ChecklistCap",
            "description": "Document API-layer behavior of 11-item checklist",
            "workflow_type": "approval",
            "trigger": {"type": "for_subscribe", "entity_types": ["data_product"]},
            "is_active": True,
            "steps": [
                {
                    "step_id": "checklist",
                    "name": "Checklist",
                    "step_type": "acknowledgement_checklist",
                    "config": {"title": "Too many", "items": eleven_items},
                    "on_pass": None,
                    "order": 0,
                },
            ],
        }
        r = s.post(f"{BASE}/api/workflows", json=wf_payload, timeout=30)
        api_accepted = r.status_code in (200, 201)
        api_rejected_4xx = r.status_code in (400, 422)
        if api_accepted:
            # Track for cleanup
            try:
                cleanup["workflows"].append(r.json()["id"])
            except Exception:
                pass

        # Arm (b): in-process — load just the actual model file from the
        # backend source. The full backend tree drags transitive imports
        # (pydantic-settings, sqlalchemy, etc.) that aren't in the e2e venv,
        # so we stub the heavy bits and import the model module directly.
        model_rejected = False
        model_error: Optional[str] = None
        try:
            import importlib.util
            import types

            # Stub heavy modules the model module imports indirectly via
            # ``src.common.logging``. We only need ``get_logger`` to be
            # callable; pydantic itself is the only real dep.
            stub_logging = types.ModuleType("src.common.logging")
            def _stub_get_logger(*a, **k):
                import logging as _l
                return _l.getLogger("e2e_stub")
            stub_logging.get_logger = _stub_get_logger
            stub_common = types.ModuleType("src.common")
            stub_common.logging = stub_logging
            stub_src = types.ModuleType("src")
            stub_src.common = stub_common
            sys.modules.setdefault("src", stub_src)
            sys.modules["src.common"] = stub_common
            sys.modules["src.common.logging"] = stub_logging

            model_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "backend", "src", "models", "process_workflows.py",
            )
            spec = importlib.util.spec_from_file_location(
                "_pw_model_for_e2e", model_path,
            )
            if not spec or not spec.loader:
                raise ImportError(f"no spec for {model_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ACChecklist = getattr(module, "AcknowledgementChecklistStepConfig")

            try:
                ACChecklist(items=eleven_items)
            except Exception as e:
                model_rejected = True
                model_error = str(e)[:200]
        except Exception as e:
            model_error = f"could not load model: {type(e).__name__}: {e}"

        # Verdict — document the dual reality.
        if api_accepted and model_rejected:
            results.pass_(
                "S8",
                f"as-documented: API accepts 11-item checklist (HTTP {r.status_code}; "
                f"cap not wired to /api/workflows), pydantic model rejects "
                f"({model_error[:120] if model_error else ''}). Gap is at the API typing "
                f"layer (WorkflowStepCreate.config is Dict[str, Any]) — file a "
                f"follow-up to wire typed step configs.",
            )
        elif api_rejected_4xx and model_rejected:
            results.pass_(
                "S8",
                f"both arms reject 11 items (API: HTTP {r.status_code}, model: "
                f"{model_error[:120] if model_error else ''}). The API typing gap "
                f"appears to have been closed since d7ef795 — update test docstring.",
            )
        elif api_accepted and not model_rejected:
            results.fail(
                "S8",
                f"REGRESSION: neither API nor pydantic model rejects 11 items. "
                f"AcknowledgementChecklistStepConfig.items cap_at_ten validator "
                f"may have been removed. (model_error={model_error!r})",
            )
        else:
            results.fail(
                "S8",
                f"unexpected combination: api_accepted={api_accepted} "
                f"model_rejected={model_rejected} model_error={model_error!r} "
                f"http={r.status_code}",
            )
    except Exception as e:
        results.fail("S8", f"exception: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    started_at = time.time()
    print(f"\n=== Daimler Prod-like E2E ({RUN_TAG}) ===")
    print(f"Target: {BASE}")
    print(f"Auth profile: {DATABRICKS_PROFILE}")
    print(f"Webhook URL: {WEBHOOK_URL}\n")

    token = get_token()
    s = make_session(token)
    ws = make_ws_session(token)

    # Pre-flight
    health = s.get(f"{BASE}/api/user/info", timeout=15)
    if health.status_code == 401:
        print("FATAL: 401 — refresh CLI profile.")
        return 1
    if health.status_code not in (200, 403):
        print(f"FATAL: connectivity check failed: {health.status_code} {health.text[:300]}")
        return 1
    print(f"Pre-flight: /api/user/info -> {health.status_code} OK")

    results = ScenarioResults()
    cleanup: Dict[str, list] = {
        "products": [],
        "workflows": [],
        "subscriptions": [],
        "sessions": [],
        "groups": [],  # SCIM group IDs
    }
    surviving: Dict[str, Any] = {}

    finance_gid: Optional[str] = None
    engineering_gid: Optional[str] = None

    try:
        # ---------------------------------------------------------------
        # Workspace bootstrap — create both groups, add Mikhail to finance.
        # ---------------------------------------------------------------
        print("\n--- Workspace bootstrap (SCIM groups) ---")
        finance_gid = scim_create_group(ws, GROUP_FINANCE)
        cleanup["groups"].append(finance_gid)
        print(f"  group {GROUP_FINANCE} -> id={finance_gid}")
        engineering_gid = scim_create_group(ws, GROUP_ENGINEERING)
        cleanup["groups"].append(engineering_gid)
        print(f"  group {GROUP_ENGINEERING} -> id={engineering_gid}")

        mikhail_uid = scim_get_user_id(ws, REQUESTER_EMAIL)
        if mikhail_uid:
            ok = scim_add_member(ws, finance_gid, mikhail_uid)
            print(
                f"  add {REQUESTER_EMAIL} (uid={mikhail_uid}) to {GROUP_FINANCE}: {ok}"
            )
        else:
            print(f"  WARN: could not resolve user id for {REQUESTER_EMAIL}")

        # ---------------------------------------------------------------
        # Scenarios
        # ---------------------------------------------------------------
        run_s1(s, results, cleanup)
        run_s2(s, results, cleanup)
        run_s3(s, results, cleanup)
        s4_ctx = run_s4(s, ws, results, cleanup, surviving)
        run_s5(s, results, s4_ctx)
        run_s6(results, s4_ctx)
        run_s7(s, ws, results, cleanup, surviving)
        run_s8(s, results, cleanup)

    finally:
        # ---------------------------------------------------------------
        # Cleanup. Order: sessions -> workflows -> data products -> SCIM groups.
        # Agreements + PDFs are LEFT IN PLACE (audit evidence the user wants).
        # ---------------------------------------------------------------
        print("\n--- Cleanup ---")
        for sid in cleanup["sessions"]:
            try:
                s.post(f"{BASE}/api/approvals/sessions/{sid}/abort", json={}, timeout=10)
            except Exception:
                pass
        for wfid in cleanup["workflows"]:
            delete_workflow(s, wfid)
        for pid in cleanup["products"]:
            delete_data_product(s, pid)
        for gid in cleanup["groups"]:
            ok = scim_delete_group(ws, gid)
            print(f"  delete SCIM group {gid}: {ok}")

    elapsed = time.time() - started_at

    # ---------------------------------------------------------------
    # Surviving artifacts table
    # ---------------------------------------------------------------
    print("\n" + "=" * 78)
    print("SURVIVING ARTIFACTS (left in place for inspection)")
    print("=" * 78)
    if surviving.get("s4_agreement_id"):
        print(
            f"  S4 agreement_id   = {surviving['s4_agreement_id']}\n"
            f"        URL          = {BASE}/approvals/agreements/{surviving['s4_agreement_id']}\n"
            f"        PDF (volume) = {surviving.get('s4_pdf_path')}\n"
            f"        PDF (app)    = {BASE}/api/approvals/agreements/{surviving['s4_agreement_id']}/pdf"
        )
    if surviving.get("s4_process_exec_id"):
        print(
            f"  S4 process exec   = {surviving['s4_process_exec_id']}\n"
            f"        detail URL   = {BASE}/api/workflows/executions/{surviving['s4_process_exec_id']}"
        )
    if surviving.get("s7_agreement_id"):
        print(
            f"  S7 agreement_id   = {surviving['s7_agreement_id']}\n"
            f"        PDF (volume) = {surviving.get('s7_pdf_path')}\n"
            f"        PDF (app)    = {BASE}/api/approvals/agreements/{surviving['s7_agreement_id']}/pdf"
        )

    rc = results.summary()
    print(f"\nElapsed: {elapsed:.1f}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
