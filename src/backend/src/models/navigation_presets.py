"""Navigation presets (#1325): menu and home page settings for the default roles.

A preset is data (``data/presets/navigation/<id>.yaml``): per role name, the menu entries to
show and the home sections to set. The API models describe what applying it would do (the
preview), what it did, and the snapshot that ``undo`` restores.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from src.common.features import NAV_MENU_ENTRIES
from src.models.settings import HomeSection


# --- Preset files -----------------------------------------------------------------------

class NavigationPresetRoleDef(BaseModel):
    """What a preset sets on one role."""

    shown: List[str] = Field(default_factory=list)
    # None = the preset leaves the role's home sections unchanged.
    home_sections: Optional[List[HomeSection]] = None

    @field_validator('shown')
    @classmethod
    def _known_entries(cls, value: List[str]) -> List[str]:
        unknown = [entry for entry in value if entry not in NAV_MENU_ENTRIES]
        if unknown:
            raise ValueError(f"unknown menu entries: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class NavigationPresetDef(BaseModel):
    """A preset file: its id and, per default role name, what it sets."""

    id: str
    roles: Dict[str, NavigationPresetRoleDef]


# --- API ----------------------------------------------------------------------------------

class NavigationPresetRolePreview(BaseModel):
    """What applying a preset would do to one role."""

    role_name: str
    role_id: Optional[str] = None
    found: bool
    shown: List[str]
    hidden: List[str]
    # Entries in ``shown`` the role has no access to: they stay absent from its menu.
    no_access: List[str]
    home_sections: Optional[List[HomeSection]] = None
    current_hidden: List[str]
    current_home_sections: List[HomeSection]
    changed: bool


class NavigationPresetPreview(BaseModel):
    id: str
    roles: List[NavigationPresetRolePreview]


class NavigationPresetRoleRef(BaseModel):
    role_id: str
    role_name: str


class NavigationPresetLastApplied(BaseModel):
    """The last application: what ``undo`` would restore."""

    preset_id: str
    applied_at: str
    applied_by: Optional[str] = None
    roles: List[NavigationPresetRoleRef]


class NavigationPresetsResponse(BaseModel):
    presets: List[NavigationPresetPreview]
    last_applied: Optional[NavigationPresetLastApplied] = None


class NavigationPresetApplyResult(BaseModel):
    preset_id: str
    changed_roles: List[NavigationPresetRoleRef]
    unchanged_roles: List[str]
    missing_roles: List[str]


class NavigationPresetUndoResult(BaseModel):
    preset_id: str
    restored_roles: List[NavigationPresetRoleRef]
    missing_roles: List[str]
