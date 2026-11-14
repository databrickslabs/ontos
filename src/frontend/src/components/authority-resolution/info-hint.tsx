import type { ReactNode } from 'react';
import { Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/** Circled-i icon that shows authoring guidance on hover/focus instead of inline text. */
export function InfoHint({ children, contentClassName }: { children: ReactNode; contentClassName?: string }) {
  const { t } = useTranslation(['authority-resolution']);
  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>
        <button type="button" aria-label={t('infoHint.ariaLabel')} className="inline-flex text-muted-foreground hover:text-foreground">
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        className={cn('max-w-sm text-xs font-normal leading-relaxed', contentClassName)}
        // The tooltip is portaled outside the dialog, whose scroll lock cancels
        // wheel/trackpad scrolling there; apply the delta ourselves so long
        // (scrollable) hints still scroll.
        onWheel={(e) => { e.currentTarget.scrollTop += e.deltaY; }}
      >
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

/** Dialog section title with an optional InfoHint. */
export function SectionTitle({ title, info }: { title: string; info?: ReactNode }) {
  return (
    <div className="text-sm font-semibold text-muted-foreground pt-2 flex items-center gap-1.5">
      {title}
      {info && <InfoHint>{info}</InfoHint>}
    </div>
  );
}
