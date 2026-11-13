/**
 * The run details list the reasons of the failed LLM_CHECKs of a failed result (#1479).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import ComplianceRunDetails from './compliance-run-details';

const RUN = {
  id: 'run-1', policy_id: 'p-1', status: 'succeeded', started_at: '2026-11-12T00:00:00Z',
  success_count: 1, failure_count: 1, score: 50,
};

function result(id: string, name: string, passed: boolean, checks: unknown[]) {
  return {
    id, run_id: 'run-1', object_type: 'domain', object_id: id, object_name: name, passed,
    message: passed ? null : `Assertion failed for domain ${name}`,
    details_json: JSON.stringify({ llm_checks: checks }), created_at: '2026-11-12T00:00:00Z',
  };
}

function renderRun() {
  return render(
    <MemoryRouter initialEntries={['/compliance/runs/run-1']}>
      <Routes>
        <Route path="/compliance/runs/:runId" element={<ComplianceRunDetails />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ComplianceRunDetails LLM check reasons', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({
      data: {
        run: RUN,
        results: [
          result('d1', 'misc', false, [
            { criterion: 'states the grain', passed: false, reason: 'no grain', code: null },
            {
              criterion: 'names the owner', passed: false, reason: '',
              code: 'llm_check_budget_exceeded',
            },
            { criterion: 'is in English', passed: true, reason: 'English text', code: null },
          ]),
          result('d2', 'orders', true, [
            { criterion: 'states the grain', passed: true, reason: 'daily grain', code: null },
          ]),
        ],
      },
    });
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('lists the failed checks of a failed result, with reasons and translated codes', async () => {
    renderRun();

    const reasons = await screen.findAllByTestId('llm-check-reasons');
    expect(reasons).toHaveLength(1);
    const items = within(reasons[0]).getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual([
      "LLM_CHECK 'states the grain': no grain",
      "LLM_CHECK 'names the owner': Not checked: the run reached its budget of model calls.",
    ]);
    expect(screen.queryByText(/daily grain/)).not.toBeInTheDocument();
  });

  it('translates the code into the user language', async () => {
    await i18n.changeLanguage('es');
    renderRun();

    const [reasons] = await screen.findAllByTestId('llm-check-reasons');
    expect(reasons).toHaveTextContent(
      'No comprobado: la ejecución alcanzó su presupuesto de llamadas al modelo.',
    );
  });
});
