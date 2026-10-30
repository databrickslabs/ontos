import { useState } from 'react';
import { cn } from '@/lib/utils';
import { useTheme } from "@/components/theme/theme-provider";
import { getAssetPath } from "@/utils/asset-path";
import { resolveBrandingAssetUrl } from '@/lib/branding';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

interface UnityCatalogLogoProps {
  className?: string;
}

function prefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Product logo: the configured branding logo (dark variant in dark mode) or the default. */
export function UnityCatalogLogo({ className }: UnityCatalogLogoProps) {
  const { theme } = useTheme();
  const customLogoUrl = useUICustomizationStore((state) => state.customLogoUrl);
  const customLogoDarkUrl = useUICustomizationStore((state) => state.customLogoDarkUrl);
  const appName = useUICustomizationStore((state) => state.getAppName());
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const isDark = theme === 'dark' || (theme === 'system' && prefersDark());
  const configured = resolveBrandingAssetUrl(
    (isDark && customLogoDarkUrl) || customLogoUrl,
  );
  // Fall back to the default logo if the configured one fails to load
  const logoSrc = configured && configured !== failedSrc
    ? configured
    : getAssetPath('/ontos-logo.svg');

  return (
    <img
      className={cn('h-10 w-10 mr-2', className)}
      src={logoSrc}
      alt={appName}
      onError={() => {
        if (configured) setFailedSrc(configured);
      }}
    />
  );
}
export default UnityCatalogLogo;
