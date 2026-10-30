import { Link } from 'react-router-dom';
import { UnityCatalogLogo } from '@/components/unity-catalog-logo';
import { cn } from '@/lib/utils';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

interface SidebarBrandProps {
  isCollapsed: boolean;
}

/**
 * Logo block at the top of the sidebar.
 *
 * Without branding config it shows only the logo (the shipped look). When a
 * display name or tagline is configured, the expanded sidebar also shows the
 * name and the tagline; `data-brand` hooks let custom CSS restyle them.
 */
export function SidebarBrand({ isCollapsed }: SidebarBrandProps) {
  const appDisplayName = useUICustomizationStore((s) => s.appDisplayName);
  const appTagline = useUICustomizationStore((s) => s.appTagline);
  const appName = useUICustomizationStore((s) => s.getAppName());
  const tagline = appTagline?.trim() || null;
  const showText = !isCollapsed && (!!appDisplayName?.trim() || !!tagline);

  return (
    <div
      className={cn(
        'flex h-16 items-center border-b shrink-0',
        showText ? 'justify-start px-3' : 'justify-center px-4',
      )}
    >
      <Link to="/" className="flex min-w-0 items-center gap-2 font-semibold">
        <UnityCatalogLogo
          className={cn('transition-all', showText ? 'h-9 w-9 mr-0 shrink-0' : 'h-10 w-10')}
        />
        {showText && (
          <span className="flex min-w-0 flex-col leading-tight" data-testid="sidebar-brand-text">
            <span data-brand="name" className="truncate text-base font-bold">
              {appName}
            </span>
            {tagline && (
              <span
                data-brand="tagline"
                className={cn(
                  'truncate text-[10px] font-medium',
                  'tracking-[0.16em] text-muted-foreground',
                )}
              >
                {tagline}
              </span>
            )}
          </span>
        )}
      </Link>
    </div>
  );
}

export default SidebarBrand;
