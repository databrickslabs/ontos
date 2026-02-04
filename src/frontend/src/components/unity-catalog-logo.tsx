import { useState } from 'react';
import { cn } from '@/lib/utils';
import { useTheme } from "@/components/theme/theme-provider";
import { getAssetPath } from "@/utils/asset-path";
import { useUICustomizationStore } from '@/stores/ui-customization-store';

interface UnityCatalogLogoProps {
  className?: string;
}

export function UnityCatalogLogo({ className }: UnityCatalogLogoProps) {
  const { theme: _theme } = useTheme();
  const customLogoUrl = useUICustomizationStore((state) => state.customLogoUrl);
  const [logoError, setLogoError] = useState(false);
  
  // Use custom logo if set and valid, otherwise fall back to default
  const logoSrc = customLogoUrl && !logoError 
    ? customLogoUrl 
    : getAssetPath('/ontos-logo.svg');
  
  return (
    <img
      className={cn('h-10 w-10 mr-2', className)}
      src={logoSrc}
      alt="Unity Catalog Logo"
      onError={() => {
        // Fall back to default logo if custom logo fails to load
        if (customLogoUrl) {
          setLogoError(true);
        }
      }}
    />
  );
} 
export default UnityCatalogLogo;