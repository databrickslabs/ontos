/**
 * Shared lifecycle types used across all entity types.
 *
 * EntityStatus replaces DataProductStatus, ContractStatus, DatasetStatus, AssetStatus.
 * PublicationScope replaces the boolean `published` flag.
 */

export type EntityStatus =
  | 'draft'
  | 'sandbox'
  | 'proposed'
  | 'under_review'
  | 'approved'
  | 'active'
  | 'deprecated'
  | 'retired';

export type PublicationScope = 'none' | 'domain' | 'organization' | 'external';

export interface CertificationInfo {
  certification_level: number | null;
  inherited_certification_level: number | null;
  certified_at: string | null;
  certified_by: string | null;
  certification_expires_at: string | null;
  certification_notes: string | null;
}

export interface PublicationInfo {
  publication_scope: PublicationScope;
  published_at: string | null;
  published_by: string | null;
}

export interface CertificationLevel {
  id: string;
  level_order: number;
  name: string;
  description: string | null;
  icon: string | null;
  color: string | null;
}

export const PUBLICATION_SCOPE_LABELS: Record<PublicationScope, string> = {
  none: 'Not Published',
  domain: 'Domain',
  organization: 'Organization',
  external: 'External',
};
