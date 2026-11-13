#!/usr/bin/env python3
"""
Integration Test Shards

Splits the backend integration tests into CI shards balanced by the per-file
durations measured on previous runs, and folds the durations of a run back in.
Standard library only: the plan job runs it without installing dependencies.

Subcommands:
    plan   Pick the shard count N and assign every test file to one shard.
           Prints the matrix JSON (for fromJSON) and writes plan.json.
    merge  Read the shards' JUnit XML, check that every planned file ran and
           write the updated durations JSON for the next runs.

The durations JSON only changes the balance and N, never which tests run:
missing or invalid data falls back to weights by test count.

Usage:
    python integration_shards.py plan --durations integ-durations.json \\
        --tests-dir src/backend/src/tests/integration
    python integration_shards.py merge --plan plan.json --junit-dir junit \\
        --previous integ-durations.json --out integ-durations.json
"""

import argparse
import ast
import json
import math
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# Test file paths are relative to src/, as pytest gets them in CI
SCRIPT_DIR = Path(__file__).parent.resolve()
SRC_DIR = SCRIPT_DIR.parent

DURATIONS_VERSION = 1
# A file can't take longer than the shard timeout; larger values are corrupt
MAX_FILE_SECONDS = 3600.0
# Hysteresis band: N changes only when the raw count is 10 % past a boundary
HYSTERESIS = 0.10
# The file paths go into a shell array in the shard job
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


class PlanError(Exception):
    """A deliberate plan failure (no fallback): the input itself is unsafe."""


def warn(message: str) -> None:
    """Print a GitHub Actions warning annotation."""
    print(f"::warning::{message}", file=sys.stderr)


def info(message: str) -> None:
    """Print a log line (stderr: stdout carries the matrix JSON)."""
    print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Test files
# ---------------------------------------------------------------------------

def list_test_files(tests_dir: Path, root: Path) -> list[str]:
    """Every test_*.py under tests_dir (recursive), relative to root, sorted."""
    tests_dir = tests_dir.resolve()
    root = root.resolve()
    if not tests_dir.is_dir():
        raise PlanError(f"Tests directory not found: {tests_dir}")
    files = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not SAFE_PATH.match(rel):
            raise PlanError(
                f"Test file name outside [A-Za-z0-9_./-]: {rel!r}. Rename it."
            )
        files.append(rel)
    if not files:
        raise PlanError(f"No test_*.py files under {tests_dir}")
    return files


def count_tests(path: Path) -> int | None:
    """Number of test functions/methods in a file, or None if it can't be parsed.

    Counts module-level ``test*`` functions and ``test*`` methods of ``Test*``
    classes (nested classes included). A parametrized test counts once.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None

    def count_in(body: list[ast.stmt]) -> int:
        total = 0
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test"):
                    total += 1
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                total += count_in(node.body)
        return total

    return count_in(tree.body)


def weights_by_test_count(files: list[str], root: Path) -> dict[str, float]:
    """Weights by number of tests; an unparsable file weighs 1."""
    weights = {}
    for rel in files:
        count = count_tests(root / rel)
        weights[rel] = float(count) if count else 1.0
    return weights


# ---------------------------------------------------------------------------
# Durations cache
# ---------------------------------------------------------------------------

def valid_seconds(value: Any) -> bool:
    """A usable duration: a finite number in [0, MAX_FILE_SECONDS]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0 <= value <= MAX_FILE_SECONDS


def load_durations(path: Path | None, files: list[str]) -> tuple[dict[str, float], int | None]:
    """Valid per-file seconds for files that still exist, and the previous N.

    A missing or unreadable file means no durations; invalid entries are dropped.
    """
    if path is None or not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn(f"Ignoring unreadable durations file {path.name}: {exc}")
        return {}, None
    if not isinstance(data, dict):
        warn(f"Ignoring durations file {path.name}: not a JSON object")
        return {}, None

    existing = set(files)
    raw = data.get("durations")
    durations = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if name in existing and valid_seconds(value):
                durations[name] = float(value)

    prev_n = data.get("shards")
    if isinstance(prev_n, bool) or not isinstance(prev_n, int) or prev_n < 1:
        prev_n = None
    return durations, prev_n


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def shard_count(total_seconds: float, workers: int, target_seconds: float,
                max_shards: int, prev_n: int | None) -> int:
    """N from the measured total, with a 10 % hysteresis around the previous N."""
    raw = total_seconds / workers / target_seconds
    n = math.ceil(raw)
    if prev_n is not None:
        going_up = raw >= prev_n * (1 + HYSTERESIS)
        going_down = raw <= (prev_n - 1) * (1 - HYSTERESIS)
        if not (going_up or going_down):
            n = prev_n
    return max(1, min(n, max_shards))


def assign(weights: dict[str, float], n: int) -> list[list[str]]:
    """Longest first, each file into the lightest shard; ties broken by path.

    Shards with the same total go by index, so the plan is deterministic.
    """
    shards: list[list[str]] = [[] for _ in range(n)]
    totals = [0.0] * n
    for rel in sorted(weights, key=lambda f: (-weights[f], f)):
        target = min(range(n), key=lambda i: (totals[i], i))
        shards[target].append(rel)
        totals[target] += weights[rel]
    return [sorted(files) for files in shards]


def build_plan(files: list[str], root: Path, durations: dict[str, float],
               prev_n: int | None, default_shards: int, max_shards: int,
               target_seconds: float, workers: int) -> dict[str, Any]:
    """The plan: N, the basis of the weights and the files of each shard."""
    if durations:
        median = statistics.median(durations.values())
        weights = {f: durations.get(f, median) for f in files}
        n = shard_count(sum(weights.values()), workers, target_seconds,
                        max_shards, prev_n)
        basis = "durations"
    else:
        weights = weights_by_test_count(files, root)
        n = max(1, min(default_shards, max_shards))
        basis = "test-count"
    return finish_plan(weights, min(n, len(files)), basis)


def default_plan(files: list[str], root: Path, default_shards: int,
                 max_shards: int) -> dict[str, Any]:
    """Fallback plan: N = default, weights by test count."""
    weights = weights_by_test_count(files, root)
    n = max(1, min(default_shards, max_shards, len(files)))
    return finish_plan(weights, n, "test-count")


def finish_plan(weights: dict[str, float], n: int, basis: str) -> dict[str, Any]:
    groups = assign(weights, n)
    return {
        "version": DURATIONS_VERSION,
        "shards": n,
        "basis": basis,
        "groups": [
            {
                "shard": i + 1,
                "weight": round(sum(weights[f] for f in group), 3),
                "files": group,
            }
            for i, group in enumerate(groups)
        ],
    }


def matrix_for(plan: dict[str, Any]) -> dict[str, Any]:
    """The strategy.matrix value: one include entry per shard."""
    n = plan["shards"]
    return {
        "include": [
            {"shard": g["shard"], "of": n, "files": " ".join(g["files"])}
            for g in plan["groups"]
        ]
    }


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        files = list_test_files(Path(args.tests_dir), root)
    except PlanError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    try:
        durations, prev_n = load_durations(
            Path(args.durations) if args.durations else None, files
        )
        plan = build_plan(files, root, durations, prev_n, args.default_shards,
                          args.max_shards, args.target_seconds, args.workers)
    except Exception as exc:  # noqa: BLE001 - any error falls back to the default plan
        warn(f"Shard planning failed ({type(exc).__name__}: {exc}); "
             f"using the default plan")
        plan = default_plan(files, root, args.default_shards, args.max_shards)

    Path(args.plan_out).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    info(f"{len(files)} files in {plan['shards']} shards (weights: {plan['basis']})")
    for group in plan["groups"]:
        info(f"  shard {group['shard']}: {len(group['files'])} files, "
             f"weight {group['weight']}")
    print(json.dumps(matrix_for(plan), separators=(",", ":")))
    return 0


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def module_of(rel: str) -> str:
    """Dotted module name pytest reports for a file (importlib mode, from src/)."""
    return rel[: -len(".py")].replace("/", ".")


def junit_seconds(junit_dir: Path, files: list[str]) -> dict[str, float]:
    """Summed testcase time per planned file across all JUnit XML files.

    pytest's JUnit (xunit2) has no file attribute: the classname is the dotted
    module, plus the class for methods; a collection error has an empty
    classname and the module as its name. Testcases of unknown files are ignored.
    """
    modules = {module_of(f): f for f in files}
    # Longest module first, so a.b.test_x.TestY never matches a shorter module
    by_length = sorted(modules, key=len, reverse=True)
    seconds: dict[str, float] = {}
    for xml_path in sorted(junit_dir.rglob("*.xml")):
        try:
            cases = list(ET.parse(xml_path).getroot().iter("testcase"))
        except (OSError, ET.ParseError) as exc:
            warn(f"Ignoring unreadable JUnit file {xml_path.name}: {exc}")
            continue
        for case in cases:
            dotted = case.get("classname") or case.get("name") or ""
            rel = None
            if case.get("file") in files:
                rel = case.get("file")
            else:
                for module in by_length:
                    if dotted == module or dotted.startswith(module + "."):
                        rel = modules[module]
                        break
            if rel is None:
                continue
            try:
                value = float(case.get("time") or 0)
            except ValueError:
                value = 0.0
            if not valid_seconds(value):
                value = 0.0
            seconds[rel] = seconds.get(rel, 0.0) + value
    return seconds


def merge_durations(previous: dict[str, float], measured: dict[str, float],
                    files: list[str]) -> dict[str, float]:
    """Average new and previous values (0.5/0.5) for the planned files.

    New files take the measured value; files that didn't run keep the previous
    one; entries for files that no longer exist are dropped.
    """
    merged = {}
    for rel in files:
        if rel in measured:
            value = measured[rel]
            if rel in previous:
                value = 0.5 * previous[rel] + 0.5 * value
            merged[rel] = round(min(value, MAX_FILE_SECONDS), 3)
        elif rel in previous:
            merged[rel] = previous[rel]
    return merged


def cmd_merge(args: argparse.Namespace) -> int:
    root = Path(args.root)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    files = sorted(f for group in plan["groups"] for f in group["files"])
    for rel in files:
        if not SAFE_PATH.match(rel):
            print(f"::error::Unexpected file name in the plan: {rel!r}", file=sys.stderr)
            return 1

    junit_dir = Path(args.junit_dir)
    measured = junit_seconds(junit_dir, files) if junit_dir.is_dir() else {}
    previous, _ = load_durations(Path(args.previous) if args.previous else None, files)
    merged = merge_durations(previous, measured, files)

    out = {"version": DURATIONS_VERSION, "shards": plan["shards"], "durations": merged}
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    info(f"Durations: {len(measured)} files measured, {len(merged)} stored, "
         f"{round(sum(measured.values()), 1)} s of test time")

    # A file with tests that has no result means a shard didn't run or died.
    # Unparsable files count: pytest reports their collection error.
    missing = [f for f in files if f not in measured and count_tests(root / f) != 0]
    if missing:
        print(f"::error::{len(missing)} planned test files have no results "
              f"(a shard failed, timed out or was cancelled):", file=sys.stderr)
        for rel in missing:
            print(f"  {rel}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--root", default=str(SRC_DIR),
                        help="Directory the test file paths are relative to (default: src/)")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Plan the shards; print the matrix JSON")
    plan.add_argument("--durations", help="Durations JSON from the cache (may be missing)")
    plan.add_argument("--tests-dir", required=True, help="Integration tests directory")
    plan.add_argument("--default-shards", type=int, default=4)
    plan.add_argument("--max-shards", type=int, default=6)
    plan.add_argument("--target-seconds", type=float, default=300.0,
                      help="Test time per shard and worker to aim for")
    plan.add_argument("--workers", type=int, default=3, help="xdist workers per shard")
    plan.add_argument("--plan-out", default="plan.json", help="Where to write plan.json")
    plan.set_defaults(func=cmd_plan)

    merge = sub.add_parser("merge", help="Fold the shards' JUnit times into the durations")
    merge.add_argument("--plan", required=True, help="plan.json written by plan")
    merge.add_argument("--junit-dir", required=True, help="Directory with the JUnit XML files")
    merge.add_argument("--previous", help="Previous durations JSON (may be missing)")
    merge.add_argument("--out", required=True, help="Where to write the new durations JSON")
    merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    if args.command == "plan":
        for name in ("default_shards", "max_shards", "workers"):
            if getattr(args, name) < 1:
                parser.error(f"--{name.replace('_', '-')} must be at least 1")
        if not args.target_seconds > 0:
            parser.error("--target-seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(argv=None))
