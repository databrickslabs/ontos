/**
 * "View changes" on review surfaces (PRD #1086): only for versioned entities
 * with something to compare against; base = parent, else previous version.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';
import EntityChangesButton, { entityKindFor } from './entity-changes-button';
import { pickBaseVersion } from './entity-diff-dialog';
import type { EntityVersionRow } from './version-selector';

afterEach(() => vi.unstubAllGlobals());

function mockVersions(rows: EntityVersionRow[]) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => rows });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('pickBaseVersion', () => {
  const rows: EntityVersionRow[] = [
    { id: 'v3', version: '1.2.0', parentProductId: 'v1' },
    { id: 'v2', version: '1.1.0' },
    { id: 'v1', version: '1.0.0' },
  ];

  it('prefers the lineage parent', () => {
    expect(pickBaseVersion(rows, 'v3')).toBe('v1');
  });

  it('falls back to the next older version', () => {
    expect(pickBaseVersion(rows, 'v2')).toBe('v1');
  });

  it('returns null for the oldest version or an unknown id', () => {
    expect(pickBaseVersion(rows, 'v1')).toBeNull();
    expect(pickBaseVersion(rows, 'nope')).toBeNull();
  });
});

describe('EntityChangesButton', () => {
  it('maps only versioned entity types', () => {
    expect(entityKindFor('data_contract')).toBe('contract');
    expect(entityKindFor('DATA_PRODUCT')).toBe('product');
    expect(entityKindFor('access_grant')).toBeNull();
  });

  it('renders nothing (and fetches nothing) for non-versioned types', () => {
    const fetchMock = mockVersions([]);
    const { container } = renderWithProviders(<EntityChangesButton entityType="access_grant" entityId="x" />);
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the button when the entity has a version to compare against', async () => {
    const fetchMock = mockVersions([
      { id: 'draft', version: '1.0.0-draft', parentContractId: 'v1' },
      { id: 'v1', version: '1.0.0' },
    ]);
    renderWithProviders(<EntityChangesButton entityType="data_contract" entityId="draft" />);

    expect(await screen.findByRole('button', { name: /View changes/ })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/data-contracts/draft/versions');
  });

  it('stays hidden for a family of one or when the versions request fails', async () => {
    mockVersions([{ id: 'only', version: '1.0.0' }]);
    const { container, unmount } = renderWithProviders(
      <EntityChangesButton entityType="data_product" entityId="only" />,
    );
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    unmount();

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const failed = renderWithProviders(<EntityChangesButton entityType="data_product" entityId="x" />);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(failed.container).toBeEmptyDOMElement();
  });
});
