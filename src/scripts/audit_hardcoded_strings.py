#!/usr/bin/env python3
"""
Hardcoded user-facing string audit (i18n migration worklist).

Complements check_translations.py: that script only sees strings already inside
`t(...)`. This one scans the frontend source for user-facing strings that are NOT
yet wrapped in `t(...)` — JSX text nodes and translatable attributes — and produces
a per-file worklist to drive the migration tracked in issue #471.

It is a *heuristic* scanner (regex-based, not a full TS AST), tuned for low noise:
it flags what a human should review, not an auto-codemod. Expect some false
positives (they cost a glance); the goal is completeness of the worklist.

Usage:
    python audit_hardcoded_strings.py [--json] [--min-count N] [--path SUBDIR]
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = SCRIPT_DIR.parent / "frontend"
SRC_DIR = FRONTEND_DIR / "src"

SCAN_EXTENSIONS = {".tsx", ".jsx"}

# Attributes whose string-literal values are user-facing and should be translated.
TRANSLATABLE_ATTRS = (
    "placeholder", "title", "aria-label", "alt", "label",
    "description", "tooltip", "helperText", "emptyMessage",
)

# JSX text between tags that contains at least one 2+ letter word.
RE_JSX_TEXT = re.compile(r">([^<>{}]*?[A-Za-z]{2,}[^<>{}]*?)<")
# Translatable attribute set to a plain string literal (not an expression {...}).
RE_ATTR = re.compile(
    r'\b(' + "|".join(TRANSLATABLE_ATTRS) + r')\s*=\s*"([^"]*[A-Za-z]{2,}[^"]*)"'
)
# toast({ title: "...", description: "..." }) style string literals.
RE_TOAST_FIELD = re.compile(r'\b(title|description)\s*:\s*"([^"]*[A-Za-z]{2,}[^"]*)"')

# Values that look like code/config, not prose — skip to cut noise.
RE_SKIP_VALUE = re.compile(
    r"^\s*(?:https?://|/|#|\{|\$|[A-Za-z0-9_.\-]+$|[A-Z0-9_]+$)"
)
# Lines that are imports / pure comments.
RE_SKIP_LINE = re.compile(r"^\s*(?://|/\*|\*|import\s|export\s+\*)")


def looks_translatable(value: str) -> bool:
    v = value.strip()
    if len(v) < 2:
        return False
    # must contain a whitespace-separated word or a capitalized word (prose-ish)
    if not re.search(r"[A-Za-z]{2,}", v):
        return False
    # single lowercase token (likely an identifier / css / enum) -> skip
    if re.fullmatch(r"[a-z][a-zA-Z0-9_]*", v):
        return False
    # single kebab/snake/dotted token -> skip
    if re.fullmatch(r"[a-zA-Z0-9]+([-_.][a-zA-Z0-9]+)+", v):
        return False
    if RE_SKIP_VALUE.match(v) and " " not in v:
        return False
    return True


def scan_file(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except Exception:
        return findings
    for n, line in enumerate(lines, 1):
        if RE_SKIP_LINE.match(line):
            continue
        # Skip regions that are clearly already translated on this line.
        for regex, kind, grp in (
            (RE_JSX_TEXT, "jsx-text", 1),
            (RE_ATTR, "attr", 2),
            (RE_TOAST_FIELD, "toast", 2),
        ):
            for m in regex.finditer(line):
                val = m.group(grp)
                # If the captured text is inside a t(...) call on this line, skip.
                if "t(" in line[max(0, m.start() - 4):m.start()]:
                    continue
                if not looks_translatable(val):
                    continue
                findings.append({
                    "kind": kind,
                    "attr": m.group(1) if kind in ("attr", "toast") else None,
                    "line": n,
                    "text": val.strip(),
                })
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="Emit full findings as JSON")
    ap.add_argument("--min-count", type=int, default=1,
                    help="Only list files with at least N findings")
    ap.add_argument("--path", default=None,
                    help="Restrict scan to SRC_DIR/<path> (e.g. views, components/knowledge)")
    args = ap.parse_args()

    root = SRC_DIR / args.path if args.path else SRC_DIR
    files = sorted(
        p for ext in SCAN_EXTENSIONS for p in root.rglob(f"*{ext}")
        if "node_modules" not in str(p)
    )

    per_file: dict[str, list[dict]] = {}
    has_usetrans: dict[str, bool] = {}
    for p in files:
        f = scan_file(p)
        rel = str(p.relative_to(FRONTEND_DIR))
        has_usetrans[rel] = "useTranslation" in p.read_text(encoding="utf-8")
        if f:
            per_file[rel] = f

    total = sum(len(v) for v in per_file.values())
    if args.json:
        print(json.dumps({
            "total_findings": total,
            "files": {k: v for k, v in per_file.items() if len(v) >= args.min_count},
            "has_useTranslation": has_usetrans,
        }, ensure_ascii=False, indent=2))
        return

    print(f"Hardcoded-string audit — scanned {len(files)} files under {root}")
    print(f"Total candidate strings: {total} in {len(per_file)} files\n")
    ranked = sorted(per_file.items(), key=lambda kv: -len(kv[1]))
    print(f"{'count':>5}  {'i18n?':<6} file")
    for rel, f in ranked:
        if len(f) < args.min_count:
            continue
        flag = "has" if has_usetrans.get(rel) else "NONE"
        print(f"{len(f):>5}  {flag:<6} {rel}")
    no_import = [r for r in per_file if not has_usetrans.get(r)]
    print(f"\nFiles with candidates but NO useTranslation import: {len(no_import)}")


if __name__ == "__main__":
    main()
