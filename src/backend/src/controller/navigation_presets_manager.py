"""Navigation presets (#1325): preview, apply and undo menu and home page settings.

A preset (``data/presets/navigation/<id>.yaml``) names default roles and, for each, the menu
entries to show and the home sections to set. Applying it changes only
``hidden_nav_features`` and ``home_sections`` of those roles, never their feature
permissions. The previous values of the changed roles are kept in an app setting, so the
last application can be undone. Roles are matched by name.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.common.api_errors import CodedValueError
from src.common.features import (
    ACCESS_LEVEL_ORDER, NAV_MENU_ENTRIES, FeatureAccessLevel, is_known_nav_id,
)
from src.common.logging import get_logger
from src.controller.settings_manager import SettingsManager
from src.db_models.settings import AppRoleDb
from src.models.navigation_presets import (
    NavigationPresetApplyResult,
    NavigationPresetDef,
    NavigationPresetLastApplied,
    NavigationPresetPreview,
    NavigationPresetRoleDef,
    NavigationPresetRolePreview,
    NavigationPresetRoleRef,
    NavigationPresetsResponse,
    NavigationPresetUndoResult,
)
from src.models.settings import AppRole, AppRoleUpdate, HomeSection
from src.repositories.app_settings_repository import app_settings_repo
from src.repositories.settings_repository import app_role_repo

logger = get_logger(__name__)

PRESETS_DIR = Path(__file__).parent.parent / 'data' / 'presets' / 'navigation'
LAST_APPLIED_SETTING_KEY = 'navigation_preset_last_applied'

_READ_ONLY = ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY]


class NavigationPresetUnknownError(CodedValueError):
    """The preset id doesn't name a shipped preset."""

    code = 'navigation_preset_unknown'


class NavigationPresetNothingToUndoError(CodedValueError):
    """No preset application is kept: there is nothing to undo."""

    code = 'navigation_preset_nothing_to_undo'


def load_navigation_presets(directory: Path = PRESETS_DIR) -> Dict[str, NavigationPresetDef]:
    """Load the preset files of ``directory``, keyed by preset id.

    A file that doesn't parse or validate (bad YAML, unknown menu entry or home section, an id
    that differs from the file name) is logged and skipped, so one bad file doesn't hide the
    others.
    """
    presets: Dict[str, NavigationPresetDef] = {}
    for path in sorted(directory.glob('*.yaml')):
        try:
            raw = yaml.safe_load(path.read_text(encoding='utf-8'))
            preset = NavigationPresetDef.model_validate(raw)
            if preset.id != path.stem:
                raise ValueError(f"preset id '{preset.id}' differs from the file name")
        except (OSError, yaml.YAMLError, ValidationError, ValueError) as e:
            logger.error("Skipping invalid navigation preset file %s: %s", path.name, e)
            continue
        presets[preset.id] = preset
    return presets


def compute_hidden_entries(role: AppRole, shown: List[str]) -> List[str]:
    """The menu entries a preset hides on ``role``: every entry it doesn't show that the role
    has access to (entries without access aren't in its menu anyway)."""
    return [
        entry for entry, feature_id in NAV_MENU_ENTRIES.items()
        if entry not in shown and _level(role, feature_id) >= _READ_ONLY
    ]


def _level(role: AppRole, feature_id: str) -> int:
    level = (role.feature_permissions or {}).get(feature_id, FeatureAccessLevel.NONE)
    return ACCESS_LEVEL_ORDER.get(level, 0)


def _home_values(sections: Optional[List[Any]]) -> List[str]:
    return [s.value if isinstance(s, HomeSection) else str(s) for s in (sections or [])]


class NavigationPresetsManager:
    """Preview, apply and undo navigation presets on the roles of a ``SettingsManager``."""

    def __init__(
        self,
        settings_manager: SettingsManager,
        presets: Optional[Dict[str, NavigationPresetDef]] = None,
    ):
        self._settings_manager = settings_manager
        self._presets = load_navigation_presets() if presets is None else presets

    # --- Preview --------------------------------------------------------------------------

    def get_presets(self) -> NavigationPresetsResponse:
        """Every preset with what it would do to each of its roles, and the last application."""
        roles_by_name = self._roles_by_name()
        return NavigationPresetsResponse(
            presets=[
                NavigationPresetPreview(
                    id=preset_id,
                    roles=[
                        self._preview_role(name, roles_by_name.get(name), definition)
                        for name, definition in preset.roles.items()
                    ],
                )
                for preset_id, preset in self._presets.items()
            ],
            last_applied=self._load_last_applied(),
        )

    def _roles_by_name(self) -> Dict[str, AppRole]:
        return {role.name: role for role in self._settings_manager.list_app_roles()}

    def _preview_role(
        self, name: str, role: Optional[AppRole], definition: NavigationPresetRoleDef
    ) -> NavigationPresetRolePreview:
        shown = list(definition.shown)
        if role is None:
            return NavigationPresetRolePreview(
                role_name=name, role_id=None, found=False, shown=shown, hidden=[],
                no_access=[], home_sections=definition.home_sections,
                current_hidden=[], current_home_sections=[], changed=False,
            )
        current_hidden = list(role.hidden_nav_features or [])
        current_home = list(role.home_sections or [])
        if role.is_admin:
            # An admin role shows every entry and is never changed by a preset.
            return NavigationPresetRolePreview(
                role_name=name, role_id=str(role.id), found=True, shown=shown, hidden=[],
                no_access=[], home_sections=None, current_hidden=current_hidden,
                current_home_sections=current_home, changed=False,
            )
        hidden = compute_hidden_entries(role, shown)
        no_access = [e for e in shown if _level(role, NAV_MENU_ENTRIES[e]) < _READ_ONLY]
        changed = set(hidden) != set(current_hidden) or (
            definition.home_sections is not None
            and set(_home_values(definition.home_sections)) != set(_home_values(current_home))
        )
        return NavigationPresetRolePreview(
            role_name=name, role_id=str(role.id), found=True, shown=shown, hidden=hidden,
            no_access=no_access, home_sections=definition.home_sections,
            current_hidden=current_hidden, current_home_sections=current_home, changed=changed,
        )

    # --- Apply ----------------------------------------------------------------------------

    def apply(
        self,
        preset_id: str,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
    ) -> NavigationPresetApplyResult:
        """Apply a preset to its roles.

        Only ``hidden_nav_features`` and (when the preset sets them) ``home_sections`` of the
        roles that would change are written, together with the snapshot ``undo`` restores, in
        one transaction. When no role changes, nothing is written and the snapshot of an
        earlier application stays. Applying another preset replaces the snapshot.
        """
        preset = self._presets.get(preset_id)
        if preset is None:
            raise NavigationPresetUnknownError(
                f"Unknown navigation preset: {preset_id}", preset_id=preset_id
            )
        db = self._settings_manager._db
        roles_by_name = self._roles_by_name()
        changed: List[Tuple[AppRoleDb, NavigationPresetRoleRef]] = []
        unchanged: List[str] = []
        missing: List[str] = []
        snapshot_roles: Dict[str, Dict[str, Any]] = {}
        try:
            for name, definition in preset.roles.items():
                role = roles_by_name.get(name)
                if role is None:
                    missing.append(name)
                    continue
                preview = self._preview_role(name, role, definition)
                row = app_role_repo.get(db=db, id=str(role.id))
                if row is None:
                    missing.append(name)
                    continue
                if not preview.changed:
                    unchanged.append(name)
                    continue
                snapshot_roles[str(role.id)] = {
                    'name': role.name,
                    'hidden_nav_features': list(role.hidden_nav_features or []),
                    'home_sections': _home_values(role.home_sections),
                }
                update = {'hidden_nav_features': preview.hidden}
                if definition.home_sections is not None:
                    update['home_sections'] = list(definition.home_sections)
                app_role_repo.update(db, db_obj=row, obj_in=AppRoleUpdate(**update))
                ref = NavigationPresetRoleRef(role_id=str(role.id), role_name=name)
                changed.append((row, ref))
            if changed:
                app_settings_repo.set(
                    db, LAST_APPLIED_SETTING_KEY,
                    json.dumps({
                        'preset_id': preset_id,
                        'applied_at': datetime.now(timezone.utc).isoformat(),
                        'applied_by': user,
                        'roles': snapshot_roles,
                    }),
                    commit=False,
                )
            db.commit()
        except SQLAlchemyError as e:
            logger.error(
                "Database error applying navigation preset %s: %s", preset_id, e, exc_info=True
            )
            db.rollback()
            raise RuntimeError("Failed to apply navigation preset due to database error.") from e
        except Exception:
            db.rollback()
            raise

        self._deliver(changed, user, background_tasks)
        logger.info(
            "Applied navigation preset %s: %d changed, %d unchanged, %d missing",
            preset_id, len(changed), len(unchanged), len(missing),
        )
        return NavigationPresetApplyResult(
            preset_id=preset_id,
            changed_roles=[ref for _, ref in changed],
            unchanged_roles=unchanged,
            missing_roles=missing,
        )

    # --- Undo -----------------------------------------------------------------------------

    def undo(
        self, user: Optional[str] = None, background_tasks: Optional[Any] = None
    ) -> NavigationPresetUndoResult:
        """Restore the menus and home sections the last application changed, then forget it.

        Roles deleted since are reported as missing. Menu entries that no longer exist are
        dropped from the restored lists.
        """
        snapshot = self._read_snapshot()
        if snapshot is None:
            raise NavigationPresetNothingToUndoError("No navigation preset application to undo.")
        db = self._settings_manager._db
        restored: List[Tuple[AppRoleDb, NavigationPresetRoleRef]] = []
        missing: List[str] = []
        try:
            for role_id, previous in snapshot['roles'].items():
                name = previous.get('name', role_id)
                row = app_role_repo.get(db=db, id=role_id)
                if row is None:
                    missing.append(name)
                    continue
                app_role_repo.update(
                    db, db_obj=row,
                    obj_in=AppRoleUpdate(
                        hidden_nav_features=[
                            e for e in previous.get('hidden_nav_features', [])
                            if isinstance(e, str) and is_known_nav_id(e)
                        ],
                        home_sections=self._valid_sections(previous.get('home_sections', [])),
                    ),
                )
                ref = NavigationPresetRoleRef(role_id=role_id, role_name=row.name)
                restored.append((row, ref))
            app_settings_repo.delete(db, LAST_APPLIED_SETTING_KEY, commit=False)
            db.commit()
        except SQLAlchemyError as e:
            logger.error("Database error undoing navigation preset: %s", e, exc_info=True)
            db.rollback()
            raise RuntimeError("Failed to undo navigation preset due to database error.") from e
        except Exception:
            db.rollback()
            raise

        self._deliver(restored, user, background_tasks)
        logger.info(
            "Undid navigation preset %s: %d restored, %d missing",
            snapshot['preset_id'], len(restored), len(missing),
        )
        return NavigationPresetUndoResult(
            preset_id=snapshot['preset_id'],
            restored_roles=[ref for _, ref in restored],
            missing_roles=missing,
        )

    # --- Snapshot -------------------------------------------------------------------------

    @staticmethod
    def _valid_sections(values: List[Any]) -> List[HomeSection]:
        valid = {s.value for s in HomeSection}
        return [HomeSection(v) for v in values if isinstance(v, str) and v in valid]

    def _read_snapshot(self) -> Optional[Dict[str, Any]]:
        """The kept application, or None when there is none or it can't be read."""
        raw = app_settings_repo.get_by_key(self._settings_manager._db, LAST_APPLIED_SETTING_KEY)
        if not raw:
            return None
        try:
            snapshot = json.loads(raw)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get('roles'), dict):
                raise ValueError("unexpected shape")
            if not isinstance(snapshot.get('preset_id'), str):
                raise ValueError("no preset id")
            return snapshot
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Ignoring unreadable %s setting: %s", LAST_APPLIED_SETTING_KEY, e)
            return None

    def _load_last_applied(self) -> Optional[NavigationPresetLastApplied]:
        snapshot = self._read_snapshot()
        if snapshot is None:
            return None
        return NavigationPresetLastApplied(
            preset_id=snapshot['preset_id'],
            applied_at=str(snapshot.get('applied_at') or ''),
            applied_by=snapshot.get('applied_by'),
            roles=[
                NavigationPresetRoleRef(
                    role_id=role_id, role_name=str(prev.get('name', role_id))
                )
                for role_id, prev in snapshot['roles'].items()
                if isinstance(prev, dict)
            ],
        )

    # --- Delivery -------------------------------------------------------------------------

    def _deliver(
        self,
        rows: List[Tuple[AppRoleDb, NavigationPresetRoleRef]],
        user: Optional[str],
        background_tasks: Optional[Any],
    ) -> None:
        """Queue the role delivery (git sync and other modes) of each changed role, as a role
        update does."""
        for row, _ in rows:
            self._settings_manager._queue_role_delivery(
                entity=row,
                change_type_name="ROLE_UPDATE",
                user=user,
                background_tasks=background_tasks,
            )
