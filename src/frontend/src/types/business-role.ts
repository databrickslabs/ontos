export type BusinessRoleStatus = 'active' | 'deprecated';
export type BusinessRoleCategory = 'governance' | 'technical' | 'business' | 'operational';

export interface BusinessRoleRead {
  id: string;
  name: string;
  description?: string | null;
  category?: BusinessRoleCategory | null;
  is_system: boolean;
  is_approver: boolean;
  status: BusinessRoleStatus;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessRoleCreate {
  name: string;
  description?: string | null;
  category?: BusinessRoleCategory | null;
  is_system?: boolean;
  is_approver?: boolean;
  status?: BusinessRoleStatus;
}

export interface BusinessRoleUpdate {
  name?: string | null;
  description?: string | null;
  category?: BusinessRoleCategory | null;
  is_system?: boolean | null;
  is_approver?: boolean | null;
  status?: BusinessRoleStatus | null;
}
