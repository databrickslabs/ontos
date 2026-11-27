/**
 * Creating a contract sends the tags picked in the dialog (#1484): the backend
 * assigns them, so they must be in the create payload.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataContractBasicFormDialog from './data-contract-basic-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// A stable function: a new one per render re-runs the dialog's fetch effect.
const fetchUserProjects = vi.fn();
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null,
    availableProjects: [],
    isLoading: false,
    fetchUserProjects,
  }),
}));

// Drive the picker directly: one button adds two tags.
vi.mock('@/components/ui/tag-selector', () => ({
  default: ({ onChange }: { onChange: (tags: unknown[]) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange([
          { tag_id: 't1', fully_qualified_name: 'default/pii', assigned_value: null },
          'default/finance',
        ])
      }
    >
      pick tags
    </button>
  ),
}));

describe('DataContractBasicFormDialog — tags on create', () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ) as any;
  });

  it('sends the picked tags in the create payload', async () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} />,
    );

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Orders' } });
    fireEvent.click(screen.getByText('pick tags'));
    fireEvent.click(screen.getByRole('button', { name: /Create Contract/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = (onSubmit.mock.calls[0] as unknown[])[0] as { tags?: unknown[] };
    expect(payload.tags).toEqual(['default/pii', 'default/finance']);
  });

  it('sends no tags when none were picked', async () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} />,
    );

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Orders' } });
    fireEvent.click(screen.getByRole('button', { name: /Create Contract/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = (onSubmit.mock.calls[0] as unknown[])[0] as { tags?: unknown[] };
    expect(payload.tags ?? []).toEqual([]);
  });
});
