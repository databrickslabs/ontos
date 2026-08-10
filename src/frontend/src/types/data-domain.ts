import { AssignedTag } from '@/components/ui/tag-chip';

export interface DataDomainBasicInfo {
  id: string;
  name: string;
}

/**
 * Result of `GET /api/data-domains/{id}/deletion-impact` (#520). A domain that is the
 * primary domain for any entity (or a descendant that would cascade-delete with it)
 * cannot be deleted; `primary_assignments` lists what to reassign first.
 */
export interface DomainDeletionImpact {
  domain_id: string;
  domain_name: string;
  deletable: boolean;
  primary_assignments: { entity_type: string; entity_id: string }[];
  assignment_counts: Record<string, { primary: number; additional: number }>;
}

/**
 * A data domain assigned to an entity (team, data contract, data product, asset),
 * with the primary flag. Mirrors the backend `AssignedDomain` model (#520 multi-domain).
 */
export interface AssignedDomain {
  domain_id: string;
  domain_name?: string | null;
  is_primary: boolean;
  assigned_by?: string | null;
  assigned_at?: string | null;
}

export interface DataDomain {
  id: string;
  name: string;
  description?: string | null;
  owner_team_id?: string | null; // UUID of the owning team
  tags?: AssignedTag[] | null; // Rich tags with metadata
  parent_id?: string | null;
  parent_name?: string | null; // Kept for now, but parent_info should be primary
  children_count?: number;
  parent_info?: DataDomainBasicInfo | null;
  children_info?: DataDomainBasicInfo[];
  created_at?: string; // Assuming ISO string format from backend
  updated_at?: string; // Assuming ISO string format from backend
  created_by?: string; // Optional based on backend model
}

export interface DataDomainCreate {
  name: string;
  description?: string | null;
  owner_team_id?: string | null; // UUID of the owning team
  tags?: (string | AssignedTag)[] | null;
  parent_id?: string | null;
}

export type DataDomainUpdate = Partial<DataDomainCreate>; 