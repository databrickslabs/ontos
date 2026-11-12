/**
 * Types for workflow configuration system.
 * 
 * Workflows can declare configurable parameters in their YAML files,
 * which can be managed through the UI.
 */

export interface WorkflowParameterDefinition {
  name: string;
  type: 'string' | 'integer' | 'boolean' | 'select' | 'entity_patterns' | 'tag_sync_configs';
  default?: any;
  description?: string;
  required?: boolean;

  // Type-specific constraints
  options?: string[];  // For select type
  min_value?: number;  // For integer/float types
  max_value?: number;  // For integer/float types
  pattern?: string;    // Regex pattern for string validation
  entity_types?: string[];  // For entity_patterns and tag_sync_configs types
}

export interface EntityPatternConfig {
  entity_type: string;  // "contract", "product", "domain", etc.
  enabled: boolean;

  // Filter pattern (optional, for scoping)
  filter_source?: string;  // "key" or "value"
  filter_pattern?: string;  // Regex pattern

  // Key pattern (required)
  key_pattern: string;  // Regex pattern to match tag keys

  // Value extraction (required)
  value_extraction_source: string;  // "key" or "value"
  value_extraction_pattern: string;  // Regex pattern with capture group
}

export interface TagSyncConfig {
  entity_type: 'semantic_assignment' | 'data_domain' | 'data_contract' | 'data_product' | 'asset';
  enabled: boolean;
  tag_key_format: string;    // Format string with {VARIABLE} placeholders
  tag_value_format: string;  // Format string with {VARIABLE} placeholders
  mapping?: string | null;   // Named mapping id, e.g. 'lifecycle_status'; none = main entry
}

export interface WorkflowConfiguration {
  workflow_id: string;
  configuration: Record<string, any>;
}

export interface WorkflowConfigurationUpdate {
  configuration: Record<string, any>;
}

export interface WorkflowConfigurationResponse {
  id: string;
  workflow_id: string;
  configuration: Record<string, any>;
  created_at: string;
  updated_at: string;
}

