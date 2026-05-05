"""
E2E test for the configurable Welcome Disclaimer (first-open dialog).

Exercises the backend-only piece of the feature:
  1. PUT /api/settings persists welcome_disclaimer_text + welcome_disclaimer_enabled.
  2. GET /api/settings returns those values.
  3. GET /api/settings/welcome-disclaimer (public) returns the same values
     in the dialog-friendly shape ({enabled, text}).
  4. Toggling enabled=false flips both endpoints accordingly.
  5. Cleanup restores original values.

The dialog rendering itself is verified in the live deploy E2E (orchestrator).

Targets the deployed Ontos app at:
    https://ontos-7474659920352264.aws.databricksapps.com

Auth pattern: Databricks CLI OAuth token via the `account-workspace` profile.

Usage:
    cd ontos
    python3 src/e2e/test_welcome_disclaimer.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict

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

RUN_TS = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
TEST_TEXT = (
    f"## Welcome Disclaimer (E2E {RUN_TS})\n\n"
    "By continuing you acknowledge that this is a controlled environment. "
    "**Do not** upload PII or sensitive data."
)


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
class BehaviorResults:
    """Records per-behavior outcomes and prints a final summary."""

    LABELS = {
        "B1": "PUT /api/settings persists welcome_disclaimer_* fields",
        "B2": "GET /api/settings echoes welcome_disclaimer_* fields",
        "B3": "GET /api/settings/welcome-disclaimer returns dialog shape",
        "B4": "Toggling enabled=false flips both endpoints",
        "B5": "Cleanup — restored original values",
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
        print("\n" + "=" * 72)
        print("SUMMARY — Welcome Disclaimer ()")
        print("=" * 72)
        total = len(self.LABELS)
        passed_count = sum(1 for k in self.LABELS if self.results.get(k, {}).get("passed"))
        for key, label in self.LABELS.items():
            r = self.results.get(key)
            if r is None:
                marker = "SKIP"
                detail = "behavior not exercised"
            elif r["passed"]:
                marker = "PASS"
                detail = r["detail"] or ""
            else:
                marker = "FAIL"
                detail = r["detail"] or ""
            line = f"  [{marker}] {key}: {label}"
            if detail:
                line += f"  ({detail})"
            print(line)
        print("-" * 72)
        print(f"  {passed_count}/{total} behaviors passed")
        return 0 if passed_count == total else 1


results = BehaviorResults()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def get_token() -> str:
    """Obtain a fresh Databricks OAuth token via the CLI."""
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
# Helpers
# ---------------------------------------------------------------------------
def get_settings(s: requests.Session) -> Dict[str, Any]:
    r = s.get(f"{BASE}/api/settings", timeout=30)
    r.raise_for_status()
    return r.json()


def put_settings(s: requests.Session, payload: Dict[str, Any]) -> None:
    r = s.put(f"{BASE}/api/settings", json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PUT /api/settings failed: {r.status_code} {r.text}")


def get_welcome_public(s: requests.Session) -> Dict[str, Any]:
    r = s.get(f"{BASE}/api/settings/welcome-disclaimer", timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"Welcome Disclaimer E2E — {RUN_TS}")
    print(f"  BASE = {BASE}")

    try:
        token = get_token()
    except Exception as e:
        print(f"  [FATAL] Could not obtain token: {e}")
        return 2

    s = make_session(token)

    # Capture original values so we can restore them at the end.
    original = get_settings(s)
    original_text = original.get("welcome_disclaimer_text") or ""
    original_enabled = bool(original.get("welcome_disclaimer_enabled"))
    print(
        f"  Original: enabled={original_enabled}, "
        f"text_len={len(original_text)}"
    )

    try:
        # --- B1 + B2: PUT then GET, both fields round-trip ---
        try:
            put_settings(
                s,
                {
                    "welcome_disclaimer_enabled": True,
                    "welcome_disclaimer_text": TEST_TEXT,
                },
            )
            results.pass_("B1", "PUT accepted")
        except Exception as e:
            results.fail("B1", str(e))
            return results.summary()

        after = get_settings(s)
        ok_text = after.get("welcome_disclaimer_text") == TEST_TEXT
        ok_enabled = after.get("welcome_disclaimer_enabled") is True
        if ok_text and ok_enabled:
            results.pass_("B2", "values echoed")
        else:
            results.fail(
                "B2",
                f"text_match={ok_text}, enabled_match={ok_enabled}, "
                f"got={after.get('welcome_disclaimer_enabled')!r}/{(after.get('welcome_disclaimer_text') or '')[:40]!r}",
            )

        # --- B3: public dialog endpoint returns matching values ---
        try:
            pub = get_welcome_public(s)
            pub_ok = bool(pub.get("enabled")) is True and pub.get("text", "").strip() != ""
            # NOTE: text may be sanitized server-side, so we don't byte-compare.
            # We assert non-empty and that the test marker substring survives.
            if pub_ok and RUN_TS in (pub.get("text") or ""):
                results.pass_("B3", "public endpoint returns enabled=true + text contains run marker")
            else:
                results.fail(
                    "B3",
                    f"enabled={pub.get('enabled')!r}, marker_in_text={RUN_TS in (pub.get('text') or '')}, "
                    f"text_preview={(pub.get('text') or '')[:60]!r}",
                )
        except Exception as e:
            results.fail("B3", str(e))

        # --- B4: toggle enabled=false ---
        try:
            put_settings(s, {"welcome_disclaimer_enabled": False})
            after_off = get_settings(s)
            pub_off = get_welcome_public(s)
            settings_off = after_off.get("welcome_disclaimer_enabled") is False
            public_off = bool(pub_off.get("enabled")) is False
            if settings_off and public_off:
                results.pass_("B4", "both endpoints report enabled=false")
            else:
                results.fail(
                    "B4",
                    f"settings_enabled={after_off.get('welcome_disclaimer_enabled')!r}, "
                    f"public_enabled={pub_off.get('enabled')!r}",
                )
        except Exception as e:
            results.fail("B4", str(e))

    finally:
        # --- B5: restore originals ---
        try:
            put_settings(
                s,
                {
                    "welcome_disclaimer_enabled": original_enabled,
                    "welcome_disclaimer_text": original_text or None,
                },
            )
            restored = get_settings(s)
            ok = (
                bool(restored.get("welcome_disclaimer_enabled")) == original_enabled
                and (restored.get("welcome_disclaimer_text") or "") == original_text
            )
            if ok:
                results.pass_("B5", "originals restored")
            else:
                results.fail(
                    "B5",
                    f"restored_enabled={restored.get('welcome_disclaimer_enabled')!r}, "
                    f"text_len={len(restored.get('welcome_disclaimer_text') or '')}",
                )
        except Exception as e:
            results.fail("B5", f"restore failed: {e}")

    return results.summary()


if __name__ == "__main__":
    sys.exit(main())
