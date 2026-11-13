/**
 * The version picker narrows its rows with the caller's row filter (the
 * contracts a port may use, by Stage Category, #1215) and then considers
 * every version, not just each family's newest.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { EntityVersionPicker } from './entity-version-picker';
import { isContractPublishable } from '@/lib/lifecycle-stages';

const ROWS = [
  { id: 'c1', name: 'Live feed', version: '1.0.0', status: 'live', status_category: 'active' },
  { id: 'c2', name: 'Vetting feed', version: '1.0.0', status: 'vetting',
    status_category: 'review' },
  { id: 'c3', name: 'Approved feed', version: '1.0.0', status: 'approved',
    status_category: 'review' },
];

describe('EntityVersionPicker row filter', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(ROWS) }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('offers only the rows the filter keeps, across every version', async () => {
    renderWithProviders(
      <EntityVersionPicker entityKind="contract" value={null} onChange={vi.fn()}
        rowFilter={isContractPublishable} />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/data-contracts?include_history=true',
    ));
    fireEvent.click(screen.getByRole('combobox'));
    expect(await screen.findByText('Live feed')).toBeInTheDocument();
    expect(screen.getByText('Approved feed')).toBeInTheDocument();
    expect(screen.queryByText('Vetting feed')).not.toBeInTheDocument();
  });

  it('fetches the family list without a filter', async () => {
    renderWithProviders(
      <EntityVersionPicker entityKind="contract" value={null} onChange={vi.fn()} />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/data-contracts'));
  });
});
