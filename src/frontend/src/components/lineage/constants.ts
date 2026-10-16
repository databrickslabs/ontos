/**
 * Shared constants for column-based lineage visualization.
 * Self-contained — no imports from existing lineage components.
 */

import {
  Box, Boxes, Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain,
  Activity, Server, Shield, BookOpen, Database, Shapes, Package, Tag, Send,
  Lightbulb, FileText, ListTree, Plug,
} from 'lucide-react';
import type React from 'react';

// ─── Entity type colors ──────────────────────────────────────────────────

export const TYPE_COLOR: Record<string, { bg: string; border: string; text: string; minimap: string; hex: string }> = {
  BusinessTerm:     { bg: 'bg-indigo-500/10',   border: 'border-indigo-500/50',  text: 'text-indigo-600 dark:text-indigo-400',   minimap: '#6366f1', hex: '#6366f1' },
  LogicalEntity:    { bg: 'bg-violet-500/10',   border: 'border-violet-500/40',  text: 'text-violet-600 dark:text-violet-400',   minimap: '#8b5cf6', hex: '#8b5cf6' },
  LogicalAttribute: { bg: 'bg-fuchsia-500/10',  border: 'border-fuchsia-500/40', text: 'text-fuchsia-600 dark:text-fuchsia-400', minimap: '#d946ef', hex: '#d946ef' },
  System:           { bg: 'bg-blue-500/10',     border: 'border-blue-500/40',    text: 'text-blue-600 dark:text-blue-400',       minimap: '#3b82f6', hex: '#3b82f6' },
  DataDomain:       { bg: 'bg-purple-500/10',   border: 'border-purple-500/40',  text: 'text-purple-600 dark:text-purple-400',   minimap: '#a855f7', hex: '#a855f7' },
  DataProduct:      { bg: 'bg-emerald-500/10',  border: 'border-emerald-500/40', text: 'text-emerald-600 dark:text-emerald-400', minimap: '#10b981', hex: '#10b981' },
  Dataset:          { bg: 'bg-amber-500/10',    border: 'border-amber-500/40',   text: 'text-amber-600 dark:text-amber-400',     minimap: '#f59e0b', hex: '#f59e0b' },
  DeliveryChannel:  { bg: 'bg-cyan-500/10',     border: 'border-cyan-500/40',    text: 'text-cyan-600 dark:text-cyan-400',       minimap: '#06b6d4', hex: '#06b6d4' },
  Policy:           { bg: 'bg-red-500/10',      border: 'border-red-500/40',     text: 'text-red-600 dark:text-red-400',         minimap: '#ef4444', hex: '#ef4444' },
  Table:            { bg: 'bg-orange-500/10',    border: 'border-orange-500/40',  text: 'text-orange-600 dark:text-orange-400',   minimap: '#f97316', hex: '#f97316' },
  View:             { bg: 'bg-teal-500/10',     border: 'border-teal-500/40',    text: 'text-teal-600 dark:text-teal-400',       minimap: '#14b8a6', hex: '#14b8a6' },
  Column:           { bg: 'bg-slate-500/10',    border: 'border-slate-500/40',   text: 'text-slate-600 dark:text-slate-400',     minimap: '#64748b', hex: '#64748b' },
  Schema:           { bg: 'bg-violet-500/10',   border: 'border-violet-500/40',  text: 'text-violet-600 dark:text-violet-400',   minimap: '#8b5cf6', hex: '#8b5cf6' },
  DataContract:     { bg: 'bg-pink-500/10',     border: 'border-pink-500/40',    text: 'text-pink-600 dark:text-pink-400',       minimap: '#ec4899', hex: '#ec4899' },
  Concept:          { bg: 'bg-sky-500/10',      border: 'border-sky-500/40',     text: 'text-sky-600 dark:text-sky-400',         minimap: '#0ea5e9', hex: '#0ea5e9' },
  OutputPort:       { bg: 'bg-green-500/10',    border: 'border-green-500/40',   text: 'text-green-600 dark:text-green-400',     minimap: '#22c55e', hex: '#22c55e' },
  SchemaObject:     { bg: 'bg-rose-500/10',     border: 'border-rose-500/40',    text: 'text-rose-600 dark:text-rose-400',       minimap: '#f43f5e', hex: '#f43f5e' },
  SchemaProperty:   { bg: 'bg-rose-400/10',     border: 'border-rose-400/40',    text: 'text-rose-500 dark:text-rose-300',       minimap: '#fb7185', hex: '#fb7185' },
};

/** Fallback icons for types the ontology does not describe (synthetic lineage nodes) */
export const TYPE_ICON_FALLBACK: Record<string, React.ElementType> = {
  Concept: Lightbulb,
  SchemaObject: FileText,
  SchemaProperty: ListTree,
  OutputPort: Plug,
};

// ─── Model layers (lanes) ────────────────────────────────────────────────

/** Lane order, business → platform. Matches ontos:modelLayer values. */
export const MODEL_LAYERS = ['business', 'delivery', 'logical', 'physical', 'other'] as const;
export type ModelLayer = typeof MODEL_LAYERS[number];

export const DEFAULT_HEX = '#6b7280';

export function hexForType(type: string): string {
  return TYPE_COLOR[type]?.hex || DEFAULT_HEX;
}

// ─── Icon map ────────────────────────────────────────────────────────────

export const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, Shapes, Box, Boxes, Package, Tag, Send,
  Lightbulb, FileText, ListTree, Plug,
};

// ─── Route helpers ───────────────────────────────────────────────────────

export const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
};

export function getEntityRoute(entityType: string, entityId: string, contextId?: string | null): string {
  if (entityType === 'Concept') return `/concepts/browser/${encodeURIComponent(entityId)}`;
  // Sub-entities navigate to their owner (contract / product)
  if ((entityType === 'SchemaObject' || entityType === 'SchemaProperty') && contextId) {
    return `/data-contracts/${contextId}`;
  }
  if (entityType === 'OutputPort' && contextId) return `/data-products/${contextId}`;
  const base = TYPE_ROUTE_MAP[entityType];
  if (base) return `${base}/${entityId}`;
  return `/assets/${entityId}`;
}

export function humanizeType(type: string): string {
  return type.replace(/([A-Z])/g, ' $1').trim();
}

// ─── Edge relationship categories ────────────────────────────────────────

/** Data flow relationships — solid lines */
export const FLOW_RELS = new Set([
  'dependsOn', 'depends on',
  'consumesFrom', 'consumes from',
  'producesTo', 'produces to',
  'feedsInto', 'feeds into',
  'derivedFrom', 'derived from',
  'inputTo', 'input to',
  'outputFrom', 'output from',
]);

/** Containment / hierarchy relationships — solid muted lines */
export const HIERARCHY_RELS = new Set([
  'hasTable', 'has table',
  'hasView', 'has view',
  'hasColumn', 'has column',
  'containsDataset', 'contains dataset',
  'contains',
  'hasLogicalAttribute', 'has logical attribute',
  'containsProduct', 'contains product',
  'hasTopic', 'has topic',
  'hasDataset', 'has dataset',
  'hasOutputPort', 'has output port',
  'hasSchemaObject', 'has schema',
  'hasProperty', 'has property',
]);

/** Refinement between model layers (logical → physical) — solid accent lines */
export const IMPLEMENTATION_RELS = new Set([
  'implementedBy', 'implemented by',
  'portHasAsset', 'exposes',
  'portHasTable', 'portHasView', 'portHasDataset',
]);

/** Governance relationships — dashed lines */
export const GOVERNANCE_RELS = new Set([
  'governedBy', 'governed by',
  'implementsContract', 'implements contract',
  'attachedPolicy', 'attached policy',
  'ownedBy', 'owned by',
  'managedBy', 'managed by',
  'certifiedBy', 'certified by',
  'portHasContract',
]);

/** Semantic relationships — dotted lines */
export const SEMANTIC_RELS = new Set([
  'hasTerm', 'has term',
  'relatesTo', 'relates to',
  'synonymOf', 'synonym of',
  'seeAlso', 'see also',
  'similarTo', 'similar to',
  'describes',
  'hasSemanticConcept',
]);

export type EdgeCategory = 'flow' | 'hierarchy' | 'implementation' | 'governance' | 'semantic';

export function categorizeEdge(relType: string): EdgeCategory {
  if (FLOW_RELS.has(relType)) return 'flow';
  if (HIERARCHY_RELS.has(relType)) return 'hierarchy';
  if (IMPLEMENTATION_RELS.has(relType)) return 'implementation';
  if (GOVERNANCE_RELS.has(relType)) return 'governance';
  if (SEMANTIC_RELS.has(relType)) return 'semantic';
  // Default: treat unknown relationships as flow
  return 'flow';
}
