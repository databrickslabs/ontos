/**
 * A gate that failed because the asset's Unity Catalog table couldn't be read
 * carries a code; the panel shows it in the UI language, not the English text.
 */
import { screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { MaturityPanel } from './maturity-panel';
import type { MaturityReport } from '@/types/maturity';

const ENGLISH = 'Table main.sales.orders was not found in Unity Catalog, so its fields are missing.';

const REPORT: MaturityReport = {
  entity_type: 'DataProduct',
  entity_id: 'p-1',
  entity_name: 'Orders',
  achieved_level_order: null,
  achieved_level_name: null,
  total_levels: 1,
  gates_passed: 0,
  gates_total: 2,
  levels: [{
    level_order: 1,
    level_name: 'Documented',
    level_icon: null,
    level_color: null,
    achieved: false,
    gates: [
      {
        gate_id: 'g-1', policy_id: 'p-1', policy_name: 'Columns documented', required: true,
        passed: false, message: ENGLISH,
        message_code: 'maturity_uc_table_not_found',
        message_params: { tableName: 'main.sales.orders' },
      },
      {
        gate_id: 'g-2', policy_id: 'p-2', policy_name: 'Has owner', required: true,
        passed: false, message: 'Assertion failed: has_owner',
      },
    ],
  }],
  evaluated_at: '2026-11-07T10:00:00Z',
  evaluated_by: null,
  notices: [],
};

async function renderPanel(lng: string) {
  await i18n.changeLanguage(lng);
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => ({
    ok: true,
    json: async () => (url.includes('/history') ? [] : REPORT),
  })));
  renderWithProviders(<MaturityPanel entityType="DataProduct" entityId="p-1" />);
  fireEvent.click(await screen.findByText('Documented'));
}

describe('MaturityPanel gate codes', () => {
  afterEach(async () => {
    vi.unstubAllGlobals();
    await i18n.changeLanguage('en');
  });

  it('shows a coded gate message in Portuguese', async () => {
    await renderPanel('pt');

    expect(await screen.findByText(
      'A tabela main.sales.orders não foi encontrada no Unity Catalog, então faltam os campos dela.',
    )).toBeInTheDocument();
    expect(screen.queryByText(ENGLISH)).not.toBeInTheDocument();
    // A gate without a code keeps its own message
    expect(screen.getByText('Assertion failed: has_owner')).toBeInTheDocument();
  });

  it('shows a coded gate message in English', async () => {
    await renderPanel('en');

    expect(await screen.findByText(ENGLISH)).toBeInTheDocument();
  });

  it('falls back to the server text for an unknown code', async () => {
    const gate = REPORT.levels[0].gates[0];
    const original = gate.message_code;
    gate.message_code = 'maturity_something_new';
    try {
      await renderPanel('pt');
      expect(await screen.findByText(ENGLISH)).toBeInTheDocument();
    } finally {
      gate.message_code = original;
    }
  });
});
