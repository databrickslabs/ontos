/**
 * The maturity panel on a table asset: current and next level, and each gate of the
 * next level with pass or fail and why, in the UI language.
 */
import { screen, within } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { MaturityPanel } from './maturity-panel';
import type { MaturityReport } from '@/types/maturity';

const gate = (id: string, name: string, passed: boolean, extra: object = {}) => ({
  gate_id: id, policy_id: `p-${id}`, policy_name: name, required: true, passed,
  message: passed ? null : `Assertion failed: ${id}`, ...extra,
});

const REPORT: MaturityReport = {
  entity_type: 'Asset',
  entity_id: 'a-1',
  entity_name: 'pedidos_diarios',
  achieved_level_order: null,
  achieved_level_name: null,
  total_levels: 4,
  gates_passed: 1,
  gates_total: 3,
  levels: [{
    level_order: 1,
    level_name: 'Pré-requisito',
    level_icon: 'lock-keyhole',
    level_color: 'blue',
    achieved: false,
    gates: [
      gate('g-1', 'Dono definido', true),
      gate('g-2', 'Domínio definido', false, { failure_message: 'Falta: domínio definido' }),
      gate('g-3', 'Colunas descritas', false, {
        message_code: 'maturity_uc_table_not_found',
        message_params: { tableName: 'ifood_demo.logistica.pedidos_diarios' },
        failure_message: 'Falta: colunas descritas',
      }),
    ],
  }],
  evaluated_at: '2026-11-12T10:00:00Z',
  evaluated_by: null,
  notices: [],
};

async function renderPanel(lng: string, report: MaturityReport = REPORT) {
  await i18n.changeLanguage(lng);
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
    ok: true,
    json: async () => (url.includes('/history') ? [] : report),
  }));
  vi.stubGlobal('fetch', fetchMock);
  renderWithProviders(<MaturityPanel entityType="Asset" entityId="a-1" />);
  await screen.findByTestId('maturity-panel');
  return fetchMock;
}

describe('MaturityPanel on a table asset', () => {
  afterEach(async () => {
    vi.unstubAllGlobals();
    await i18n.changeLanguage('en');
  });

  it('reads the asset maturity endpoints', async () => {
    const fetchMock = await renderPanel('en');
    expect(fetchMock).toHaveBeenCalledWith('/api/assets/a-1/maturity', { method: 'GET' });
    expect(fetchMock).toHaveBeenCalledWith('/api/assets/a-1/maturity/history?limit=10');
  });

  it('shows the current and the next level in Portuguese', async () => {
    await renderPanel('pt');

    const summary = screen.getByTestId('maturity-summary');
    expect(within(summary).getByText('Nível atual')).toBeInTheDocument();
    expect(within(summary).getByText('Abaixo do primeiro nível')).toBeInTheDocument();
    expect(within(summary).getByText('Próximo nível')).toBeInTheDocument();
    expect(within(summary).getByText('Pré-requisito')).toBeInTheDocument();
    expect(screen.queryByText('Not assessed')).not.toBeInTheDocument();
  });

  it('lists each gate of the next level with pass or fail and the reason', async () => {
    await renderPanel('pt');

    const rows = screen.getAllByTestId('maturity-gate');
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['pass', 'fail', 'fail']);

    expect(within(rows[0]).getByText('Dono definido')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Aprovado')).toBeInTheDocument();
    expect(within(rows[0]).queryByText(/Falta/)).not.toBeInTheDocument();

    expect(within(rows[1]).getByText('Reprovado')).toBeInTheDocument();
    // The policy's failure text, not the rule's technical message
    expect(within(rows[1]).getByText('Falta: domínio definido')).toBeInTheDocument();
    expect(within(rows[1]).queryByText('Assertion failed: g-2')).not.toBeInTheDocument();

    // A coded reason wins over the policy text
    expect(within(rows[2]).getByText(
      'A tabela ifood_demo.logistica.pedidos_diarios não foi encontrada no Unity Catalog, '
      + 'então faltam os campos dela.',
    )).toBeInTheDocument();
  });

  it('falls back to the rule message when the policy has no failure text', async () => {
    const levels = [{
      ...REPORT.levels[0],
      gates: [gate('g-9', 'Certificada', false)],
    }];
    await renderPanel('en', { ...REPORT, levels });

    expect(screen.getByText('Assertion failed: g-9')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    // In the header badge and in the summary
    expect(screen.getAllByText('Below the first level')).toHaveLength(2);
  });

  it('says the highest level is reached and keeps the levels closed', async () => {
    const levels = [{ ...REPORT.levels[0], achieved: true,
      gates: [gate('g-1', 'Dono definido', true)] }];
    await renderPanel('pt', {
      ...REPORT, levels, total_levels: 1,
      achieved_level_order: 1, achieved_level_name: 'Pré-requisito',
    });

    expect(screen.getByText('Nível mais alto alcançado')).toBeInTheDocument();
    expect(screen.queryAllByTestId('maturity-gate')).toHaveLength(0);
  });

  it('translates the badge when no level is defined', async () => {
    await renderPanel('pt', { ...REPORT, levels: [], total_levels: 0, gates_total: 0 });

    expect(screen.getAllByText('Não avaliada').length).toBeGreaterThan(0);
    expect(screen.getByText(
      'Ainda não há níveis de maturidade definidos para este tipo.',
    )).toBeInTheDocument();
    expect(screen.queryByText('Not assessed')).not.toBeInTheDocument();
  });
});
