/**
 * The contract metadata dialog's status: chosen when creating, read-only when
 * editing (a status change goes through Change Status), and only the stages
 * of the contract's lifecycle stage group (from the API) are offered.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataContractBasicFormDialog from './data-contract-basic-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Stable between renders: the dialog refetches its teams when it changes
const fetchUserProjects = vi.fn();
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null,
    availableProjects: [],
    isLoading: false,
    fetchUserProjects,
  }),
}));

describe('DataContractBasicFormDialog — status', () => {
  const stages = [
    'draft', 'proposed', 'under_review', 'approved', 'active', 'deprecated', 'retired',
  ];
  const labels = [
    'Draft', 'Proposed', 'Under Review', 'Approved', 'Active', 'Deprecated', 'Retired',
  ];
  const defaultGroup = {
    id: 'g-contract', name: 'Default data contract lifecycle', entity_type: 'data_contract',
    is_default_for_type: true, transitions: [],
    stages: stages.map((key, order) => ({
      key, label: labels[order], order, color: null, is_initial: order === 0,
      category: ['draft', 'review', 'review', 'review', 'active', 'deprecated', 'retired'][order],
    })),
  };

  beforeEach(() => {
    global.fetch = vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: () => Promise.resolve(
          url.startsWith('/api/lifecycle-stage-groups') ? [defaultGroup] : [],
        ),
      } as Response),
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

  it('offers the stages of the lifecycle when creating, without certified or archived',
    async () => {
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={vi.fn()} />,
    );

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/api/lifecycle-stage-groups?entity_type=data_contract',
    ));
    const select = screen.getByRole('combobox', { name: /Status/ });
    await waitFor(() => expect(select).toHaveTextContent('Draft'));
    expect(select).not.toBeDisabled();
    fireEvent.click(select);
    const options = screen.getAllByRole('option').map(o => o.textContent);
    expect(options).toEqual(labels);
    // A single group: no group picker
    expect(screen.queryByRole('combobox', { name: 'Lifecycle' })).not.toBeInTheDocument();
  });
});
