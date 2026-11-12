import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import InputPortFormDialog from './input-port-form-dialog';

const toast = vi.fn();

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast }),
}));

const initial = { name: 'in', version: '1.0.0', contractId: 'c-1' };

const renderDialog = (onSubmit: () => Promise<void | boolean>, onOpenChange = vi.fn()) => {
  renderWithProviders(
    <InputPortFormDialog
      isOpen
      onOpenChange={onOpenChange}
      onSubmit={onSubmit}
      initial={initial}
    />,
  );
  return onOpenChange;
};

describe('InputPortFormDialog submit outcome', () => {
  beforeEach(() => toast.mockReset());

  it('toasts success and closes when the change was saved', async () => {
    const onOpenChange = renderDialog(vi.fn().mockResolvedValue(undefined));

    fireEvent.click(screen.getByRole('button', { name: /save|update|submit/i }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Success' }));
  });

  it('closes without a success toast when the change was not saved (versioning dialog took over)', async () => {
    const onOpenChange = renderDialog(vi.fn().mockResolvedValue(false));

    fireEvent.click(screen.getByRole('button', { name: /save|update|submit/i }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast).not.toHaveBeenCalled();
  });
});
