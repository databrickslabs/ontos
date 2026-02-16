import { create } from 'zustand';
import { setI18nBrand } from '@/i18n/config';
import { getStoredBrandName, normalizeBrandName, setStoredBrandName } from '@/utils/brand';

export interface UICustomizationSettings {
  i18nEnabled: boolean;
  brandName: string;
  customLogoUrl: string | null;
  aboutContent: string | null;
  customCss: string | null;
  isLoaded: boolean;
}

interface UICustomizationStore extends UICustomizationSettings {
  setSettings: (settings: Partial<UICustomizationSettings>) => void;
  fetchSettings: () => Promise<void>;
}

export const useUICustomizationStore = create<UICustomizationStore>((set) => ({
  i18nEnabled: true,
  brandName: getStoredBrandName(),
  customLogoUrl: null,
  aboutContent: null,
  customCss: null,
  isLoaded: false,

  setSettings: (settings) => set((state) => ({ ...state, ...settings })),

  fetchSettings: async () => {
    try {
      const response = await fetch('/api/settings/ui-customization');
      if (response.ok) {
        const data = await response.json();
        const brandName = normalizeBrandName(data.brand_name);

        set({
          i18nEnabled: data.i18n_enabled ?? true,
          brandName,
          customLogoUrl: data.custom_logo_url || null,
          aboutContent: data.about_content || null,
          customCss: data.custom_css || null,
          isLoaded: true,
        });

        // Inject custom CSS if present
        injectCustomCss(data.custom_css);

        // Update localStorage for i18n
        if (data.i18n_enabled === false) {
          localStorage.setItem('i18n-disabled', 'true');
        } else {
          localStorage.removeItem('i18n-disabled');
        }

        setStoredBrandName(brandName);
        setI18nBrand(brandName);
      }
    } catch (error) {
      console.error('Failed to fetch UI customization settings:', error);
      set({ isLoaded: true });
    }
  },
}));

/**
 * Inject custom CSS into the document head.
 * Creates or updates a <style> element with id="custom-user-css".
 */
function injectCustomCss(css: string | null): void {
  const styleId = 'custom-user-css';
  let styleElement = document.getElementById(styleId) as HTMLStyleElement | null;

  if (!css) {
    // Remove existing custom CSS if cleared
    if (styleElement) {
      styleElement.remove();
    }
    return;
  }

  if (!styleElement) {
    styleElement = document.createElement('style');
    styleElement.id = styleId;
    document.head.appendChild(styleElement);
  }

  styleElement.textContent = css;
}

// Initialize on module load for early CSS injection
if (typeof window !== 'undefined') {
  useUICustomizationStore.getState().fetchSettings();
}
