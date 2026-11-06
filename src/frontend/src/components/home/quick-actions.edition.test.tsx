/** Home quick actions follow the edition like the sidebar does. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';

vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline.
  globalThis.fetch = (async () => ({ ok: false, json: async () => ({}) })) as any;
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ isLoading: false, hasPermission: () => true }),
}));

import QuickActions from './quick-actions';
import { useUICustomizationStore, toEdition } from '@/stores/ui-customization-store';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';

const actionPaths = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));

describe('QuickActions by edition', () => {
  beforeEach(() => {
    useFeatureVisibilityStore.setState({
      showAllFeatures: false, allowedMaturities: ['ga', 'beta', 'alpha'],
    });
  });

  it('Full offers products, contracts and compliance', () => {
    useUICustomizationStore.setState({ edition: 'full' });
    const { container } = renderWithProviders(<QuickActions />);
    expect(actionPaths(container)).toEqual(
      expect.arrayContaining(['/data-contracts', '/compliance', '/estate-manager']),
    );
  });

  it('Essentials offers only Essentials features', () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    const { container } = renderWithProviders(<QuickActions />);
    expect(actionPaths(container).sort()).toEqual(
      ['/assets', '/concepts', '/data-asset-reviews', '/data-catalog', '/search'],
    );
  });
});

describe('toEdition', () => {
  it('keeps a known edition and falls back to full otherwise', () => {
    expect(toEdition('essentials')).toBe('essentials');
    expect(toEdition('full')).toBe('full');
    expect(toEdition('pro')).toBe('full');
    expect(toEdition(undefined)).toBe('full');
  });
});
