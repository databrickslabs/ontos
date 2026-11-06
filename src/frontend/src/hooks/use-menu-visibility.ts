import { type Edition, type FeatureMaturity } from '@/config/features';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { useIsOntosAdmin } from '@/hooks/use-is-ontos-admin';

/** Maturities non-admins see in Essentials, where they have no maturity switches. */
export const ESSENTIALS_DEFAULT_MATURITIES: FeatureMaturity[] = ['ga', 'beta'];

/**
 * What the menus (sidebar, home quick actions, About) filter by. Presentation only.
 *
 * - edition: the admin-chosen one, or `full` while an admin has "Show all features" on
 *   (a stored `true` has no effect for a non-admin).
 * - allowedMaturities: the user's beta/alpha switches, except for non-admins in
 *   Essentials, who can't change them there and get the defaults instead.
 */
export function useMenuVisibility(): {
  edition: Edition;
  allowedMaturities: FeatureMaturity[];
} {
  const edition = useUICustomizationStore((state) => state.edition);
  const showAllFeatures = useFeatureVisibilityStore((state) => state.showAllFeatures);
  const storedMaturities = useFeatureVisibilityStore((state) => state.allowedMaturities);
  const isAdmin = useIsOntosAdmin();

  if (edition === 'essentials' && !isAdmin) {
    return { edition, allowedMaturities: ESSENTIALS_DEFAULT_MATURITIES };
  }
  return {
    edition: isAdmin && showAllFeatures ? 'full' : edition,
    allowedMaturities: storedMaturities,
  };
}
