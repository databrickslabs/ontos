/**
 * UnityCatalogLogo follows the OS color scheme live while the theme is "system".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { UnityCatalogLogo } from './unity-catalog-logo';
import { ThemeProvider } from '@/components/theme/theme-provider';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

// The store fetches its settings on import; keep that request inert.
vi.hoisted(() => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch;
});

type Listener = (e: { matches: boolean }) => void;

function mockSystemScheme(initialDark: boolean) {
  let dark = initialDark;
  const listeners = new Set<Listener>();
  window.matchMedia = ((query: string) => ({
    get matches() {
      return dark;
    },
    media: query,
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
    addListener: (l: Listener) => listeners.add(l),
    removeListener: (l: Listener) => listeners.delete(l),
    dispatchEvent: () => false,
    onchange: null,
  })) as unknown as typeof window.matchMedia;
  return (next: boolean) => {
    dark = next;
    listeners.forEach((l) => l({ matches: next }));
  };
}

describe('UnityCatalogLogo', () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    localStorage.removeItem('vite-ui-theme');
    useUICustomizationStore.getState().setSettings({
      customLogoUrl: '/branding/acme/light.svg',
      customLogoDarkUrl: '/branding/acme/dark.svg',
    });
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it('switches to the dark logo when the OS theme changes in system mode', () => {
    const setSystemDark = mockSystemScheme(false);
    render(
      <ThemeProvider>
        <UnityCatalogLogo />
      </ThemeProvider>,
    );
    expect(screen.getByRole('img').getAttribute('src')).toBe('/branding/acme/light.svg');
    act(() => setSystemDark(true));
    expect(screen.getByRole('img').getAttribute('src')).toBe('/branding/acme/dark.svg');
    act(() => setSystemDark(false));
    expect(screen.getByRole('img').getAttribute('src')).toBe('/branding/acme/light.svg');
  });

  it('falls back to the default logo when the configured one fails to load', () => {
    mockSystemScheme(false);
    render(
      <ThemeProvider>
        <UnityCatalogLogo />
      </ThemeProvider>,
    );
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByRole('img').getAttribute('src')).toMatch(/\/ontos-logo\.svg$/);
    // A different configured URL is tried again
    act(() => useUICustomizationStore.getState().setSettings({
      customLogoUrl: '/branding/acme/other.svg',
    }));
    expect(screen.getByRole('img').getAttribute('src')).toBe('/branding/acme/other.svg');
  });
});
