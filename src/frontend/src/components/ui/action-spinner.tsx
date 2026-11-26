import { Loader2, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ActionSpinnerProps {
  className?: string;
  /** Icon to spin, e.g. RefreshCw for a refresh button; defaults to Loader2 */
  icon?: LucideIcon;
  /** Spins only while true, for an icon that is also shown at rest */
  spinning?: boolean;
}

/**
 * The spinner for an action in progress: a button that saves, submits,
 * deletes or runs; an inline refresh next to content already shown; a
 * background job's progress. Content that is loading gets a skeleton instead
 * (components/common/list-view-skeleton.tsx, components/common/content-skeleton.tsx).
 * The only place `animate-spin` is allowed (see eslint.config.js).
 */
export function ActionSpinner({ className, icon: Icon = Loader2, spinning = true }: ActionSpinnerProps) {
  return <Icon aria-hidden="true" className={cn('h-4 w-4', spinning && 'animate-spin', className)} />;
}

export default ActionSpinner;
