/**
 * The run details page shows a failed run's error from its code, never a stored
 * error text, and pages the results the backend sends one page at a time.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get, post: vi.fn(), delete: vi.fn() }) }));

import i18n from '@/i18n/config';
import ComplianceRunDetails from './compliance-run-details';

const RUN = {
  id: 'run-1', policy_id: 'p-1', status: 'succeeded', started_at: '2026-11-22T10:00:00Z',
  success_count: 2, failure_count: 1, score: 66.67,
  coverage: { evaluated: 3, not_evaluated: 0 },
};

function result(id: string) {
  return {
    id, run_id: 'run-1', object_type: 'data_product', object_id: id, object_name: `product-${id}`,
    passed: false, message: null, details_json: null, created_at: '2026-11-22T10:00:00Z',
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/compliance/runs/run-1']}>
      <Routes>
        <Route path="/compliance/runs/:runId" element={<ComplianceRunDetails />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ComplianceRunDetails', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    get.mockReset();
  });

  it('shows the generic run error for a failed run without a translated code', async () => {
    get.mockResolvedValue({
      data: {
        run: {
          ...RUN, status: 'failed', score: null, error_code: 'run_failed', error_params: null,
        },
        results: [], total: 0, hidden_count: 0,
      },
    });
    await i18n.changeLanguage('pt');
    renderPage();

    expect(
      await screen.findByText(/A execução falhou. Os detalhes estão no log do app./),
    ).toBeInTheDocument();
  });

  it('loads the next page of results after the ones it shows', async () => {
    get.mockImplementation(async (url: string) => {
      const second = url.includes('offset=1');
      return {
        data: {
          run: RUN, results: [result(second ? 'b' : 'a')], total: 2, hidden_count: 0,
        },
      };
    });
    renderPage();

    expect(await screen.findByText('product-a')).toBeInTheDocument();
    expect(screen.getByTestId('results-paging')).toHaveTextContent('Showing 1 of 2 results.');

    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('product-b')).toBeInTheDocument();
    expect(get).toHaveBeenLastCalledWith(
      '/api/compliance/runs/run-1/results?only_failed=true&offset=1',
    );
    await waitFor(() => expect(screen.queryByTestId('results-paging')).toBeNull());
  });
});
