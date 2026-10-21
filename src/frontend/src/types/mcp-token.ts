/**
 * Types for MCP (Model Context Protocol) tokens.
 * 
 * MCP tokens are API keys that allow AI assistants to interact
 * with the application's tools via the MCP endpoint.
 */

export interface MCPTokenCreate {
  name: string;
  scopes: string[];
  expires_days?: number | null;
  is_keyless_default?: boolean;
}

export interface MCPTokenResponse {
  id: string;
  name: string;
  token: string; // Plaintext token - only shown once on creation
  scopes: string[];
  created_at: string;
  expires_at: string | null;
}

export interface MCPTokenInfo {
  id: string;
  name: string;
  scopes: string[];
  created_by: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  is_expired: boolean;
  is_keyless_default: boolean;
}

export interface MCPTokenList {
  tokens: MCPTokenInfo[];
  total: number;
}

/**
 * Available scopes for MCP tokens.
 * Organized by category for the UI.
 */
export const MCP_SCOPE_CATEGORIES = {
  'Data Products': [
    { value: 'data-products:read', label: 'Read Data Products', description: 'Search, view, and list data products' },
    { value: 'data-products:write', label: 'Write Data Products', description: 'Create, update, and delete data products' },
  ],
  'Data Contracts': [
    { value: 'contracts:read', label: 'Read Contracts', description: 'Search, view, and list data contracts' },
    { value: 'contracts:write', label: 'Write Contracts', description: 'Create, update, and delete data contracts' },
  ],
  'Domains': [
    { value: 'domains:read', label: 'Read Domains', description: 'Search and view domains' },
    { value: 'domains:write', label: 'Write Domains', description: 'Create, update, and delete domains' },
  ],
  'Teams': [
    { value: 'teams:read', label: 'Read Teams', description: 'Search and view teams' },
    { value: 'teams:write', label: 'Write Teams', description: 'Create, update, and delete teams' },
  ],
  'Projects': [
    { value: 'projects:read', label: 'Read Projects', description: 'Search and view projects' },
    { value: 'projects:write', label: 'Write Projects', description: 'Create, update, and delete projects' },
  ],
  'Tags': [
    { value: 'tags:read', label: 'Read Tags', description: 'Search tags and view entity tags' },
    { value: 'tags:write', label: 'Write Tags', description: 'Create, update, delete tags and assignments' },
  ],
  'Semantic Models': [
    { value: 'semantic:read', label: 'Read Semantic', description: 'Search concepts, view semantic links' },
    { value: 'semantic:write', label: 'Write Semantic', description: 'Add and remove semantic links' },
    { value: 'sparql:query', label: 'SPARQL Query', description: 'Execute SPARQL queries against the knowledge graph' },
  ],
  'Analytics': [
    { value: 'analytics:read', label: 'Analytics', description: 'Get schemas, explore catalogs, execute queries' },
  ],
  'Other': [
    { value: 'search:read', label: 'Global Search', description: 'Search across all indexed entities' },
    { value: 'costs:read', label: 'Costs', description: 'View data product cost information' },
  ],
  'Admin': [
    { value: '*', label: 'Full Access (Admin)', description: 'Access to all tools - use with caution' },
  ],
} as const;

/**
 * Flatten all scopes for easy iteration
 */
export const ALL_MCP_SCOPES = Object.values(MCP_SCOPE_CATEGORIES).flat();

