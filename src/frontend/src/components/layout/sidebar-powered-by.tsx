import { useTranslation } from 'react-i18next';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { DEFAULT_APP_NAME } from '@/lib/branding';
import { cn } from '@/lib/utils';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { getAssetPath } from '@/utils/asset-path';

interface SidebarPoweredByProps {
  isCollapsed: boolean;
}

/**
 * "powered by Ontos" footer of the sidebar.
 *
 * Shown only while a custom brand is active (a display name or a logo is
 * configured) and the UI_SHOW_POWERED_BY setting is on. The collapsed sidebar
 * keeps only the small Ontos mark, with the text in a tooltip.
 */
export function SidebarPoweredBy({ isCollapsed }: SidebarPoweredByProps) {
  const { t } = useTranslation('navigation');
  const showPoweredBy = useUICustomizationStore((s) => s.showPoweredBy);
  const isBranded = useUICustomizationStore((s) =>
    [s.appDisplayName, s.customLogoUrl, s.customLogoDarkUrl].some((v) => !!v?.trim()),
  );
  if (!showPoweredBy || !isBranded) return null;

  const label = t('branding.poweredBy', { name: DEFAULT_APP_NAME });
  const mark = (
    <img
      src={getAssetPath('/ontos-logo.svg')}
      alt=""
      aria-hidden="true"
      className="h-4 w-4 shrink-0 object-contain opacity-80"
    />
  );

  return (
    <div
      data-testid="sidebar-powered-by"
      data-brand="powered-by"
      className={cn(
        'flex h-10 shrink-0 items-center border-t text-xs text-muted-foreground',
        isCollapsed ? 'justify-center' : 'gap-2 px-4',
      )}
    >
      {isCollapsed ? (
        <TooltipProvider delayDuration={0}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                role="img"
                aria-label={label}
                tabIndex={0}
                className={cn(
                  'flex rounded-sm p-1',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
              >
                {mark}
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        <>
          {mark}
          <span className="truncate">{label}</span>
        </>
      )}
    </div>
  );
}

export default SidebarPoweredBy;
