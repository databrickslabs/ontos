import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import type { ManagementPort } from '@/types/data-product';
import ManagementPortFormDialog from './management-port-form-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const initial: ManagementPort = {
  name: 'health', content: 'observability', type: 'rest',
  url: 'https://example.com/health', channel: '#ops', description: 'Probe',
};

describe('ManagementPortFormDialog payload', () => {
  it('sends null for a cleared url and channel (an omitted field is kept)', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <ManagementPortFormDialog
        isOpen
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        initial={initial}
      />,
    );
    fireEvent.change(document.getElementById('url')!, { target: { value: '' } });
    fireEvent.change(document.getElementById('channel')!, { target: { value: ' ' } });

    fireEvent.click(screen.getByRole('button', { name: /save|update|submit/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      url: null, channel: null, description: 'Probe',
    });
  });
});
