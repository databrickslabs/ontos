export type OwnerObjectType =
  | 'data_product'
  | 'data_contract'
  | 'data_domain'
  | 'business_term'
  | 'asset'
  | 'tag'
  | 'access_policy'
  | 'access_audience'
  | 'access_asset_collection';

export interface BusinessOwnerRead {
  id: string;
  object_type: OwnerObjectType;
  object_id: string;
  user_email: string;
  user_name?: string | null;
  role_id: string;
  role_name?: string | null;
  is_active: boolean;
  assigned_at: string;
  removed_at?: string | null;
  removal_reason?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessOwnerCreate {
  object_type: OwnerObjectType;
  object_id: string;
  user_email: string;
  user_name?: string | null;
  role_id: string;
}

export interface BusinessOwnerUpdate {
  user_email?: string | null;
  user_name?: string | null;
  role_id?: string | null;
  is_active?: boolean | null;
  removal_reason?: string | null;
}

export interface BusinessOwnerHistory {
  object_type: OwnerObjectType;
  object_id: string;
  current_owners: BusinessOwnerRead[];
  previous_owners: BusinessOwnerRead[];
}
