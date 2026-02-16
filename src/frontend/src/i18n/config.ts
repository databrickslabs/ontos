import i18n from 'i18next';
import type { Resource } from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { getStoredBrandName, normalizeBrandName } from '@/utils/brand';

// Dynamically import all translation JSON files using Vite's import.meta.glob
// This makes path resolution resilient across environments (e.g., Databricks Apps)
const localeModules = import.meta.glob('./locales/*/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, any>;

// Fallback explicit imports to guarantee inclusion of critical namespaces
// If packaging ever misses a file, these ensure it's still bundled.
import settingsEN from './locales/en/settings.json';
import settingsDE from './locales/de/settings.json';
import settingsJA from './locales/ja/settings.json';
import settingsFR from './locales/fr/settings.json';
import settingsIT from './locales/it/settings.json';
import settingsES from './locales/es/settings.json';
import settingsNL from './locales/nl/settings.json';

const resources: Resource = {};

for (const [modulePath, moduleExports] of Object.entries(localeModules)) {
  const match = modulePath.match(/\.\/locales\/([^/]+)\/([^/]+)\.json$/);
  if (!match) continue;
  const [, languageCode, namespace] = match;
  if (!resources[languageCode]) resources[languageCode] = {};
  (resources[languageCode] ||= {} as any)[namespace] = moduleExports as any;
}

const namespaces = resources['en'] ? Object.keys(resources['en']) : ['common'];

// Diagnostics to verify loaded languages and namespaces at runtime
try {
  // eslint-disable-next-line no-console
  console.log('[i18n] Discovered locale modules:', Object.keys(localeModules));
  // eslint-disable-next-line no-console
  console.log('[i18n] Loaded languages:', Object.keys(resources));
  // eslint-disable-next-line no-console
  console.log('[i18n] Namespaces for en:', namespaces);
} catch {}

// Ensure 'settings' namespace exists by injecting explicit imports if missing
const fallbackSettingsByLang: Record<string, any> = {
  en: settingsEN,
  de: settingsDE,
  ja: settingsJA,
  fr: settingsFR,
  it: settingsIT,
  es: settingsES,
  nl: settingsNL,
};

for (const [lang, data] of Object.entries(fallbackSettingsByLang)) {
  if (!resources[lang]) resources[lang] = {};
  if (!(resources[lang] as any)['settings']) {
    (resources[lang] as any)['settings'] = data as any;
  }
}

// Check if i18n is disabled via settings (set in localStorage)
// When disabled, we force English regardless of browser settings
const isI18nDisabled =
  typeof window !== 'undefined' && localStorage.getItem('i18n-disabled') === 'true';
const initialBrandName = getStoredBrandName();

// Configure i18next
i18n
  .use(LanguageDetector) // Detect user language
  .use(initReactI18next) // Pass i18n instance to react-i18next
  .init({
    resources,
    fallbackLng: 'en', // Fallback language
    defaultNS: 'common', // Default namespace
    ns: namespaces, // Available namespaces discovered from files
    load: 'languageOnly', // Normalize languages like en-US -> en
    supportedLngs: Object.keys(resources),
    // Force English if i18n is disabled
    lng: isI18nDisabled ? 'en' : undefined,

    interpolation: {
      escapeValue: false, // React already escapes values
      defaultVariables: {
        brand: initialBrandName,
      },
    },

    detection: {
      // Order of language detection (skipped if lng is set explicitly)
      order: ['localStorage', 'navigator'],
      // Cache user language
      caches: ['localStorage'],
      lookupLocalStorage: 'i18nextLng',
    },

    react: {
      useSuspense: false, // Disable suspense for easier integration
    },
  });

// Log i18n status
if (isI18nDisabled) {
  console.log('[i18n] Internationalization disabled - using English');
}

export function setI18nBrand(brandName: string): void {
  const normalizedBrandName = normalizeBrandName(brandName);
  const interpolation = i18n.options.interpolation || {};

  i18n.options.interpolation = {
    ...interpolation,
    defaultVariables: {
      ...(interpolation.defaultVariables || {}),
      brand: normalizedBrandName,
    },
  };

  // Trigger rerender of translated content that depends on default interpolation variables.
  void i18n.changeLanguage(i18n.language || 'en');
}

export default i18n;
