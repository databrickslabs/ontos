/**
 * The startup warning banner: translated health codes, no exception text, and
 * a way back once the workspace recovers (#613).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import i18n from '@/i18n/config';
import Layout from './layout';

vi.mock('./sidebar', () => ({ Sidebar: () => null }));
vi.mock('./header', () => ({ Header: () => null }));
vi.mock('@/components/ui/breadcrumbs', () => ({ Breadcrumbs: () => null }));
vi.mock('@/components/copilot/copilot-panel', () => ({ default: () => null }));

const WS_MESSAGE =
  'The Databricks workspace client could not be created. The cause is in the server logs.';

const wsDown = {
  db_ok: true,
  ws_ok: false,
  seed_ok: true,
  warnings: [WS_MESSAGE, 'Some services could not be initialized. The cause is in the server logs.'],
  warning_details: [
    { code: 'workspace_client_unavailable', message: WS_MESSAGE, params: {} },
    {
      code: 'manager_init_failed',
      message: 'Some services could not be initialized. The cause is in the server logs.',
      params: {},
    },
  ],
  db_error: null,
  db_error_code: null,
};

const dbDown = {
  db_ok: false,
  ws_ok: false,
  seed_ok: true,
  warnings: [],
  warning_details: [],
  db_error: 'The metadata database could not be initialized. The cause is in the server logs.',
  db_error_code: 'database_unavailable',
};

function respond(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe('Layout health banner', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let reload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    reload = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload },
    });
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    await i18n.changeLanguage('en');
  });

  it('shows the warning codes in the user language, once', async () => {
    await i18n.changeLanguage('pt');
    fetchMock.mockImplementation(() => respond(wsDown));

    render(<Layout><div /></Layout>);

    expect(await screen.findByText('Aviso do sistema')).toBeInTheDocument();
    expect(screen.getByText(/Falha na conexão com o workspace do Databricks/)).toBeInTheDocument();
    expect(
      screen.getByText('Alguns serviços não puderam ser inicializados. A causa está nos logs do servidor.'),
    ).toBeInTheDocument();
    // The workspace code repeats the first line, so it isn't listed again
    expect(screen.queryByText(/cliente do workspace/)).not.toBeInTheDocument();
    expect(screen.queryByText(WS_MESSAGE)).not.toBeInTheDocument();
  });

  it('retries from the warning and reloads once the workspace is back', async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('/retry')
        ? respond({ status: 'ok', health: { ...wsDown, ws_ok: true, warnings: [], warning_details: [] } })
        : respond(wsDown),
    );

    render(<Layout><div /></Layout>);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry connection' }));

    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith('/api/health/retry', { method: 'POST' });
  });

  it('says so and keeps the page when the workspace is still unreachable', async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('/retry') ? respond({ status: 'ok', health: wsDown }) : respond(wsDown),
    );

    render(<Layout><div /></Layout>);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry connection' }));

    expect(
      await screen.findByText('The workspace is still unreachable. Try again later.'),
    ).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it('polls the health while the workspace is unreachable', async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(() => respond(wsDown));

    render(<Layout><div /></Layout>);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const before = fetchMock.mock.calls.filter(([u]) => u === '/api/health').length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(fetchMock.mock.calls.filter(([u]) => u === '/api/health').length).toBe(before + 1);
  });

  it('translates the database error and a failed retry from their codes', async () => {
    await i18n.changeLanguage('pt');
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('/retry')
        ? respond({ status: 'error', detail: { code: 'database_unavailable', message: dbDown.db_error, params: {} } }, 503)
        : respond(dbDown),
    );

    render(<Layout><div /></Layout>);
    const text = 'Não foi possível inicializar o banco de dados de metadados. A causa está nos logs do servidor.';
    expect(await screen.findByText(text)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tentar reconectar' }));

    await waitFor(() => expect(screen.getAllByText(text)).toHaveLength(2));
  });
});
