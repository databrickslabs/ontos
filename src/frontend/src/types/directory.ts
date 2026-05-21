/**
 * TypeScript counterparts to the backend's Directory API models
 * (see api/models/directory.py).
 *
 * The Directory layer is the generic abstraction over identity
 * providers. v1 ships one concrete provider (Microsoft Entra ID via
 * Microsoft Graph); these types stay provider-agnostic.
 */

export type PrincipalType = 'user' | 'group' | 'unknown';

export interface Principal {
  /** user | group | unknown */
  type: PrincipalType;
  /**
   * Persisted identifier. UPN/email for users, displayName for groups.
   * This is the value the picker emits and consumes -- NOT a GUID.
   */
  id: string;
  display_name: string;
  /**
   * Secondary identifier shown on row two of search results and as
   * tooltip on selected badges. Email/UPN for users, GUID for groups.
   */
  sub_label?: string | null;
}

export interface DirectoryStatus {
  configured: boolean;
  provider_type: string | null;
  connection_name: string | null;
}

export interface DirectoryTestResult {
  healthy: boolean;
  error?: string | null;
}

export interface DirectorySearchResponse {
  results: Principal[];
}

export interface DirectorySettingsUpdate {
  provider_type?: string | null;
  connection_name?: string | null;
}

export interface UcHttpConnection {
  name: string;
  connection_type: string;
  comment?: string | null;
  owner?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
}

/**
 * Supported provider types. ``entra`` is the only one enabled in v1;
 * additional entries here will be rendered disabled in the Settings
 * tab to telegraph the abstraction.
 */
export const DIRECTORY_PROVIDER_TYPES = ['entra'] as const;
export type DirectoryProviderType = (typeof DIRECTORY_PROVIDER_TYPES)[number];
