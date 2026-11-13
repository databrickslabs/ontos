/**
 * Settings > Lifecycle Stage Groups lists the groups of the chosen entity type,
 * with their stages drawn from the stage data (#1214).
 */
import { screen, within, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import LifecycleStageGroupsSettings from './lifecycle-stage-groups-settings';
import type { LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast }),
  useToast: () => ({ toast }),
}));
let canWrite = true;
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => canWrite }),
}));

const stage = (key: string, label: string, category: string, order: number, color = 'gray') => ({
  key, label, category, color, order, is_initial: order === 0,
});

const PRODUCT_GROUPS: LifecycleStageGroup[] = [
  {
    id: 'g-default', name: 'Default data product lifecycle', entity_type: 'data_product',
    is_default_for_type: true,
    stages: [
      stage('draft', 'Draft', 'draft', 0),
      stage('active', 'Active', 'active', 1, 'green'),
    ] as any,
    transitions: [{ from_key: 'draft', to_key: 'active' }],
  },
  {
    id: 'g-loop', name: 'Authority resolution', entity_type: 'data_product',
    is_default_for_type: false,
    stages: [
      stage('draft', 'Draft', 'draft', 0),
      stage('active', 'Active', 'active', 1, 'green'),
      stage('needs_review', 'Needs Review', 'review', 2, 'amber'),
    ] as any,
    transitions: [
      { from_key: 'draft', to_key: 'active' },
      { from_key: 'active', to_key: 'needs_review' },
      { from_key: 'needs_review', to_key: 'active' },
    ],
  },
];

const ASSET_GROUPS: LifecycleStageGroup[] = [
  {
    id: 'g-asset', name: 'Default asset lifecycle', entity_type: 'asset',
    is_default_for_type: true,
    stages: [stage('draft', 'Draft', 'draft', 0), stage('active', 'Active', 'active', 1)] as any,
    transitions: [{ from_key: 'draft', to_key: 'active' }],
  },
];

const json = (body: unknown, status = 200) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: () => Promise.resolve(body),
  });

describe('LifecycleStageGroupsSettings', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    canWrite = true;
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return json({
          detail: {
            code: 'lifecycle_group_in_use', message: "'Authority resolution' is in use",
            params: { groupId: 'g-loop', count: 3 },
          },
        }, 409);
      }
      if (init?.method === 'PUT') return json(PRODUCT_GROUPS[1]);
      if (url.includes('entity_type=asset')) return json(ASSET_GROUPS);
      if (url.includes('entity_type=data_product')) return json(PRODUCT_GROUPS);
      return json([]);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('lists the groups of the entity type with their stages', async () => {
    renderWithProviders(<LifecycleStageGroupsSettings />);

    const list = await screen.findByRole('list', { name: 'Lifecycle stage groups' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('Default data product lifecycle')).toBeInTheDocument();
    expect(within(items[0]).getByText('Default')).toBeInTheDocument();
    expect(within(items[1]).getByText('Authority resolution')).toBeInTheDocument();
    // A custom label is user data, shown as written; its colour comes from the stage
    const custom = within(items[1]).getByText('Needs Review');
    expect(custom.className).toContain('bg-amber-100');
    expect(fetchMock).toHaveBeenCalledWith('/api/lifecycle-stage-groups?entity_type=data_product');
  });

  it('switches to the groups of another entity type', async () => {
    renderWithProviders(<LifecycleStageGroupsSettings />);
    await screen.findByText('Authority resolution');

    const tab = screen.getByRole('tab', { name: 'Assets' });
    fireEvent.mouseDown(tab);
    fireEvent.click(tab);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/lifecycle-stage-groups?entity_type=asset'),
    );
    expect(await screen.findByText('Default asset lifecycle')).toBeInTheDocument();
    expect(screen.queryByText('Authority resolution')).not.toBeInTheDocument();
  });

  it('makes a group the default with its whole definition', async () => {
    renderWithProviders(<LifecycleStageGroupsSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Make default' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/lifecycle-stage-groups/g-loop', expect.objectContaining({ method: 'PUT' }),
    ));
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!;
    const body = JSON.parse(put[1].body);
    expect(body.is_default_for_type).toBe(true);
    expect(body.stages.map((s: any) => s.key)).toEqual(['draft', 'active', 'needs_review']);
    expect(body.transitions).toHaveLength(3);
  });

  it('explains a refused delete in the UI language', async () => {
    renderWithProviders(<LifecycleStageGroupsSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete Authority resolution' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      variant: 'destructive',
      description: 'This lifecycle is used by 3 entities and can’t be deleted.',
    })));
    // The default can't be deleted, so it offers no delete
    expect(screen.queryByRole('button', { name: 'Delete Default data product lifecycle' }))
      .not.toBeInTheDocument();
  });

  it('offers no changes without write access', async () => {
    canWrite = false;
    renderWithProviders(<LifecycleStageGroupsSettings />);
    await screen.findByText('Authority resolution');

    expect(screen.queryByRole('button', { name: 'New group' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Make default' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View Authority resolution' })).toBeInTheDocument();
  });
});
