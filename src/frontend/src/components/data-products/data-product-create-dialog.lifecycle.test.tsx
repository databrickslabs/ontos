/**
 * The product create dialog follows the product's Lifecycle Stage Group
 * (#1215): with several groups it offers a picker, the status picker lists
 * the picked group's stages and starts in its first one, and the POST names
 * the group (`lifecycleStageGroupId`, as the product route reads it).
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataProductCreateDialog from './data-product-create-dialog';

const mockGet = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-domains', () => ({ useDomains: () => ({ domains: [], loading: false }) }));
vi.mock('@/hooks/use-teams', () => ({ useTeams: () => ({ teams: [], loading: false }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet }) }));
vi.mock('./consumer-groups-picker', () => ({ ConsumerGroupsPicker: () => null }));
const fetchUserProjects = vi.fn();
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null, availableProjects: [], isLoading: false, fetchUserProjects,
  }),
}));
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
    id: 'g-default', name: 'Default data product lifecycle', entity_type: 'data_product',
    is_default_for_type: true, transitions: [],
    stages: [st('draft', 'Draft', 'draft', 0), st('active', 'Active', 'active', 1)],
  },
  {
    id: 'g-loop', name: 'Authority resolution', entity_type: 'data_product',
    is_default_for_type: false, transitions: [],
    stages: [st('ideation', 'Ideation', 'draft', 0), st('needs_review', 'Needs Review',
      'review', 1)],
  },
];

const selectWith = (value: string) => screen.getAllByRole('combobox').find(
  (select) => select.querySelector(`option[value="${value}"]`),
) as HTMLSelectElement | undefined;

describe('DataProductCreateDialog lifecycle', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation(async (url: string) =>
      url.startsWith('/api/lifecycle-stage-groups') ? { data: GROUPS } : { data: [] });
    fetchMock = vi.fn((_url: string, init?: RequestInit) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ id: 'new', ...(init?.body ? JSON.parse(init.body as string)
        : {}) }),
    }));
    global.fetch = fetchMock as any;
  });

  it('creates the product in the picked group, starting in its first stage', async () => {
    renderWithProviders(
      <DataProductCreateDialog open onOpenChange={vi.fn()} onSuccess={vi.fn()} />,
    );

    await waitFor(() => expect(selectWith('g-loop')).toBeDefined());
    fireEvent.change(selectWith('g-loop')!, { target: { value: 'g-loop' } });
    await waitFor(() => expect(selectWith('ideation')?.value).toBe('ideation'));
    expect(Array.from(selectWith('ideation')!.options).map((o) => o.value).filter(Boolean))
      .toEqual(['ideation', 'needs_review']);
    fireEvent.change(screen.getByLabelText(/Product Name/), { target: { value: 'Orders' } });
    fireEvent.click(screen.getByRole('button', { name: /Create Product/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/data-products', expect.objectContaining({ method: 'POST' }),
    ));
    const post = fetchMock.mock.calls.find(([url]) => url === '/api/data-products')!;
    expect(JSON.parse(post[1].body)).toMatchObject({
      name: 'Orders', status: 'ideation', lifecycleStageGroupId: 'g-loop',
    });
  });
});
