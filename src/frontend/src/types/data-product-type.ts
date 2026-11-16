/** An admin-configurable Data Product Type (`GET /api/data-product-types`). */
export interface DataProductType {
  id: string;
  /** Immutable; the value products and ODPS files carry as `productType`. */
  key: string;
  label: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  sort_order: number;
  is_active: boolean;
  is_default: boolean;
  /** Created by an ODPS import or the upgrade from an unknown value. */
  is_imported: boolean;
  /** One of the built-in types; these can't be deleted. */
  is_seeded: boolean;
  /** A built-in type whose label hasn't been changed: show the translated label. */
  has_seeded_label: boolean;
  /** Number of data products using this type. */
  usage_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}
