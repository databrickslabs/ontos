import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useTheme } from "@/components/theme/theme-provider";
import { getAssetPath } from "@/utils/asset-path";
import { resolveBrandingAssetUrl } from '@/lib/branding';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

interface UnityCatalogLogoProps {
  className?: string;
}

const DARK_QUERY = '(prefers-color-scheme: dark)';

function prefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(DARK_QUERY).matches;
}

/** The OS color scheme, kept current when it changes (used while the theme is "system"). */
function useSystemPrefersDark(): boolean {
  const [dark, setDark] = useState(prefersDark);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (e: { matches: boolean }) => setDark(e.matches);
    setDark(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return dark;
}

/** Product logo: the configured branding logo (dark variant in dark mode) or the default. */
export function UnityCatalogLogo({ className }: UnityCatalogLogoProps) {
  const { theme } = useTheme();
  const customLogoUrl = useUICustomizationStore((state) => state.customLogoUrl);
  const customLogoDarkUrl = useUICustomizationStore((state) => state.customLogoDarkUrl);
  const appName = useUICustomizationStore((state) => state.getAppName());
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const systemDark = useSystemPrefersDark();
  const isDark = theme === 'dark' || (theme === 'system' && systemDark);
  const configured = resolveBrandingAssetUrl(
    (isDark && customLogoDarkUrl) || customLogoUrl,
  );
  // Fall back to the default logo if the configured one fails to load
  const logoSrc = configured && configured !== failedSrc
    ? configured
    : getAssetPath('/ontos-logo.svg');

  return (
    <img
      // object-contain keeps a non-square or round logo's aspect ratio inside the
      // fixed box, and shrink-0 stops a flex row from squeezing it (issue #226).
      className={cn('h-10 w-10 mr-2 shrink-0 object-contain', className)}
      src={logoSrc}
      alt={appName}
      onError={() => {
        if (configured) setFailedSrc(configured);
      }}
    />
  );
}
export default UnityCatalogLogo;
