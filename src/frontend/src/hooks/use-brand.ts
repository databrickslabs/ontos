import { useMemo } from 'react';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { normalizeBrandName } from '@/utils/brand';

export function useBrand(): string {
  const brandName = useUICustomizationStore((state) => state.brandName);
  return useMemo(() => normalizeBrandName(brandName), [brandName]);
}
