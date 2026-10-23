/**
 * The contract metadata dialog's status: chosen when creating, read-only when
 * editing (a status change goes through Change Status), and only lifecycle
 * statuses are offered.
 */
import { screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataContractBasicFormDialog from './data-contract-basic-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null,
    availableProjects: [],
    isLoading: false,
    fetchUserProjects: vi.fn(),
  }),
}));

describe('DataContractBasicFormDialog — status', () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ) as any;
  });

  it('keeps the status read-only when editing, pointing to Change Status', () => {
    renderWithProviders(
      <DataContractBasicFormDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        initial={{ name: 'Orders', version: '1.0.0', status: 'active' }}
      />,
    );

    expect(screen.getByRole('combobox', { name: /Status/ })).toBeDisabled();
    expect(screen.getByText(/The status changes with Change Status on the page/)).toBeInTheDocument();
  });

  it('offers the lifecycle statuses when creating, without certified or archived', () => {
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={vi.fn()} />,
    );

    const select = screen.getByRole('combobox', { name: /Status/ });
    expect(select).not.toBeDisabled();
    fireEvent.click(select);
    const options = screen.getAllByRole('option').map(o => o.textContent);
    expect(options).toEqual(['Draft', 'Proposed', 'Under Review', 'Approved', 'Active', 'Deprecated', 'Retired']);
  });
});
