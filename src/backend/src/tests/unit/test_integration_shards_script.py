"""Tests for src/scripts/integration_shards.py (CI integration test shards)."""

import importlib.util
import json
import math
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "integration_shards.py"
TESTS_DIR = "backend/src/tests/integration"


def _load_script():
    spec = importlib.util.spec_from_file_location("integration_shards", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


shards = _load_script()


def _write(root: Path, rel: str, body: str) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _tests(n: int) -> str:
    return "".join(f"def test_{i}():\n    pass\n" for i in range(n))


@pytest.fixture
def tree(tmp_path):
    """A src/ root with integration test files of 1..4 tests and a helper file."""
    root = tmp_path / "src"
    files = [
        _write(root, f"{TESTS_DIR}/test_a.py", _tests(4)),
        _write(root, f"{TESTS_DIR}/test_b.py", _tests(3)),
        _write(root, f"{TESTS_DIR}/test_c.py", _tests(2)),
        _write(root, f"{TESTS_DIR}/sub/test_d.py", _tests(1)),
    ]
    _write(root, f"{TESTS_DIR}/conftest.py", "")
    _write(root, f"{TESTS_DIR}/helpers.py", _tests(5))
    return root, sorted(files)


def _plan(root: Path, tmp_path: Path, durations: dict | None = None, *extra: str):
    """Run `plan` through main(); return (exit code, plan.json, matrix)."""
    argv = ["--root", str(root), "plan", "--tests-dir", str(root / TESTS_DIR),
            "--plan-out", str(tmp_path / "plan.json"), *extra]
    if durations is not None:
        dur_path = tmp_path / "durations.json"
        dur_path.write_text(json.dumps(durations), encoding="utf-8")
        argv += ["--durations", str(dur_path)]
    return argv


def _run_plan(capsys, root, tmp_path, durations=None, *extra):
    rc = shards.main(_plan(root, tmp_path, durations, *extra))
    out = capsys.readouterr().out
    plan = json.loads((tmp_path / "plan.json").read_text()) if rc == 0 else None
    matrix = json.loads(out) if rc == 0 else None
    return rc, plan, matrix


# ---------------------------------------------------------------------------
# File listing and assignment
# ---------------------------------------------------------------------------

def test_lists_only_test_files_relative_to_src(tree):
    root, files = tree
    assert shards.list_test_files(root / TESTS_DIR, root) == files
    assert f"{TESTS_DIR}/sub/test_d.py" in files


def test_bad_file_name_fails_the_plan(tree, tmp_path, capsys):
    root, _ = tree
    _write(root, f"{TESTS_DIR}/test_$(boom).py", _tests(1))
    rc = shards.main(_plan(root, tmp_path))
    assert rc == 1
    assert "outside [A-Za-z0-9_./-]" in capsys.readouterr().err
    assert not (tmp_path / "plan.json").exists()


def test_assignment_is_deterministic_and_complete():
    weights = {f"t/test_{i:02d}.py": float((i * 7) % 11 + 1) for i in range(30)}
    reordered = dict(reversed(list(weights.items())))
    groups = shards.assign(weights, 4)
    assert groups == shards.assign(reordered, 4)
    placed = [f for group in groups for f in group]
    assert sorted(placed) == sorted(weights)
    assert len(placed) == len(set(placed))


def test_assignment_longest_first_into_lightest_shard_ties_by_path():
    weights = {"t/test_b.py": 5.0, "t/test_a.py": 5.0, "t/test_c.py": 3.0,
               "t/test_d.py": 2.0}
    # a before b (same weight, by path) -> shard 1, b -> shard 2; c -> shard 1
    # (both shards at 5: the lower index wins), d -> shard 2 (5 < 8)
    groups = shards.assign(weights, 2)
    assert groups == [["t/test_a.py", "t/test_c.py"], ["t/test_b.py", "t/test_d.py"]]


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

def test_count_tests_counts_functions_and_methods_parametrized_once(tmp_path):
    body = (
        "import pytest\n"
        "@pytest.mark.parametrize('x', [1, 2, 3])\n"
        "def test_p(x):\n    pass\n"
        "async def test_async():\n    pass\n"
        "def helper():\n    pass\n"
        "class TestGroup:\n"
        "    def test_one(self):\n        pass\n"
        "    def setup_method(self):\n        pass\n"
        "    class TestNested:\n"
        "        def test_two(self):\n            pass\n"
        "class Helper:\n"
        "    def test_not_collected(self):\n        pass\n"
    )
    path = tmp_path / "test_x.py"
    path.write_text(body)
    assert shards.count_tests(path) == 4


def test_unparsable_file_weighs_one(tmp_path):
    rel = _write(tmp_path, "test_bad.py", "def test_x(:\n")
    assert shards.count_tests(tmp_path / rel) is None
    assert shards.weights_by_test_count([rel], tmp_path) == {rel: 1.0}


def test_no_durations_uses_test_counts_and_default_n(tree, tmp_path, capsys):
    root, files = tree
    rc, plan, matrix = _run_plan(capsys, root, tmp_path, None, "--default-shards", "2")
    assert rc == 0
    assert plan["basis"] == "test-count"
    assert plan["shards"] == 2
    # Weights 4, 3, 2, 1 -> {4, 1} and {3, 2}
    assert [g["weight"] for g in plan["groups"]] == [5.0, 5.0]
    assert matrix == {"include": [
        {"shard": 1, "of": 2, "files": f"{TESTS_DIR}/sub/test_d.py {TESTS_DIR}/test_a.py"},
        {"shard": 2, "of": 2, "files": f"{TESTS_DIR}/test_b.py {TESTS_DIR}/test_c.py"},
    ]}


def test_shard_count_never_exceeds_the_file_count(tree, tmp_path, capsys):
    root, files = tree
    rc, plan, matrix = _run_plan(capsys, root, tmp_path, None, "--default-shards", "6")
    assert rc == 0
    assert plan["shards"] == len(files)
    assert all(entry["files"] for entry in matrix["include"])


def test_file_without_duration_gets_the_median(tree, tmp_path, capsys):
    root, files = tree
    a, b, c, d = (f"{TESTS_DIR}/{n}" for n in
                  ("test_a.py", "test_b.py", "test_c.py", "sub/test_d.py"))
    durations = {"shards": 1, "durations": {a: 10.0, b: 30.0, c: 100.0}}
    rc, plan, _ = _run_plan(capsys, root, tmp_path, durations, "--target-seconds", "1000")
    assert rc == 0
    assert plan["basis"] == "durations"
    assert plan["shards"] == 1
    assert plan["groups"][0]["weight"] == 10.0 + 30.0 + 100.0 + 30.0
    assert d in plan["groups"][0]["files"]


# ---------------------------------------------------------------------------
# Shard count
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("total", "prev_n", "expected"),
    [
        (3600, None, 4),   # raw 4.0
        (3700, None, 5),   # raw 4.11 -> ceil
        (3700, 4, 4),      # 4.11 < 4.4: hold
        (3960, 4, 5),      # 4.4 >= 4 * 1.1: up
        (2500, 4, 4),      # 2.78 > 2.7: hold
        (2430, 4, 3),      # 2.7 <= (4 - 1) * 0.9: down
        (900, 4, 1),       # 1.0: down to 1
        (0, 1, 1),         # never below 1
        (99999, None, 6),  # capped at max
        (99999, 6, 6),
    ],
)
def test_shard_count_rule_and_hysteresis(total, prev_n, expected):
    assert shards.shard_count(total, workers=3, target_seconds=300, max_shards=6,
                              prev_n=prev_n) == expected


def test_previous_n_from_the_cache_holds_inside_the_band(tree, tmp_path, capsys):
    root, files = tree
    # raw = 4 x 461.25 / 3 workers / 300 s = 2.05: ceil 3, but prev 2 holds (< 2.2)
    durations = {"shards": 2, "durations": {f: 461.25 for f in files}}
    _, plan, _ = _run_plan(capsys, root, tmp_path, durations)
    assert plan["shards"] == 2
    # raw = 1.9: ceil 2, but prev 3 holds (> (3 - 1) x 0.9 = 1.8)
    durations = {"shards": 3, "durations": {f: 427.5 for f in files}}
    _, plan, _ = _run_plan(capsys, root, tmp_path, durations)
    assert plan["shards"] == 3
    # Without a previous N: ceil(raw)
    durations = {"durations": {f: 427.5 for f in files}}
    _, plan, _ = _run_plan(capsys, root, tmp_path, durations)
    assert plan["shards"] == 2


# ---------------------------------------------------------------------------
# Invalid cache data
# ---------------------------------------------------------------------------

def test_invalid_cache_values_are_dropped(tree, tmp_path):
    root, files = tree
    a, b, c, d = files
    path = tmp_path / "durations.json"
    path.write_text(
        '{"shards": "4", "durations": {'
        f'"{a}": "12", "{b}": -1, "{c}": NaN, "{d}": Infinity, '
        f'"{TESTS_DIR}/test_gone.py": 5, "x": true}}}}'
    )
    assert shards.load_durations(path, files) == ({}, None)

    path.write_text(json.dumps({"shards": 3, "durations": {
        a: 3600.5, b: 3600, c: 0, d: True}}))
    assert shards.load_durations(path, files) == ({b: 3600.0, c: 0.0}, 3)


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"durations": [1]}', ""])
def test_unusable_cache_file_means_no_durations(tree, tmp_path, content):
    root, files = tree
    path = tmp_path / "durations.json"
    path.write_text(content)
    assert shards.load_durations(path, files) == ({}, None)


def test_missing_cache_file_means_no_durations(tree, tmp_path, capsys):
    root, files = tree
    argv = _plan(root, tmp_path) + ["--durations", str(tmp_path / "missing.json")]
    assert shards.main(argv) == 0
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["basis"] == "test-count"
    assert plan["shards"] == 4


def test_planning_error_falls_back_to_the_default_plan(tree, tmp_path, capsys,
                                                      monkeypatch):
    root, files = tree

    def boom(*args, **kwargs):
        raise RuntimeError("bad cache")

    monkeypatch.setattr(shards, "build_plan", boom)
    durations = {"shards": 1, "durations": {f: 1.0 for f in files}}
    rc = shards.main(_plan(root, tmp_path, durations, "--default-shards", "2"))
    captured = capsys.readouterr()
    assert rc == 0
    assert "::warning::Shard planning failed (RuntimeError: bad cache)" in captured.err
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["basis"] == "test-count"
    assert plan["shards"] == 2
    assert len(json.loads(captured.out)["include"]) == 2


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _junit(path: Path, cases: list[tuple[str, str, float]]) -> None:
    body = "".join(
        f'<testcase classname="{cls}" name="{name}" time="{secs}" />'
        for cls, name, secs in cases
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest">{body}</testsuite></testsuites>'
    )


def _merge(root: Path, tmp_path: Path, previous: dict | None):
    prev_path = tmp_path / "previous.json"
    if previous is not None:
        prev_path.write_text(json.dumps(previous))
    out = tmp_path / "out.json"
    rc = shards.main(["--root", str(root), "merge", "--plan", str(tmp_path / "plan.json"),
                      "--junit-dir", str(tmp_path / "junit"),
                      "--previous", str(prev_path), "--out", str(out)])
    return rc, json.loads(out.read_text())


def test_merge_averages_with_previous_and_keeps_unmeasured(tree, tmp_path, capsys):
    root, _ = tree
    _run_plan(capsys, root, tmp_path, None, "--default-shards", "2")
    mod = "backend.src.tests.integration"
    _junit(tmp_path / "junit" / "junit-1.xml", [
        (f"{mod}.sub.test_d", "test_0", 2.0),
        (f"{mod}.test_a", "test_0", 1.0),
        (f"{mod}.test_a.TestX", "test_1", 3.0),
    ])
    _junit(tmp_path / "junit" / "junit-2.xml", [
        (f"{mod}.test_b", "test_0", 6.0),
        ("", f"{mod}.test_c", 0.5),  # collection error: module in the name
        ("other.module", "test_0", 9.0),
    ])
    test_a = f"{TESTS_DIR}/test_a.py"
    test_b = f"{TESTS_DIR}/test_b.py"
    previous = {"shards": 3, "durations": {
        test_a: 12.0, test_b: 10.0, f"{TESTS_DIR}/test_gone.py": 7.0}}
    rc, out = _merge(root, tmp_path, previous)
    assert rc == 0
    assert out["shards"] == 2  # N of the plan, not of the previous entry
    assert out["durations"] == {
        test_a: 0.5 * 12.0 + 0.5 * (1.0 + 3.0),
        test_b: 0.5 * 10.0 + 0.5 * 6.0,
        f"{TESTS_DIR}/test_c.py": 0.5,  # new file: the measured value
        f"{TESTS_DIR}/sub/test_d.py": 2.0,
    }  # test_gone.py no longer exists: dropped


def test_merge_keeps_previous_value_for_files_that_did_not_run(tree, tmp_path, capsys):
    root, files = tree
    _run_plan(capsys, root, tmp_path, None, "--default-shards", "2")
    test_d = f"{TESTS_DIR}/sub/test_d.py"
    _junit(tmp_path / "junit" / "junit-1.xml", [
        ("backend.src.tests.integration.test_a", "test_0", 1.0),
    ])
    rc, out = _merge(root, tmp_path, {"shards": 2, "durations": {test_d: 9.0}})
    assert out["durations"][test_d] == 9.0
    assert rc == 1  # the files of the shard that didn't run are reported


def test_merge_fails_when_a_planned_file_with_tests_has_no_result(tree, tmp_path, capsys):
    root, files = tree
    _write(root, f"{TESTS_DIR}/test_empty.py", "# no tests yet\n")
    _run_plan(capsys, root, tmp_path, None, "--default-shards", "1")
    mod = "backend.src.tests.integration"
    _junit(tmp_path / "junit" / "junit-1.xml", [
        (f"{mod}.test_a", "test_0", 1.0),
        (f"{mod}.test_b", "test_0", 1.0),
        (f"{mod}.sub.test_d", "test_0", 1.0),
    ])
    rc, out = _merge(root, tmp_path, None)
    err = capsys.readouterr().err
    assert rc == 1
    assert "1 planned test files have no results" in err
    assert f"{TESTS_DIR}/test_c.py" in err
    assert "test_empty.py" not in err  # no test functions: may be absent
    # The durations of what ran are still written
    assert set(out["durations"]) == {f"{TESTS_DIR}/{n}" for n in
                                     ("test_a.py", "test_b.py", "sub/test_d.py")}

    _junit(tmp_path / "junit" / "junit-2.xml", [(f"{mod}.test_c", "test_0", 1.0)])
    rc, _ = _merge(root, tmp_path, None)
    assert rc == 0


def test_merge_ignores_invalid_times_and_unreadable_xml(tree, tmp_path, capsys):
    root, files = tree
    _run_plan(capsys, root, tmp_path, None, "--default-shards", "1")
    mod = "backend.src.tests.integration"
    cases = [(f"{mod}.{n}", "test_0", 1.0) for n in ("test_a", "test_b", "sub.test_d")]
    cases.append((f"{mod}.test_c", "test_0", "nan"))
    _junit(tmp_path / "junit" / "junit-1.xml", cases)
    (tmp_path / "junit" / "junit-2.xml").write_text("<testsuites")
    rc, out = _merge(root, tmp_path, None)
    assert rc == 0
    assert out["durations"][f"{TESTS_DIR}/test_c.py"] == 0.0
    assert all(math.isfinite(v) for v in out["durations"].values())
    assert "Ignoring unreadable JUnit file junit-2.xml" in capsys.readouterr().err
