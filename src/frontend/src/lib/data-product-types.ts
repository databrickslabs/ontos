import type { TFunction } from 'i18next';
import type { DataProductType } from '@/types/data-product-type';

/**
 * The label to show for a data product type. Labels are user data and aren't
 * translated, except a built-in type's label while an admin hasn't changed it:
 * that one renders through `data-products:dataProductType.<key>`.
 */
export const dataProductTypeLabel = (
  type: Pick<DataProductType, 'key' | 'label' | 'has_seeded_label'>,
  t: TFunction,
): string =>
  type.has_seeded_label
    ? t(`data-products:dataProductType.${type.key}`, { defaultValue: type.label })
    : type.label;

/**
 * The types to offer in a picker: the active ones, plus `currentKey` when it's
 * inactive so editing a product doesn't drop its type.
 */
export const pickableDataProductTypes = (
  types: DataProductType[],
  currentKey?: string | null,
): DataProductType[] =>
  types.filter((type) => type.is_active || type.key === currentKey);

/** The key of the default type, if an active one is set. */
export const defaultDataProductTypeKey = (types: DataProductType[]): string | undefined =>
  types.find((type) => type.is_default && type.is_active)?.key;
