#!/usr/bin/env python3
"""
Write the release notes of a version into src/docs/RELEASE_NOTES.md from git history.

Run on the release branch. Reads the commits in `<last tag>..HEAD` (merge commits
skipped, and commits of a PR already named in the tag's first-parent history,
i.e. in a past release's squash commit) and replaces the `# Release Notes - Unreleased` block with a
`# Release Notes - v<version> (<date>)` block, keeping the notes written by hand
in the Unreleased block.

- One bullet per commit, from its subject only (on development, one squash
  commit per PR). Subjects of the original commits inside a squash body are
  never used.
- Trailers anywhere in the body (a squash body keeps every original commit
  message): `BREAKING CHANGE:` and `Upgrade-Note:` go to "Upgrade Notes"
  (breaking ones marked), `Docs-Note:` to "Docs Notes". A trailer continues on
  the following indented lines. The same note repeated (stacked PRs) is kept once.
- A subject with `!` (`feat(api)!: ...`) and no `BREAKING CHANGE:` trailer gets a
  breaking upgrade note from the subject.

Usage:
    python generate_release_notes.py [since-tag] [--version X.Y.Z] [--date YYYY-MM-DD]
                                     [--dry-run]

Examples:
    python generate_release_notes.py                  # since the latest v* tag
    python generate_release_notes.py v1.1.0           # since tag v1.1.0
    python generate_release_notes.py --dry-run        # print the block, write nothing
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

UPGRADE_HEADING = "## ⚠️ Upgrade Notes"
DOCS_HEADING = "## 📝 Docs Notes"
OTHER_HEADING = "## 🔄 Other"

CATEGORIES = {
    "feat": "## ✨ Features",
    "fix": "## 🐛 Bug Fixes",
    "docs": "## 📚 Documentation",
    "perf": "## ⚡ Performance",
    "refactor": "## ♻️ Refactoring",
    "test": "## 🧪 Testing",
    "chore": "## 🔧 Maintenance",
}

# Section headings, in the order they are written.
SECTION_ORDER: List[str] = [UPGRADE_HEADING, DOCS_HEADING, *CATEGORIES.values(), OTHER_HEADING]

UNRELEASED_HEADING = "# Release Notes - Unreleased"
RELEASE_HEADING_PREFIX = "# Release Notes - "

RELEASE_NOTES_PATH = Path(__file__).parent.parent / "docs" / "RELEASE_NOTES.md"
PYPROJECT_PATH = Path(__file__).parent.parent / "pyproject.toml"

BREAKING = "breaking"
UPGRADE = "upgrade"
DOCS = "docs"
# Trailer keys (matched without case) and the kind of note they make.
TRAILER_KINDS = {
    "breaking change": BREAKING,
    "breaking-change": BREAKING,
    "upgrade-note": UPGRADE,
    "docs-note": DOCS,
}
_TRAILER_RE = re.compile(
    r"^(BREAKING CHANGE|BREAKING-CHANGE|Upgrade-Note|Docs-Note):\s*(.*)$", re.IGNORECASE
)
_SUBJECT_RE = re.compile(r"^(\w+)(?:\(([^)]+)\))?(!)?: (.+)$")
_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
_ANY_PR_RE = re.compile(r"\(#(\d+)\)")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?$")
_BULLET_RE = re.compile(r"^[-*+]\s")
# A note shorter than this is only "already written by hand" on an exact match.
_MIN_CONTAINED_KEY = 20


@dataclass
class Commit:
    sha: str
    subject: str
    body: str


@dataclass
class _Note:
    text: str
    scope: Optional[str]
    pr: Optional[str]
    breaking: bool
    age: int  # 0 = oldest commit of the range

    def render(self) -> str:
        text = " ".join(self.text.split())
        if self.pr and not text.endswith(f"(#{self.pr})"):
            text = f"{text} (#{self.pr})"
        prefix = f"**{self.scope}**: " if self.scope else ""
        mark = "**BREAKING** " if self.breaking else ""
        return f"- {mark}{prefix}{text}"


@dataclass
class Notes:
    """What a range of commits adds to a release block (newest commit first)."""

    bullets: Dict[str, List[str]] = field(default_factory=dict)
    upgrade: List[str] = field(default_factory=list)
    docs: List[str] = field(default_factory=list)


def parse_trailers(body: str) -> List[Tuple[str, str]]:
    """Return the (kind, text) of every release-note trailer in a commit body.

    A trailer starts at the beginning of a line, anywhere in the body (in the
    final trailer block next to `Co-authored-by:` or in its own paragraph), and
    continues on the following lines that start with whitespace.
    """
    found: List[Tuple[str, str]] = []
    kind = ""
    parts: Optional[List[str]] = None

    def close() -> None:
        if parts:
            text = " ".join(part for part in parts if part)
            if text:
                found.append((kind, text))

    for line in body.splitlines():
        match = _TRAILER_RE.match(line)
        if match:
            close()
            kind = TRAILER_KINDS[match.group(1).lower()]
            parts = [match.group(2).strip()]
        elif parts is not None and line[:1] in (" ", "\t") and line.strip():
            parts.append(line.strip())
        else:
            close()
            parts = None
    close()
    return found


def parse_subject(subject: str) -> Tuple[Optional[str], Optional[str], bool, str]:
    """Return (type, scope, breaking, message) of a Conventional Commit subject.

    A subject that is not one gives (None, None, False, subject).
    """
    match = _SUBJECT_RE.match(subject.strip())
    if not match:
        return None, None, False, subject.strip()
    type_, scope, bang, message = match.groups()
    return type_, scope, bool(bang), message


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _written_by_hand(key: str, existing: List[str]) -> bool:
    if len(key) < _MIN_CONTAINED_KEY:
        return any(key == bullet for bullet in existing)
    return any(key in bullet for bullet in existing)


def _bullet_keys(block: str) -> List[str]:
    """Normalized text of each top-level bullet (with its continuation lines) of a block."""
    bullets: List[List[str]] = []
    for line in block.splitlines():
        if _BULLET_RE.match(line):
            bullets.append([line[2:]])
        elif bullets and line.strip() and not line.startswith("#"):
            bullets[-1].append(line)
    return [_key(" ".join(parts)) for parts in bullets]


def collect(commits: List[Commit], existing: str = "") -> Notes:
    """Build the bullets and notes of ``commits`` (newest first, as `git log` gives them).

    A note repeated in several commits (stacked PRs) is kept once, on the oldest
    commit that has it; a note already in ``existing`` (the hand-written
    Unreleased block) is skipped. The same text as `BREAKING CHANGE` and as
    `Upgrade-Note` is one breaking note.
    """
    existing_keys = _bullet_keys(existing)
    upgrade: Dict[str, _Note] = {}
    docs: Dict[str, _Note] = {}
    for age, commit in enumerate(reversed(commits)):
        _type, scope, bang, message = parse_subject(commit.subject)
        pr_match = _PR_RE.search(commit.subject)
        pr = pr_match.group(1) if pr_match else None
        trailers = parse_trailers(commit.body)
        if bang and not any(kind == BREAKING for kind, _ in trailers):
            trailers.insert(0, (BREAKING, _PR_RE.sub("", message).strip()))
        for kind, text in trailers:
            key = _key(text)
            if _written_by_hand(key, existing_keys):
                continue
            target = docs if kind == DOCS else upgrade
            note = target.get(key)
            if note is None:
                target[key] = _Note(text, scope, pr, kind == BREAKING, age)
            elif kind == BREAKING:
                note.breaking = True

    notes = Notes()
    for commit in commits:
        type_, scope, _bang, message = parse_subject(commit.subject)
        heading = CATEGORIES.get(type_ or "", OTHER_HEADING)
        prefix = f"**{scope}**: " if scope else ""
        notes.bullets.setdefault(heading, []).append(f"- {prefix}{message}")
    # Newest commit first, as the bullets; a commit's notes in the order written.
    notes.upgrade = [n.render() for n in sorted(upgrade.values(), key=lambda n: -n.age)]
    notes.docs = [n.render() for n in sorted(docs.values(), key=lambda n: -n.age)]
    return notes


def _sections_of(block: List[str]) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Split a release block body into its preamble and its (heading, lines) sections."""
    preamble: List[str] = []
    sections: List[Tuple[str, List[str]]] = []
    for line in block:
        if line.startswith("## "):
            sections.append((line.strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return preamble, sections


def _trim(lines: List[str]) -> List[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def render_block(heading: str, hand_written: List[str], notes: Notes) -> List[str]:
    """The release block. In each section the hand-written lines come first, as written.

    Sections are written in ``SECTION_ORDER``; a hand-written section with another
    heading is kept after them.
    """
    preamble, sections = _sections_of(hand_written)
    generated: Dict[str, List[str]] = dict(notes.bullets)
    if notes.upgrade:
        generated[UPGRADE_HEADING] = notes.upgrade
    if notes.docs:
        generated[DOCS_HEADING] = notes.docs
    kept: Dict[str, List[str]] = {}
    for title, lines in sections:
        kept.setdefault(title, []).extend(_trim(lines))
    titles = [t for t in SECTION_ORDER if t in kept or t in generated]
    titles += [t for t in kept if t not in SECTION_ORDER]

    out = [heading, "", ""]
    preamble = _trim(preamble)
    if preamble:
        out += preamble + [""]
    for title in titles:
        body = kept.get(title, []) + generated.get(title, [])
        if body:
            out += [title, ""] + body + [""]
    return out


def normalize_version(version: str) -> str:
    """Return ``X.Y.Z`` (or ``X.Y.Z.N``) for itself or ``v``-prefixed; else raise ValueError."""
    bare = version[1:] if version.startswith("v") else version
    if not _VERSION_RE.match(bare):
        raise ValueError(f"invalid version '{version}': expected X.Y.Z")
    return bare


def update_notes(text: str, commits: List[Commit], version: str, date: str) -> Tuple[str, str]:
    """Return (new file text, release block) with the Unreleased block replaced.

    Without an Unreleased block the release block goes on top. Raises ValueError
    when the version is already in the file or there is nothing to release.
    """
    version = normalize_version(version)
    heading = f"{RELEASE_HEADING_PREFIX}v{version} ({date})"
    lines = text.split("\n")
    if any(line.startswith(f"{RELEASE_HEADING_PREFIX}v{version} ") for line in lines):
        raise ValueError(f"v{version} is already in the release notes")
    start = next((i for i, line in enumerate(lines) if line.strip() == UNRELEASED_HEADING), None)
    if start is None:
        start = next(
            (i for i, line in enumerate(lines) if line.startswith(RELEASE_HEADING_PREFIX)),
            len(lines),
        )
        end, hand_written = start, []
    else:
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith(RELEASE_HEADING_PREFIX)),
            len(lines),
        )
        hand_written = lines[start + 1:end]
    notes = collect(commits, "\n".join(hand_written))
    block = render_block(heading, hand_written, notes)
    if not any(_BULLET_RE.match(line) for line in block):
        raise ValueError("no commits and no hand-written notes: nothing to release")
    rest = lines[end:]
    new_lines = lines[:start] + block + rest
    if not rest:
        new_lines = new_lines[:-1]
    return "\n".join(new_lines), "\n".join(block).rstrip() + "\n"


def git_commits(since: str, repo: Optional[Path] = None) -> List[Commit]:
    """Commits of ``since..HEAD`` without merge commits, newest first."""
    result = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", f"{since}..HEAD"],
        capture_output=True, text=True, check=True, cwd=repo,
    )
    commits = []
    for record in result.stdout.split("\x1e"):
        record = record.strip("\n")
        if record:
            sha, subject, body = record.split("\x1f", 2)
            commits.append(Commit(sha=sha, subject=subject, body=body))
    return commits


def released_prs(tag: str, repo: Optional[Path] = None) -> Set[str]:
    """PR numbers named in the messages of the tag's first-parent history.

    Releases reach main as squash commits whose body lists every development
    commit, so the development commits of a past release are not ancestors of
    its tag: ``<tag>..HEAD`` alone would list them again.
    """
    result = subprocess.run(
        ["git", "log", "--first-parent", "--format=%B", tag],
        capture_output=True, text=True, check=True, cwd=repo,
    )
    return set(_ANY_PR_RE.findall(result.stdout))


def drop_released(commits: List[Commit], released: Set[str]) -> List[Commit]:
    """The commits whose subject's PR number is not in ``released``."""
    kept = []
    for commit in commits:
        match = _PR_RE.search(commit.subject)
        if not match or match.group(1) not in released:
            kept.append(commit)
    return kept


def last_tag(repo: Optional[Path] = None) -> str:
    """The latest ``v*`` tag reachable from HEAD."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD"],
        capture_output=True, text=True, cwd=repo,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("no v* tag reachable from HEAD: pass the since-tag")
    return result.stdout.strip()


def get_current_version() -> str:
    """Extract the current version from pyproject.toml."""
    if PYPROJECT_PATH.exists():
        match = re.search(r'version\s*=\s*"([^"]+)"', PYPROJECT_PATH.read_text())
        if match:
            return match.group(1)
    raise ValueError("no version in pyproject.toml: pass --version")


def _write_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the release notes of a version into RELEASE_NOTES.md from git.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("since_tag", nargs="?", default=None,
                        help="Start of the range (default: the latest v* tag before HEAD)")
    parser.add_argument("--version", "-v", default=None,
                        help="Version for the heading (default: from pyproject.toml)")
    parser.add_argument("--date", default=None, help="Release date (default: today)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the release block without changing the file")
    args = parser.parse_args(argv)

    try:
        since = args.since_tag or last_tag()
        version = normalize_version(args.version or get_current_version())
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        commits = drop_released(git_commits(since), released_prs(since))
        text = RELEASE_NOTES_PATH.read_text(encoding="utf-8")
        new_text, block = update_notes(text, commits, version, date)
    except subprocess.CalledProcessError as exc:
        print(f"error: git failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(block, end="")
        return 0
    _write_atomically(RELEASE_NOTES_PATH, new_text)
    print(f"v{version}: {len(commits)} commits since {since} written to {RELEASE_NOTES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
