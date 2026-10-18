import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * A plain <select> styled to match the shadcn Radix `SelectTrigger` — same
 * border/height/padding and a single, correctly-placed ChevronDown caret. Use
 * this for simple option lists where a full Radix Select is overkill, so native
 * selects stop rendering the mismatched OS caret next to the app's dropdowns.
 *
 * `className` is applied to the wrapper (for width/layout); `selectClassName`
 * overrides the inner control if needed.
 */
export interface NativeSelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  className?: string;
  selectClassName?: string;
}

const NativeSelect = React.forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, selectClassName, children, ...props }, ref) => (
    <div className={cn('relative', className)}>
      <select
        ref={ref}
        className={cn(
          'flex h-9 w-full items-center rounded-md border border-input bg-transparent pl-3 pr-8 py-1 text-sm shadow-sm appearance-none',
          'ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          selectClassName,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 opacity-50" />
    </div>
  ),
);
NativeSelect.displayName = 'NativeSelect';

export default NativeSelect;
