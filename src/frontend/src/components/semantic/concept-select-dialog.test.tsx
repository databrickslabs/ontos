import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// ---------------------------------------------------------------------------
// ConceptSelectDialog: default flat list is unchanged; the optional
// conceptTypes prop asks the server to narrow the list by concept type, and
// scopeSourceKey narrows it to one scheme (opt-in widening, grouped).
// ---------------------------------------------------------------------------

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: postMock }),
}));

import ConceptSelectDialog from './concept-select-dialog';

const FLAT = [
  { value: 'urn:x:Party', label: 'Party', type: 'class' },
  { value: 'urn:x:Europe', label: 'Europe', type: 'class' },
];

// What the server returns for concept_types=class.
const CLASSES = [
  { value: 'urn:x:Asset', label: 'Asset', type: 'class' },
  { value: 'urn:x:Party', label: 'Party', type: 'class' },
];

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  getMock.mockImplementation(async (url: string) =>
    url.includes('concept_types=') ? { data: CLASSES } : { data: FLAT },
  );
});

describe('ConceptSelectDialog', () => {
  it('without conceptTypes: lists the flat concepts endpoint as before', async () => {
    render(<ConceptSelectDialog isOpen onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Europe')).toBeInTheDocument());
    expect(screen.getByText('Select Business Concept')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search business concepts...')).toBeInTheDocument();
    expect(screen.queryByText('Include other schemes')).not.toBeInTheDocument();
    expect(screen.getByText('Party')).toBeInTheDocument();
    const urls = getMock.mock.calls.map((c) => c[0] as string);
    expect(urls.every((u) => u.startsWith('/api/semantic-models/concepts?'))).toBe(true);
    expect(urls[0]).toContain('limit=50');
  });

  it("conceptTypes ['class']: requests the flat endpoint with concept_types", async () => {
    const onSelect = vi.fn();
    render(<ConceptSelectDialog isOpen onOpenChange={vi.fn()} onSelect={onSelect} conceptTypes={['class']} />);
    await waitFor(() => expect(screen.getByText('Asset')).toBeInTheDocument());
    expect(screen.getByText('Party')).toBeInTheDocument();
    const urls = getMock.mock.calls.map((c) => c[0] as string);
    expect(urls).toHaveLength(1);
    expect(urls[0].startsWith('/api/semantic-models/concepts?')).toBe(true);
    expect(urls[0]).toContain('concept_types=class');
    expect(urls[0]).toContain('limit=50');
    expect(urls.some((u) => u.includes('concepts-grouped'))).toBe(false);
    fireEvent.click(screen.getAllByRole('button', { name: 'Select' })[0]);
    expect(onSelect).toHaveBeenCalledWith('urn:x:Asset');
  });

  it('conceptTypes: typing sends the query to the server (debounced)', async () => {
    render(<ConceptSelectDialog isOpen onOpenChange={vi.fn()} onSelect={vi.fn()} conceptTypes={['class', 'individual']} />);
    await waitFor(() => expect(screen.getByText('Asset')).toBeInTheDocument());
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'ass' } });
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    const last = getMock.mock.calls[1][0] as string;
    expect(last).toContain('q=ass');
    expect(last).toContain('concept_types=class%2Cindividual');
    expect(last.includes('concepts-grouped')).toBe(false);
  });

  it('without conceptTypes: requests carry no concept_types param', async () => {
    render(<ConceptSelectDialog isOpen onOpenChange={vi.fn()} onSelect={vi.fn()} parentConceptIris={['urn:x:Root']} />);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    const url = getMock.mock.calls[0][0] as string;
    expect(url.startsWith('/api/semantic-models/concepts/suggestions?')).toBe(true);
    expect(url.includes('concept_types')).toBe(false);
  });
});

// Scoped lists: the target scheme's rows, then (widened) rows of other schemes.
const SCOPED = [
  { value: 'urn:x:Asset', label: 'Asset', type: 'class', source_context: 'core' },
  { value: 'urn:x:Self', label: 'Self', type: 'class', source_context: 'core' },
  { value: 'urn:x:Chosen', label: 'Chosen', type: 'class', source_context: 'core' },
];
const WIDE = [
  ...SCOPED,
  { value: 'urn:sys:Agent', label: 'Agent', type: 'class', source_context: 'zeta-sys' },
  { value: 'urn:ext:Thing', label: 'Thing', type: 'class', source_context: 'ext' },
];

function urls() {
  return getMock.mock.calls.map((c) => c[0] as string);
}

describe('ConceptSelectDialog scoped to one scheme', () => {
  beforeEach(() => {
    getMock.mockImplementation(async (url: string) =>
      url.includes('source_context=') ? { data: SCOPED } : { data: WIDE },
    );
  });

  const scopedProps = {
    isOpen: true,
    onOpenChange: vi.fn(),
    onSelect: vi.fn(),
    conceptTypes: ['class'],
    scopeSourceKey: 'core',
    scopeLabel: 'Core',
    schemeLabels: { core: 'Core', ext: 'Extensions', 'zeta-sys': 'A System Ontology' },
  };

  it('requests the scheme with source_context, concept_types and a higher limit', async () => {
    render(<ConceptSelectDialog {...scopedProps} title="Select Superclass" searchPlaceholder="Search classes..." />);
    await waitFor(() => expect(screen.getByText('Asset')).toBeInTheDocument());
    expect(urls()).toHaveLength(1);
    expect(urls()[0]).toContain('source_context=core');
    expect(urls()[0]).toContain('concept_types=class');
    expect(urls()[0]).toContain('limit=200');
    expect(screen.getByText('Select Superclass')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search classes...')).toBeInTheDocument();
    // Single scheme: no group headers, no widening checkbox unless allowed.
    expect(screen.queryByText(/This scheme/)).not.toBeInTheDocument();
    expect(screen.queryByText('Include other schemes')).not.toBeInTheDocument();
  });

  it('does not render excluded IRIs', async () => {
    render(<ConceptSelectDialog {...scopedProps} excludeIris={['urn:x:Self', 'urn:x:Chosen']} />);
    await waitFor(() => expect(screen.getByText('Asset')).toBeInTheDocument());
    expect(screen.queryByText('Self')).not.toBeInTheDocument();
    expect(screen.queryByText('Chosen')).not.toBeInTheDocument();
  });

  it('"Include other schemes" drops source_context and groups by scheme, this scheme first', async () => {
    render(<ConceptSelectDialog {...scopedProps} allowOtherSchemes excludeIris={['urn:x:Self']} />);
    await waitFor(() => expect(screen.getByText('Asset')).toBeInTheDocument());
    const box = screen.getByRole('checkbox');
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    await waitFor(() => expect(screen.getByText('Thing')).toBeInTheDocument());
    const last = urls()[urls().length - 1];
    expect(last.includes('source_context')).toBe(false);
    expect(last).toContain('concept_types=class');
    expect(last).toContain('limit=200');
    const headers = ['This scheme: Core', 'A System Ontology', 'Extensions'];
    const nodes = headers.map((h) => screen.getByText(h));
    // Document order: this scheme, then the others sorted by label.
    for (let i = 1; i < nodes.length; i++) {
      expect(nodes[i - 1].compareDocumentPosition(nodes[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(nodes[0].compareDocumentPosition(screen.getByText('Asset')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Self')).not.toBeInTheDocument();
  });

  it('shows an empty state with the widening hint for classes', async () => {
    getMock.mockImplementation(async () => ({ data: [] }));
    render(<ConceptSelectDialog {...scopedProps} allowOtherSchemes />);
    await waitFor(() => expect(screen.getByText('No classes in this scheme yet.')).toBeInTheDocument());
    expect(screen.getByText('Tick "Include other schemes" to pick from another scheme.')).toBeInTheDocument();
  });

  it('empty state for taxonomy concepts, also when all rows are excluded', async () => {
    getMock.mockImplementation(async () => ({ data: [{ value: 'urn:x:Self', label: 'Self', type: 'concept', source_context: 'regions' }] }));
    render(
      <ConceptSelectDialog
        isOpen
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        conceptTypes={['concept']}
        scopeSourceKey="regions"
        excludeIris={['urn:x:Self']}
      />,
    );
    await waitFor(() => expect(screen.getByText('No concepts in this scheme yet.')).toBeInTheDocument());
    expect(urls()[0]).toContain('concept_types=concept');
    expect(urls()[0]).toContain('source_context=regions');
    expect(screen.queryByText(/Include other schemes/)).not.toBeInTheDocument();
  });

  it('scopeSourceKey without conceptTypes keeps the default request', async () => {
    getMock.mockImplementation(async () => ({ data: FLAT }));
    render(<ConceptSelectDialog isOpen onOpenChange={vi.fn()} onSelect={vi.fn()} scopeSourceKey="core" />);
    await waitFor(() => expect(screen.getByText('Europe')).toBeInTheDocument());
    expect(urls()[0].includes('source_context')).toBe(false);
    expect(urls()[0]).toContain('limit=50');
  });
});
