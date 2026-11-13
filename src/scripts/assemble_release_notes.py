#!/usr/bin/env python3
"""Assemble release-note fragments into src/docs/RELEASE_NOTES.md.

Fragments live in src/docs/release-notes/unreleased/<section>/<slug>.md (see the
README next to it). Standard library only.

Usage:
    python assemble_release_notes.py --check [files...]   # validate (all, or the given files)
    python assemble_release_notes.py --preview            # print the result, write nothing
    python assemble_release_notes.py --version 1.2.0 [--date 2026-12-01]
"""
import argparse
import importlib.util
import sys
from datetime import date as _date
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
NOTES_PATH = DOCS_DIR / "RELEASE_NOTES.md"
UNRELEASED_DIR = DOCS_DIR / "release-notes" / "unreleased"
MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "src" / "common" / "release_notes.py"
)


def _load_module():
    # Load by path: importing src.common would pull in the backend dependencies.
    spec = importlib.util.spec_from_file_location("release_notes", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rn = _load_module()


def check(files) -> int:
    if files:
        problems = [
            f"{f}: {p}"
            for f in files
            for p in (
                rn.validate_file(Path(f))
                if Path(f).is_file()
                else ["file not found"]
            )
        ]
    else:
        _, problems = rn.load_fragments(UNRELEASED_DIR)
    for line in problems:
        print(line)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--version", help="release version, X.Y.Z")
    parser.add_argument("--date", help="release date, YYYY-MM-DD (default: today)")
    parser.add_argument("--preview", action="store_true", help="print the result, write nothing")
    parser.add_argument(
        "--check", nargs="*", metavar="FILE", help="validate fragments (all, or the given files)"
    )
    args = parser.parse_args()

    if args.check is not None:
        return check(args.check)

    fragments, problems = rn.load_fragments(UNRELEASED_DIR)
    if problems:
        print("\n".join(problems))
        return 1
    notes = NOTES_PATH.read_text(encoding="utf-8")
    if args.preview and not args.version:
        print(rn.merge_into_unreleased(notes, fragments), end="")
        return 0
    if not args.version:
        parser.error("--version is required (or use --preview / --check)")
    release_date = args.date or _date.today().isoformat()
    try:
        _date.fromisoformat(release_date)
        result = rn.assemble(notes, fragments, args.version, release_date)
    except ValueError as exc:
        print(str(exc))
        return 1
    if args.preview:
        print(result, end="")
        return 0
    NOTES_PATH.write_text(result, encoding="utf-8")
    for fragment in fragments:
        fragment.path.unlink()
    print(f"Released {len(fragments)} fragment(s) as v{args.version} ({release_date}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
