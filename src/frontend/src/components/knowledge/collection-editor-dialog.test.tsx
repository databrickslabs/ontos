import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';
import { CollectionEditorDialog, isNestableParent } from './collection-editor-dialog';

// Native <select> stand-in for Radix Select (driving Radix in jsdom hung CI).
vi.mock('@/components/ui/select', async () => {
  const React = await import('react');
  const SelectTrigger = (_: { children?: React.ReactNode }) => null;
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
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
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
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

  it('uses Scheme wording for the parent field and its root option', () => {
    render(
      <CollectionEditorDialog open onOpenChange={() => {}} collection={null} collections={[]} onSave={async () => {}} />,
    );
    expect(screen.getByText('Parent Scheme')).toBeTruthy();
    expect(screen.getByRole('option', { name: 'None (root scheme)' })).toBeTruthy();
  });

  it('defaults the Type of a new scheme to glossary', () => {
    render(
      <CollectionEditorDialog open onOpenChange={() => {}} collection={null} collections={[]} onSave={async () => {}} />,
    );
    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('glossary');
  });

  it('preselects initialCollectionType when creating and saves it', async () => {
    const onSave = vi.fn(async () => {});
    render(
      <CollectionEditorDialog
        open
        onOpenChange={() => {}}
        collection={null}
        collections={[]}
        onSave={onSave}
        initialCollectionType="ontology"
      />,
    );
    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('ontology');
    fireEvent.change(document.getElementById('label')!, { target: { value: 'Core' } });
    fireEvent.click(screen.getByRole('button', { name: 'common:actions.create' }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect((onSave.mock.calls[0] as any[])[0].collection_type).toBe('ontology');
  });

  it('ignores initialCollectionType when editing', () => {
    render(
      <CollectionEditorDialog
        open
        onOpenChange={() => {}}
        collection={makeCollection({ collection_type: 'taxonomy' })}
        collections={[]}
        onSave={async () => {}}
        initialCollectionType="ontology"
      />,
    );
    // The Type select is create-only; the remaining selects are scope and parent.
    expect(screen.queryByRole('option', { name: 'semantic-models:collections.ontology' })).toBeNull();
  });
});
