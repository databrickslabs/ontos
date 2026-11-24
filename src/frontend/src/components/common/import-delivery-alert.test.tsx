/**
 * The import dialog's "not delivered" line links to Settings > Delivery Modes,
 * where the delivery outbox lists them (#1688).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const permissions = vi.hoisted(() => ({ allowed: true }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => permissions.allowed }),
}));

import i18n from '@/i18n/config';
import ImportDeliveryAlert, { undeliveredCount } from './import-delivery-alert';
import { importItemLine, reportedImportItems } from '@/lib/import-item-text';
import type { BatchImportResult } from '@/types/import-results';

const result: BatchImportResult = {
  created: 3, skipped: 0, failed: 0, total: 3, created_ids: ['p-1', 'p-2', 'p-3'],
  delivery_failed: 1,
  items: [
    { index: 0, name: 'Delivered', entity_id: 'p-1', status: 'created',
      delivery: { status: 'delivered', params: { modes: ['indirect'] } } },
    { index: 1, name: 'Orders', entity_id: 'p-2', status: 'created',
      delivery: { status: 'failed', code: 'delivery_git_unavailable' } },
    { index: 2, name: 'Queued', entity_id: 'p-3', status: 'created',
      delivery: { status: 'pending', code: 'delivery_pending' } },
  ],
};

function renderAlert(value: BatchImportResult | null) {
  return render(<MemoryRouter><ImportDeliveryAlert result={value} /></MemoryRouter>);
}

describe('ImportDeliveryAlert', () => {
  beforeEach(async () => {
    permissions.allowed = true;
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('counts the failed and queued deliveries and links to the delivery settings', () => {
    renderAlert(result);

    expect(screen.getByTestId('import-delivery-alert')).toHaveTextContent(
      'Ainda não entregues: 2. O Ontos tenta de novo automaticamente.');
    expect(screen.getByRole('link', { name: 'Abrir Configurações > Modos de entrega' }))
      .toHaveAttribute('href', '/settings/delivery');
  });

  it('has no link for a user who can not open the delivery settings', () => {
    permissions.allowed = false;
    renderAlert(result);

    expect(screen.getByTestId('import-delivery-alert')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('shows nothing when everything was delivered', () => {
    const delivered = { ...result, items: [result.items[0]] };
    renderAlert(delivered);
    renderAlert(null);

    expect(undeliveredCount(delivered)).toBe(0);
    expect(screen.queryByTestId('import-delivery-alert')).toBeNull();
  });

  it('reports a queued delivery in the import lines', () => {
    expect(reportedImportItems(result).map((i) => i.name)).toEqual(['Orders', 'Queued']);
    expect(importItemLine(result.items[2], i18n.t)).toBe(
      '• Queued: Importado; a entrega está na fila e roda em instantes.');
  });
});
