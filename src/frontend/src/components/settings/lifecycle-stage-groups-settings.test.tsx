/**
 * Settings > Lifecycle Stage Groups lists the groups of the chosen entity type,
 * with their stages drawn from the stage data (#1214).
 */
import { screen, within, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import LifecycleStageGroupsSettings from './lifecycle-stage-groups-settings';
import type { LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: vi.fn() }),
  useToast: () => ({ toast: vi.fn() }),
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

const json = (body: unknown) =>
  Promise.resolve({
    ok: true, status: 200,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: () => Promise.resolve(body),
  });

describe('LifecycleStageGroupsSettings', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((url: string) => {
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
});
