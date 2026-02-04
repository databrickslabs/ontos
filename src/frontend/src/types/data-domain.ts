import { AssignedTag } from '@/components/ui/tag-chip';

export interface DataDomainBasicInfo {
  id: string;
  name: string;
}

export interface DataDomain {
  id: string;
  name: string;
  description?: string | null;
  // Optional: legacy owners list retained for backward compatibility in UI
  owner?: string[] | null;
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
  owner?: string[] | null; // Legacy owners list
  owner_team_id?: string | null; // UUID of the owning team
  tags?: (string | AssignedTag)[] | null;
  parent_id?: string | null;
}

export type DataDomainUpdate = Partial<DataDomainCreate>; 