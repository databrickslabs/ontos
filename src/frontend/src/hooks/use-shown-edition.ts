import { type Edition } from '@/config/features';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

/**
 * The edition the menus filter by: the admin-chosen edition, or `full` when the
 * admin "Show all features" switch is on. Presentation only: routes stay reachable.
 */
export function useShownEdition(): Edition {
  const edition = useUICustomizationStore((state) => state.edition);
  const showAllFeatures = useFeatureVisibilityStore((state) => state.showAllFeatures);
  return showAllFeatures ? 'full' : edition;
}
