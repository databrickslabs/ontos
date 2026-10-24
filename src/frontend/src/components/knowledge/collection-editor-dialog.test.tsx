import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';
import { CollectionEditorDialog, isNestableParent } from './collection-editor-dialog';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (typeof options === 'string') return options;
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

const makeCollection = (overrides: Partial<KnowledgeCollection>): KnowledgeCollection => ({
  iri: 'urn:glossary:x',
  label: 'X',
  collection_type: 'glossary',
  scope_level: 'enterprise',
  source_type: 'custom',
  is_editable: true,
  status: 'active',
  concept_count: 0,
  child_collections: [],
  ...overrides,
});

describe('isNestableParent', () => {
  it('accepts an editable user scheme', () => {
    expect(isNestableParent(makeCollection({ created_by: 'urn:user:alice@example.com' }))).toBe(true);
  });

  it('rejects read-only schemes', () => {
    expect(isNestableParent(makeCollection({ is_editable: false }))).toBe(false);
  });

  it('rejects system (auto-registered) sources even if flagged editable', () => {
    expect(isNestableParent(makeCollection({ created_by: 'urn:user:system' }))).toBe(false);
  });
});

describe('CollectionEditorDialog', () => {
  it('uses Title Case for the create title', () => {
    render(
      <CollectionEditorDialog open onOpenChange={() => {}} collection={null} collections={[]} onSave={async () => {}} />,
    );
    expect(screen.getByText('Create Scheme')).toBeTruthy();
  });

  it('uses Title Case for the edit title', () => {
    render(
      <CollectionEditorDialog
        open
        onOpenChange={() => {}}
        collection={makeCollection({})}
        collections={[]}
        onSave={async () => {}}
      />,
    );
    expect(screen.getByText('Edit Scheme')).toBeTruthy();
  });
});
