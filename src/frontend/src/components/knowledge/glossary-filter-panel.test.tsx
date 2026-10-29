import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';

// A scheme whose concepts are grouped under a fixed name (urn:demo -> "Demo
// Data") must be matched to its collection through source_key, so its chip
// shows the scheme label (and its count) instead of the raw group name.

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: any) => (typeof fallback === 'string' ? fallback : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/lib/system-rdf-namespace-labels', () => ({
  systemRdfNamespaceDisplayLabel: (id: string) => id,
}));

vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: (selector: any) =>
    selector({ sourceSortMode: 'name', setSourceSortMode: vi.fn() }),
}));

import { GlossaryFilterPanel } from './glossary-filter-panel';

const demoScheme = {
  iri: 'urn:demo',
  label: 'Demo Scheme',
  collection_type: 'glossary',
  is_editable: true,
  source_type: 'custom',
  source_key: 'Demo Data',
  child_collections: [],
} as unknown as KnowledgeCollection;

const renderPanel = (collections: KnowledgeCollection[]) =>
  render(
    <GlossaryFilterPanel
      filteredConcepts={[]}
      sourceConceptCounts={{ 'Demo Data': 43 }}
      availableSources={['Demo Data']}
      hiddenSources={[]}
      onToggleSource={vi.fn()}
      onSelectAllSources={vi.fn()}
      onSelectNoneSources={vi.fn()}
      groupByDimension="none"
      onSetGroupByDimension={vi.fn()}
      showProperties={false}
      onSetShowProperties={vi.fn()}
      selectedLanguage="en"
      onSetSelectedLanguage={vi.fn()}
      isFilterExpanded
      onSetFilterExpanded={vi.fn()}
      collections={collections}
    />,
  );

describe('GlossaryFilterPanel source matching', () => {
  it('labels a source with the collection matched by source_key', () => {
    renderPanel([demoScheme]);
    const chip = screen.getByTitle('Demo Data');
    expect(chip.textContent).toBe('Demo Scheme');
    expect(chip.parentElement?.textContent).toContain('43');
  });

  it('shows the raw source name when no collection matches', () => {
    renderPanel([{ ...demoScheme, source_key: undefined } as KnowledgeCollection]);
    expect(screen.getByTitle('Demo Data').textContent).toBe('Demo Data');
  });
});
