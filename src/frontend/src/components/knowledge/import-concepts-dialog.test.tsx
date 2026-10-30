import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';

// Native <select> stand-in for Radix Select (driving Radix in jsdom hung CI).
// Groups become <optgroup>s; headings and separators become disabled options.
vi.mock('@/components/ui/select', async () => {
  const React = await import('react');
  const SelectTrigger = (_: { children?: React.ReactNode }) => null;
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
  const SelectGroup = ({ children }: { children?: React.ReactNode }) => (
    <optgroup data-testid="scheme-group">{children}</optgroup>
  );
  const SelectLabel = ({ children }: { children?: React.ReactNode }) => (
    <option disabled data-testid="scheme-group-label">{children}</option>
  );
  const SelectSeparator = () => <option disabled value="" data-testid="separator" />;
  const SelectItem = ({ value, children }: { value: string; children?: React.ReactNode }) => (
    <option value={value}>{children}</option>
  );
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange?: (v: string) => void;
    children?: React.ReactNode;
  }) => {
    const options: React.ReactNode[] = [];
    React.Children.forEach(children, (child) => {
      if (!React.isValidElement(child)) return;
      if ((child as React.ReactElement).type !== SelectTrigger) options.push(child);
    });
    return (
      <select value={value} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    );
  };
  return {
    Select,
    SelectTrigger,
    SelectValue,
    SelectContent,
    SelectGroup,
    SelectLabel,
    SelectSeparator,
    SelectItem,
  };
});

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

const make = (overrides: Partial<KnowledgeCollection>): KnowledgeCollection => ({
  iri: 'urn:coll:x',
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

const COLLECTIONS: KnowledgeCollection[] = [
  make({ iri: 'urn:coll:a', label: 'Finance' }),
  make({ iri: 'urn:coll:b', label: 'Locked', is_editable: false }),
];

const NO_EDITABLE_MSG = 'No editable schemes available. Create one first.';
const READ_ONLY_HINT = /Only editable schemes can receive imports/;

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

  it('explains one-scheme-per-file and drops the target selector when chosen', () => {
    renderDialog();
    // Target selector is visible for the default (merge) strategy.
    expect(screen.getByText('Target concept scheme')).toBeInTheDocument();
    fireEvent.click(screen.getByText('One scheme per file'));
    // Now shows the per-file note and hides the target selector (each file
    // creates its own scheme, so no target selection is needed).
    expect(
      screen.getByText(/each file creates a new scheme named after the file/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('Target concept scheme')).not.toBeInTheDocument();
  });
});

describe('ImportConceptsDialog (target scheme select)', () => {
  const targetSelect = () => screen.getAllByRole('combobox')[0] as HTMLSelectElement;

  it('pads the scroll container on both sides so focus rings are not clipped', () => {
    renderDialog();
    const scroller = document.querySelector('form .overflow-y-auto')!;
    expect(scroller).toHaveClass('px-1', '-mx-1');
    expect(scroller).not.toHaveClass('pr-1');
  });

  it('groups editable schemes by type, alphabetically, with no dash prefixes', () => {
    renderDialog({
      collections: [
        make({ iri: 'urn:o', label: 'Ontology B', collection_type: 'ontology' }),
        make({
          iri: 'urn:g',
          label: 'zeta glossary',
          child_collections: [
            make({ iri: 'urn:g:child', label: 'Alpha child', parent_collection_iri: 'urn:g' }),
          ],
        }),
        make({ iri: 'urn:t', label: 'Tax', collection_type: 'taxonomy' }),
      ],
    });
    const labels = screen.getAllByTestId('scheme-group-label').map((el) => el.textContent);
    expect(labels).toEqual(['Glossaries', 'Taxonomies', 'Ontologies']);
    const [glossaries] = screen.getAllByTestId('scheme-group');
    expect(within(glossaries).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Glossaries',
      'Alpha child',
      'zeta glossary',
    ]);
    // Create-new stays first.
    expect(targetSelect().options[0].value).toBe('__create_new_scheme__');
    expect(targetSelect().textContent).not.toMatch(/[\u2014\u2013]/);
  });

  it('selecting a scheme sets its iri', () => {
    renderDialog();
    fireEvent.change(targetSelect(), { target: { value: 'urn:coll:a' } });
    expect(targetSelect().value).toBe('urn:coll:a');
  });

  it('shows the read-only hint only when a read-only scheme exists', () => {
    const { unmount } = renderDialog();
    expect(screen.getByText(READ_ONLY_HINT)).toBeInTheDocument();
    unmount();
    renderDialog({ collections: [make({ iri: 'urn:coll:a', label: 'Finance' })] });
    expect(screen.queryByText(READ_ONLY_HINT)).not.toBeInTheDocument();
  });

  it('detects a read-only scheme nested in the tree', () => {
    renderDialog({
      collections: [
        make({
          iri: 'urn:p',
          label: 'Parent',
          child_collections: [make({ iri: 'urn:c', label: 'Bundled', is_editable: false })],
        }),
      ],
    });
    expect(screen.getByText(READ_ONLY_HINT)).toBeInTheDocument();
  });

  it('hides the hint for the per-file strategy', () => {
    renderDialog();
    fireEvent.click(screen.getByText('One scheme per file'));
    expect(screen.queryByText(READ_ONLY_HINT)).not.toBeInTheDocument();
  });

  it('does not show the empty message when only a child scheme is editable', () => {
    renderDialog({
      collections: [
        make({
          iri: 'urn:p',
          label: 'Read-only parent',
          is_editable: false,
          child_collections: [
            make({ iri: 'urn:c', label: 'Editable child', parent_collection_iri: 'urn:p' }),
          ],
        }),
      ],
    });
    expect(screen.queryByText(NO_EDITABLE_MSG)).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Editable child' })).toBeInTheDocument();
  });

  it('shows the empty message when no scheme is editable', () => {
    renderDialog({ collections: [make({ iri: 'urn:b', label: 'Locked', is_editable: false })] });
    expect(screen.getByText(NO_EDITABLE_MSG)).toBeInTheDocument();
  });
});
