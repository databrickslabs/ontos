/**
 * The layout waits for the branding settings before its first paint, so the
 * default logo and colors don't flash before the configured ones.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import Layout from './layout';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

vi.mock('./sidebar', () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock('./header', () => ({ Header: () => null }));
vi.mock('@/components/ui/breadcrumbs', () => ({ Breadcrumbs: () => null }));
vi.mock('@/components/copilot/copilot-panel', () => ({ default: () => null }));

describe('Layout branding gate', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
  });

  it('renders the shell only once the branding settings are loaded', () => {
    useUICustomizationStore.setState({ isLoaded: false });
    render(<Layout><div>content</div></Layout>);
    expect(screen.getByTestId('branding-pending')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar')).toBeNull();
    expect(screen.queryByText('content')).toBeNull();

    act(() => {
      useUICustomizationStore.setState({ isLoaded: true });
    });
    expect(screen.queryByTestId('branding-pending')).toBeNull();
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    expect(screen.getByText('content')).toBeInTheDocument();
  });
});
