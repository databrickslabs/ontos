import type { HomeSection } from '@/types/settings';

/** What applying a navigation preset (#1325) would do to one role. */
export interface NavigationPresetRolePreview {
  role_name: string;
  role_id: string | null;
  found: boolean;
  /** Menu entries the preset shows (menu entry ids, see `getNavFeatureId`). */
  shown: string[];
  hidden: string[];
  /** Entries in `shown` the role has no access to: they stay absent from its menu. */
  no_access: string[];
  /** Null = the preset leaves the role's home page unchanged. */
  home_sections: HomeSection[] | null;
  current_hidden: string[];
  current_home_sections: HomeSection[];
  changed: boolean;
}

export interface NavigationPreset {
  id: string;
  roles: NavigationPresetRolePreview[];
}

export interface NavigationPresetRoleRef {
  role_id: string;
  role_name: string;
}

export interface NavigationPresetLastApplied {
  preset_id: string;
  applied_at: string;
  applied_by: string | null;
  roles: NavigationPresetRoleRef[];
}

export interface NavigationPresetsResponse {
  presets: NavigationPreset[];
  last_applied: NavigationPresetLastApplied | null;
}

export interface NavigationPresetApplyResult {
  preset_id: string;
  changed_roles: NavigationPresetRoleRef[];
  unchanged_roles: string[];
  missing_roles: string[];
}

export interface NavigationPresetUndoResult {
  preset_id: string;
  restored_roles: NavigationPresetRoleRef[];
  missing_roles: string[];
}

export const NAVIGATION_PRESETS_URL = '/api/settings/navigation-presets';
