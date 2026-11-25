/**
 * The contract metadata dialog sets the ODCS apiVersion of a new contract only:
 * editing a v3.0.x contract must not move it to v3.1.0 (the backend reads the
 * field by name).
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataContractBasicFormDialog from './data-contract-basic-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// One stable context: a new fetchUserProjects per render re-runs the dialog's fetch effect forever
const projectContext = {
  currentProject: null,
  availableProjects: [],
  isLoading: false,
  fetchUserProjects: () => Promise.resolve(),
};
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => projectContext,
}));

// A stable object: the dialog resets its form whenever `initial` changes
const EDITED = { name: 'Orders', version: '1.0.0', status: 'active' };

describe('DataContractBasicFormDialog — apiVersion', () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ) as any;
  });

  it('sends no apiVersion when editing', async () => {
    const onSubmit = vi.fn((_payload: unknown) => Promise.resolve());
    renderWithProviders(
      <DataContractBasicFormDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        initial={EDITED}
      />,
    );

    fireEvent.click(screen.getByText('Save Changes'));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('apiVersion');
  });

  it('sets v3.1.0 on a new contract', async () => {
    const onSubmit = vi.fn((_payload: unknown) => Promise.resolve());
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} />,
    );

    fireEvent.change(document.getElementById('name') as HTMLInputElement, {
      target: { value: 'Orders' },
    });
    fireEvent.click(screen.getByText('Create Contract'));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ apiVersion: 'v3.1.0' });
  });
});
