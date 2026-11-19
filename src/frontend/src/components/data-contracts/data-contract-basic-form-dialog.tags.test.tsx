/**
 * The contract metadata dialog sends `tags: []` when the user removed every tag
 * (#1435), and leaves `tags` out when the selection wasn't changed.
 */
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

// The real picker needs the tag catalog; the tests only need to change the selection.
vi.mock('@/components/ui/tag-selector', () => ({
  default: ({ onChange }: { onChange: (tags: unknown[]) => void }) => (
    <div>
      <button type="button" onClick={() => onChange([])}>remove all tags</button>
      <button type="button" onClick={() => onChange(['ns/other'])}>pick other tag</button>
    </div>
  ),
}));

const initial = {
  name: 'Orders',
  version: '1.0.0',
  status: 'draft',
  tags: [{ tag_id: 't1', fully_qualified_name: 'ns/pii', assigned_value: 'x' }],
};

describe('DataContractBasicFormDialog — tags', () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ) as any;
  });

  const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

  it('sends an empty list when the last tag is removed', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} initial={initial as any} />,
    );

    fireEvent.click(screen.getByText('remove all tags'));
    save();

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0].tags).toEqual([]);
  });

  it('leaves tags out when only another field changed', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} initial={initial as any} />,
    );

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Orders v2' } });
    save();

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0].tags).toBeUndefined();
  });

  it('sends the new selection when a tag is swapped', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DataContractBasicFormDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={onSubmit} initial={initial as any} />,
    );

    fireEvent.click(screen.getByText('pick other tag'));
    save();

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0].tags).toEqual(['ns/other']);
  });

  it('leaves the domain assignment out when it was not changed', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DataContractBasicFormDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        initial={{ ...initial, domainIds: ['d1', 'd2'], primaryDomainId: 'd1' } as any}
      />,
    );

    fireEvent.click(screen.getByText('pick other tag'));
    save();

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('domainIds');
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('primaryDomainId');
  });
});
