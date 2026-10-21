/**
 * A subscription refused with `product_not_subscribable` shows the coded error
 * in the UI language, not the raw detail.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import SubscribeDialog from './subscribe-dialog';

const mockToast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));

const REFUSAL = {
  detail: {
    code: 'product_not_subscribable',
    message: "Cannot subscribe to Old Product in status 'deprecated'. "
      + 'Product must be in one of: active, certified',
    params: { status: 'deprecated', productName: 'Old Product' },
  },
};

async function submitRefused(lng: string) {
  await i18n.changeLanguage(lng);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, status: 400, json: async () => REFUSAL,
  }));
  renderWithProviders(
    <SubscribeDialog open onOpenChange={vi.fn()} productId="p-1" productName="Old Product" />,
  );
  const buttons = await screen.findAllByRole('button');
  const submit = buttons.filter(b => /^(Subscribe|Assinar)$/.test(b.textContent?.trim() ?? '')).pop()!;
  fireEvent.click(submit);
  await waitFor(() => expect(mockToast).toHaveBeenCalled());
  return mockToast.mock.calls[0][0];
}

describe('SubscribeDialog refusal', () => {
  afterEach(async () => {
    mockToast.mockClear();
    vi.unstubAllGlobals();
    await i18n.changeLanguage('en');
  });

  it('shows the refusal in English', async () => {
    const toast = await submitRefused('en');
    expect(toast.variant).toBe('destructive');
    expect(toast.description).toBe(
      "Cannot subscribe to 'Old Product': its status is 'Deprecated'. "
      + 'Only active or certified products accept new subscriptions.',
    );
  });

  it('shows the refusal in Portuguese', async () => {
    const toast = await submitRefused('pt');
    expect(toast.description).toContain("Não é possível assinar 'Old Product'");
    expect(toast.description).not.toContain('[object Object]');
  });
});
