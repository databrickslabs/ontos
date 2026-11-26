import { describe, it, expect } from 'vitest';
import type { OntologyConcept } from '@/types/ontology';
import {
  resolveLabel,
  resolveLabelFromMap,
  resolveLabelFromMaps,
  iriLocalName,
  resolveComment,
  getAvailableLanguages,
  getLanguageDisplayName,
  LANGUAGE_NAMES,
} from './ontology-utils';

function concept(partial: Partial<OntologyConcept>): OntologyConcept {
  return {
    iri: 'http://example.org/onto#Thing',
    concept_type: 'class',
    parent_concepts: [],
    child_concepts: [],
    properties: [],
    tagged_assets: [],
    synonyms: [],
    examples: [],
    ...partial,
  } as OntologyConcept;
}

describe('ontology-utils', () => {
  describe('resolveLabel', () => {
    it('prefers the requested language', () => {
      const c = concept({ labels: { en: 'Dataset', ja: 'データセット' } });
      expect(resolveLabel(c, 'ja')).toBe('データセット');
    });

    it('matches regional variants of the preferred language', () => {
      const c = concept({ labels: { 'en-US': 'Color' } });
      expect(resolveLabel(c, 'en')).toBe('Color');
    });

    it('falls back to English when preferred is missing', () => {
      const c = concept({ labels: { en: 'Dataset', de: 'Datensatz' } });
      expect(resolveLabel(c, 'fr')).toBe('Dataset');
    });

    it('falls back to the no-language-tag label', () => {
      const c = concept({ labels: { '': 'Untagged' } });
      expect(resolveLabel(c, 'fr')).toBe('Untagged');
    });

    it('falls back to the IRI local name when no usable label exists', () => {
      const c = concept({ iri: 'http://example.org/onto#Widget', labels: {} });
      expect(resolveLabel(c, 'fr')).toBe('Widget');
    });

    it('uses the legacy label field when present', () => {
      const c = concept({ iri: 'urn:noslash', labels: {}, label: 'Legacy' });
      expect(resolveLabel(c, 'fr')).toBe('Legacy');
    });

    it('returns any available label as a last resort', () => {
      const c = concept({ iri: 'urn:noslash', labels: { zz: 'Only' } });
      expect(resolveLabel(c, 'fr')).toBe('Only');
    });

    it('returns the IRI itself when nothing else is available', () => {
      const c = concept({ iri: 'urn:noslash', labels: {} });
      expect(resolveLabel(c, 'fr')).toBe('urn:noslash');
    });

    it('handles a concept with no labels field at all (labels || {} branch)', () => {
      // labels is undefined (not just empty), exercising the `labels || {}`
      // guard; falls through to the IRI local name.
      const c = concept({ iri: 'http://example.org/onto#Widget' });
      expect(resolveLabel(c, 'fr')).toBe('Widget');
    });
  });

  describe('label precedence (issue #1616)', () => {
    const iri = 'http://example.org/onto#BiogenicCarbon';

    it('prefers a label in any other language over the IRI local name', () => {
      const c = concept({ iri, label: 'BiogenicCarbon', labels: { pt: 'Carbono biogenico' } });
      expect(resolveLabel(c, 'en')).toBe('Carbono biogenico');
    });

    it('prefers the UI language label over other languages', () => {
      const labels = { en: 'Biogenic carbon', pt: 'Carbono biogenico' };
      expect(resolveLabelFromMap(labels, iri, 'pt')).toBe('Carbono biogenico');
      expect(resolveLabelFromMap(labels, iri, 'en')).toBe('Biogenic carbon');
    });

    it('falls to the local name only when there is no label at all', () => {
      expect(resolveLabelFromMap({}, iri, 'pt')).toBe('BiogenicCarbon');
      expect(resolveLabelFromMap(undefined, iri, 'pt')).toBe('BiogenicCarbon');
    });

    it('prefLabel in any language beats rdfs:label in the UI language', () => {
      const maps = { prefLabel: { en: 'Pref en' }, rdfsLabel: { pt: 'Rdfs pt' } };
      expect(resolveLabelFromMaps(maps, iri, 'pt')).toBe('Pref en');
    });

    it('prefLabel: UI language, then en, then untagged, then any', () => {
      expect(resolveLabelFromMaps({ prefLabel: { en: 'E', pt: 'P' } }, iri, 'pt')).toBe('P');
      expect(resolveLabelFromMaps({ prefLabel: { en: 'E', de: 'D' } }, iri, 'pt')).toBe('E');
      expect(resolveLabelFromMaps({ prefLabel: { '': 'U', de: 'D' } }, iri, 'pt')).toBe('U');
      expect(resolveLabelFromMaps({ prefLabel: { de: 'D' } }, iri, 'pt')).toBe('D');
    });

    it('uses rdfs:label only when there is no prefLabel, then legacy, then local name', () => {
      expect(resolveLabelFromMaps({ rdfsLabel: { de: 'R' } }, iri, 'pt')).toBe('R');
      expect(resolveLabelFromMaps({}, iri, 'pt', 'Legacy')).toBe('Legacy');
      expect(resolveLabelFromMaps(null, iri, 'pt')).toBe('BiogenicCarbon');
    });

    it('title: prefLabel@en beats rdfs:label@pt for a pt UI (label_maps)', () => {
      const c = concept({
        iri,
        label: 'RdfsPT',
        labels: { en: 'PrefEN', pt: 'RdfsPT' },
        label_maps: { prefLabel: { en: 'PrefEN' }, rdfsLabel: { pt: 'RdfsPT' } },
      });
      expect(resolveLabel(c, 'pt')).toBe('PrefEN');
    });

    it('old payloads without label_maps still use the merged labels', () => {
      const c = concept({ iri, labels: { pt: 'Merged' } });
      expect(resolveLabel(c, 'pt')).toBe('Merged');
    });

    it('skips whitespace-only labels', () => {
      expect(resolveLabelFromMaps({ prefLabel: { pt: '   ', en: 'E' } }, iri, 'pt')).toBe('E');
      expect(resolveLabelFromMaps({ prefLabel: { pt: ' ' } }, iri, 'pt')).toBe('BiogenicCarbon');
    });

    it('compares language tags case-insensitively', () => {
      const maps = { prefLabel: { de: 'D', PT: 'Upper' } };
      expect(resolveLabelFromMaps(maps, iri, 'pt')).toBe('Upper');
      expect(resolveLabelFromMaps({ prefLabel: { 'pt-BR': 'BR', en: 'E' } }, iri, 'pt')).toBe('BR');
      expect(resolveLabelFromMaps({ prefLabel: { EN: 'E', de: 'D' } }, iri, 'pt')).toBe('E');
    });

    it('is stable regardless of key order for ties', () => {
      const a = resolveLabelFromMaps({ prefLabel: { de: 'D', fr: 'F' } }, iri, 'pt');
      const b = resolveLabelFromMaps({ prefLabel: { fr: 'F', de: 'D' } }, iri, 'pt');
      expect(a).toBe(b);
    });

    it('iriLocalName ignores a trailing / or #', () => {
      expect(iriLocalName('http://x/o#')).toBe('o');
      expect(iriLocalName('http://x/a/')).toBe('a');
    });

    it('iriLocalName handles fragment, path and empty IRIs', () => {
      expect(iriLocalName('http://a/b#c')).toBe('c');
      expect(iriLocalName('http://a/b/c')).toBe('c');
      expect(iriLocalName('')).toBe('');
    });
  });

  describe('resolveComment', () => {
    it('prefers the requested language and its regional variants', () => {
      expect(resolveComment(concept({ comments: { de: 'Hallo' } }), 'de')).toBe('Hallo');
      expect(resolveComment(concept({ comments: { 'de-AT': 'Servus' } }), 'de')).toBe('Servus');
    });

    it('falls back through English, untagged, then any', () => {
      expect(resolveComment(concept({ comments: { en: 'Hi' } }), 'fr')).toBe('Hi');
      expect(resolveComment(concept({ comments: { '': 'Untagged' } }), 'fr')).toBe('Untagged');
      expect(resolveComment(concept({ comments: { zz: 'Other' } }), 'fr')).toBe('Other');
    });

    it('uses the legacy comment field, else undefined', () => {
      expect(resolveComment(concept({ comments: {}, comment: 'Legacy' }), 'fr')).toBe('Legacy');
      expect(resolveComment(concept({ comments: {} }), 'fr')).toBeUndefined();
    });

    it('handles a concept with no comments field at all (comments || {} branch)', () => {
      // comments is undefined, exercising the `comments || {}` guard; with a
      // legacy comment present it still resolves.
      expect(resolveComment(concept({ comment: 'Legacy only' }), 'fr')).toBe('Legacy only');
    });
  });

  describe('getAvailableLanguages', () => {
    it('collects and normalizes language codes with English first', () => {
      const concepts = [
        concept({ labels: { 'en-US': 'A', de: 'B' } }),
        concept({ labels: { ja: 'C', '': 'no-tag' } }),
      ];
      expect(getAvailableLanguages(concepts)).toEqual(['en', 'de', 'ja']);
    });

    it('returns an empty array when there are no labels', () => {
      expect(getAvailableLanguages([concept({})])).toEqual([]);
    });

    it('sorts English first even when it is not encountered first (b === en branch)', () => {
      // 'de'/'aa' are collected before 'en' so the comparator must hit the
      // `b === "en"` arm (return 1) to push English to the front.
      const concepts = [
        concept({ labels: { de: 'B', aa: 'A' } }),
        concept({ labels: { en: 'C' } }),
      ];
      expect(getAvailableLanguages(concepts)).toEqual(['en', 'aa', 'de']);
    });
  });

  describe('getLanguageDisplayName', () => {
    it('returns the known display name', () => {
      expect(getLanguageDisplayName('en')).toBe(LANGUAGE_NAMES.en);
      expect(getLanguageDisplayName('ja')).toBe('日本語');
    });

    it('uppercases unknown codes', () => {
      expect(getLanguageDisplayName('xx')).toBe('XX');
    });
  });
});
