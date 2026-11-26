import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';

import { DescriptionResetDialog, canResetDescription } from './description-reset-dialog';

const getMock = vi.fn();
const postMock = vi.fn();
const toastMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: postMock }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

const preview = {
  asset_id: 'a1',
  target: 'main.sales.orders',
  object_type: 'table',
  description: 'Old text',
  uc_comment: 'Orders placed online',
  in_sync: false,
  table_type: 'MANAGED',
};

function renderDialog(onOpenChange = vi.fn(), onReset = vi.fn()) {
  render(
    <DescriptionResetDialog assetId="a1" open onOpenChange={onOpenChange} onReset={onReset} />
  );
  return { onOpenChange, onReset };
}

describe('canResetDescription', () => {
  it('applies to Databricks tables, views and columns only', () => {
    expect(canResetDescription('Table', 'databricks')).toBe(true);
    expect(canResetDescription('Column', 'Databricks')).toBe(true);
    expect(canResetDescription('View', ' databricks ')).toBe(true);
    expect(canResetDescription('Metric View', 'databricks')).toBe(false);
    expect(canResetDescription('Dashboard', 'databricks')).toBe(false);
    expect(canResetDescription('Table', 'snowflake')).toBe(false);
    expect(canResetDescription('Table', null)).toBe(false);
    expect(canResetDescription(null, 'databricks')).toBe(false);
  });
});

describe('DescriptionResetDialog', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    toastMock.mockReset();
  });

  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('shows the Ontos description next to the Unity Catalog comment', async () => {
    getMock.mockResolvedValue({ data: preview });
    renderDialog();

    expect(await screen.findByTestId('description-reset-old')).toHaveTextContent('Old text');
    expect(screen.getByTestId('description-reset-new')).toHaveTextContent(
      'Orders placed online'
    );
    expect(getMock).toHaveBeenCalledWith('/api/assets/a1/description/uc-comment');
    expect(screen.getByRole('button', { name: 'Replace description' })).toBeEnabled();
  });

  it('sends the comment it showed, then reports and reloads', async () => {
    getMock.mockResolvedValue({ data: preview });
    postMock.mockResolvedValue({
      data: { asset_id: 'a1', target: 'main.sales.orders', changed: true, warnings: [] },
    });
    const { onOpenChange, onReset } = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Replace description' }));

    await waitFor(() => expect(onReset).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/api/assets/a1/description/reset-to-uc', {
      expected_uc_comment: 'Orders placed online',
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Description replaced' })
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('lets a description that already matches be confirmed, to clear a not-in-sync mark', async () => {
    getMock.mockResolvedValue({
      data: { ...preview, description: 'Same', uc_comment: 'Same', in_sync: true },
    });
    postMock.mockResolvedValue({ data: { changed: false, warnings: [] } });
    renderDialog();

    expect(await screen.findByText(/already matches/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Mark as in sync' }));

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/api/assets/a1/description/reset-to-uc', { expected_uc_comment: 'Same' }));
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Description unchanged' }));
  });

  it('does not offer to replace the description with an empty comment', async () => {
    getMock.mockResolvedValue({ data: { ...preview, uc_comment: null } });
    renderDialog();

    expect(await screen.findByText(/has no comment on this object/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Replace description' })).toBeDisabled();
  });

  it('translates a coded error of the preview', async () => {
    getMock.mockResolvedValue({
      data: null,
      error: 'english fallback',
      errorCode: 'uc_reset_permission_denied',
      errorParams: { object: 'main.sales.orders' },
    });
    renderDialog();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("You can't read main.sales.orders in Unity Catalog");
    expect(alert).not.toHaveTextContent('english fallback');
    expect(screen.getByRole('button', { name: 'Replace description' })).toBeDisabled();
  });

  it('shows the error of a comment that changed meanwhile, reloads it and stays open', async () => {
    getMock
      .mockResolvedValueOnce({ data: preview })
      .mockResolvedValue({ data: { ...preview, uc_comment: 'Changed in Unity Catalog' } });
    postMock.mockResolvedValue({
      data: null,
      error: 'changed',
      errorCode: 'uc_reset_uc_changed',
      errorParams: { object: 'main.sales.orders' },
    });
    const { onReset } = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Replace description' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('changed since you looked at it');
    await waitFor(() =>
      expect(screen.getByTestId('description-reset-new')).toHaveTextContent(
        'Changed in Unity Catalog'
      )
    );
    expect(screen.getByRole('alert')).toHaveTextContent('changed since you looked at it');
    expect(onReset).not.toHaveBeenCalled();
  });

  it('falls back to the server message for an unknown code', async () => {
    getMock.mockResolvedValue({
      data: null, error: 'english fallback', errorCode: 'something_new',
    });
    renderDialog();

    expect(await screen.findByRole('alert')).toHaveTextContent('english fallback');
  });

  it('speaks Portuguese', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    getMock.mockResolvedValue({ data: preview });
    renderDialog();

    expect(
      await screen.findByRole('button', { name: 'Substituir descrição' })
    ).toBeInTheDocument();
    expect(screen.getByText('No Unity Catalog')).toBeInTheDocument();
  });
});
