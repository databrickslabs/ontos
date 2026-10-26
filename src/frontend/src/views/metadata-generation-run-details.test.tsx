/**
 * Run detail page: polls the run only while it is in flight (one request at a
 * time), loads suggestions once it completed and groups them by table, and
 * offers cancel while active / delete once finished.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import MetadataGenerationRunDetails from './metadata-generation-run-details';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));
vi.mock('@/stores/breadcrumb-store', () => ({ default: () => () => undefined }));

const run = (status: string) => ({
  run_id: 'run-1', user_id: 'a@x.com', status, selection: [{ type: 'schema', fqn: 'main.sales' }],
  options: { comment_style: 'standard', model: 'm' }, suggestion_count: 2,
  created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z',
  counts: status === 'completed' ? { pending: 2 } : {},
});

const SUGGESTIONS = [
  { id: 's1', run_id: 'run-1', kind: 'description', object_type: 'table', table_fqn: 'main.sales.orders',
    column_name: null, base_text: null, proposed_text: 'Customer orders.', status: 'pending' },
  { id: 's2', run_id: 'run-1', kind: 'description', object_type: 'column', table_fqn: 'main.sales.customers',
    column_name: 'email', base_text: 'Mail', proposed_text: 'Customer email address.', status: 'pending' },
];

function Probe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/metadata-generation/runs/run-1']}>
      <Routes>
        <Route path="/metadata-generation/runs/:runId" element={<MetadataGenerationRunDetails />} />
        <Route path="/metadata-generation" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );

const runCalls = () => api.get.mock.calls.filter(([url]) => url === '/api/metadata-generation/runs/run-1').length;

describe('MetadataGenerationRunDetails', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.delete.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('polls while running, stops once completed, then loads suggestions', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const statuses = ['running', 'ingesting', 'completed'];
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions')
        ? { data: { suggestions: SUGGESTIONS, total: 2 } }
        : { data: run(statuses.shift() ?? 'completed') },
    );
    renderPage();

    expect(await screen.findByText('Cancel run')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(await screen.findByText('main.sales.orders')).toBeInTheDocument();
    expect(runCalls()).toBe(3);

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(runCalls()).toBe(3); // no polling once terminal
  });

  it('groups suggestions under their table and shows current vs proposed', async () => {
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: SUGGESTIONS, total: 2 } } : { data: run('completed') },
    );
    renderPage();

    expect(await screen.findByText('main.sales.orders')).toBeInTheDocument();
    expect(screen.getByText('main.sales.customers')).toBeInTheDocument();
    expect(screen.getByText('Customer orders.')).toBeInTheDocument();
    expect(screen.getByText('Mail')).toBeInTheDocument();
    expect(screen.getByText('Customer email address.')).toBeInTheDocument();
    expect(screen.queryByText('Cancel run')).not.toBeInTheDocument();
  });

  it('pages through all suggestions of a large run', async () => {
    const make = (n: number) => ({ ...SUGGESTIONS[0], id: `s${n}`, table_fqn: `main.sales.t${n}` });
    api.get.mockImplementation(async (url: string) => {
      if (!url.includes('/suggestions')) return { data: run('completed') };
      const skip = Number(new URL(url, 'http://x').searchParams.get('skip'));
      const page = skip === 0 ? Array.from({ length: 1000 }, (_, i) => make(i)) : [make(1000)];
      return { data: { suggestions: page, total: 1001 } };
    });
    renderPage();

    expect(await screen.findByText('main.sales.t1000')).toBeInTheDocument();
    const pages = api.get.mock.calls.map(([url]) => url).filter((url) => url.includes('/suggestions'));
    expect(pages).toEqual([
      '/api/metadata-generation/runs/run-1/suggestions?limit=1000&skip=0',
      '/api/metadata-generation/runs/run-1/suggestions?limit=1000&skip=1000',
    ]);
  });

  it('shows an error instead of a partial list when a later page fails', async () => {
    api.get.mockImplementation(async (url: string) => {
      if (!url.includes('/suggestions')) return { data: run('completed') };
      return url.includes('skip=0')
        ? { data: { suggestions: [SUGGESTIONS[0]], total: 2 } }
        : { data: {}, error: 'Gateway timeout' };
    });
    renderPage();

    expect(await screen.findByText(/Failed to load the suggestions: Gateway timeout/)).toBeInTheDocument();
    expect(screen.queryByText('main.sales.orders')).not.toBeInTheDocument();
  });

  it('filters suggestions by status', async () => {
    // Radix Select needs pointer capture, which jsdom lacks
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => undefined;
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: SUGGESTIONS, total: 2 } } : { data: run('completed') },
    );
    renderPage();

    await userEvent.click(await screen.findByRole('combobox', { name: 'Filter by status' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Rejected' }));

    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/suggestions?limit=1000&skip=0&status=rejected'),
    );
  });

  it('deletes a finished run and returns to the list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: [], total: 0 } } : { data: run('failed') },
    );
    api.delete.mockResolvedValue({ data: null });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: /Delete run/ }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1'));
    expect(await screen.findByTestId('location')).toHaveTextContent('/metadata-generation');
  });
});

describe('MetadataGenerationRunDetails review', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  const reviewed = (unsubmitted: number, reviews: string[]) => ({
    ...run('completed'), unsubmitted, review_request_ids: reviews,
  });

  it('submits the pending suggestions for review and links the review', async () => {
    let state = reviewed(2, []);
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: SUGGESTIONS, total: 2 } } : { data: state },
    );
    api.post.mockImplementation(async () => {
      state = reviewed(0, ['rev-1']);
      return { data: { run_id: 'run-1', review_request_id: 'rev-1', reviewer_email: 'r@x.com', suggestion_count: 2 } };
    });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: /Submit 2 for review/ }));
    await userEvent.type(screen.getByLabelText('Notes for the reviewer'), 'please check');
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/review', {
        reviewer_email: null, notes: 'please check',
      }),
    );
    expect(await screen.findByRole('link', { name: /Review 1/ })).toHaveAttribute('href', '/data-asset-reviews/rev-1');
    expect(screen.queryByRole('button', { name: /for review/ })).not.toBeInTheDocument();
  });

  it('shows the error of a failed submit in the dialog', async () => {
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: SUGGESTIONS, total: 2 } } : { data: reviewed(2, []) },
    );
    api.post.mockResolvedValue({ error: 'No Data Steward found to review the run; pick a reviewer' });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: /Submit 2 for review/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/pick a reviewer/)).toBeInTheDocument();
  });

  it("shows the reviewer's edit and comment on a suggestion", async () => {
    const decided = [{ ...SUGGESTIONS[0], status: 'accepted', edited_text: 'Orders placed by customers.',
      review_comment: 'shorter', decided_by: 'r@x.com', review_request_id: 'rev-1' }];
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions: decided, total: 1 } } : { data: reviewed(0, ['rev-1']) },
    );
    renderPage();

    expect(await screen.findByText('Orders placed by customers.')).toBeInTheDocument();
    expect(screen.getByText('Edited by reviewer')).toBeInTheDocument();
    expect(screen.getByText('r@x.com: shorter')).toBeInTheDocument();
  });
});

describe('MetadataGenerationRunDetails apply', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const applied = { ...SUGGESTIONS[0], status: 'applied', applied_by: 'r@x.com', applied_at: '2026-10-26T10:00:00Z' };
  const conflict = { ...SUGGESTIONS[1], status: 'conflict', error: 'The description in Unity Catalog changed since it was generated' };

  it('applies the approved suggestions and shows the outcome per suggestion', async () => {
    let state: Record<string, unknown> = { ...run('completed'), counts: { accepted: 2 }, applicable: 2 };
    let suggestions: Record<string, unknown>[] = SUGGESTIONS.map((s) => ({ ...s, status: 'accepted' }));
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions') ? { data: { suggestions, total: 2 } } : { data: state },
    );
    api.post.mockImplementation(async () => {
      state = { ...run('completed'), counts: { applied: 1, conflict: 1 }, applicable: 0 };
      suggestions = [applied, conflict];
      return { data: { applied: 1, conflict: 1, not_applicable: 0, failed: 0, errors: [] } };
    });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: /Apply 2 approved/ }));

    expect(api.post).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/apply', { force: false });
    expect(await screen.findByText(/Applied by r@x.com/)).toBeInTheDocument();
    expect(screen.getByText(/changed since it was generated/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approved/ })).not.toBeInTheDocument();
  });

  it('lets admins force-apply conflicts after confirming', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.get.mockImplementation(async (url: string) =>
      url.includes('/suggestions')
        ? { data: { suggestions: [conflict], total: 1 } }
        : { data: { ...run('completed'), counts: { conflict: 1 }, applicable: 0 } },
    );
    api.post.mockResolvedValue({ data: { applied: 1, conflict: 0, not_applicable: 0, failed: 0, errors: [] } });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Force-apply 1 conflict' }));

    expect(window.confirm).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/apply', { force: true });
  });
});
