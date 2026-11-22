import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The spinner for an action in progress: a button that saves, submits,
 * deletes or runs; an inline refresh next to content already shown; a
 * background job's progress. Content that is loading gets a skeleton instead
 * (components/common/list-view-skeleton.tsx, components/common/content-skeleton.tsx).
 */
export function ActionSpinner({ className }: { className?: string }) {
  return <Loader2 aria-hidden="true" className={cn('h-4 w-4 animate-spin', className)} />;
}

export default ActionSpinner;
