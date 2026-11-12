import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Compact segmented size toggle (S | M | L style), matching the view buttons
// on the Data Contracts detail page. Purely presentational: the caller owns the
// value and persistence. Works for any number of options (2 or 3 today).
// ---------------------------------------------------------------------------

export interface SizeToggleOption<T extends string> {
  value: T;
  /** Short visible label, e.g. 'S' or 'L'. */
  label: string;
  /** Tooltip / accessible description shown via the native title attribute. */
  title: string;
}

interface SizeToggleProps<T extends string> {
  options: SizeToggleOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  'aria-label'?: string;
}

export function SizeToggle<T extends string>({
  options,
  value,
  onChange,
  className,
  'aria-label': ariaLabel,
}: SizeToggleProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        'inline-flex items-stretch h-8 gap-px border rounded-md bg-background overflow-hidden flex-shrink-0',
        className
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Button
            key={option.value}
            type="button"
            variant={active ? 'default' : 'ghost'}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className="h-full w-8 p-0 font-semibold text-xs rounded-none"
            title={option.title}
            aria-label={option.title}
          >
            {option.label}
          </Button>
        );
      })}
    </div>
  );
}
