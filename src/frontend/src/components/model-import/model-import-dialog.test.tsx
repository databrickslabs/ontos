/**
 * ModelImportDialog (PRD #1718): the upload step stages a run on the server and
 * opens its review page; nothing is imported from the dialog itself.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ModelImportDialog from './model-import-dialog';

const navigate = vi.fn();
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()),
  useNavigate: () => navigate,
}));

function renderDialog(props: Partial<Parameters<typeof ModelImportDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  render(
    <MemoryRouter>
      <ModelImportDialog open onOpenChange={onOpenChange} {...props} />
    </MemoryRouter>,
  );
  return { onOpenChange };
}

const fileInput = () => document.querySelector('input[type="file"]') as HTMLInputElement;
const xmlFile = () => new File(['<erwin/>'], 'model.xml', { type: 'application/xml' });

afterEach(() => {
  vi.restoreAllMocks();
  navigate.mockReset();
});

describe('ModelImportDialog', () => {
  it('explains how to export from erwin', () => {
    renderDialog();
    expect(screen.getByText('Import an erwin data model')).toBeInTheDocument();
    expect(screen.getByText(/File → Save As → XML/)).toBeInTheDocument();
  });

  it('uploads the file with the preselected layers and opens the run', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'run-1' }), { status: 201, headers: { 'Content-Type': 'application/json' } }),
    );
    const { onOpenChange } = renderDialog({ layers: { logical: false, physical: true } });
    await userEvent.upload(fileInput(), xmlFile());

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/model-imports/run-1'));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/model-import/runs');
    const body = (init as RequestInit).body as FormData;
    expect((body.get('file') as File).name).toBe('model.xml');
    expect(JSON.parse(body.get('options') as string)).toEqual({ import_logical: false, import_physical: true });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows the server error and stays open', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not an erwin XML export.' }), {
        status: 422, headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { onOpenChange } = renderDialog();
    await userEvent.upload(fileInput(), xmlFile());
    expect(await screen.findByText('Not an erwin XML export.')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
