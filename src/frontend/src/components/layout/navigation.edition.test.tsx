/**
 * The sidebar follows the admin-chosen edition: Essentials shows the curated set,
 * and the admin "Show all features" switch brings back the full menu.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { features } from '@/config/features';

vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline.
  globalThis.fetch = (async () => ({ ok: false, json: async () => ({}) })) as any;
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    permissions: { search: 'Read-only' },
    isLoading: false,
    hasPermission: () => true,
  }),
}));

import { Navigation } from './navigation';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';

const ESSENTIALS_PATHS = [
  '/search', '/data-catalog', '/assets', '/concepts', '/data-asset-reviews', '/my-requests',
];

const navPaths = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('a'))
    .map((a) => a.getAttribute('href'))
    .filter((href): href is string => !!href && href !== '/');

const setVisibility = (showAllFeatures: boolean) =>
  useFeatureVisibilityStore.setState({
    showBeta: true,
    showAlpha: true,
    showAllFeatures,
    allowedMaturities: ['ga', 'beta', 'alpha'],
  });

describe('Navigation by edition', () => {
  beforeEach(() => {
    useUICustomizationStore.setState({ edition: 'full' });
    setVisibility(false);
  });

  it('shows every feature in Full', () => {
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container).sort()).toEqual(features.map((f) => f.path).sort());
  });

  it('shows only the Essentials set in Essentials', () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container).sort()).toEqual([...ESSENTIALS_PATHS].sort());
  });

  it('"Show all features" restores the full menu in Essentials, and updates live', () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container)).toHaveLength(ESSENTIALS_PATHS.length);

    act(() => useFeatureVisibilityStore.getState().actions.toggleShowAllFeatures());
    expect(navPaths(container).sort()).toEqual(features.map((f) => f.path).sort());
  });

  it('keeps the maturity filter when showing all features', () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    useFeatureVisibilityStore.setState({
      showAllFeatures: true, showBeta: false, showAlpha: false, allowedMaturities: ['ga'],
    });
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    const expected = features.filter((f) => f.maturity === 'ga').map((f) => f.path);
    expect(navPaths(container).sort()).toEqual(expected.sort());
  });
});
