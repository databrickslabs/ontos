/**
 * UI Customization form, co-branding fields: tagline, dark logo, theme colors
 * ("essential + auto": derived dark colors and the contrast hint) and the
 * powered-by toggle, saved through the existing PUT /api/settings.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// The UI customization store fetches on import; keep that request inert.
vi.hoisted(() => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch;
});

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

import UICustomizationSettings from './ui-customization-settings';
import { deriveDarkColor, isValidImageUrl } from '@/lib/branding';

const STORED = {
  ui_i18n_enabled: true,
  ui_app_display_name: 'Acme Graph',
  ui_custom_logo_url: '/branding/acme/mark.svg',
  ui_app_tagline: 'Ontology of Acme',
  ui_theme_primary: '#1d4ed8',
  ui_theme_primary_dark: null,
  ui_theme_accent: '#dbeafe',
  ui_theme_accent_dark: '#1e293b',
  ui_show_powered_by: true,
};

let putBody: Record<string, unknown> | null = null;

function mockFetch() {
  putBody = null;
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path === '/api/settings' && init?.method === 'PUT') {
      putBody = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({}) } as Response;
    }
    if (path === '/api/settings') return { ok: true, json: async () => STORED } as Response;
    // UI customization store refresh after save; keep it pending
    return new Promise(() => {}) as Promise<Response>;
  }) as unknown as typeof fetch;
}

describe('UICustomizationSettings co-branding fields', () => {
  beforeEach(() => {
    toast.mockReset();
    mockFetch();
  });

  it('shows the derived dark color when the dark field is empty', async () => {
    render(<UICustomizationSettings />);
    const darkInput = await screen.findByLabelText('Primary color (dark mode)');
    const derived = deriveDarkColor('#1d4ed8', 'primary')!;
    expect(darkInput).toHaveValue('');
    expect(darkInput).toHaveAttribute('placeholder', derived);
    expect(screen.getByTestId('theme-color-themePrimaryDark-auto'))
      .toHaveTextContent(`Automatic: ${derived}`);
    expect(screen.getByTestId('theme-color-themePrimaryDark-chip'))
      .toHaveStyle({ backgroundColor: derived });
    // A configured dark color is shown as is, without the automatic hint
    expect(screen.getByLabelText('Accent color (dark mode)')).toHaveValue('#1e293b');
    expect(screen.queryByTestId('theme-color-themeAccentDark-auto')).toBeNull();
  });

  it('shows the text color and the WCAG contrast of each color', async () => {
    render(<UICustomizationSettings />);
    await screen.findByLabelText('Primary color');
    const primary = screen.getByTestId('theme-color-themePrimary');
    expect(primary).toHaveTextContent(/Light text, contrast \d+\.\d:1/);
    expect(primary).toHaveTextContent('AA');
    expect(primary).not.toHaveTextContent('Below AA');

    fireEvent.change(screen.getByLabelText('Primary color'), { target: { value: '#777777' } });
    expect(primary).toHaveTextContent('Below AA');
    expect(screen.getByTestId('theme-color-themePrimary-chip'))
      .toHaveStyle({ color: '#fafafa' });

    fireEvent.change(screen.getByLabelText('Primary color'), { target: { value: '#zz' } });
    expect(primary).toHaveTextContent('Enter a hex color like #2563eb');
  });

  it('updates the text field from the color picker', async () => {
    render(<UICustomizationSettings />);
    const picker = await screen.findByLabelText('Accent color: color picker');
    fireEvent.change(picker, { target: { value: '#123456' } });
    expect(screen.getByLabelText('Accent color')).toHaveValue('#123456');
  });

  it('saves the new fields through PUT /api/settings', async () => {
    render(<UICustomizationSettings />);
    const tagline = await screen.findByLabelText('Tagline (optional)');
    fireEvent.change(tagline, { target: { name: 'appTagline', value: '  New tagline ' } });
    fireEvent.change(screen.getByLabelText('Dark mode logo URL (optional)'), {
      target: { name: 'customLogoDarkUrl', value: '/branding/acme/mark-dark.svg' },
    });
    fireEvent.click(screen.getByRole('switch', { name: 'Show "powered by Ontos" in the sidebar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save UI Settings' }));

    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody).toMatchObject({
      ui_app_tagline: 'New tagline',
      ui_custom_logo_dark_url: '/branding/acme/mark-dark.svg',
      ui_theme_primary: '#1d4ed8',
      // empty dark color: stored unset, derived at runtime
      ui_theme_primary_dark: null,
      ui_theme_accent_dark: '#1e293b',
      ui_show_powered_by: false,
    });
  });

  it('accepts app asset paths as image URLs', async () => {
    expect(isValidImageUrl('/branding/acme/mark.svg')).toBe(true);
    expect(isValidImageUrl('https://cdn.example/x.png')).toBe(true);
    expect(isValidImageUrl('//evil.example/x.png')).toBe(false);
    expect(isValidImageUrl('javascript:alert(1)')).toBe(false);
    expect(isValidImageUrl('/a b.svg')).toBe(false);

    render(<UICustomizationSettings />);
    await screen.findByLabelText('Logo URL');
    expect(screen.queryByText('Enter an HTTP or HTTPS URL, or an app path starting with /'))
      .toBeNull();
  });
});
