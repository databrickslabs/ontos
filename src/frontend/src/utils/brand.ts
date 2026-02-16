export const DEFAULT_BRAND_NAME = 'Ontos';
const BRAND_STORAGE_KEY = 'ui-brand-name';

export function normalizeBrandName(brandName: string | null | undefined): string {
  const normalized = (brandName || '').trim();
  return normalized || DEFAULT_BRAND_NAME;
}

export function getStoredBrandName(): string {
  if (typeof window === 'undefined') {
    return DEFAULT_BRAND_NAME;
  }

  try {
    return normalizeBrandName(localStorage.getItem(BRAND_STORAGE_KEY));
  } catch {
    return DEFAULT_BRAND_NAME;
  }
}

export function setStoredBrandName(brandName: string): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.setItem(BRAND_STORAGE_KEY, normalizeBrandName(brandName));
  } catch {
    // Ignore storage write failures (e.g. privacy mode).
  }
}
