/**
 * Editing a product's metadata sends `tags: []` when the user removed every tag
 * (#1435), and leaves `tags` out when the selection wasn't changed, so the
 * loaded tags are never sent back as they are.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataProductCreateDialog from './data-product-create-dialog';
import type { DataProduct } from '@/types/data-product';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));
vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false }),
}));
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: [], loading: false }),
}));
// A stable context value, so the dialog's fetch effect doesn't re-run on every render.
const projectContext = vi.hoisted(() => ({
  currentProject: null,
  availableProjects: [],
  isLoading: false,
  fetchUserProjects: () => {},
}));
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => projectContext,
}));
vi.mock('@/components/ui/tag-selector', () => ({
  default: ({ onChange }: { onChange: (tags: unknown[]) => void }) => (
    <button type="button" onClick={() => onChange([])}>remove all tags</button>
  ),
}));

const product = {
  id: 'prod-1',
  apiVersion: 'v1.0.0',
  kind: 'DataProduct',
  name: 'Existing Product',
  version: '1.0.0',
  status: 'draft',
  inputPorts: [],
  outputPorts: [],
  managementPorts: [],
  support: [],
  authoritativeDefinitions: [],
  customProperties: [],
  tags: [{ tag_id: 't1', fully_qualified_name: 'ns/pii', assigned_value: 'x' }],
} as unknown as DataProduct;

let fetchMock: ReturnType<typeof vi.fn>;

const putBody = () => {
  const call = fetchMock.mock.calls.find(([url, init]) =>
    String(url).startsWith('/api/data-products/') && (init as RequestInit)?.method === 'PUT');
  return call ? JSON.parse((call[1] as RequestInit).body as string) : undefined;
};

describe('DataProductCreateDialog — tags on edit', () => {
  beforeEach(() => {
    fetchMock = vi.fn((url: RequestInfo | URL, init?: RequestInit) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(String(url).includes('/api/workspace/groups')
        ? []
        : { id: 'prod-1', ...(init?.body ? JSON.parse(init.body as string) : {}) }),
    } as Response));
    global.fetch = fetchMock as any;
  });

  const open = () => renderWithProviders(
    <DataProductCreateDialog open={true} onOpenChange={vi.fn()} onSuccess={vi.fn()} product={product} mode="edit" />,
  );

  it('sends an empty list when the last tag is removed', async () => {
    open();
    fireEvent.click(screen.getByText('remove all tags'));
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }));

    await waitFor(() => expect(putBody()).toBeDefined());
    expect(putBody().tags).toEqual([]);
  });

  it('leaves tags out when they were not changed', async () => {
    open();
    fireEvent.change(screen.getByDisplayValue('Existing Product'), { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }));

    await waitFor(() => expect(putBody()).toBeDefined());
    expect(putBody()).not.toHaveProperty('tags');
    expect(putBody().name).toBe('Renamed');
  });
});
