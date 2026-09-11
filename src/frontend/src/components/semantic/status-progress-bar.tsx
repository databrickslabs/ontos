import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Compact lifecycle progress bar for a concept. Shows the full ordered chain
 * (Draft → Under review → Approved → Published → Certified) with the current
 * position highlighted, so users get full-lifecycle visibility even though the
 * "Change status" dropdown only offers the single valid next hop.
 *
 * Deprecated / archived are terminal off-ramps, not part of the forward bar; a
 * concept in one of those states shows that terminal state as a trailing chip.
 */
const FORWARD_CHAIN = ['draft', 'under_review', 'approved', 'published', 'certified'] as const;
const TERMINAL = ['deprecated', 'archived'] as const;

interface Props {
  status: string;
  className?: string;
}

export function StatusProgressBar({ status, className }: Props) {
  const { t } = useTranslation(['semantic-models']);
  const isTerminal = (TERMINAL as readonly string[]).includes(status);
  const currentIdx = FORWARD_CHAIN.indexOf(status as (typeof FORWARD_CHAIN)[number]);

  const label = (s: string) => t(`semantic-models:status.${s}`, s.replace(/_/g, ' '));

  return (
    <div className={cn('flex flex-wrap items-center gap-1 text-[11px]', className)}>
      {FORWARD_CHAIN.map((s, i) => {
        const done = !isTerminal && currentIdx > i;
        const current = !isTerminal && currentIdx === i;
        return (
          <div key={s} className="flex items-center gap-1">
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5',
                current && 'border-primary bg-primary text-primary-foreground font-medium',
                done && 'border-muted-foreground/30 bg-muted text-muted-foreground',
                !current && !done && 'border-dashed border-muted-foreground/30 text-muted-foreground',
              )}
            >
              {done && <Check className="h-3 w-3" />}
              {label(s)}
            </span>
            {i < FORWARD_CHAIN.length - 1 && (
              <span className="text-muted-foreground/40">→</span>
            )}
          </div>
        );
      })}
      {isTerminal && (
        <>
          <span className="text-muted-foreground/40">·</span>
          <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
            {label(status)}
          </span>
        </>
      )}
    </div>
  );
}
