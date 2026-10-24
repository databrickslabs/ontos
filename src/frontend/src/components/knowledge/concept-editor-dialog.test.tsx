import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';

// ---------------------------------------------------------------------------
// ConceptEditorDialog: preset type from the Explore Create menu, allowed-type
// validation per scheme, and the Simple-mode Parent (broader) field.
// ---------------------------------------------------------------------------

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

let modeMock: 'simple' | 'advanced' = 'simple';
vi.mock('@/components/concepts/mode-switch', () => ({
  useConceptMode: () => [modeMock, vi.fn()],
  ConceptModeSwitch: () => null,
}));

// Stand-in for the concept picker: one button that picks a fixed IRI.
let pickerEntityType: string | undefined;
vi.mock('@/components/semantic/concept-select-dialog', () => ({
  default: ({ isOpen, onSelect, entityType }: { isOpen: boolean; onSelect: (iri: string) => void; entityType?: string }) => {
    pickerEntityType = entityType;
    return isOpen ? (
      <button type="button" data-testid="pick-parent" onClick={() => onSelect('https://example.org/onto#Party')}>
        pick
      </button>
    ) : null;
  },
}));

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
    disabled,
    children,
  }: {
    value?: string;
    onValueChange?: (v: string) => void;
    disabled?: boolean;
    children?: React.ReactNode;
  }) => {
    const options: React.ReactNode[] = [];
    React.Children.forEach(children, (child) => {
      if (!React.isValidElement(child)) return;
      if ((child as React.ReactElement).type !== SelectTrigger) options.push(child);
    });
    return (
      <select value={value} disabled={disabled} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    );
  };
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import { ConceptEditorDialog, parentFieldLabelKey } from './concept-editor-dialog';

const ONTOLOGY = { iri: 'urn:ontology:core', label: 'Core', collection_type: 'ontology', is_editable: true } as unknown as KnowledgeCollection;
const TAXONOMY = { iri: 'urn:taxonomy:regions', label: 'Regions', collection_type: 'taxonomy', is_editable: true } as unknown as KnowledgeCollection;
const GLOSSARY = { iri: 'urn:glossary:business', label: 'Business', collection_type: 'glossary', is_editable: true } as unknown as KnowledgeCollection;

function renderDialog(props: Partial<React.ComponentProps<typeof ConceptEditorDialog>> = {}) {
  const onSave = vi.fn(async () => {});
  render(
    <ConceptEditorDialog
      open
      onOpenChange={vi.fn()}
      concept={null}
      collection={ONTOLOGY}
      collections={[ONTOLOGY, TAXONOMY, GLOSSARY]}
      onSave={onSave}
      {...props}
    />,
  );
  return onSave;
}

async function fillAndSubmit(onSave: ReturnType<typeof vi.fn>) {
  fireEvent.change(document.getElementById('label')!, { target: { value: 'Thing' } });
  fireEvent.click(screen.getByRole('button', { name: 'common:actions.create' }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
  return onSave.mock.calls[0][0] as Record<string, any>;
}

beforeEach(() => {
  modeMock = 'simple';
  pickerEntityType = undefined;
});

describe('ConceptEditorDialog preset type', () => {
  it('saves the preset type when the scheme allows it', async () => {
    const onSave = renderDialog({ initialConceptType: 'class' });
    const data = await fillAndSubmit(onSave);
    expect(data.concept_type).toBe('class');
    expect(data.collection_iri).toBe(ONTOLOGY.iri);
  });

  it('saves a glossary term preset as concept_type "term"', async () => {
    const onSave = renderDialog({ collection: GLOSSARY, initialConceptType: 'term' });
    const data = await fillAndSubmit(onSave);
    expect(data.concept_type).toBe('term');
  });

  it('resets a preset the scheme does not allow to "concept"', async () => {
    const onSave = renderDialog({ collection: TAXONOMY, initialConceptType: 'property' });
    const data = await fillAndSubmit(onSave);
    expect(data.concept_type).toBe('concept');
  });

  it('re-validates the preset when the user switches scheme in the dialog', async () => {
    const onSave = renderDialog({ collection: ONTOLOGY, initialConceptType: 'class' });
    // Simple mode: the only select is the scheme picker.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: TAXONOMY.iri } });
    const data = await fillAndSubmit(onSave);
    expect(data.collection_iri).toBe(TAXONOMY.iri);
    expect(data.concept_type).toBe('concept');
  });

  it('Simple mode: names a preset property and points to Advanced for domain/range', () => {
    renderDialog({ initialConceptType: 'property' });
    expect(screen.getByTestId('simple-type-hint')).toHaveTextContent('semantic-models:types.property');
    expect(screen.getByText('Domain and range are set in Advanced view.')).toBeInTheDocument();
    expect(document.getElementById('domain')).toBeNull();
  });

  it('Advanced mode: a preset property reaches the domain/range fields', () => {
    modeMock = 'advanced';
    renderDialog({ initialConceptType: 'property' });
    expect(document.getElementById('domain')).not.toBeNull();
    expect(document.getElementById('range')).not.toBeNull();
    expect(screen.queryByTestId('simple-type-hint')).not.toBeInTheDocument();
  });
});

describe('ConceptEditorDialog Parent field', () => {
  it('labels the parent by concept type', () => {
    expect(parentFieldLabelKey('concept').defaultLabel).toBe('Parent Concept');
    expect(parentFieldLabelKey('term').defaultLabel).toBe('Parent Concept');
    expect(parentFieldLabelKey('class').defaultLabel).toBe('Parent Class');
    expect(parentFieldLabelKey('property').defaultLabel).toBe('Parent Property');
  });

  it('is shown in Simple mode and saves picks as broader_iris', async () => {
    const onSave = renderDialog({ initialConceptType: 'class' });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Parent Class');
    fireEvent.click(screen.getByRole('button', { name: 'Add Parent' }));
    expect(pickerEntityType).toBe('class');
    fireEvent.click(screen.getByTestId('pick-parent'));
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Party');
    const data = await fillAndSubmit(onSave);
    expect(data.broader_iris).toEqual(['https://example.org/onto#Party']);
  });

  it('uses the property picker for a Parent Property', () => {
    renderDialog({ initialConceptType: 'property' });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Parent Property');
    fireEvent.click(screen.getByRole('button', { name: 'Add Parent' }));
    expect(pickerEntityType).toBe('property');
  });

  it('is shown for an existing concept, prefilled from parent_concepts', () => {
    renderDialog({
      collection: undefined,
      concept: {
        iri: 'urn:x:Child',
        label: 'Child',
        concept_type: 'concept',
        status: 'draft',
        source_context: 'regions',
        parent_concepts: ['urn:x:Parent'],
        child_concepts: [],
        related_concepts: [],
      } as any,
    });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Parent Concept');
    expect(screen.getByTestId('parent-field')).toHaveTextContent('urn:x:Parent');
  });
});
