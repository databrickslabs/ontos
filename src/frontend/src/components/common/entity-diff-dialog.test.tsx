/**
 * EntityDiffDialog (PRD #1086): renders a version comparison from the
 * `/diff/{target}` endpoint — grouped classified changes, the suggested bump,
 * the "version doesn't reflect the changes" warning, and the YAML diff tab.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { renderWithProviders } from '@/test/utils';
import EntityDiffDialog, { diffEndpointFor, orderPair, type EntityDiffResponse } from './entity-diff-dialog';
import type { EntityVersionRow } from './version-selector';

const VERSIONS: EntityVersionRow[] = [
  { id: 'v2', version: '1.0.1', status: 'draft' },
  { id: 'v1', version: '1.0.0', status: 'active' },
];

function diffResponse(overrides: Partial<EntityDiffResponse> = {}): EntityDiffResponse {
  return {
    entity_type: 'data_product',
    base: { id: 'v1', version: '1.0.0', status: 'active' },
    target: { id: 'v2', version: '1.0.1', status: 'draft' },
    changes: [
      { path: 'outputPorts[orders]', op: 'removed', bump: 'major', rule_id: 'output-port-removed',
        message: 'Output port removed', old: { name: 'orders' } },
      { path: 'description.purpose', op: 'modified', bump: 'patch', rule_id: 'description',
        message: 'Description changed', old: 'old words', new: 'new words' },
    ],
    counts: { major: 1, minor: 0, patch: 1, none: 0 },
    suggested_bump: 'major',
    suggested_version: '2.0.0',
    version_consistent: false,
    unified_diff: '--- a\n+++ b\n@@ -1 +1 @@\n-purpose: old words\n+purpose: new words\n',
    ...overrides,
  };
}

function mockFetch(body: unknown, ok = true) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 500, json: async () => body });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderDialog() {
  return renderWithProviders(
    <EntityDiffDialog open onOpenChange={() => {}} entityKind="product" versions={VERSIONS}
      baseId="v1" targetId="v2" />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('helpers', () => {
  it('builds the per-entity diff endpoint', () => {
    expect(diffEndpointFor('product', 'a', 'b')).toBe('/api/data-products/a/diff/b');
    expect(diffEndpointFor('contract', 'a', 'b')).toBe('/api/data-contracts/a/diff/b');
  });

  it('orders a pair oldest → newest from the newest-first list', () => {
    expect(orderPair(VERSIONS, 'v2', 'v1')).toEqual(['v1', 'v2']);
    expect(orderPair(VERSIONS, 'v1', 'v2')).toEqual(['v1', 'v2']);
  });
});

describe('EntityDiffDialog', () => {
  it('fetches the pair and shows grouped changes with the suggested bump', async () => {
    const fetchMock = mockFetch(diffResponse());
    renderDialog();

    expect(await screen.findByText('Output port removed')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/data-products/v1/diff/v2');
    expect(screen.getByText('outputPorts[orders]')).toBeInTheDocument();
    expect(screen.getByText('→ 2.0.0')).toBeInTheDocument();
    // modified values are shown old → new
    expect(screen.getByText('old words')).toBeInTheDocument();
    expect(screen.getByText('new words')).toBeInTheDocument();
  });

  it('warns when the target version does not reflect the changes', async () => {
    mockFetch(diffResponse());
    renderDialog();

    expect(await screen.findByRole('alert')).toHaveTextContent(/1\.0\.1/);
  });

  it('does not warn when the version is consistent', async () => {
    mockFetch(diffResponse({ version_consistent: true }));
    renderDialog();

    await screen.findByText('Output port removed');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the YAML diff tab', async () => {
    mockFetch(diffResponse());
    renderDialog();
    await screen.findByText('Output port removed');

    await userEvent.click(screen.getByRole('tab', { name: /YAML/ }));

    expect(await screen.findByText('+purpose: new words')).toBeInTheDocument();
  });

  it('shows the empty state for identical versions', async () => {
    mockFetch(diffResponse({ changes: [], counts: { major: 0, minor: 0, patch: 0, none: 0 },
      suggested_bump: 'none', version_consistent: true, unified_diff: '' }));
    renderDialog();

    await waitFor(() => expect(screen.getAllByText(/No differences/).length).toBeGreaterThan(0));
  });

  it('shows an error when the comparison fails to load', async () => {
    mockFetch({}, false);
    renderDialog();

    expect(await screen.findByText(/Failed to load the version comparison/)).toBeInTheDocument();
  });
});
