import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import type { KnowledgeCollection } from '@/types/ontology';

// ---------------------------------------------------------------------------
// ConceptEditorDialog: fixed type (read-only), scheme list filtered by type,
// the no-fitting-scheme notice, and the per-type Parent field.
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

// The dialog must not depend on the page-level mode: fail loudly if it does.
vi.mock('@/components/concepts/mode-switch', () => ({
  useConceptMode: () => {
    throw new Error('ConceptEditorDialog must not read the concept mode');
  },
  ConceptModeSwitch: () => <div data-testid="mode-switch" />,
}));

// Stand-in for the concept picker: one button that picks a fixed IRI.
let pickerEntityType: string | undefined;
let pickerConceptTypes: string[] | undefined;
let pickerOnSelect: ((iri: string) => void) | undefined;
vi.mock('@/components/semantic/concept-select-dialog', () => ({
  default: ({ isOpen, onSelect, entityType, conceptTypes }: { isOpen: boolean; onSelect: (iri: string) => void; entityType?: string; conceptTypes?: string[] }) => {
    pickerEntityType = entityType;
    pickerConceptTypes = conceptTypes;
    pickerOnSelect = onSelect;
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

import { ConceptEditorDialog } from './concept-editor-dialog';

const ONTOLOGY = { iri: 'urn:ontology:core', label: 'Core', collection_type: 'ontology', is_editable: true } as unknown as KnowledgeCollection;
const ONTOLOGY_2 = { iri: 'urn:ontology:ext', label: 'Ext', collection_type: 'ontology', is_editable: true } as unknown as KnowledgeCollection;
const TAXONOMY = { iri: 'urn:taxonomy:regions', label: 'Regions', collection_type: 'taxonomy', is_editable: true } as unknown as KnowledgeCollection;
const GLOSSARY = { iri: 'urn:glossary:business', label: 'Business', collection_type: 'glossary', is_editable: true } as unknown as KnowledgeCollection;
const READONLY_GLOSSARY = { iri: 'urn:glossary:ro', label: 'Read Only', collection_type: 'glossary', is_editable: false } as unknown as KnowledgeCollection;

function renderDialog(props: Partial<React.ComponentProps<typeof ConceptEditorDialog>> = {}) {
  const onSave = vi.fn(async () => {});
  render(
    <ConceptEditorDialog
      open
      onOpenChange={vi.fn()}
      concept={null}
      collection={ONTOLOGY}
      collections={[ONTOLOGY, ONTOLOGY_2, TAXONOMY, GLOSSARY]}
      onSave={onSave}
      {...props}
    />,
  );
  return onSave;
}

async function fillAndSubmit(onSave: ReturnType<typeof vi.fn>, buttonName = 'common:actions.create') {
  if (buttonName === 'common:actions.create') {
    fireEvent.change(document.getElementById('label')!, { target: { value: 'Thing' } });
  }
  fireEvent.click(screen.getByRole('button', { name: buttonName }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
  return onSave.mock.calls[0][0] as Record<string, any>;
}

// Options of the scheme picker (the first select; a property also has a
// property-type select further down).
function schemeOptions() {
  const select = screen.getAllByRole('combobox')[0];
  return Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
}

const EXISTING_CLASS = {
  iri: 'urn:x:Customer',
  label: 'Customer',
  concept_type: 'class',
  status: 'draft',
  source_context: 'core',
  parent_concepts: ['urn:x:Party'],
  child_concepts: [],
  related_concepts: [],
} as any;

beforeEach(() => {
  pickerEntityType = undefined;
  pickerConceptTypes = undefined;
  pickerOnSelect = undefined;
});

describe('ConceptEditorDialog header and type', () => {
  it('create: neutral title and description', () => {
    renderDialog({ initialConceptType: 'class' });
    expect(screen.getByText('Create Entry')).toBeInTheDocument();
    expect(screen.getByText('Add a new entry to a scheme.')).toBeInTheDocument();
  });

  it('edit: "Edit Entry" with the status badge and the IRI as description', () => {
    renderDialog({ collection: undefined, concept: EXISTING_CLASS });
    expect(screen.getByText('Edit Entry')).toBeInTheDocument();
    expect(screen.getByText('draft')).toBeInTheDocument();
    expect(screen.getByText('urn:x:Customer')).toBeInTheDocument();
  });

  it('shows the type read-only, with no type dropdown and no mode switch', () => {
    renderDialog({ collection: GLOSSARY, initialConceptType: 'term' });
    expect(screen.getByTestId('concept-type-row')).toHaveTextContent('semantic-models:types.term');
    // The only select is the (disabled, single-option) scheme picker.
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
    expect(screen.queryByRole('option', { name: 'semantic-models:types.concept' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('mode-switch')).not.toBeInTheDocument();
  });

  it('edit mode shows the entry type read-only too', () => {
    renderDialog({ collection: undefined, concept: EXISTING_CLASS });
    expect(screen.getByTestId('concept-type-row')).toHaveTextContent('semantic-models:types.class');
  });

  it('saves the preset type unchanged', async () => {
    const onSave = renderDialog({ initialConceptType: 'class' });
    const data = await fillAndSubmit(onSave);
    expect(data.concept_type).toBe('class');
    expect(data.collection_iri).toBe(ONTOLOGY.iri);
  });

  it('defaults to concept_type "concept" without a preset', async () => {
    const onSave = renderDialog({ collection: TAXONOMY });
    const data = await fillAndSubmit(onSave);
    expect(data.concept_type).toBe('concept');
    expect(data.collection_iri).toBe(TAXONOMY.iri);
  });
});

describe('ConceptEditorDialog scheme list follows the type', () => {
  it('term: glossaries only (editable ones), single fit is read-only', () => {
    renderDialog({ collection: undefined, initialConceptType: 'term', collections: [ONTOLOGY, GLOSSARY, READONLY_GLOSSARY, TAXONOMY] });
    expect(schemeOptions()).toEqual(['Business']);
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('concept: taxonomies only', () => {
    renderDialog({ collection: undefined, initialConceptType: 'concept' });
    expect(schemeOptions()).toEqual(['Regions']);
  });

  it('class and property: ontologies only', () => {
    renderDialog({ initialConceptType: 'class' });
    expect(schemeOptions()).toEqual(['Core', 'Ext']);
    expect(screen.getByRole('combobox')).not.toBeDisabled();
  });

  it('property: ontologies only', () => {
    renderDialog({ initialConceptType: 'property' });
    expect(schemeOptions()).toEqual(['Core', 'Ext']);
  });

  it('includes fitting schemes nested under other schemes', () => {
    const parent = { ...TAXONOMY, child_collections: [ONTOLOGY_2] } as unknown as KnowledgeCollection;
    renderDialog({ collection: undefined, initialConceptType: 'class', collections: [parent] });
    expect(schemeOptions()).toEqual(['Ext']);
  });

  it('preselects the first fitting scheme when the preset scheme does not fit', async () => {
    const onSave = renderDialog({ collection: GLOSSARY, initialConceptType: 'class' });
    const data = await fillAndSubmit(onSave);
    expect(data.collection_iri).toBe(ONTOLOGY.iri);
    expect(data.concept_type).toBe('class');
  });

  it('saves the scheme the user picks', async () => {
    const onSave = renderDialog({ initialConceptType: 'class' });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: ONTOLOGY_2.iri } });
    const data = await fillAndSubmit(onSave);
    expect(data.collection_iri).toBe(ONTOLOGY_2.iri);
  });
});

describe('ConceptEditorDialog with no fitting scheme', () => {
  it('shows the notice, disables Create, and asks for a scheme of the right kind', () => {
    const onCreateScheme = vi.fn();
    renderDialog({ collection: undefined, initialConceptType: 'term', collections: [ONTOLOGY, READONLY_GLOSSARY], onCreateScheme });
    expect(screen.getByTestId('no-scheme-notice')).toHaveTextContent('Create one first.');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    fireEvent.change(document.getElementById('label')!, { target: { value: 'Thing' } });
    expect(screen.getByRole('button', { name: 'common:actions.create' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'New Concept Scheme' }));
    expect(onCreateScheme).toHaveBeenCalledWith('glossary');
  });

  it('asks for an ontology for a class', () => {
    const onCreateScheme = vi.fn();
    renderDialog({ collection: undefined, initialConceptType: 'class', collections: [GLOSSARY], onCreateScheme });
    fireEvent.click(screen.getByRole('button', { name: 'New Concept Scheme' }));
    expect(onCreateScheme).toHaveBeenLastCalledWith('ontology');
  });

  it('asks for a taxonomy for a concept', () => {
    const onCreateScheme = vi.fn();
    renderDialog({ collection: undefined, initialConceptType: 'concept', collections: [GLOSSARY], onCreateScheme });
    fireEvent.click(screen.getByRole('button', { name: 'New Concept Scheme' }));
    expect(onCreateScheme).toHaveBeenLastCalledWith('taxonomy');
  });

  it('hides the button without onCreateScheme', () => {
    renderDialog({ collection: undefined, initialConceptType: 'term', collections: [ONTOLOGY] });
    expect(screen.getByTestId('no-scheme-notice')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New Concept Scheme' })).not.toBeInTheDocument();
  });
});

describe('ConceptEditorDialog Parent field', () => {
  it('is shown for a concept as Parent Concept and saves picks as broader_iris', async () => {
    const onSave = renderDialog({ collection: TAXONOMY, initialConceptType: 'concept' });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Parent Concept');
    fireEvent.click(screen.getByRole('button', { name: 'Add Parent' }));
    expect(pickerEntityType).toBe('class');
    // Taxonomy parents: any concept, no type filter.
    expect(pickerConceptTypes).toBeUndefined();
    fireEvent.click(screen.getByTestId('pick-parent'));
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Party');
    const data = await fillAndSubmit(onSave);
    expect(data.broader_iris).toEqual(['https://example.org/onto#Party']);
  });

  it('is shown for a class as "Subclass of" with a classes-only picker', async () => {
    const onSave = renderDialog({ initialConceptType: 'class' });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Subclass of');
    expect(screen.queryByRole('button', { name: 'Add Parent' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Select Class' }));
    expect(pickerConceptTypes).toEqual(['class']);
    fireEvent.click(screen.getByTestId('pick-parent'));
    const data = await fillAndSubmit(onSave);
    // Same payload field; the backend writes rdfs:subClassOf for a class.
    expect(data.broader_iris).toEqual(['https://example.org/onto#Party']);
  });

  it.each(['term', 'property', 'individual'] as const)('is hidden for %s', (type) => {
    renderDialog({ collection: type === 'term' ? GLOSSARY : ONTOLOGY, initialConceptType: type });
    expect(screen.queryByTestId('parent-field')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add Parent' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Select Class' })).not.toBeInTheDocument();
  });

  it('is shown for an existing concept, prefilled from parent_concepts', () => {
    renderDialog({
      collection: undefined,
      concept: { ...EXISTING_CLASS, iri: 'urn:x:Child', concept_type: 'concept', parent_concepts: ['urn:x:Parent'] },
    });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Parent Concept');
    expect(screen.getByTestId('parent-field')).toHaveTextContent('urn:x:Parent');
  });

  it('editing a class shows its superclasses and keeps them in the payload', async () => {
    const onSave = renderDialog({ collection: undefined, concept: EXISTING_CLASS });
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Subclass of');
    expect(screen.getByTestId('parent-field')).toHaveTextContent('Party');
    const data = await fillAndSubmit(onSave, 'common:actions.save');
    expect(data.broader_iris).toEqual(['urn:x:Party']);
    expect(data.concept_type).toBe('class');
  });

  it('a class cannot pick itself or one of its subclasses as superclass', async () => {
    const onSave = renderDialog({
      collection: undefined,
      concept: { ...EXISTING_CLASS, child_concepts: ['urn:x:VipCustomer'] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Select Class' }));
    act(() => pickerOnSelect!('urn:x:Customer'));
    fireEvent.click(screen.getByRole('button', { name: 'Select Class' }));
    act(() => pickerOnSelect!('urn:x:VipCustomer'));
    const data = await fillAndSubmit(onSave, 'common:actions.save');
    expect(data.broader_iris).toEqual(['urn:x:Party']);
  });

  it.each([
    ['term', { concept_type: 'term', source_context: 'business' }],
    ['property', { concept_type: 'property', domain: 'urn:x:A' }],
    ['individual', { concept_type: 'individual' }],
  ] as const)('editing a %s keeps stored parents even though the field is hidden', async (_type, extra) => {
    const onSave = renderDialog({
      collection: undefined,
      concept: { ...EXISTING_CLASS, ...extra, parent_concepts: ['urn:x:Stored'] },
    });
    expect(screen.queryByTestId('parent-field')).not.toBeInTheDocument();
    const data = await fillAndSubmit(onSave, 'common:actions.save');
    expect(data.broader_iris).toEqual(['urn:x:Stored']);
  });
});

describe('ConceptEditorDialog property block', () => {
  it('shows property type, domain and range for a new property without any mode', () => {
    renderDialog({ initialConceptType: 'property' });
    expect(screen.getByText('semantic-models:conceptEditor.propertyConfiguration')).toBeInTheDocument();
    expect(document.getElementById('domain')).not.toBeNull();
    expect(document.getElementById('range')).not.toBeNull();
    expect(screen.queryByText('Domain and range are set in Advanced view.')).not.toBeInTheDocument();
  });

  it('shows the property block when editing a property', () => {
    renderDialog({ collection: undefined, concept: { ...EXISTING_CLASS, concept_type: 'property', domain: 'urn:x:A' } });
    expect((document.getElementById('domain') as HTMLInputElement).value).toBe('urn:x:A');
  });

  it('is not shown for a class', () => {
    renderDialog({ initialConceptType: 'class' });
    expect(document.getElementById('domain')).toBeNull();
  });
});
