import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';

import { DescriptionCompareDialog } from './description-compare-dialog';

const getMock = vi.fn();
const postMock = vi.fn();
const toastMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock, post: postMock }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

const field = (id: string, name: string, over = {}) => ({
  asset_id: id,
  name,
  object_type: id === 't' ? 'table' : 'column',
  target: `main.sales.orders${id === 't' ? '' : `.${name}`}`,
  description: `${name} (Ontos)`,
  uc_comment: `${name} (UC)`,
  baseline_known: true,
  baseline_text: `${name} (UC)`,
  differs: true,
  changed_in_uc: false,
  missing_in_uc: false,
  ...over,
});

const drift = (fields: unknown[], over = {}) => ({
  asset_id: 't', target: 'main.sales.orders', table_type: 'MANAGED', fields, truncated: false,
  ...over,
});

function renderDialog() {
  const onReset = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <DescriptionCompareDialog
      assetId="t" open onOpenChange={onOpenChange} onReset={onReset}
    />
  );
  return { onReset, onOpenChange };
}

describe('DescriptionCompareDialog', () => {
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

  it('lists only the descriptions that differ, with nothing selected', async () => {
    getMock.mockResolvedValue({
      data: drift([
        field('t', 'orders'),
        field('c1', 'order_id', { changed_in_uc: true }),
        field('c2', 'note', { differs: false }),
        field('c3', 'gone', { missing_in_uc: true }),
      ]),
    });
    renderDialog();

    expect(await screen.findByText('order_id')).toBeInTheDocument();
    expect(screen.getByText('orders')).toBeInTheDocument();
    expect(screen.queryByText('note')).not.toBeInTheDocument();
    expect(screen.queryByText('gone')).not.toBeInTheDocument();
    expect(screen.getByText('Changed in Unity Catalog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset selected (0)' })).toBeDisabled();
    expect(getMock).toHaveBeenCalledWith('/api/assets/t/description/drift');
  });

  it('resets the selected fields in one request, sending the comments it showed', async () => {
    getMock.mockResolvedValue({
      data: drift([field('t', 'orders'), field('c1', 'order_id'), field('c2', 'note')]),
    });
    postMock.mockResolvedValue({
      data: {
        results: [
          { asset_id: 't', changed: true, warnings: [] },
          { asset_id: 'c1', changed: true, warnings: [] },
        ],
        changed: 2, failed: 0,
      },
    });
    const { onReset, onOpenChange } = renderDialog();

    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select orders' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select order_id' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset selected (2)' }));

    await waitFor(() => expect(onReset).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/api/assets/t/description/reset-selected', {
      fields: [
        { asset_id: 't', expected_uc_comment: 'orders (UC)' },
        { asset_id: 'c1', expected_uc_comment: 'order_id (UC)' },
      ],
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Descriptions replaced: 2' })
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('selects every field that can be reset, and clears the selection again', async () => {
    getMock.mockResolvedValue({
      data: drift([field('t', 'orders'), field('c1', 'order_id'),
        field('c2', 'note', { uc_comment: null })]),
    });
    renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Select all' }));
    expect(screen.getByRole('button', { name: 'Reset selected (2)' })).toBeEnabled();
    expect(screen.getByRole('checkbox', { name: 'Select note' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Select none' }));
    expect(screen.getByRole('button', { name: 'Reset selected (0)' })).toBeDisabled();
  });

  it('never offers to replace a description with an empty comment', async () => {
    getMock.mockResolvedValue({
      data: drift([field('c1', 'note', { uc_comment: null })]),
    });
    renderDialog();

    expect(await screen.findByText(/has no comment here/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Select note' })).toBeDisabled();
  });

  it('says so when everything matches', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders', { differs: false })]) });
    renderDialog();

    expect(await screen.findByText('The descriptions match the Unity Catalog comments.'))
      .toBeInTheDocument();
  });

  it('keeps the dialog open and names the fields that were refused', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders'), field('c1', 'order_id')]) });
    postMock.mockResolvedValue({
      data: {
        results: [
          { asset_id: 't', changed: true, warnings: [] },
          {
            asset_id: 'c1', changed: false, warnings: [],
            error: { code: 'uc_reset_uc_changed', message: 'english', params: { object: 'x' } },
          },
        ],
        changed: 1, failed: 1,
      },
    });
    const { onReset, onOpenChange } = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Select all' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset selected (2)' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('order_id');
    expect(alert).toHaveTextContent('changed since you looked at it');
    expect(onReset).toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(getMock).toHaveBeenCalledTimes(2);
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
  });

  it('translates the codes of a refused field', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders'), field('c1', 'order_id'),
      field('c2', 'note')]) });
    postMock.mockResolvedValue({
      data: {
        results: [
          { asset_id: 't', changed: true, warnings: [] },
          {
            asset_id: 'c1', changed: false, warnings: [],
            error: { code: 'uc_reset_field_not_in_table', message: 'english', params: {
              object: 'main.sales.items.id' } },
          },
          { asset_id: 'c2', changed: false, warnings: [],
            error: { code: 'asset_not_found', message: 'english', params: {} } },
        ],
        changed: 1, failed: 2,
      },
    });
    renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Select all' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset selected (3)' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('main.sales.items.id is not part of this table.');
    expect(alert).toHaveTextContent('This asset no longer exists.');
    expect(alert).not.toHaveTextContent('english');
  });

  it('translates a failure of the whole request', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders')]) });
    postMock.mockResolvedValue({
      data: null, error: 'english', errorCode: 'uc_reset_failed', errorParams: {} });
    renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Select all' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset selected (1)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('none was changed');
  });

  it('shows the warnings of a field that was reset, and keeps the dialog open', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders'), field('c1', 'order_id')]) });
    postMock.mockResolvedValue({
      data: {
        results: [
          { asset_id: 't', changed: true, warnings: [] },
          { asset_id: 'c1', changed: false, warnings: [{
            code: 'uc_description_empty', message: 'english', params: { object: 'x.order_id' },
          }] },
        ],
        changed: 1, failed: 0,
      },
    });
    const { onOpenChange } = renderDialog();

    await userEvent.click(await screen.findByRole('button', { name: 'Select all' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset selected (2)' }));

    const notes = await screen.findAllByRole('status');
    const warning = notes.find((n) => n.textContent?.includes('order_id: '));
    expect(warning).toHaveTextContent('Unity Catalog has no comment on x.order_id');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it('names the kind of object in the language of the user', async () => {
    getMock.mockResolvedValue({ data: drift([field('t', 'orders'), field('c1', 'order_id')]) });
    renderDialog();

    expect(await screen.findByText('Column')).toBeInTheDocument();
    expect(screen.queryByText('column')).not.toBeInTheDocument();
  });

  it('translates a coded error of the read', async () => {
    getMock.mockResolvedValue({
      data: null, error: 'english', errorCode: 'uc_reset_permission_denied',
      errorParams: { object: 'main.sales.orders' },
    });
    renderDialog();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "You can't read main.sales.orders in Unity Catalog"
    );
  });

  it('speaks Portuguese', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    getMock.mockResolvedValue({ data: drift([field('t', 'orders')]) });
    renderDialog();

    expect(await screen.findByText('Comparar com o Unity Catalog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Redefinir selecionadas (0)' })).toBeInTheDocument();
  });
});
