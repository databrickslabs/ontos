export type EntityKind = 'data_domain' | 'data_product' | 'data_contract';

export type CostCenter = 'INFRASTRUCTURE' | 'HR' | 'STORAGE' | 'MAINTENANCE' | 'OTHER';

export interface CostItem {
  id: string;
  entity_id: string;
  entity_type: EntityKind;
  title?: string | null;
  description?: string | null;
  cost_center: CostCenter;
  custom_center_name?: string | null;
  amount_cents: number;
  currency: string; // ISO 4217
  start_month: string; // YYYY-MM-DD
  end_month?: string | null; // YYYY-MM-DD
  created_at: string;
  updated_at: string;
}

export interface CostItemCreate {
  entity_id: string;
  entity_type: EntityKind;
  title?: string | null;
  description?: string | null;
  cost_center: CostCenter;
  custom_center_name?: string | null;
  amount_cents: number;
  currency: string;
  start_month: string; // YYYY-MM-DD
  end_month?: string | null; // YYYY-MM-DD
}

export interface CostItemUpdate extends Partial<Omit<CostItemCreate, 'entity_id' | 'entity_type'>> {}

export interface CostSummary {
  month: string; // YYYY-MM
  currency: string;
  total_cents: number;
  items_count: number;
  by_center: Record<CostCenter | string, number>;
}

export const formatCents = (amountCents: number, currency: string) => {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
      (amountCents || 0) / 100
    );
  } catch {
    return `$${((amountCents || 0) / 100).toFixed(2)}`;
  }
};


