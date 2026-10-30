/**
 * "powered by Ontos" sidebar footer: hidden without a custom brand, shown
 * (text or collapsed mark + tooltip) with one, and hidden by the setting.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SidebarPoweredBy } from './sidebar-powered-by';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

// The store fetches its settings on import; keep that request inert.
vi.hoisted(() => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch;
});

const UNSET = {
  appDisplayName: null,
  customLogoUrl: null,
  customLogoDarkUrl: null,
  showPoweredBy: true,
};

describe('SidebarPoweredBy', () => {
  beforeEach(() => {
    useUICustomizationStore.getState().setSettings(UNSET);
  });

  it('renders nothing with the default branding', () => {
    useUICustomizationStore.getState().setSettings({ appDisplayName: '   ' });
    const { container } = render(<SidebarPoweredBy isCollapsed={false} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the small Ontos mark and the text when a display name is set', () => {
    useUICustomizationStore.getState().setSettings({ appDisplayName: 'Acme Graph' });
    render(<SidebarPoweredBy isCollapsed={false} />);
    const footer = screen.getByTestId('sidebar-powered-by');
    expect(footer).toHaveTextContent('powered by Ontos');
    const mark = footer.querySelector('img');
    expect(mark?.getAttribute('src')).toBe('/ontos-logo.svg');
    expect(mark?.className).toContain('object-contain');
  });

  it('counts a custom logo alone as a custom brand', () => {
    useUICustomizationStore.getState().setSettings({ customLogoUrl: '/branding/acme/mark.svg' });
    render(<SidebarPoweredBy isCollapsed={false} />);
    expect(screen.getByTestId('sidebar-powered-by')).toBeInTheDocument();
  });

  it('keeps only the mark when collapsed and shows the text in a tooltip', async () => {
    useUICustomizationStore.getState().setSettings({ appDisplayName: 'Acme Graph' });
    render(<SidebarPoweredBy isCollapsed />);
    const footer = screen.getByTestId('sidebar-powered-by');
    expect(footer).not.toHaveTextContent('powered by Ontos');
    const trigger = screen.getByRole('img', { name: 'powered by Ontos' });

    await userEvent.hover(trigger);
    expect((await screen.findAllByText('powered by Ontos')).length).toBeGreaterThan(0);
  });

  it('is hidden when the powered-by setting is off', () => {
    useUICustomizationStore.getState().setSettings({
      appDisplayName: 'Acme Graph',
      showPoweredBy: false,
    });
    const { container } = render(<SidebarPoweredBy isCollapsed={false} />);
    expect(container.firstChild).toBeNull();
  });
});
