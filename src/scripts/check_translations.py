#!/usr/bin/env python3
"""
Translation Validation Script

Checks:
1. All translation keys are consistent across all language files
2. All translation keys used in source files exist in the i18n files
3. Detects unused translation keys (optional)

Usage:
    python check_translations.py [--verbose] [--fix-missing] [--check-unused]
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# Resolve paths relative to script location
SCRIPT_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = SCRIPT_DIR.parent / "frontend"
I18N_DIR = FRONTEND_DIR / "src" / "i18n" / "locales"
SRC_DIRS = [
    FRONTEND_DIR / "src" / "views",
    FRONTEND_DIR / "src" / "components",
    FRONTEND_DIR / "src" / "hooks",
    FRONTEND_DIR / "src" / "stores",
]

# Reference language (source of truth for keys)
REFERENCE_LANG = "en"

# Value prefix marking a key that exists structurally but is not yet translated.
# Per issue #471: makes the gap visible in the UI instead of silently falling back
# to English, and gives translators a machine-findable worklist.
TODO_MARKER = "__TODO__ "

# File extensions to scan for translation usage
SOURCE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Patterns to match translation function calls
# Matches: t('key'), t("key"), t('namespace:key'), t(`template`)
T_FUNCTION_PATTERNS = [
    # t('key') or t("key") - simple keys
    r"\bt\(\s*['\"]([^'\"]+)['\"]\s*[,\)]",
    # t('key', { ... }) with options
    r"\bt\(\s*['\"`]([^'\"`]+)['\"`]\s*,",
]


class Colors:
    """ANSI color codes for terminal output."""
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def flatten_keys(obj: dict, prefix: str = "") -> set[str]:
    """Recursively flatten nested dict keys into dot-notation strings."""
    keys = set()
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(flatten_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def load_json_file(path: Path) -> dict:
    """Load and parse a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"{Colors.RED}Error parsing {path}: {e}{Colors.RESET}")
        return {}
    except FileNotFoundError:
        return {}


def get_languages() -> list[str]:
    """Get list of available language directories."""
    if not I18N_DIR.exists():
        print(f"{Colors.RED}Error: i18n directory not found at {I18N_DIR}{Colors.RESET}")
        sys.exit(1)
    return sorted([d.name for d in I18N_DIR.iterdir() if d.is_dir()])


def get_namespaces(lang: str) -> list[str]:
    """Get list of namespace files for a language."""
    lang_dir = I18N_DIR / lang
    if not lang_dir.exists():
        return []
    return sorted([f.stem for f in lang_dir.glob("*.json")])


def load_all_translations() -> dict[str, dict[str, dict]]:
    """
    Load all translation files.
    Returns: {lang: {namespace: {keys...}}}
    """
    translations = {}
    languages = get_languages()
    
    for lang in languages:
        translations[lang] = {}
        lang_dir = I18N_DIR / lang
        for json_file in lang_dir.glob("*.json"):
            namespace = json_file.stem
            translations[lang][namespace] = load_json_file(json_file)
    
    return translations


def check_key_consistency(translations: dict, verbose: bool = False) -> list[dict]:
    """
    Check that all keys in reference language exist in all other languages.
    Returns list of missing key reports.
    """
    issues = []
    languages = list(translations.keys())
    
    if REFERENCE_LANG not in languages:
        print(f"{Colors.RED}Reference language '{REFERENCE_LANG}' not found!{Colors.RESET}")
        return issues
    
    ref_translations = translations[REFERENCE_LANG]
    other_langs = [l for l in languages if l != REFERENCE_LANG]
    
    # Check each namespace
    for namespace, ref_content in ref_translations.items():
        ref_keys = flatten_keys(ref_content)
        
        for lang in other_langs:
            lang_content = translations.get(lang, {}).get(namespace, {})
            lang_keys = flatten_keys(lang_content)
            
            # Keys in reference but not in this language
            missing_keys = ref_keys - lang_keys
            if missing_keys:
                for key in sorted(missing_keys):
                    issues.append({
                        "type": "missing_in_lang",
                        "namespace": namespace,
                        "key": key,
                        "language": lang,
                        "reference": REFERENCE_LANG,
                    })
            
            # Keys in this language but not in reference (extra keys)
            extra_keys = lang_keys - ref_keys
            if extra_keys and verbose:
                for key in sorted(extra_keys):
                    issues.append({
                        "type": "extra_in_lang",
                        "namespace": namespace,
                        "key": key,
                        "language": lang,
                        "reference": REFERENCE_LANG,
                    })
    
    # Check for namespaces missing in other languages
    ref_namespaces = set(ref_translations.keys())
    for lang in other_langs:
        lang_namespaces = set(translations.get(lang, {}).keys())
        missing_ns = ref_namespaces - lang_namespaces
        if missing_ns:
            for ns in sorted(missing_ns):
                issues.append({
                    "type": "missing_namespace",
                    "namespace": ns,
                    "language": lang,
                    "reference": REFERENCE_LANG,
                })
    
    return issues


def extract_translation_keys_from_source(file_path: Path) -> list[tuple[str, int, str]]:
    """
    Extract translation keys from a source file.
    Returns list of (key, line_number, raw_match).
    """
    keys = []
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        
        for line_num, line in enumerate(lines, 1):
            for pattern in T_FUNCTION_PATTERNS:
                matches = re.finditer(pattern, line)
                for match in matches:
                    key = match.group(1)
                    # Skip template literals with variables
                    if "${" in key or "$" in key:
                        continue
                    keys.append((key, line_num, match.group(0)))
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not read {file_path}: {e}{Colors.RESET}")
    
    return keys


def get_all_source_files() -> list[Path]:
    """Get all source files to scan for translation usage."""
    files = []
    for src_dir in SRC_DIRS:
        if src_dir.exists():
            for ext in SOURCE_EXTENSIONS:
                files.extend(src_dir.rglob(f"*{ext}"))
    return files


def check_source_keys(translations: dict, verbose: bool = False) -> list[dict]:
    """
    Check that all translation keys used in source files exist in i18n files.
    Returns list of missing key reports.
    """
    issues = []
    ref_translations = translations.get(REFERENCE_LANG, {})
    
    # Build a map of all available keys by namespace
    available_keys: dict[str, set[str]] = {}
    for namespace, content in ref_translations.items():
        available_keys[namespace] = flatten_keys(content)
    
    # Also build a flat set of all keys (for keys without namespace prefix)
    all_keys_flat = set()
    for namespace, keys in available_keys.items():
        for key in keys:
            all_keys_flat.add(f"{namespace}:{key}")
            all_keys_flat.add(key)  # Also add without namespace for default ns
    
    source_files = get_all_source_files()
    keys_used: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    
    for file_path in source_files:
        file_keys = extract_translation_keys_from_source(file_path)
        for key, line_num, _ in file_keys:
            keys_used[key].append((file_path, line_num))
    
    # i18next plural/context suffixes: a base key is satisfied by any suffixed form.
    plural_suffixes = ("_zero", "_one", "_two", "_few", "_many", "_other")

    def key_present(subkey: str, keyset: set[str]) -> bool:
        if subkey in keyset:
            return True
        # base key used in code, plural variants defined in JSON
        return any(f"{subkey}{suf}" in keyset for suf in plural_suffixes)

    # Check each used key
    for key, locations in keys_used.items():
        key_found = False

        # Ignore regex false-positives: a "namespace" containing a space is not a
        # real namespace (e.g. placeholder text like "e.g., xsd:string").
        if ":" in key and " " in key.split(":", 1)[0]:
            continue

        # Check if key has namespace prefix (namespace:key)
        if ":" in key:
            namespace, subkey = key.split(":", 1)
            if namespace in available_keys:
                if key_present(subkey, available_keys[namespace]):
                    key_found = True
        else:
            # Key without namespace - check all namespaces
            for namespace, keys in available_keys.items():
                if key_present(key, keys):
                    key_found = True
                    break
        
        if not key_found:
            for file_path, line_num in locations:
                rel_path = file_path.relative_to(FRONTEND_DIR)
                issues.append({
                    "type": "missing_in_i18n",
                    "key": key,
                    "file": str(rel_path),
                    "line": line_num,
                })
    
    return issues


def check_unused_keys(translations: dict, verbose: bool = False) -> list[dict]:
    """
    Check for translation keys that are not used in any source file.
    Returns list of unused key reports.
    """
    issues = []
    ref_translations = translations.get(REFERENCE_LANG, {})
    
    # Collect all keys used in source files
    source_files = get_all_source_files()
    used_keys: set[str] = set()
    
    for file_path in source_files:
        file_keys = extract_translation_keys_from_source(file_path)
        for key, _, _ in file_keys:
            used_keys.add(key)
            # Also add namespace:key variants
            if ":" in key:
                namespace, subkey = key.split(":", 1)
                used_keys.add(subkey)
    
    # Check each defined key
    for namespace, content in ref_translations.items():
        defined_keys = flatten_keys(content)
        for key in defined_keys:
            # Check various forms the key might be used
            full_key = f"{namespace}:{key}"
            if key not in used_keys and full_key not in used_keys:
                # Skip some common keys that might be used dynamically
                if not any(part in key for part in ["_plural", "_zero", "_one", "_two", "_few", "_many", "_other"]):
                    issues.append({
                        "type": "unused",
                        "namespace": namespace,
                        "key": key,
                    })
    
    return issues


def _ordered_merge(
    en_obj: dict,
    tgt_obj: Any,
    lang: str,
    namespace: str,
    path: str,
    manifest: list[dict],
    extras: list[dict],
) -> dict:
    """
    Build a dict that follows `en_obj`'s key order.
    - Nested dicts recurse.
    - Leaf keys keep an existing *translated* target value.
    - Missing leaves (or values still carrying TODO_MARKER) are seeded with the
      English value prefixed by TODO_MARKER and recorded in `manifest`.
    - Target-only keys absent from `en_obj` are PRESERVED verbatim (never dropped —
      they are usually real translations for keys en is missing) and recorded in
      `extras` so en can be back-filled separately.
    """
    out: dict = {}
    tgt = tgt_obj if isinstance(tgt_obj, dict) else {}
    for key, en_val in en_obj.items():
        cur_path = f"{path}.{key}" if path else key
        if isinstance(en_val, dict):
            out[key] = _ordered_merge(
                en_val, tgt.get(key), lang, namespace, cur_path, manifest, extras
            )
        else:
            existing = tgt.get(key)
            is_translated = (
                isinstance(existing, str)
                and not existing.startswith(TODO_MARKER)
                and key in tgt
            )
            if is_translated:
                out[key] = existing
            else:
                out[key] = f"{TODO_MARKER}{en_val}" if isinstance(en_val, str) else en_val
                manifest.append({
                    "language": lang,
                    "namespace": namespace,
                    "key": cur_path,
                    "en": en_val,
                })
    # Preserve target-only keys (en is missing them) after the en-ordered keys.
    for key, tgt_val in tgt.items():
        if key in en_obj:
            continue
        cur_path = f"{path}.{key}" if path else key
        out[key] = tgt_val
        for leaf, val in flatten_keys_with_values(tgt_val, cur_path).items():
            extras.append({"language": lang, "namespace": namespace, "key": leaf, "value": val})
    return out


def flatten_keys_with_values(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten to {dot.path: leaf_value}; a non-dict at top level maps prefix->value."""
    if not isinstance(obj, dict):
        return {prefix: obj}
    out: dict[str, Any] = {}
    for key, value in obj.items():
        fp = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_keys_with_values(value, fp))
        else:
            out[fp] = value
    return out


def scaffold_locales(translations: dict, manifest_path: Path) -> None:
    """
    Bring every target language up to en's key set:
    - create missing namespace files,
    - insert missing keys as TODO-marked English values,
    - preserve existing real translations,
    - write a manifest of every seeded key for the translation pass.
    Does not touch the reference language.
    """
    ref = translations.get(REFERENCE_LANG, {})
    if not ref:
        print(f"{Colors.RED}Reference language '{REFERENCE_LANG}' has no data; aborting.{Colors.RESET}")
        sys.exit(1)

    languages = [l for l in get_languages() if l != REFERENCE_LANG]
    manifest: list[dict] = []
    extras: list[dict] = []
    files_written = 0
    files_created = 0

    for lang in languages:
        lang_dir = I18N_DIR / lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        for namespace, en_content in ref.items():
            path = lang_dir / f"{namespace}.json"
            existed = path.exists()
            tgt_content = translations.get(lang, {}).get(namespace, {})
            merged = _ordered_merge(
                en_content, tgt_content, lang, namespace, "", manifest, extras
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
                f.write("\n")
            files_written += 1
            if not existed:
                files_created += 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{Colors.GREEN}{Colors.BOLD}Scaffold complete{Colors.RESET}")
    print(f"  Files written:        {files_written} ({files_created} newly created)")
    print(f"  Keys seeded as TODO:  {len(manifest)}")
    if extras:
        # Distinct key paths (across languages) that exist in targets but not in en.
        distinct = sorted({f"{e['namespace']}:{e['key']}" for e in extras})
        print(f"  {Colors.YELLOW}Target-only keys PRESERVED (missing from en): "
              f"{len(extras)} across langs, {len(distinct)} distinct{Colors.RESET}")
        print(f"    {Colors.YELLOW}→ consider back-filling these into en/*.json:{Colors.RESET}")
        for d in distinct[:20]:
            print(f"      - {d}")
        if len(distinct) > 20:
            print(f"      ... and {len(distinct) - 20} more")
    print(f"  Manifest (worklist):  {manifest_path}")
    # Per-language breakdown
    by_lang = defaultdict(int)
    for m in manifest:
        by_lang[m["language"]] += 1
    for lang in sorted(by_lang):
        print(f"    {Colors.CYAN}{lang}{Colors.RESET}: {by_lang[lang]} keys")


def print_report(issues: list[dict], title: str, color: str = Colors.RED) -> None:
    """Print a formatted report of issues."""
    if not issues:
        return
    
    print(f"\n{color}{Colors.BOLD}{title}{Colors.RESET}")
    print("=" * 60)
    
    # Group by type
    by_type = defaultdict(list)
    for issue in issues:
        by_type[issue["type"]].append(issue)
    
    for issue_type, type_issues in by_type.items():
        if issue_type == "missing_in_lang":
            print(f"\n{Colors.YELLOW}Missing keys in translations:{Colors.RESET}")
            # Group by language
            by_lang = defaultdict(list)
            for issue in type_issues:
                by_lang[issue["language"]].append(issue)
            for lang, lang_issues in sorted(by_lang.items()):
                print(f"  {Colors.CYAN}{lang}:{Colors.RESET}")
                for issue in lang_issues[:20]:  # Limit output
                    print(f"    - {issue['namespace']}:{issue['key']}")
                if len(lang_issues) > 20:
                    print(f"    ... and {len(lang_issues) - 20} more")
        
        elif issue_type == "extra_in_lang":
            print(f"\n{Colors.BLUE}Extra keys (not in {REFERENCE_LANG}):{Colors.RESET}")
            for issue in type_issues[:10]:
                print(f"  - [{issue['language']}] {issue['namespace']}:{issue['key']}")
            if len(type_issues) > 10:
                print(f"  ... and {len(type_issues) - 10} more")
        
        elif issue_type == "missing_namespace":
            print(f"\n{Colors.RED}Missing namespace files:{Colors.RESET}")
            for issue in type_issues:
                print(f"  - [{issue['language']}] {issue['namespace']}.json")
        
        elif issue_type == "missing_in_i18n":
            print(f"\n{Colors.RED}Keys used in code but not defined in i18n:{Colors.RESET}")
            for issue in type_issues:
                print(f"  - {issue['key']}")
                print(f"    {Colors.CYAN}at {issue['file']}:{issue['line']}{Colors.RESET}")
        
        elif issue_type == "unused":
            print(f"\n{Colors.MAGENTA}Potentially unused keys:{Colors.RESET}")
            # Group by namespace
            by_ns = defaultdict(list)
            for issue in type_issues:
                by_ns[issue["namespace"]].append(issue["key"])
            for ns, keys in sorted(by_ns.items()):
                print(f"  {Colors.CYAN}{ns}:{Colors.RESET}")
                for key in keys[:10]:
                    print(f"    - {key}")
                if len(keys) > 10:
                    print(f"    ... and {len(keys) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Validate translation files and usage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show extra keys and detailed output",
    )
    parser.add_argument(
        "--check-unused",
        action="store_true",
        help="Check for unused translation keys (may have false positives)",
    )
    parser.add_argument(
        "--check-source",
        action="store_true",
        default=True,
        help="Check that keys used in source exist in i18n (default: True)",
    )
    parser.add_argument(
        "--no-check-source",
        action="store_true",
        help="Skip checking source files for key usage",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Create missing namespace files and seed missing keys with TODO-marked "
             "English values in every non-reference language (preserves existing translations)",
    )
    parser.add_argument(
        "--scaffold-manifest",
        default=str(SCRIPT_DIR / "i18n_scaffold_manifest.json"),
        help="Path to write the seeded-key worklist when using --scaffold",
    )

    args = parser.parse_args()

    # Scaffold mode: mutate locale files, then exit (skips the read-only checks).
    if args.scaffold:
        print(f"{Colors.BOLD}Translation Scaffold{Colors.RESET}")
        print(f"i18n directory: {I18N_DIR}")
        translations = load_all_translations()
        scaffold_locales(translations, Path(args.scaffold_manifest))
        sys.exit(0)
    
    print(f"{Colors.BOLD}Translation Validation Script{Colors.RESET}")
    print(f"i18n directory: {I18N_DIR}")
    print(f"Reference language: {REFERENCE_LANG}")
    
    # Load all translations
    print(f"\n{Colors.CYAN}Loading translations...{Colors.RESET}")
    translations = load_all_translations()
    
    languages = list(translations.keys())
    print(f"Languages found: {', '.join(languages)}")
    
    namespaces = get_namespaces(REFERENCE_LANG)
    print(f"Namespaces found: {len(namespaces)}")
    
    all_issues = []
    
    # Check key consistency across languages
    print(f"\n{Colors.CYAN}Checking key consistency across languages...{Colors.RESET}")
    consistency_issues = check_key_consistency(translations, args.verbose)
    all_issues.extend(consistency_issues)
    
    # Check source files for missing keys
    if not args.no_check_source:
        print(f"\n{Colors.CYAN}Checking source files for translation usage...{Colors.RESET}")
        source_files = get_all_source_files()
        print(f"Scanning {len(source_files)} source files...")
        source_issues = check_source_keys(translations, args.verbose)
        all_issues.extend(source_issues)
    
    # Check for unused keys
    if args.check_unused:
        print(f"\n{Colors.CYAN}Checking for unused translation keys...{Colors.RESET}")
        unused_issues = check_unused_keys(translations, args.verbose)
        all_issues.extend(unused_issues)
    
    # Output results
    if args.json:
        print(json.dumps(all_issues, indent=2))
    else:
        if not all_issues:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All checks passed!{Colors.RESET}")
        else:
            # Count by type
            missing_in_lang = len([i for i in all_issues if i["type"] == "missing_in_lang"])
            missing_in_i18n = len([i for i in all_issues if i["type"] == "missing_in_i18n"])
            missing_ns = len([i for i in all_issues if i["type"] == "missing_namespace"])
            unused = len([i for i in all_issues if i["type"] == "unused"])
            
            print_report(all_issues, "Issues Found")
            
            print(f"\n{Colors.BOLD}Summary:{Colors.RESET}")
            if missing_in_lang:
                print(f"  {Colors.YELLOW}⚠ {missing_in_lang} keys missing in non-{REFERENCE_LANG} languages{Colors.RESET}")
            if missing_ns:
                print(f"  {Colors.RED}✗ {missing_ns} namespace files missing{Colors.RESET}")
            if missing_in_i18n:
                print(f"  {Colors.RED}✗ {missing_in_i18n} keys used in code but not defined{Colors.RESET}")
            if unused:
                print(f"  {Colors.MAGENTA}? {unused} potentially unused keys{Colors.RESET}")
    
    # Exit with error if critical issues found
    critical_issues = [i for i in all_issues if i["type"] in ("missing_in_i18n", "missing_namespace")]
    if critical_issues:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

