// Types for the workflow-designer template-variable inspector.
//
// Mirror of the Pydantic models in
// ``src/backend/src/models/process_workflows.py`` (TemplateVarDescriptor,
// TemplateVarGroup, TemplateVarsResponse).
//
// Workflow authors editing a webhook ``body_template`` see these
// descriptors in a side panel so they know what ``${...}`` placeholders
// are available for the workflow's (trigger, entity_type) pair.

export type TemplateVarType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'array'
  | 'object'
  | 'enum';

export interface TemplateVarDescriptor {
  // Placeholder body (no ``${}`` wrapper) — e.g. ``entity.catalogs``.
  path: string;
  type: TemplateVarType;
  description: string;
  // Realistic example value. Lists/objects render as JSON in the preview chip.
  sample?: unknown;
  // Populated only when ``type === 'enum'``.
  enum_values?: string[] | null;
}

export interface TemplateVarGroup {
  // Short slug — e.g. ``entity``, ``flat``.
  namespace: string;
  description: string;
  variables: TemplateVarDescriptor[];
}

export interface TemplateVarsResponse {
  trigger: string;
  entity_type: string;
  groups: TemplateVarGroup[];
}
