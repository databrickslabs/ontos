/** The Edition select loads the saved edition and sends the chosen one on save. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';

vi.hoisted(() => {
  // The real UI customization store fetches on import; keep it offline.
  globalThis.fetch = (async () => ({ ok: false, json: async () => ({}) })) as any;
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));
// A native <select> instead of the Radix one, which needs pointer capture jsdom lacks.
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children, disabled }: any) => (
    <select
      aria-label="edition"
      value={value}
      disabled={disabled}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/stores/ui-customization-store', async () => {
  const actual: any = await vi.importActual('@/stores/ui-customization-store');
  return {
    ...actual,
    useUICustomizationStore: (selector: (s: { fetchSettings: () => void }) => unknown) =>
      selector({ fetchSettings: vi.fn() }),
  };
});

import UICustomizationSettings from './ui-customization-settings';

describe('UI customization: edition', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => ({
      ok: true,
      json: async () => (init?.method === 'PUT' ? {} : { ui_edition: 'essentials' }),
    }));
    vi.stubGlobal('fetch', fetchMock);
  });

  it('shows the saved edition, the presentation-only help, and saves a new choice', async () => {
    renderWithProviders(<UICustomizationSettings />);
    const select = (await screen.findByRole('combobox', { name: 'edition' })) as HTMLSelectElement;
    expect(select.value).toBe('essentials');
    expect(screen.getByRole('option', { name: 'Essentials' })).toBeInTheDocument();
    expect(screen.getByText(/Permissions are unchanged/)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.selectOptions(select, 'full');
    await user.click(screen.getByRole('button', { name: /Save UI Settings/ }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
      expect(put).toBeTruthy();
      expect(JSON.parse(put![1].body).ui_edition).toBe('full');
    });
  });
});
