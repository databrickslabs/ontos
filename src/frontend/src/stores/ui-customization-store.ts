import { create } from 'zustand';
import {
  applyBranding,
  applyThemeColors,
  type BrandingTheme,
  DEFAULT_APP_NAME,
  resolveAppName,
  resolveShortName,
} from '@/lib/branding';

export interface UICustomizationSettings {
  i18nEnabled: boolean;
  customLogoUrl: string | null;
  aboutContent: string | null;
  customCss: string | null;
  // Branding (issue #240)
  appDisplayName: string | null;
  appShortName: string | null;
  faviconUrl: string | null;
  /** Optional subtitle shown next to the name (sidebar, home). */
  appTagline: string | null;
  /** Logo for dark mode; falls back to customLogoUrl. */
  customLogoDarkUrl: string | null;
  theme: BrandingTheme;
  /** Show "powered by Ontos" in the sidebar footer while a custom brand is set. */
  showPoweredBy: boolean;
  isLoaded: boolean;
}

interface UICustomizationStore extends UICustomizationSettings {
  setSettings: (settings: Partial<UICustomizationSettings>) => void;
  fetchSettings: () => Promise<void>;
  /** Resolved app name (display name or default). Safe to use in render. */
  getAppName: () => string;
  /** Resolved short name (short name -> display name -> default). */
  getShortName: () => string;
}

export const useUICustomizationStore = create<UICustomizationStore>((set, get) => ({
  i18nEnabled: true,
  customLogoUrl: null,
  aboutContent: null,
  customCss: null,
  appDisplayName: null,
  appShortName: null,
  faviconUrl: null,
  appTagline: null,
  customLogoDarkUrl: null,
  theme: {},
  showPoweredBy: true,
  isLoaded: false,

  setSettings: (settings) => set((state) => ({ ...state, ...settings })),

  fetchSettings: async () => {
    try {
      const response = await fetch('/api/settings/ui-customization');
      if (response.ok) {
        const data = await response.json();
        set({
          i18nEnabled: data.i18n_enabled ?? true,
          customLogoUrl: data.custom_logo_url || null,
          aboutContent: data.about_content || null,
          customCss: data.custom_css || null,
          appDisplayName: data.app_display_name || null,
          appShortName: data.app_short_name || null,
          faviconUrl: data.favicon_url || null,
          appTagline: data.app_tagline || null,
          customLogoDarkUrl: data.custom_logo_dark_url || null,
          theme: {
            primary: data.theme?.primary || null,
            primaryDark: data.theme?.primary_dark || null,
            accent: data.theme?.accent || null,
            accentDark: data.theme?.accent_dark || null,
          },
          showPoweredBy: data.show_powered_by ?? true,
          isLoaded: true,
        });

        injectCustomCss(data.custom_css);
        applyThemeColors(get().theme);

        // Apply branding side effects (title + favicon)
        applyBranding({
          displayName: data.app_display_name,
          faviconUrl: data.favicon_url,
        });

        if (data.i18n_enabled === false) {
          localStorage.setItem('i18n-disabled', 'true');
        } else {
          localStorage.removeItem('i18n-disabled');
        }
      }
    } catch (error) {
      console.error('Failed to fetch UI customization settings:', error);
      set({ isLoaded: true });
    }
  },

  getAppName: () => resolveAppName(get().appDisplayName),
  getShortName: () => resolveShortName(get().appShortName, get().appDisplayName),
}));

export { DEFAULT_APP_NAME };

/**
 * Inject custom CSS into the document head.
 * Creates or updates a <style> element with id="custom-user-css".
 */
function injectCustomCss(css: string | null): void {
  const styleId = 'custom-user-css';
  let styleElement = document.getElementById(styleId) as HTMLStyleElement | null;

  if (!css) {
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
