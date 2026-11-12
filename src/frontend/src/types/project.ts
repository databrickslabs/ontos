import { TeamSummary } from './team';
import type { TagPayload } from '@/components/ui/tag-selector';
import { AssignedTag } from '@/components/ui/tag-chip';

export interface Project {
  id: string;
  name: string;
  title?: string | null;
  description?: string | null;
  tags?: AssignedTag[] | null;
  metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
  teams: TeamSummary[];
  project_type?: 'PERSONAL' | 'TEAM';
}

export interface ProjectCreate {
  name: string;
  title?: string | null;
  description?: string | null;
  tags?: (string | AssignedTag | TagPayload)[] | null;
  metadata?: Record<string, any> | null;
  team_ids?: string[] | null;
  project_type?: 'PERSONAL' | 'TEAM';
}

export interface ProjectUpdate {
  name?: string;
  title?: string | null;
  description?: string | null;
  tags?: (string | AssignedTag | TagPayload)[] | null;
  metadata?: Record<string, any> | null;
  project_type?: 'PERSONAL' | 'TEAM';
}

export interface ProjectSummary {
  id: string;
  name: string;
  title?: string | null;
  team_count: number;
}

export interface ProjectTeamAssignment {
  team_id: string;
}

export interface UserProjectAccess {
  projects: ProjectSummary[];
  current_project_id?: string | null;
}

export interface ProjectContext {
  project_id?: string | null;
}

export interface ProjectAccessRequest {
  project_id: string;
  message?: string | null;
}

export interface ProjectAccessRequestResponse {
  message: string;
  project_name: string;
}

// Convenience alias for API responses
export interface ProjectRead extends Project {}