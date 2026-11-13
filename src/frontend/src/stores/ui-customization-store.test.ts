import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useUICustomizationStore } from './ui-customization-store';

function mockBootstrap(body: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) }),
  );
}

describe('ui-customization store: fetchSettings', () => {
  beforeEach(() => {
    document.head.innerHTML = '';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('maps the branding fields and applies the theme colors', async () => {
    mockBootstrap({
      app_tagline: 'Ontology of Acme',
      custom_logo_dark_url: '/branding/acme/logo-dark.svg',
      theme: { primary: '#2563eb', primary_dark: '#93c5fd', accent: null, accent_dark: '#1e293b' },
      show_powered_by: false,
    });
    await useUICustomizationStore.getState().fetchSettings();
    const state = useUICustomizationStore.getState();
    expect(state.appTagline).toBe('Ontology of Acme');
    expect(state.customLogoDarkUrl).toBe('/branding/acme/logo-dark.svg');
    expect(state.theme).toEqual({
      primary: '#2563eb',
      primaryDark: '#93c5fd',
      accent: null,
      accentDark: '#1e293b',
    });
    expect(state.showPoweredBy).toBe(false);
    expect(document.getElementById('branding-theme')?.textContent).toContain(
      '--primary: 221 83% 53%',
    );
  });

  it('keeps the default look when the branding fields are missing', async () => {
    mockBootstrap({});
    await useUICustomizationStore.getState().fetchSettings();
    const state = useUICustomizationStore.getState();
    expect(state.appTagline).toBeNull();
    expect(state.customLogoDarkUrl).toBeNull();
    expect(state.theme).toEqual({
      primary: null,
      primaryDark: null,
      accent: null,
      accentDark: null,
    });
    expect(state.showPoweredBy).toBe(true);
    expect(document.getElementById('branding-theme')).toBeNull();
  });
});
