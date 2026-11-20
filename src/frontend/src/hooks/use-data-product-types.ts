import { useEffect, useState } from 'react';
import { useApi } from '@/hooks/use-api';
import type { DataProductType } from '@/types/data-product-type';

interface DataProductTypesState {
  /** All types, ordered by `sort_order` (inactive ones included). */
  types: DataProductType[];
  /** True until the first load has finished. */
  loading: boolean;
  error: string | null;
}

/**
 * Loads the data product types when `enabled` (e.g. while a dialog is open),
 * and again each time it becomes enabled. All types are returned so a picker
 * can keep a product's inactive type; see `pickableDataProductTypes`.
 */
export function useDataProductTypes(enabled = true): DataProductTypesState {
  const { get } = useApi();
  const [result, setResult] = useState<{
    types: DataProductType[];
    error: string | null;
    loaded: boolean;
  }>({ types: [], error: null, loaded: false });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    get<DataProductType[]>('/api/data-product-types').then(({ data, error }) => {
      if (cancelled) return;
      setResult({ types: Array.isArray(data) ? data : [], error: error ?? null, loaded: true });
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, get]);

  return { types: result.types, error: result.error, loading: enabled && !result.loaded };
}
