#!/usr/bin/env python3
"""
bump_version.py - Synchronize version across all project files.

This script updates the version number in all version files to ensure consistency.
It supports semantic versioning (MAJOR.MINOR.PATCH).

Usage:
    python scripts/bump_version.py <version>
    python scripts/bump_version.py 0.5.0

The script updates:
    - src/pyproject.toml (Python/Hatch build config)
    - src/backend/src/__init__.py (Python runtime import)
    - src/frontend/package.json (Node/npm frontend)
    - src/package.json (Root build helper)
"""

import json
import re
import sys
from pathlib import Path

# Version file configurations
# Format: (relative_path, is_json, pattern_to_find, replacement_template)
VERSION_FILES = [
    # Python/Hatch build config
    (
        "pyproject.toml",
        False,
        r'(version\s*=\s*")[^"]+(")',
        r'\g<1>{version}\g<2>',
    ),
    # Python runtime __version__
    (
        "backend/src/__init__.py",
        False,
        r'(__version__\s*=\s*")[^"]+(")',
        r'\g<1>{version}\g<2>',
    ),
    # Frontend package.json
    ("frontend/package.json", True, None, None),
    # Root package.json (build helper)
    ("package.json", True, None, None),
]


def validate_version(version: str) -> bool:
    """Validate that the version follows semantic versioning."""
    pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$"
    return bool(re.match(pattern, version))


def update_json_version(filepath: Path, new_version: str) -> str | None:
    """Update version in a JSON file (package.json)."""
    try:
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)
        old_version = data.get("version", "unknown")
        data["version"] = new_version
        filepath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return old_version
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ✗ Error updating {filepath}: {e}")
        return None


def update_text_version(
    filepath: Path, pattern: str, replacement: str, new_version: str
) -> str | None:
    """Update version in a text file using regex replacement."""
    try:
        content = filepath.read_text(encoding="utf-8")

        # Extract old version
        match = re.search(pattern, content)
        if not match:
            print(f"  ✗ Could not find version pattern in {filepath}")
            return None

        # Get old version from the matched content
        old_match = re.search(r"\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?", match.group(0))
        old_version = old_match.group(0) if old_match else "unknown"

        # Replace with new version
        new_content = re.sub(pattern, replacement.format(version=new_version), content)
        filepath.write_text(new_content, encoding="utf-8")
        return old_version
    except IOError as e:
        print(f"  ✗ Error updating {filepath}: {e}")
        return None


def bump_version(new_version: str, dry_run: bool = False) -> bool:
    """Update version across all project files."""
    # Determine project root (script is in src/scripts/)
    script_dir = Path(__file__).resolve().parent
    src_root = script_dir.parent  # src/

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Bumping version to {new_version}\n")
    print(f"Project src root: {src_root}\n")

    success = True
    updates = []

    for rel_path, is_json, pattern, replacement in VERSION_FILES:
        filepath = src_root / rel_path

        if not filepath.exists():
            print(f"  ⚠ File not found: {filepath}")
            continue

        if dry_run:
            print(f"  → Would update: {rel_path}")
            continue

        if is_json:
            old_version = update_json_version(filepath, new_version)
        else:
            old_version = update_text_version(filepath, pattern, replacement, new_version)

        if old_version:
            updates.append((rel_path, old_version, new_version))
            print(f"  ✓ {rel_path}: {old_version} → {new_version}")
        else:
            success = False

    if not dry_run and updates:
        print(f"\n{'=' * 50}")
        print(f"Updated {len(updates)} file(s) to version {new_version}")
        print(f"{'=' * 50}\n")

        print("Next steps:")
        print(f"  1. Review changes: git diff")
        print(f"  2. Commit: git add -A && git commit -m 'chore: bump version to {new_version}'")
        print(f"  3. Tag: git tag v{new_version}")
        print(f"  4. Push: git push && git push --tags")

    return success


def get_current_version(src_root: Path) -> str | None:
    """Get the current version from pyproject.toml (source of truth)."""
    pyproject = src_root / "pyproject.toml"
    if not pyproject.exists():
        return None

    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else None


def show_current_versions(src_root: Path) -> None:
    """Display current versions from all tracked files."""
    print("\nCurrent versions:")
    print("-" * 40)

    for rel_path, is_json, pattern, _ in VERSION_FILES:
        filepath = src_root / rel_path

        if not filepath.exists():
            print(f"  {rel_path}: (not found)")
            continue

        try:
            content = filepath.read_text(encoding="utf-8")

            if is_json:
                data = json.loads(content)
                version = data.get("version", "unknown")
            else:
                match = re.search(pattern, content)
                if match:
                    ver_match = re.search(r"\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?", match.group(0))
                    version = ver_match.group(0) if ver_match else "unknown"
                else:
                    version = "pattern not found"

            print(f"  {rel_path}: {version}")
        except Exception as e:
            print(f"  {rel_path}: (error: {e})")

    print("-" * 40)


def main():
    """Main entry point."""
    script_dir = Path(__file__).resolve().parent
    src_root = script_dir.parent

    if len(sys.argv) < 2:
        current = get_current_version(src_root)
        show_current_versions(src_root)
        print(f"\nUsage: python {sys.argv[0]} <version>")
        print(f"       python {sys.argv[0]} --dry-run <version>")
        print(f"\nExample: python {sys.argv[0]} 0.5.0")
        if current:
            print(f"\nCurrent version (from pyproject.toml): {current}")
        sys.exit(1)

    # Handle --dry-run flag
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if not args:
        print("Error: No version specified")
        sys.exit(1)

    new_version = args[0]

    if not validate_version(new_version):
        print(f"Error: Invalid version format '{new_version}'")
        print("Expected format: MAJOR.MINOR.PATCH (e.g., 1.0.0, 0.5.0-beta)")
        sys.exit(1)

    if not bump_version(new_version, dry_run):
        print("\nSome files failed to update. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

