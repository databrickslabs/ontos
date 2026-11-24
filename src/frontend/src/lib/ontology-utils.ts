import type { OntologyConcept } from '@/types/ontology';

/** IRI local name (after the last # or /, ignoring a trailing one); the IRI itself when none. */
export function iriLocalName(iri: string): string {
  if (!iri) return '';
  const trimmed = iri.replace(/[/#]+$/, '');
  const fragment = trimmed.split('#').pop();
  if (fragment && fragment !== trimmed) return fragment;
  const path = trimmed.split('/').pop();
  return path || iri;
}

/** Language-keyed label maps of a resource, skos:prefLabel kept apart from rdfs:label. */
export interface LabelMaps {
  prefLabel?: Record<string, string> | null;
  rdfsLabel?: Record<string, string> | null;
}

// Pick a label by language (case-insensitive tags), including regional variants
// (en-US, pt-BR, ...). Blank values are ignored; ties resolve by sorted tag.
function pickByLang(map: Record<string, string>, lang: string): string | undefined {
  const want = lang.toLowerCase();
  const entries = Object.entries(map)
    .filter(([, v]) => typeof v === 'string' && v.trim() !== '')
    .map(([k, v]) => [k.toLowerCase(), v] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const exact = entries.find(([k]) => k === want);
  if (exact) return exact[1];
  const regional = entries.find(([k]) => k.startsWith(want + '-'));
  return regional?.[1];
}

// UI language, then English, then untagged, then any other language.
function pickLabel(map: Record<string, string>, preferredLang: string): string | undefined {
  const byLang = pickByLang(map, preferredLang) || pickByLang(map, 'en');
  if (byLang) return byLang;
  const rest = Object.entries(map)
    .filter(([, v]) => typeof v === 'string' && v.trim() !== '')
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return (rest.find(([k]) => k === '') || rest[0])?.[1];
}

/**
 * Resolve the display label for a resource.
 *
 * Precedence:
 * 1. skos:prefLabel: UI language, English, untagged, any other language
 * 2. rdfs:label: UI language, English, untagged, any other language
 * 3. Legacy single `label` (when it is not just the IRI)
 * 4. IRI local name (after last # or /)
 * 5. The IRI itself
 *
 * @param maps prefLabel / rdfsLabel language-keyed maps ({"en": "Dataset", "pt": "Conjunto"})
 * @param iri The resource IRI
 * @param preferredLang The preferred language code (e.g., 'en', 'pt')
 * @param legacyLabel Optional single-valued label
 */
export function resolveLabelFromMaps(
  maps: LabelMaps | null | undefined,
  iri: string,
  preferredLang: string = 'en',
  legacyLabel?: string
): string {
  const found =
    pickLabel(maps?.prefLabel || {}, preferredLang) ||
    pickLabel(maps?.rdfsLabel || {}, preferredLang);
  if (found) return found;
  if (legacyLabel && legacyLabel.trim() && legacyLabel !== iri) return legacyLabel;
  return iriLocalName(iri) || iri;
}

/**
 * Single-map variant for data that already merged both label kinds per language
 * (concept `labels`, prefLabel first). Same fallbacks as {@link resolveLabelFromMaps}.
 */
export function resolveLabelFromMap(
  labels: Record<string, string> | null | undefined,
  iri: string,
  preferredLang: string = 'en',
  legacyLabel?: string
): string {
  return resolveLabelFromMaps({ prefLabel: labels }, iri, preferredLang, legacyLabel);
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
  return resolveLabelFromMaps(
    concept.label_maps && (concept.label_maps.prefLabel || concept.label_maps.rdfsLabel)
      ? concept.label_maps
      : { prefLabel: concept.labels },
    concept.iri,
    preferredLang,
    concept.label
  );
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
