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
import os
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


def _version(value: str) -> str:
    try:
        return rn.normalize_version(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
    parser.add_argument(
        "--version", type=_version, help="release version, X.Y.Z (a leading v is accepted)"
    )
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
    # Write next to the target and swap it in, so a failed write leaves the notes intact;
    # only then delete the fragments.
    temp_path = NOTES_PATH.with_name(NOTES_PATH.name + ".tmp")
    try:
        temp_path.write_text(result, encoding="utf-8")
        os.replace(temp_path, NOTES_PATH)
    finally:
        temp_path.unlink(missing_ok=True)
    leftovers = []
    for fragment in fragments:
        try:
            fragment.path.unlink()
        except OSError:
            leftovers.append(fragment)
    if leftovers:
        print(
            f"Released v{args.version} but could not delete {len(leftovers)} fragment(s). "
            "Delete them by hand, or the next run will release them again:"
        )
        print("\n".join(f"  {f.section}/{f.name}" for f in leftovers))
        return 1
    print(f"Released {len(fragments)} fragment(s) as v{args.version} ({release_date}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
