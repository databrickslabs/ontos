/**
 * The asset form follows the asset's Lifecycle Stage Group (#1215): a new
 * asset picks its group (when there are several) and starts in that group's
 * first stage; an edit offers only the current stage and the allowed moves.
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { AssetFormDialog } from './asset-form-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: mockPut }),
}));
vi.mock('@/components/ui/domain-multi-selector', () => ({ default: () => null }));
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: any) => (
    <select value={value ?? ''} onChange={(e) => onValueChange(e.target.value)}>
      <option value="" />
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));

const st = (key: string, label: string, category: string, order: number) => ({
  key, label, category, color: null, order, is_initial: order === 0,
});
const GROUPS = [
  {
    id: 'g-default', name: 'Default asset lifecycle', entity_type: 'asset',
    is_default_for_type: true, transitions: [],
    stages: [st('draft', 'Draft', 'draft', 0), st('active', 'Active', 'active', 1)],
  },
  {
    id: 'g-certified', name: 'Certified tables', entity_type: 'asset',
    is_default_for_type: false, transitions: [],
    stages: [st('intake', 'Intake', 'draft', 0), st('live', 'Live', 'active', 1)],
  },
];

const selectWith = (value: string) => screen.getAllByRole('combobox').find(
  (select) => select.querySelector(`option[value="${value}"]`),
) as HTMLSelectElement | undefined;

const optionValues = (select: HTMLSelectElement) =>
  Array.from(select.querySelectorAll('option')).map((o) => o.value).filter(Boolean);

describe('AssetFormDialog lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/lifecycle-stage-groups')) return { data: GROUPS };
      if (url === '/api/lifecycle/asset/a1') {
        return { data: {
          entity_type: 'asset', entity_id: 'a1', status: 'live',
          group: { id: 'g-certified', name: 'Certified tables', entity_type: 'asset',
            is_default_for_type: false },
          stage: st('live', 'Live', 'active', 1),
          allowed_transitions: [st('retired', 'Retired', 'retired', 2)],
        } };
      }
      return { data: null };
    });
    mockPost.mockResolvedValue({ data: { id: 'new' } });
    mockPut.mockResolvedValue({ data: { id: 'a1' } });
  });

  it('creates an asset in the picked group, starting in its first stage', async () => {
    renderWithProviders(
      <AssetFormDialog isOpen onOpenChange={vi.fn()} onSuccess={vi.fn()}
        assetTypeId="t1" assetTypeName="Table" />,
    );

    await waitFor(() => expect(selectWith('g-certified')).toBeDefined());
    fireEvent.change(selectWith('g-certified')!, { target: { value: 'g-certified' } });
    await waitFor(() => expect(optionValues(selectWith('intake')!)).toEqual(['intake', 'live']));
    expect(selectWith('intake')!.value).toBe('intake');
    fireEvent.change(screen.getByRole('textbox', { name: /Name/ }), {
      target: { value: 'orders' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Create/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][0]).toBe('/api/assets');
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      status: 'intake', lifecycle_stage_group_id: 'g-certified',
    });
  });

  it('offers the current stage and the allowed moves when editing', async () => {
    renderWithProviders(
      <AssetFormDialog isOpen onOpenChange={vi.fn()} onSuccess={vi.fn()}
        assetTypeId="t1" assetTypeName="Table"
        asset={{ id: 'a1', name: 'orders', status: 'live', asset_type_id: 't1',
          lifecycle_stage_group_id: 'g-certified', relationships: [],
          created_at: '', updated_at: '' } as any} />,
    );

    await waitFor(() => expect(selectWith('retired')).toBeDefined());
    expect(optionValues(selectWith('retired')!)).toEqual(['live', 'retired']);
    // No group picker on an existing asset: its group changes with "Change lifecycle"
    expect(selectWith('g-certified')).toBeUndefined();
  });
});
