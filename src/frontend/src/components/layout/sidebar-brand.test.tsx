/**
 * Sidebar brand block: the shipped look when branding is unset, and the
 * configured name, tagline and logo (light/dark) when it is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SidebarBrand } from './sidebar-brand';
import { ThemeProvider } from '@/components/theme/theme-provider';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

// The store fetches its settings on import; keep that request inert.
vi.hoisted(() => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch;
});

const UNSET = {
  appDisplayName: null,
  appShortName: null,
  appTagline: null,
  customLogoUrl: null,
  customLogoDarkUrl: null,
};

function renderBrand(isCollapsed = false) {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <SidebarBrand isCollapsed={isCollapsed} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('SidebarBrand', () => {
  beforeEach(() => {
    localStorage.removeItem('vite-ui-theme');
    document.documentElement.classList.remove('dark');
    useUICustomizationStore.getState().setSettings(UNSET);
  });

  it('shows only the default logo when no branding is configured', () => {
    renderBrand();
    const logo = screen.getByRole('img');
    expect(logo.getAttribute('src')).toBe('/ontos-logo.svg');
    expect(logo.getAttribute('alt')).toBe('Ontos');
    expect(screen.queryByTestId('sidebar-brand-text')).toBeNull();
  });

  it('shows the configured name, tagline and logo', () => {
    useUICustomizationStore.getState().setSettings({
      appDisplayName: 'Acme Graph',
      appTagline: 'Ontology of Acme',
      customLogoUrl: '/branding/acme/mark.svg',
    });
    renderBrand();
    expect(screen.getByText('Acme Graph').getAttribute('data-brand')).toBe('name');
    expect(screen.getByText('Ontology of Acme').getAttribute('data-brand')).toBe('tagline');
    const logo = screen.getByRole('img');
    expect(logo.getAttribute('src')).toBe('/branding/acme/mark.svg');
    expect(logo.getAttribute('alt')).toBe('Acme Graph');
  });

  it('keeps only the logo when the sidebar is collapsed', () => {
    useUICustomizationStore.getState().setSettings({
      appDisplayName: 'Acme Graph',
      appTagline: 'Ontology of Acme',
    });
    renderBrand(true);
    expect(screen.queryByTestId('sidebar-brand-text')).toBeNull();
    expect(screen.getByRole('img')).toBeTruthy();
  });

  it('uses the dark logo in dark mode and the light one otherwise', () => {
    useUICustomizationStore.getState().setSettings({
      appDisplayName: 'Acme Graph',
      customLogoUrl: 'https://cdn.example/light.svg',
      customLogoDarkUrl: 'https://cdn.example/dark.svg',
    });
    const { unmount } = renderBrand();
    expect(screen.getByRole('img').getAttribute('src')).toBe('https://cdn.example/light.svg');
    unmount();

    localStorage.setItem('vite-ui-theme', 'dark');
    renderBrand();
    expect(screen.getByRole('img').getAttribute('src')).toBe('https://cdn.example/dark.svg');
  });
});
