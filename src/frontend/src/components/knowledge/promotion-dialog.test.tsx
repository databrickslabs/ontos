import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import type { KnowledgeCollection, OntologyConcept } from '@/types/ontology';

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
  const SelectSeparator = () => <option disabled value="" />;
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
        return options.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

import { PromotionDialog } from './promotion-dialog';

const make = (overrides: Partial<KnowledgeCollection>): KnowledgeCollection => ({
  iri: 'urn:scheme:x',
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

const concept = {
  iri: 'urn:concept:1',
  label: 'Customer',
  concept_type: 'concept',
  source_context: 'urn:source',
  parent_concepts: [],
  child_concepts: [],
  properties: [],
  tagged_assets: [],
} as unknown as OntologyConcept;

const COLLECTIONS = [
  make({ iri: 'urn:source', label: 'Source scheme' }),
  make({
    iri: 'urn:ro',
    label: 'Read-only root',
    is_editable: false,
    child_collections: [make({ iri: 'urn:kid', label: 'Nested child', parent_collection_iri: 'urn:ro' })],
  }),
  make({ iri: 'urn:onto', label: 'Core ontology', collection_type: 'ontology', scope_level: 'domain' }),
];

function renderDialog() {
  const onPromote = vi.fn(async () => {});
  render(
    <PromotionDialog
      open
      onOpenChange={() => {}}
      concept={concept}
      collections={COLLECTIONS}
      onPromote={onPromote}
      onMigrate={vi.fn(async () => {})}
    />,
  );
  return { onPromote };
}

// The action select comes first; the target scheme select second.
const targetSelect = () => screen.getAllByRole('combobox')[1] as HTMLSelectElement;

describe('PromotionDialog target scheme select', () => {
  it('groups editable targets by type, excludes the source and read-only schemes, no dashes', () => {
    renderDialog();
    expect(screen.getAllByTestId('scheme-group-label').map((el) => el.textContent)).toEqual([
      'Glossaries',
      'Ontologies',
    ]);
    const [glossaries] = screen.getAllByTestId('scheme-group');
    expect(within(glossaries).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Glossaries',
      'Nested child',
    ]);
    expect(screen.queryByRole('option', { name: 'Source scheme' })).toBeNull();
    expect(screen.queryByRole('option', { name: 'Read-only root' })).toBeNull();
    expect(targetSelect().textContent).not.toMatch(/[\u2014\u2013]/);
  });

  it('submits the selected target iri', async () => {
    const { onPromote } = renderDialog();
    fireEvent.change(targetSelect(), { target: { value: 'urn:onto' } });
    expect(targetSelect().value).toBe('urn:onto');
    const submit = screen
      .getAllByRole('button')
      .find((b) => !b.hasAttribute('disabled') && /promot/i.test(b.textContent ?? ''));
    expect(submit).toBeTruthy();
    fireEvent.click(submit!);
    await vi.waitFor(() => expect(onPromote).toHaveBeenCalled());
    expect((onPromote.mock.calls[0] as unknown[])[1]).toBe('urn:onto');
  });
});
