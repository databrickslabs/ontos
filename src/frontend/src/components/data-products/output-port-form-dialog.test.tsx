import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import type { OutputPort } from '@/types/data-product';
import OutputPortFormDialog from './output-port-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const initial: OutputPort = {
  id: 'p-1', name: 'out', version: '1.0.0', description: 'Daily orders', status: 'active',
};

const submitted = async (edit: () => void): Promise<OutputPort> => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  renderWithProviders(
    <OutputPortFormDialog isOpen onOpenChange={vi.fn()} onSubmit={onSubmit} initial={initial} />,
  );
  edit();
  fireEvent.click(screen.getByRole('button', { name: /save|update|submit/i }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  return onSubmit.mock.calls[0][0];
};

describe('OutputPortFormDialog payload', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('sends null for a cleared description and status (an omitted field is kept)', async () => {
    const port = await submitted(() => {
      fireEvent.change(screen.getByLabelText(/description/i), { target: { value: ' ' } });
      fireEvent.change(screen.getByLabelText(/status/i), { target: { value: '' } });
    });

    expect(port.description).toBeNull();
    expect(port.status).toBeNull();
  });

  it('sends the values it holds', async () => {
    const port = await submitted(() => {});

    expect(port).toMatchObject({ description: 'Daily orders', status: 'active' });
  });
});
