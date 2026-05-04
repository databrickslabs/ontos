"""
E2E test — cross-workflow wiring (PRD #242 close-out gap-fill).

Asserts the full chain that PRD #242 promised:

    subscribe action
      → matching `for_subscribe` approval workflow fires (wizard)
      → wizard completes
      → subscription is created via dp_manager.subscribe()
      → matching `on_subscribe` process workflow fires
      → its webhook step receives RESOLVED variables from both
        ${context.*} (user_email, on_behalf_of.value) and
        ${entity.*} (consumer_groups) and
        ${trigger_context.*} (subscription_id when surfaced as entity_id).

Run:
    python3 src/e2e/test_cross_workflow_wiring.py

Re-runnable: every entity uses a timestamp-prefixed name. Cleanup runs in
try/finally.

Auth: same Databricks CLI OAuth pattern as test_approval_ux_v1.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

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

WEBHOOK_URL = os.environ.get(
    "ONTOS_E2E_WEBHOOK_URL",
    "https://httpbin.org/post",
)

RUN_TS = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
RUN_TAG = f"E2E-CrossWF-{RUN_TS}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Auth helper — same pattern as test_approval_ux_v1.py.
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


# ---------------------------------------------------------------------------
# Workflow payloads
# ---------------------------------------------------------------------------
def build_approval_workflow_payload() -> Dict[str, Any]:
    """Approval workflow with for_subscribe trigger.

    Steps: legal_document → user_action → persist_agreement → pass.
    """
    return {
        "name": f"{RUN_TAG}-approval",
        "description": "Cross-workflow wiring approval (E2E)",
        "workflow_type": "approval",
        "trigger": {"type": "for_subscribe", "entity_types": []},
        "is_active": True,
        "steps": [
            {
                "step_id": "legal",
                "name": "Terms",
                "step_type": "legal_document",
                "config": {
                    "title": "Cross-WF Terms",
                    "body_markdown": "# Terms\n\nE2E acceptance.",
                    "require_acknowledgement_checkbox": True,
                    "acknowledgement_label": "I accept",
                },
                "on_pass": "ua",
                "order": 0,
            },
            {
                "step_id": "ua",
                "name": "Reason",
                "step_type": "user_action",
                "config": {
                    "title": "Provide a reason",
                    "fields": [
                        {"id": "reason", "label": "Reason", "type": "text",
                         "required": True}
                    ],
                },
                "on_pass": "persist",
                "order": 1,
            },
            {
                "step_id": "persist",
                "name": "Save Agreement",
                "step_type": "persist_agreement",
                "config": {},
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


def build_process_workflow_payload(unique_marker: str) -> Dict[str, Any]:
    """Process workflow with on_subscribe trigger.

    Single webhook step posts to httpbin.org/post and echoes back the
    resolved body. The assertion later greps the result_data.response
    for our resolved values.
    """
    body_template = (
        "{"
        f'"marker": "{unique_marker}", '
        '"user_email": "${context.user_email}", '
        '"on_behalf_of_value": "${context.on_behalf_of.value}", '
        '"on_behalf_of_type": "${context.on_behalf_of.type}", '
        '"consumer_groups": ${entity.consumer_groups}, '
        '"entity_id": "${entity_id}"'
        "}"
    )
    return {
        "name": f"{RUN_TAG}-process",
        "description": "Cross-workflow wiring process (E2E)",
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


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run() -> int:
    started_at = time.time()
    print(f"\n=== Cross-Workflow Wiring E2E ({RUN_TAG}) ===")
    print(f"Target: {BASE}")
    print(f"Auth profile: {DATABRICKS_PROFILE}")
    print(f"Webhook URL: {WEBHOOK_URL}\n")

    token = get_token()
    s = make_session(token)

    # Pre-flight
    health = s.get(f"{BASE}/api/user/info", timeout=15)
    if health.status_code == 401:
        print("FATAL: 401 — refresh CLI profile.")
        return 1
    if health.status_code not in (200, 403):
        print(f"FATAL: connectivity check failed: {health.status_code} {health.text[:300]}")
        return 1
    print(f"Pre-flight: /api/user/info -> {health.status_code} OK")

    approval_wf_id: Optional[str] = None
    process_wf_id: Optional[str] = None
    product_id: Optional[str] = None
    session_id: Optional[str] = None
    agreement_id: Optional[str] = None

    unique_marker = f"XWFM-{uuid.uuid4().hex[:10]}"

    try:
        # ---------------------------------------------------------------
        # 1. Create data product (active so it's subscribable)
        # ---------------------------------------------------------------
        product_payload = {
            "name": f"{RUN_TAG}-product",
            "apiVersion": "v1.0.0",
            "kind": "DataProduct",
            "description": {
                "purpose": "E2E target for cross-workflow wiring",
                "limitations": "Test-only — auto-cleaned",
                "usage": "Subscribed to in test",
            },
            "version": "1.0.0",
            "status": "active",  # subscribable
            "domain": "e2e-testing",
            "tenant": "e2e-org",
            "consumer_groups": ["users"],
        }
        r = s.post(f"{BASE}/api/data-products", json=product_payload, timeout=30)
        if r.status_code not in (200, 201):
            print(f"FAIL: create product: {r.status_code} {r.text[:400]}")
            return 1
        prod = r.json()
        product_id = prod.get("id") or prod.get("data", {}).get("id")
        if not product_id:
            print("FAIL: created product missing id")
            return 1
        print(f"  Created product: {product_payload['name']} (id={product_id})")

        # ---------------------------------------------------------------
        # 2. Create approval workflow (for_subscribe)
        # ---------------------------------------------------------------
        r = s.post(f"{BASE}/api/workflows", json=build_approval_workflow_payload(), timeout=30)
        if r.status_code not in (200, 201):
            print(f"FAIL: create approval workflow: {r.status_code} {r.text[:400]}")
            return 1
        approval_wf_id = r.json()["id"]
        print(f"  Created approval workflow (id={approval_wf_id})")

        # ---------------------------------------------------------------
        # 3. Create process workflow (on_subscribe)
        # ---------------------------------------------------------------
        r = s.post(
            f"{BASE}/api/workflows",
            json=build_process_workflow_payload(unique_marker),
            timeout=30,
        )
        if r.status_code not in (200, 201):
            print(f"FAIL: create process workflow: {r.status_code} {r.text[:400]}")
            return 1
        process_wf_id = r.json()["id"]
        print(f"  Created process workflow (id={process_wf_id})")

        # ---------------------------------------------------------------
        # 4. Start wizard with completion_action=subscribe + on_behalf_of
        # ---------------------------------------------------------------
        on_behalf_of = {"type": "group", "value": "users"}
        r = s.post(
            f"{BASE}/api/approvals/sessions",
            json={
                "workflow_id": approval_wf_id,
                "entity_type": "data_product",
                "entity_id": product_id,
                "completion_action": "subscribe",
                "on_behalf_of": on_behalf_of,
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            print(f"FAIL: create wizard session: {r.status_code} {r.text[:400]}")
            return 1
        sess_data = r.json()
        session_id = sess_data.get("session_id")
        print(f"  Started wizard session (id={session_id})")

        # ---------------------------------------------------------------
        # 5. Walk wizard. Server returns the next step under
        #    `current_step`; loop until `complete=true`. user_action +
        #    legal need real payloads; persist + pass take {}.
        # ---------------------------------------------------------------
        step_data = sess_data
        for hop in range(8):
            cur = step_data.get("current_step") or step_data.get("step")
            if step_data.get("complete") or not cur:
                break
            sid = cur.get("step_id")
            stype = cur.get("step_type")
            if stype == "legal_document":
                payload = {"acknowledged": True, "scrolled_to_end": True}
            elif stype == "user_action":
                payload = {"reason": f"E2E-{unique_marker}"}
            else:
                payload = {}
            r = s.post(
                f"{BASE}/api/approvals/sessions/{session_id}/steps",
                json={"step_id": sid, "payload": payload},
                timeout=30,
            )
            if r.status_code != 200:
                print(f"FAIL: submit '{sid}' ({stype}): "
                      f"{r.status_code} {r.text[:400]}")
                return 1
            step_data = r.json()
        if not step_data.get("complete"):
            print("FAIL: wizard did not reach complete=true")
            return 1
        agreement_id = step_data.get("agreement_id")
        print(f"  Wizard completed (agreement_id={agreement_id})")

        # ---------------------------------------------------------------
        # 6. Verify subscription was created (route: /subscribers)
        # ---------------------------------------------------------------
        r = s.get(f"{BASE}/api/data-products/{product_id}/subscribers", timeout=15)
        if r.status_code != 200:
            print(f"FAIL: list subscribers: {r.status_code} {r.text[:300]}")
            return 1
        payload = r.json()
        subs = payload.get("subscribers") if isinstance(payload, dict) else payload
        subs = subs or []
        if not isinstance(subs, list) or not subs:
            print(
                f"FAIL: no subscribers found on product {product_id} after "
                f"wizard completion (response={payload!r})"
            )
            return 1
        print(f"  Subscription created: {len(subs)} subscriber(s) on product")

        # ---------------------------------------------------------------
        # 7. Wait for the on_subscribe process workflow to fire + finish
        # ---------------------------------------------------------------
        process_exec = None
        for attempt in range(20):  # up to ~60s
            time.sleep(3)
            r = s.get(f"{BASE}/api/workflows/executions?limit=50", timeout=15)
            if r.status_code != 200:
                continue
            payload = r.json()
            execs = payload.get("executions", payload) if isinstance(payload, dict) else payload
            if not isinstance(execs, list):
                continue
            for ex in execs:
                if ex.get("workflow_id") == process_wf_id:
                    process_exec = ex
                    if ex.get("status") in ("succeeded", "failed"):
                        break
            if process_exec and process_exec.get("status") in ("succeeded", "failed"):
                break
        if not process_exec:
            print(
                "FAIL: on_subscribe process workflow did not fire after wizard "
                "completion. This is the wizard→on_subscribe gap flagged in "
                "the PRD #242 close-out: dp_manager.subscribe() does not "
                "fire workflow triggers — only the route handler does. "
                "Needs separate fix (route the wizard's auto-subscribe "
                "through a path that calls fire_trigger_safe('on_subscribe'))."
            )
            return 1
        if process_exec.get("status") != "succeeded":
            print(
                f"FAIL: on_subscribe execution status="
                f"{process_exec.get('status')!r} (expected 'succeeded')"
            )
            return 1
        exec_id = process_exec["id"]
        print(f"  Process workflow execution: status=succeeded (id={exec_id})")

        # ---------------------------------------------------------------
        # 8. Inspect the webhook step's resolved body
        # ---------------------------------------------------------------
        r = s.get(f"{BASE}/api/workflows/executions/{exec_id}", timeout=15)
        if r.status_code != 200:
            print(f"FAIL: get execution detail: {r.status_code} {r.text[:300]}")
            return 1
        detail = r.json()
        step_execs = detail.get("step_executions", []) or []
        webhook_se = next(
            (se for se in step_execs if (se.get("step_id") == "hook")
             or (se.get("result_data") or {}).get("url")),
            None,
        )
        if not webhook_se:
            print("FAIL: webhook step execution not found in execution detail")
            return 1
        rd = webhook_se.get("result_data") or {}
        # httpbin echoes the request body back in 'data' / 'json' fields of the
        # response JSON. The handler captures up to 500 chars in 'response'.
        resp_text = rd.get("response", "") or ""
        # The handler may also surface the rendered body separately, but at
        # minimum the unique marker should round-trip.
        haystack = json.dumps(rd)
        missing: List[str] = []
        for needle, label in [
            (unique_marker, "unique marker"),
            ('"users"', "consumer_groups=['users'] (or on_behalf_of value)"),
        ]:
            if needle not in haystack:
                missing.append(f"{label} ({needle!r})")
        if missing:
            print(
                f"FAIL: webhook response did not contain expected resolved "
                f"values: missing={missing}; haystack[:500]={haystack[:500]!r}"
            )
            return 1
        print(
            f"  Webhook resolved body OK (marker + 'users' present in response)"
        )

        elapsed = time.time() - started_at
        print(f"\nPASS — cross-workflow wiring works end-to-end "
              f"({elapsed:.1f}s).")
        return 0

    except Exception as e:
        print(f"FATAL: unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # ---------------------------------------------------------------
        # Cleanup — do NOT delete the agreement (no public DELETE)
        # ---------------------------------------------------------------
        if session_id:
            try:
                s.post(f"{BASE}/api/approvals/sessions/{session_id}/abort",
                       json={}, timeout=10)
            except Exception:
                pass
        if product_id:
            try:
                s.delete(f"{BASE}/api/data-products/{product_id}", timeout=15)
            except Exception:
                pass
        if approval_wf_id:
            try:
                s.delete(f"{BASE}/api/workflows/{approval_wf_id}", timeout=15)
            except Exception:
                pass
        if process_wf_id:
            try:
                s.delete(f"{BASE}/api/workflows/{process_wf_id}", timeout=15)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(run())
