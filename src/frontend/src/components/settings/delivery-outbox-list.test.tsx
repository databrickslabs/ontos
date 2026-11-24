/**
 * Settings > Delivery Modes lists the changes not delivered yet and delivers one
 * again (#1688), in the user's language.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));

import i18n from '@/i18n/config';
import DeliveryOutboxList, { outboxReasonText } from './delivery-outbox-list';
import type { DeliveryOutboxRow } from '@/types/delivery-outbox';

const pending: DeliveryOutboxRow = {
  id: 'r-1', entity_type: 'DataProduct', entity_id: 'p-1', entity_name: 'Orders',
  change_type: 'product_create', mode: 'indirect', status: 'pending',
  code: 'delivery_git_unavailable', params: { mode: 'indirect' }, attempts: 1, max_attempts: 5,
  next_attempt_at: '2026-11-24T12:01:00Z',
};
const failed: DeliveryOutboxRow = {
  ...pending, id: 'r-2', entity_id: 'p-2', entity_name: null, status: 'failed',
  code: 'delivery_entity_not_found', attempts: 5, next_attempt_at: null,
};

type Route = { ok?: boolean; body: unknown };

function respond(routes: Record<string, Route | Route[]>) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(url)}`;
    calls.push(key);
    const entry = routes[key];
    if (!entry) throw new Error(`unexpected fetch ${key}`);
    const route = Array.isArray(entry) ? (entry.length > 1 ? entry.shift()! : entry[0]) : entry;
    return { ok: route.ok ?? true, json: async () => route.body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

function renderList(canWrite = true) {
  return render(
    <MemoryRouter>
      <DeliveryOutboxList canWrite={canWrite} />
    </MemoryRouter>,
  );
}

describe('DeliveryOutboxList', () => {
  beforeEach(async () => {
    toast.mockReset();
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('lists the rows with their translated reason and a link to the product', async () => {
    respond({ 'GET /api/delivery/outbox': { body: { rows: [pending, failed], counts: {} } } });

    renderList();

    const link = await screen.findByRole('link', { name: 'Orders' });
    expect(link).toHaveAttribute('href', '/data-products/p-1');
    const reason = 'O repositório Git não está disponível. Verifique Configurações > Git.';
    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByText('(não existe mais)')).toBeInTheDocument();
    expect(screen.getByText('Sem novas tentativas automáticas')).toBeInTheDocument();
    expect(screen.getByText('1 de 5')).toBeInTheDocument();
    expect(screen.getAllByText('Produto de dados criado')).toHaveLength(2);
    expect(screen.getByText('Falhou')).toBeInTheDocument();
  });

  it('delivers an entity again and reloads the list', async () => {
    const calls = respond({
      'GET /api/delivery/outbox': [
        { body: { rows: [pending], counts: { pending: 1 } } },
        { body: { rows: [], counts: {} } },
      ],
      'POST /api/delivery/DataProduct/p-1/redeliver': {
        body: { entity_type: 'DataProduct', entity_id: 'p-1', rows: [],
          delivery: { status: 'delivered', params: { modes: ['indirect'] } } },
      },
    });
    renderList();
    const row = (await screen.findByRole('link', { name: 'Orders' })).closest('tr')!;

    fireEvent.click(within(row).getByRole('button', { name: 'Entregar de novo' }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Entregue.' })));
    expect(await screen.findByText('Todas as alterações foram entregues.')).toBeInTheDocument();
    expect(calls).toEqual([
      'GET /api/delivery/outbox', 'POST /api/delivery/DataProduct/p-1/redeliver',
      'GET /api/delivery/outbox',
    ]);
  });

  it('says why a delivery failed again, and a coded refusal', async () => {
    respond({
      'GET /api/delivery/outbox': { body: { rows: [pending], counts: {} } },
      'POST /api/delivery/DataProduct/p-1/redeliver': [
        { body: { entity_type: 'DataProduct', entity_id: 'p-1', rows: [],
          delivery: { status: 'failed', code: 'delivery_git_write_failed' } } },
        { ok: false, body: { detail: { code: 'delivery_no_active_mode', message: 'x' } } },
      ],
    });
    renderList();
    const button = await screen.findByRole('button', { name: 'Entregar de novo' });

    fireEvent.click(button);
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Ainda não entregue: Não foi possível gravar o arquivo no repositório Git.',
      variant: 'destructive',
    })));

    fireEvent.click(await screen.findByRole('button', { name: 'Entregar de novo' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Não foi possível entregar de novo.',
      description: 'Nenhum modo de entrega está ativo.',
    })));
  });

  it('has no "Deliver again" for a read-only admin, and says when the list fails', async () => {
    respond({ 'GET /api/delivery/outbox': { body: { rows: [pending], counts: {} } } });
    const { unmount } = renderList(false);
    await screen.findByRole('link', { name: 'Orders' });
    expect(screen.queryByRole('button', { name: 'Entregar de novo' })).toBeNull();
    unmount();

    respond({ 'GET /api/delivery/outbox': { ok: false, body: {} } });
    renderList();
    expect(await screen.findByText(
      'Não foi possível carregar as alterações ainda não entregues.')).toBeInTheDocument();
  });

  it('reads an unknown code as a failed delivery', () => {
    expect(outboxReasonText('something_new', i18n.t)).toBe(
      'A entrega falhou. Os logs do servidor têm os detalhes.');
  });
});
