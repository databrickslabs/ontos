/**
 * New run dialog: what the user picks is what the backend gets. Views go out
 * as `table` selections (the API's selection types are catalog/schema/table),
 * schemas load their tables and views lazily, and API errors are shown inline.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NewRunDialog from './new-run-dialog';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));

vi.mock('@/components/ui/tree-view', () => ({
  TreeView: ({ data, onSelectChange }: { data: any[]; onSelectChange: (i: { id: string }) => void }) => {
    const flat = (items: any[]): any[] => items.flatMap((i) => [i, ...flat(i.children || [])]);
    return (
      <div>
        {flat(data).map((item) => (
          <div key={item.id}>
            <button type="button" onClick={() => onSelectChange({ id: item.id })}>
              {item.id}
            </button>
            {item.hasChildren && (
              <button type="button" onClick={item.onExpand}>
                expand {item.id}
              </button>
            )}
          </div>
        ))}
      </div>
    );
  },
}));

const CHILDREN: Record<string, unknown[]> = {
  '/api/catalogs': [{ id: 'main', name: 'main', type: 'catalog' }],
  '/api/catalogs/main/schemas': [{ id: 'main.sales', name: 'sales', type: 'schema' }],
  '/api/catalogs/main/schemas/sales/tables': [{ id: 'main.sales.orders', name: 'orders', type: 'table' }],
  '/api/catalogs/main/schemas/sales/views': [{ id: 'main.sales.revenue', name: 'revenue', type: 'view' }],
};

const renderDialog = (onStarted = vi.fn()) => {
  render(<NewRunDialog isOpen onOpenChange={vi.fn()} onStarted={onStarted} />);
  return onStarted;
};

describe('NewRunDialog', () => {
  beforeEach(() => {
    api.get.mockReset().mockImplementation(async (url: string) => ({ data: CHILDREN[url] ?? [] }));
    api.post.mockReset();
  });

  it('loads schemas and tables lazily and posts views as table selections', async () => {
    api.post.mockResolvedValue({ data: { run_id: 'run-1', status: 'running' } });
    const onStarted = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'expand main' }));
    await userEvent.click(await screen.findByRole('button', { name: 'expand main.sales' }));
    await userEvent.click(await screen.findByRole('button', { name: 'main.sales.revenue' }));
    await userEvent.click(screen.getByRole('button', { name: 'main.sales' }));
    await userEvent.click(screen.getByRole('button', { name: 'Start run' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.get).toHaveBeenCalledWith('/api/catalogs/main/schemas/sales/views');
    expect(api.post).toHaveBeenCalledWith('/api/metadata-generation/runs', {
      selection: [
        { type: 'table', fqn: 'main.sales.revenue' },
        { type: 'schema', fqn: 'main.sales' },
      ],
      comment_style: 'standard',
      model: null,
      regenerate_existing: false,
      auto_submit: false,
      reviewer_email: null,
    });
    expect(onStarted).toHaveBeenCalledWith('run-1');
  });

  it('asks to auto-submit with the picked reviewer', async () => {
    api.post.mockResolvedValue({ data: { run_id: 'run-1', status: 'running' } });
    renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'main' }));
    expect(screen.queryByLabelText('Reviewer')).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('Submit for review when done'));
    await userEvent.type(screen.getByLabelText('Reviewer'), 'steward@x.com{enter}');
    await userEvent.click(screen.getByRole('button', { name: 'Start run' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ auto_submit: true, reviewer_email: 'steward@x.com' });
  });

  it('toggles a selection off again', async () => {
    renderDialog();
    const main = await screen.findByRole('button', { name: 'main' });
    await userEvent.click(main);
    expect(screen.getByRole('button', { name: 'Start run' })).toBeEnabled();
    await userEvent.click(main);
    expect(screen.getByRole('button', { name: 'Start run' })).toBeDisabled();
  });

  it('shows the API error and does not report a start', async () => {
    api.post.mockResolvedValue({ data: {}, error: 'The Metadata Generation background job is not enabled.' });
    const onStarted = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'main' }));
    await userEvent.click(screen.getByRole('button', { name: 'Start run' }));

    expect(await screen.findByText('The Metadata Generation background job is not enabled.')).toBeInTheDocument();
    expect(onStarted).not.toHaveBeenCalled();
  });
});
