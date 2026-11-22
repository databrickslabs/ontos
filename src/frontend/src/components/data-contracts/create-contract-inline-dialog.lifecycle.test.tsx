/**
 * The inline "new contract" dialog follows the Lifecycle Stage Groups (#1215):
 * a group picker when there are several, the picked group's stages as the
 * status options, its first stage preselected, and the group in the POST.
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import CreateContractInlineDialog from './create-contract-inline-dialog';

const mockGet = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet }) }));
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
    id: 'g-default', name: 'Default data contract lifecycle', entity_type: 'data_contract',
    is_default_for_type: true, transitions: [],
    stages: [st('draft', 'Draft', 'draft', 0), st('active', 'Active', 'active', 1)],
  },
  {
    id: 'g-live', name: 'Certified feeds', entity_type: 'data_contract',
    is_default_for_type: false, transitions: [],
    stages: [st('intake', 'Intake', 'draft', 0), st('live', 'Live', 'active', 1)],
  },
];

const selectWith = (value: string) => screen.getAllByRole('combobox').find(
  (select) => select.querySelector(`option[value="${value}"]`),
) as HTMLSelectElement | undefined;

describe('CreateContractInlineDialog lifecycle', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation(async (url: string) =>
      url.startsWith('/api/lifecycle-stage-groups') ? { data: GROUPS } : { data: [] });
    fetchMock = vi.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ id: 'c-new' }),
    }));
    global.fetch = fetchMock as any;
  });

  it('creates the contract in the picked group, in its first stage', async () => {
    const onSuccess = vi.fn();
    renderWithProviders(
      <CreateContractInlineDialog isOpen onOpenChange={vi.fn()} onSuccess={onSuccess} />,
    );

    await waitFor(() => expect(selectWith('draft')?.value).toBe('draft'));
    fireEvent.change(selectWith('g-live')!, { target: { value: 'g-live' } });
    await waitFor(() => expect(selectWith('intake')?.value).toBe('intake'));
    expect(Array.from(selectWith('intake')!.options).map((o) => o.value).filter(Boolean))
      .toEqual(['intake', 'live']);
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Feed' } });
    fireEvent.click(screen.getByRole('button', { name: /Create/ }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('c-new'));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      name: 'Feed', status: 'intake', lifecycle_stage_group_id: 'g-live',
    });
  });
});
