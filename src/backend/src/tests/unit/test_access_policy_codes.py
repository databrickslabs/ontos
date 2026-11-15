"""Every code the Access Policies backend can emit has a translation key in the frontend.

The codes (validation issues, compile issues, activation problems, route errors) are collected from
the source and written to ``frontend/src/i18n/access-policy-codes.json``; a vitest checks that each one
has an English ``access-policies:issues.<code>`` string whose placeholders the emitters supply.
Regenerate after adding a code: ``UPDATE_ACCESS_POLICY_CODES=1 pytest tests/unit/test_access_policy_codes.py``.
"""
import ast
import json
import os
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
FIXTURE = SRC.parents[1] / "frontend" / "src" / "i18n" / "access-policy-codes.json"
FILES = ["common/odrl.py", "common/odrl_compiler.py", "common/uc_policy_adapter.py",
         "common/snowflake_policy_adapter.py", "common/policy_targets.py",
         "controller/access_policies_manager.py", "controller/access_policy_releases_manager.py",
         "controller/access_agreements.py", "routes/access_policies_routes.py"]
# Codes with no literal emitter: the generic fallbacks.
EXTRA = {"access_policy_error": [], "message": []}


def _const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _codes(node):
    """Literal codes of an expression: a string, or both branches of ``a if c else b``."""
    if isinstance(node, ast.IfExp):
        return _codes(node.body) + _codes(node.orelse)
    return [c] if (c := _const(node)) else []


def _params(node):
    """Literal param names, or None when the dict isn't a literal (not checkable)."""
    if node is None:
        return []
    if isinstance(node, ast.Dict) and all(_const(k) for k in node.keys):
        return sorted(_const(k) for k in node.keys)
    return None


def collect():
    found = {}

    def add(node, params):
        for code in _codes(node) if node is not None else []:
            found.setdefault(code, []).append(params)

    for rel in FILES:
        tree = ast.parse((SRC / rel).read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                d = {_const(k): v for k, v in zip(n.keys, n.values, strict=True) if _const(k)}
                if "code" in d and "params" in d:
                    add(d["code"], _params(d["params"]))
            if not isinstance(n, ast.Call):
                continue
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            kw = {k.arg: k.value for k in n.keywords}
            a = n.args
            if name == "Issue" and len(a) >= 3:
                add(kw["code"] if "code" in kw else a[3] if len(a) > 3 else None,
                    _params(kw.get("params") or (a[4] if len(a) > 4 else None)))
            elif name == "issue" and len(a) >= 3 and isinstance(n.func, ast.Attribute):
                add(a[1], _params(kw.get("params")))
            elif name == "Problem" and len(a) >= 2:
                add(kw["code"] if "code" in kw else a[1],
                    _params(kw.get("params") or (a[2] if len(a) > 2 else None)))
            elif name == "AccessPolicyError" and "code" in kw:
                add(kw["code"], _params(kw.get("params")))
    out = dict.fromkeys(EXTRA)
    for code, sets in found.items():
        if any(s is None for s in sets):
            out[code] = None  # dynamic params: placeholders aren't checked
        else:
            common = set(sets[0])
            for s in sets[1:]:
                common &= set(s)
            out[code] = sorted(common)
    return dict(sorted(out.items()))


def test_every_emitted_code_is_exported_for_the_frontend():
    codes = collect()
    assert len(codes) > 100, "scanner found too few codes"
    text = json.dumps(codes, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_ACCESS_POLICY_CODES"):
        FIXTURE.write_text(text)
    assert FIXTURE.exists() and FIXTURE.read_text() == text, (
        "access-policy-codes.json is stale — run with UPDATE_ACCESS_POLICY_CODES=1")


def test_no_error_falls_back_to_the_generic_code():
    """Every AccessPolicyError is built with a code (raised directly or wrapped, e.g. ``_http(...)``)."""
    for rel in FILES:
        for n in ast.walk(ast.parse((SRC / rel).read_text())):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "AccessPolicyError":
                assert any(k.arg == "code" for k in n.keywords), f"{rel}:{n.lineno} builds an error without a code"


def test_problem_survives_copy_and_pickle():
    import copy
    import pickle

    from src.common import odrl

    p = odrl.Problem("Scope entry 'x' is invalid", "scope_entry_invalid", {"entry": "x"})
    for clone in (copy.copy(p), copy.deepcopy(p), pickle.loads(pickle.dumps(p))):
        assert clone == p and clone.code == p.code and clone.params == p.params
