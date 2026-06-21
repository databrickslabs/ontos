/**
 * Tests for the pure helpers exported from `estate-manager.tsx`.
 *
 * The component file pulls in many heavy modules (API, breadcrumb store,
 * graph view, i18n), so we deliberately keep these tests at the helper level
 * and avoid importing/rendering the full view.
 *
 * `buildEstateDetailPath` is the contract that has to stay in lock-step with
 * the route registered in `app.tsx` (`/estates/:estateId`). Regression guard
 * for ONT-FEAT-008: "View Details" used to navigate to `/estate-manager/${id}`,
 * an unregistered URL that rendered the 404 page.
 */
import { describe, it, expect } from 'vitest';
import { buildEstateDetailPath } from './estate-manager';

describe('buildEstateDetailPath', () => {
  it('targets the registered /estates/:estateId route', () => {
    expect(buildEstateDetailPath('1')).toBe('/estates/1');
  });

  it('does NOT derive the path from the /estate-manager list location', () => {
    // The old bug produced `/estate-manager/1`, which has no matching route
    // and rendered "404 - Page Not Found".
    expect(buildEstateDetailPath('1')).not.toBe('/estate-manager/1');
    expect(buildEstateDetailPath('1').startsWith('/estate-manager/')).toBe(false);
  });

  it('handles arbitrary estate ids (uuid-style)', () => {
    const id = 'a1b2c3d4-0000-1111-2222-333344445555';
    expect(buildEstateDetailPath(id)).toBe(`/estates/${id}`);
  });
});
