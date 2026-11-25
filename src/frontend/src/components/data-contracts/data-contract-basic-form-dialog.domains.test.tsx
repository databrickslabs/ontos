/** The contract metadata dialog sends the domains the user picked, on edit and on create. */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataContractBasicFormDialog from './data-contract-basic-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// A stable context value: a new fetchUserProjects on every render would re-run the
// dialog's fetch effect after each render.
const projectContext = vi.hoisted(() => ({
  currentProject: null,
  availableProjects: [],
  isLoading: false,
  fetchUserProjects: () => {},
}));
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => projectContext,
}));

// Stand-in: one button that picks domains d1 and d3 (primary d3).
vi.mock('@/components/ui/domain-multi-selector', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/components/ui/domain-multi-selector')>()),
  default: ({ onChange }: any) => (
    <button type="button" onClick={() => onChange(['d1', 'd3'], 'd3')}>pick domains</button>
  ),
}));

describe('DataContractBasicFormDialog — domains', () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ) as any;
  });

  it('sends the changed domains on edit', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(
      <DataContractBasicFormDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        initial={{
          name: 'Orders', version: '1.0.0', status: 'draft', tags: [],
          domainIds: ['d1', 'd2'], primaryDomainId: 'd1',
        }}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /pick domains/i }))
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0].domainIds).toEqual(['d1', 'd3'])
    expect(onSubmit.mock.calls[0][0].primaryDomainId).toBe('d3')
  })

  it('sends the domains on create', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} />,
    )

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'New contract' } })
    fireEvent.click(await screen.findByRole('button', { name: /pick domains/i }))
    fireEvent.click(screen.getByRole('button', { name: /Create Contract/ }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0].domainIds).toEqual(['d1', 'd3'])
  })
});
