import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// ---------------------------------------------------------------------------
// ConceptSelectDialog: default flat list is unchanged; the optional
// conceptTypes prop asks the server to narrow the list by concept type.
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
