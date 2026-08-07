import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (typeof options === 'string') return options;
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return (options.defaultValue as string)
          .replace('{{count}}', String(options.count ?? ''))
          .replace('{{files}}', String(options.files ?? ''));
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

import { ImportConceptsDialog } from './import-concepts-dialog';

const COLLECTIONS: KnowledgeCollection[] = [
  { iri: 'urn:coll:a', label: 'Finance', is_editable: true } as unknown as KnowledgeCollection,
  { iri: 'urn:coll:b', label: 'Locked', is_editable: false } as unknown as KnowledgeCollection,
];

beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ success: true, triples_imported: 42 }),
  })) as unknown as typeof fetch;
});

function renderDialog(props: Partial<React.ComponentProps<typeof ImportConceptsDialog>> = {}) {
  return render(
    <ImportConceptsDialog
      open
      onOpenChange={vi.fn()}
      collections={COLLECTIONS}
      onImported={vi.fn()}
      {...props}
    />
  );
}

describe('ImportConceptsDialog (multi-file + scheme strategy)', () => {
  it('renders both scheme-strategy options and the reconcile note', () => {
    renderDialog();
    expect(screen.getByText('One scheme')).toBeInTheDocument();
    expect(screen.getByText('One scheme per file')).toBeInTheDocument();
    // conflicts reconciled later, NOT here
    expect(screen.getByText(/reconciled later in the Review Board/i)).toBeInTheDocument();
  });

  it('accepts multiple files and lists them', () => {
    renderDialog();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const f1 = new File(['@prefix : <urn:x#> .'], 'a.ttl', { type: 'text/turtle' });
    const f2 = new File(['@prefix : <urn:y#> .'], 'b.ttl', { type: 'text/turtle' });
    fireEvent.change(input, { target: { files: [f1, f2] } });
    expect(screen.getByText('a.ttl')).toBeInTheDocument();
    expect(screen.getByText('b.ttl')).toBeInTheDocument();
  });

  it('surfaces a per-file TODO note when one-scheme-per-file is chosen', () => {
    renderDialog();
    fireEvent.click(screen.getByText('One scheme per file'));
    expect(
      screen.getByText(/needs a backend that creates a scheme per file/i)
    ).toBeInTheDocument();
  });
});
