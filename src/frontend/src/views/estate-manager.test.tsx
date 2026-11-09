/**
 * Tests for the pure helpers exported from `estate-manager.tsx`.
 *
 * The component file pulls in many heavy modules (API, breadcrumb store,
 * graph view, i18n), so we deliberately keep these tests at the helper level
 * and avoid importing/rendering the full view.
 *
 * `buildEstateDetailPath` is the contract that has to stay in lock-step with
 * the route registered in `app.tsx` (`/estates/:estateId`). Regression guard
 * for ONT-FEAT-008: "View Details" used to navigate to `/estate-manager/${id}`,
 * an unregistered URL that rendered the 404 page.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';

import '@/i18n/config';
import type { Estate } from '@/types/estate';
import EstateManager, { buildEstateDetailPath } from './estate-manager';

const api = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/components/estates/estate-graph-view', () => ({ default: () => null }));

describe('buildEstateDetailPath', () => {
  it('targets the registered /estates/:estateId route', () => {
    expect(buildEstateDetailPath('1')).toBe('/estates/1');
  });

  it('does NOT derive the path from the /estate-manager list location', () => {
    // The old bug produced `/estate-manager/1`, which has no matching route
    // and rendered "404 - Page Not Found".
    expect(buildEstateDetailPath('1')).not.toBe('/estate-manager/1');
    expect(buildEstateDetailPath('1').startsWith('/estate-manager/')).toBe(false);
  });

  it('handles arbitrary estate ids (uuid-style)', () => {
    const id = 'a1b2c3d4-0000-1111-2222-333344445555';
    expect(buildEstateDetailPath(id)).toBe(`/estates/${id}`);
  });
});

const estate: Estate = {
  id: 'e-1',
  name: 'EU Analytics',
  description: 'Analytics workspace',
  workspace_url: 'https://eu.cloud.databricks.com',
  cloud_type: 'azure',
  metastore_name: 'eu',
  connection_type: 'delta_share',
  export_policies: [],
  import_policies: [],
  is_enabled: true,
  sync_schedule: '0 0 * * *',
  created_at: '2026-10-19T00:00:00Z',
  updated_at: '2026-10-19T00:00:00Z',
};

function LocationProbe() {
  return <p data-testid="search">{useLocation().search}</p>;
}

function renderAt(url: string) {
  api.get.mockResolvedValue({ data: [estate] });
  return render(
    <MemoryRouter initialEntries={[url]}>
      <EstateManager />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('?edit deep link', () => {
  it('opens the edit dialog prefilled for a known id and removes the param', async () => {
    renderAt('/estate-manager?edit=e-1');

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('EU Analytics')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent(/^$/));
  });

  it('opens no dialog for an unknown id and still clears the param', async () => {
    renderAt('/estate-manager?edit=nope');

    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent(/^$/));
    expect(api.get).toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
