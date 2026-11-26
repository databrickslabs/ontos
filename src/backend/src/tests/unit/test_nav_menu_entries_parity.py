"""``NAV_MENU_ENTRIES`` mirrors the sidebar entries of ``frontend/src/config/features.ts``.

The backend map is kept by hand; this test reads the frontend file and fails when the two
drift (an entry added, removed, renamed, reordered, or pointed at another permission).
"""
import re
from pathlib import Path
from typing import Dict

from src.common.features import APP_FEATURES, NAV_ENTRY_FEATURES, NAV_MENU_ENTRIES

FEATURES_TS = Path(__file__).resolve().parents[4] / 'frontend' / 'src' / 'config' / 'features.ts'


def _frontend_entries() -> Dict[str, str]:
    """Menu entry id -> permission id, in menu order, as the frontend derives them: the
    entry's flag id is ``navId || permissionId || id``, its permission ``permissionId || id``.
    Entries without a permission feature (Search, My Requests) have no flag and are skipped."""
    source = FEATURES_TS.read_text(encoding='utf-8')
    start = source.index('export const features')
    body = source[start:re.search(r'\n\s*\];', source[start:]).end() + start]
    entries: Dict[str, str] = {}
    for block in re.findall(r'\{\s*\n(.*?)\n\s*\},', body, flags=re.S):
        fields = dict(re.findall(r"^\s*(id|permissionId|navId):\s*'([^']+)'", block, flags=re.M))
        permission_id = fields.get('permissionId') or fields['id']
        if permission_id not in APP_FEATURES:
            continue
        entries[fields.get('navId') or permission_id] = permission_id
    return entries


def test_the_frontend_file_is_found_and_parsed():
    entries = _frontend_entries()
    assert len(entries) > 10
    assert entries['semantic-models'] == 'semantic-models'  # the Concepts entry


def test_nav_menu_entries_match_the_frontend_sidebar_in_order():
    frontend = _frontend_entries()
    assert list(NAV_MENU_ENTRIES.items()) == list(frontend.items())


def test_entries_with_their_own_flag_match_the_frontend():
    frontend = {e: f for e, f in _frontend_entries().items() if e != f}
    assert NAV_ENTRY_FEATURES == frontend
