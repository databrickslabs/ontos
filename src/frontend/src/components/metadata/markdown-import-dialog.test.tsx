/**
 * Import Markdown from a volume (#1478): the dialog posts the path, shows the
 * summary and the per-file outcome, and shows coded errors in the user's language.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import i18n from '@/i18n/config';
import MarkdownImportDialog, { MarkdownImportResult } from './markdown-import-dialog';

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => ({
    ok: status < 400,
    status,
    statusText: '',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const RESULT: MarkdownImportResult = {
  path: '/Volumes/main/docs/context',
  added: 1,
  updated: 1,
  unchanged: 0,
  unlinked: 1,
  failed: 1,
  files: [
    {
      path: '/Volumes/main/docs/context/domain.md', status: 'added', title: 'Customer',
      targets: [{ entity_type: 'data_domain', entity_id: 'd1', name: 'Customer' }], unresolved: [],
    },
    {
      path: '/Volumes/main/docs/context/terms.md', status: 'updated', title: 'Terms',
      targets: [{ entity_type: 'concept', entity_id: 'http://ex.org#Churn', name: 'Churn' }],
      unresolved: [{ kind: 'asset', value: 'main.crm.gone', reason: 'not_found' }],
    },
    {
      path: '/Volumes/main/docs/context/loose.md', status: 'unlinked', title: 'Loose',
      targets: [], unresolved: [],
    },
    {
      path: '/Volumes/main/docs/context/bad.md', status: 'failed', targets: [], unresolved: [],
      reason: 'front_matter_invalid',
    },
  ],
};

function open(onImported = vi.fn()) {
  render(<MarkdownImportDialog open onOpenChange={() => {}} onImported={onImported} />);
  fireEvent.change(screen.getByLabelText('Volume folder or file'), {
    target: { value: ' /Volumes/main/docs/context ' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Import' }));
  return onImported;
}

describe('MarkdownImportDialog', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('posts the trimmed path and shows the summary and each file', async () => {
    const fetchMock = respond(200, RESULT);
    const onImported = open();

    expect(await screen.findByText('Added: 1')).toBeInTheDocument();
    expect(screen.getByText('Updated: 1')).toBeInTheDocument();
    expect(screen.getByText('Unchanged: 0')).toBeInTheDocument();
    expect(screen.getByText('Unlinked: 1')).toBeInTheDocument();
    expect(screen.getByText('Failed: 1')).toBeInTheDocument();
    expect(screen.getByText('Linked to: Customer')).toBeInTheDocument();
    expect(screen.getByText('Asset "main.crm.gone" not found')).toBeInTheDocument();
    expect(screen.getByText('The front matter names no domain, asset or concept.'))
      .toBeInTheDocument();
    expect(screen.getByText('The front matter is not a valid YAML mapping.')).toBeInTheDocument();

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/metadata/markdown-import');
    expect(JSON.parse(String(init.body))).toEqual({ path: '/Volumes/main/docs/context' });
    expect(onImported).toHaveBeenCalledWith(RESULT);
  });

  it('shows a coded error in the user\'s language', async () => {
    await i18n.changeLanguage('pt');
    respond(403, {
      detail: {
        code: 'markdown_import_access_denied',
        message: "Can't read /Volumes/main/secret",
        params: { path: '/Volumes/main/secret' },
      },
    });
    render(<MarkdownImportDialog open onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText('Pasta ou arquivo do volume'), {
      target: { value: '/Volumes/main/secret' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Importar' }));

    expect(await screen.findByText(
      'Você não pode ler "/Volumes/main/secret". Peça READ VOLUME no volume.',
    )).toBeInTheDocument();
  });

  it('keeps the import button off without a path', () => {
    respond(200, RESULT);
    render(<MarkdownImportDialog open onOpenChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('does not report an import that changed nothing', async () => {
    respond(200, { ...RESULT, added: 0, updated: 0, unchanged: 2, files: [] });
    const onImported = open();
    await waitFor(() => expect(screen.getByText('Unchanged: 2')).toBeInTheDocument());
    expect(screen.getByText('No Markdown files found at this path.')).toBeInTheDocument();
    expect(onImported).not.toHaveBeenCalled();
  });
});
