/**
 * The product "Export ODPS" button downloads what the server builds
 * (GET /api/data-products/{id}/odps/export), not the object the page holds.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import ImportExportDialog from './import-export-dialog';
import type { DataProduct } from '@/types/data-product';

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));

const product = { id: 'p-1', name: 'Orders', status: 'active', version: '1.0.0' } as DataProduct;
const YAML_BODY = 'apiVersion: v1.0.0\nkind: DataProduct\nid: p-1\n';

const renderExportTab = async () => {
  renderWithProviders(
    <ImportExportDialog isOpen onOpenChange={() => {}} currentProduct={product} />,
  );
  const tab = screen.getByRole('tab', { name: /export/i });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
  return screen.findByRole('button', { name: /export as yaml/i });
};

describe('ImportExportDialog export', () => {
  let blobs: Blob[];
  let downloads: string[];

  beforeEach(() => {
    blobs = [];
    downloads = [];
    toast.mockClear();
    URL.createObjectURL = vi.fn((b: Blob) => (blobs.push(b), 'blob:x'));
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(
      function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('downloads the file the server exports, under its file name', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(YAML_BODY, {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="orders-odps.yaml"' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    fireEvent.click(await renderExportTab());

    await waitFor(() => expect(downloads).toEqual(['orders-odps.yaml']));
    expect(fetchMock).toHaveBeenCalledWith('/api/data-products/p-1/odps/export');
    expect(blobs[0].size).toBe(YAML_BODY.length);
    expect(blobs[0].type).toContain('yaml');
  });

  it('downloads nothing when the server refuses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('no', { status: 500 })));

    fireEvent.click(await renderExportTab());

    await waitFor(() => expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Export Failed', variant: 'destructive' }),
    ));
    expect(downloads).toEqual([]);
  });
});
