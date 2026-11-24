import type { OntologyConcept } from '@/types/ontology';

/** IRI local name (after the last # or /); the IRI itself when there is none. */
export function iriLocalName(iri: string): string {
  if (!iri) return '';
  const fragment = iri.split('#').pop();
  if (fragment && fragment !== iri) return fragment;
  const path = iri.split('/').pop();
  return path || iri;
}

/**
 * Resolve the display label for a resource from its language-keyed labels.
 *
 * The map is built by the backend with skos:prefLabel taking precedence over
 * rdfs:label for the same language, so the precedence applied here is:
 * 1. Preferred language (UI language, regional variants included)
 * 2. English ('en')
 * 3. No language tag ('')
 * 4. Any other language
 * 5. Legacy single `label` (when it is not just the IRI)
 * 6. IRI local name (after last # or /)
 * 7. The IRI itself
 *
 * @param labels Language-keyed labels ({"en": "Dataset", "pt": "Conjunto"}), may be empty
 * @param iri The resource IRI
 * @param preferredLang The preferred language code (e.g., 'en', 'pt')
 * @param legacyLabel Optional single-valued label
 */
export function resolveLabelFromMap(
  labels: Record<string, string> | null | undefined,
  iri: string,
  preferredLang: string = 'en',
  legacyLabel?: string
): string {
  const map = labels || {};

  // Helper to find label by language, including regional variants (en-US, en-GB, etc.)
  const findByLang = (lang: string): string | undefined => {
    if (map[lang]) return map[lang];
    const prefix = lang + '-';
    for (const [key, value] of Object.entries(map)) {
      if (value && key.startsWith(prefix)) return value;
    }
    return undefined;
  };

  const preferred = findByLang(preferredLang);
  if (preferred) return preferred;

  const english = findByLang('en');
  if (english) return english;

  if (map['']) return map[''];

  const anyLabel = Object.values(map).find(Boolean);
  if (anyLabel) return anyLabel;

  if (legacyLabel && legacyLabel !== iri) return legacyLabel;

  return iriLocalName(iri) || iri;
}

/**
 * Resolve the best label for a concept based on language preference.
 * See {@link resolveLabelFromMap} for the precedence.
 *
 * @param concept The ontology concept
 * @param preferredLang The preferred language code (e.g., 'en', 'ja', 'de')
 * @returns The best available label for display
 */
export function resolveLabel(
  concept: OntologyConcept,
  preferredLang: string = 'en'
): string {
  return resolveLabelFromMap(concept.labels, concept.iri, preferredLang, concept.label);
}

/**
 * Resolve the best comment/definition for a concept based on language preference.
 * 
 * Priority chain:
 * 1. Preferred language (e.g., user's selected language)
 * 2. English ('en')
 * 3. No language tag ('')
 * 4. Any available comment
 * 5. Fallback to legacy comment field
 * 
 * @param concept The ontology concept
 * @param preferredLang The preferred language code (e.g., 'en', 'ja', 'de')
 * @returns The best available comment for display, or undefined if none
 */
export function resolveComment(
  concept: OntologyConcept,
  preferredLang: string = 'en'
): string | undefined {
  const comments = concept.comments || {};
  
  // Helper to find comment by language, including regional variants (en-US, en-GB, etc.)
  const findByLang = (lang: string): string | undefined => {
    // Exact match first
    if (comments[lang]) return comments[lang];
    // Try regional variants (e.g., 'en' matches 'en-US', 'en-GB')
    const prefix = lang + '-';
    for (const [key, value] of Object.entries(comments)) {
      if (key.startsWith(prefix)) return value;
    }
    return undefined;
  };
  
  // Priority: preferred lang > English > no lang tag > any available > legacy comment
  const preferred = findByLang(preferredLang);
  if (preferred) return preferred;
  
  const english = findByLang('en');
  if (english) return english;
  
  if (comments['']) return comments[''];  // No language tag
  
  const anyComment = Object.values(comments)[0];
  if (anyComment) return anyComment;
  
  // Legacy fallback: use the comment field if available
  return concept.comment || undefined;
}

/**
 * Get all available language codes from a set of concepts.
 * Normalizes regional variants (en-US, en-GB) to base language codes (en).
 * 
 * @param concepts Array of ontology concepts
 * @returns Sorted array of unique base language codes (e.g., ['en', 'de', 'ja'])
 */
export function getAvailableLanguages(concepts: OntologyConcept[]): string[] {
  const languages = new Set<string>();
  
  for (const concept of concepts) {
    if (concept.labels) {
      for (const lang of Object.keys(concept.labels)) {
        if (lang) {  // Skip empty string (no language tag)
          // Normalize regional variants to base language (en-US -> en)
          const baseLang = lang.split('-')[0];
          languages.add(baseLang);
        }
      }
    }
  }
  
  // Sort with English first, then alphabetically
  return Array.from(languages).sort((a, b) => {
    if (a === 'en') return -1;
    if (b === 'en') return 1;
    return a.localeCompare(b);
  });
}

/**
 * Language display names for common language codes.
 */
export const LANGUAGE_NAMES: Record<string, string> = {
  'en': 'English',
  'de': 'Deutsch',
  'ja': '日本語',
  'fr': 'Français',
  'it': 'Italiano',
  'es': 'Español',
  'nl': 'Nederlands',
  'pt': 'Português',
  'zh': '中文',
  'ko': '한국어',
  'ru': 'Русский',
  'ar': 'العربية',
  'cs': 'Čeština',
  'da': 'Dansk',
  'el': 'Ελληνικά',
  'fi': 'Suomi',
  'hu': 'Magyar',
  'no': 'Norsk',
  'pl': 'Polski',
  'sv': 'Svenska',
  'tr': 'Türkçe',
  'uk': 'Українська',
};

/**
 * Get the display name for a language code.
 * 
 * @param langCode The ISO 639-1 language code
 * @returns The display name or the code itself if unknown
 */
export function getLanguageDisplayName(langCode: string): string {
  return LANGUAGE_NAMES[langCode] || langCode.toUpperCase();
}
