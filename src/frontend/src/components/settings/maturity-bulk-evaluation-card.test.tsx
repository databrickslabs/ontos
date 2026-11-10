import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';

const getMock = vi.fn();
const postMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: postMock, put: vi.fn(), delete: vi.fn() }),
}));

import MaturityBulkEvaluationCard from './maturity-bulk-evaluation-card';

const completedRun = {
  id: 'run-1', state: 'completed',
  scope: { catalog: 'main', schema: 'sales', asset_types: ['Table', 'View'] },
  started_by: 'admin@example.com', started_at: '2026-11-10T20:00:00Z',
  finished_at: '2026-11-10T20:01:00Z', total: 5, processed: 5, evaluated: 2, changed: 1,
  skipped: { maturity_bulk_skipped_not_found: 2, maturity_bulk_skipped_no_levels: 0 },
  error_count: 1,
  errors: [{ asset_id: 'a-9', code: 'maturity_bulk_evaluation_failed', params: {} }],
};

const assetLevel = { id: 'l2', name: 'Prerequisite', entity_type: 'Asset', level_order: 1 };

/** The card reads the levels and the latest run; each answers from the given values. */
function answers({ levels = [assetLevel], run = null }: { levels?: unknown; run?: unknown }) {
  getMock.mockImplementation(async (url: string) =>
    url === '/api/maturity-levels' ? { data: levels } : { data: run },
  );
}

describe('MaturityBulkEvaluationCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('disables the trigger and explains why when there are no Asset levels', async () => {
    answers({ levels: [{ id: 'p', name: 'Accessible', entity_type: 'all', level_order: 1 }] });
    render(<MaturityBulkEvaluationCard />);

    expect(await screen.findByText('maturityBulkEvaluation.noAssetLevels')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'maturityBulkEvaluation.start' })).toBeDisabled();
    expect(await screen.findByText('maturityBulkEvaluation.none')).toBeInTheDocument();
  });

  it('shows the last run with its counts, skip reasons and error codes', async () => {
    answers({ run: completedRun });
    render(<MaturityBulkEvaluationCard />);

    const summary = await screen.findByTestId('maturity-bulk-summary');
    expect(summary).toHaveTextContent('maturityBulkEvaluation.summary');
    expect(summary).toHaveTextContent(
      'maturityBulkEvaluation.codes.maturity_bulk_skipped_not_found: 2',
    );
    expect(summary).toHaveTextContent(
      'maturityBulkEvaluation.codes.maturity_bulk_evaluation_failed',
    );
    expect(getMock).toHaveBeenCalledWith('/api/maturity-evaluations/assets/latest');
    await waitFor(() => expect(screen.getByRole('button', { name: 'maturityBulkEvaluation.start' }))
      .toBeEnabled());
  });

  it('starts a run for the typed scope and shows it as running', async () => {
    answers({});
    postMock.mockResolvedValue({
      data: { ...completedRun, state: 'running', processed: 0, total: 0 },
    });
    render(<MaturityBulkEvaluationCard />);

    fireEvent.change(screen.getByLabelText('maturityBulkEvaluation.catalog'), {
      target: { value: ' main ' },
    });
    fireEvent.change(screen.getByLabelText('maturityBulkEvaluation.schema'), {
      target: { value: 'sales' },
    });
    const start = await screen.findByRole('button', { name: 'maturityBulkEvaluation.start' });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/api/maturity-evaluations/assets', { catalog: 'main', schema_name: 'sales' },
    ));
    expect(await screen.findByRole('status')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'maturityBulkEvaluation.start' })).toBeDisabled();
  });

  it('shows a coded refusal, such as a run already in progress', async () => {
    answers({});
    postMock.mockResolvedValue({
      data: {}, error: 'A bulk maturity evaluation is already running.',
      errorCode: 'maturity_bulk_run_in_progress',
    });
    render(<MaturityBulkEvaluationCard />);

    const start = await screen.findByRole('button', { name: 'maturityBulkEvaluation.start' });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    expect(await screen.findByText(
      'maturityBulkEvaluation.codes.maturity_bulk_run_in_progress',
    )).toBeInTheDocument();
  });

  it('ignores a latest-run answer that is not a run', async () => {
    answers({ run: [] });
    render(<MaturityBulkEvaluationCard />);

    expect(await screen.findByText('maturityBulkEvaluation.none')).toBeInTheDocument();
    expect(screen.queryByTestId('maturity-bulk-summary')).not.toBeInTheDocument();
  });

  it('polls the run while it runs and stops once it has finished', async () => {
    vi.useFakeTimers();
    try {
      let current: unknown = { ...completedRun, state: 'running', processed: 1, total: 4 };
      getMock.mockImplementation(async (url: string) =>
        url === '/api/maturity-levels' ? { data: [assetLevel] } : { data: current });
      render(<MaturityBulkEvaluationCard />);
      const latestCalls = () => getMock.mock.calls.filter(
        ([url]) => url === '/api/maturity-evaluations/assets/latest',
      ).length;
      await act(async () => {});
      const initial = latestCalls();

      await act(async () => { vi.advanceTimersByTime(2000); });
      expect(latestCalls()).toBe(initial + 1);

      current = completedRun;
      await act(async () => { vi.advanceTimersByTime(2000); });
      const finished = latestCalls();
      await act(async () => { vi.advanceTimersByTime(10000); });
      expect(latestCalls()).toBe(finished);
    } finally {
      vi.useRealTimers();
    }
  });
});
