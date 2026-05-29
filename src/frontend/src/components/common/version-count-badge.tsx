/**
 * Tiny pill rendered next to a version cell that surfaces how many other
 * versions live in the same family. Click bubbles via `onClick` so the
 * parent can scope an "include_history" expansion to this single family
 * (or, more commonly, navigate into the details view where the
 * VersionNavigator already provides full prev/next + dropdown navigation).
 *
 * Renders nothing for single-version families — there's nothing useful
 * to surface, and the badge would just add visual noise.
 *
 * See PRD docs/prds/prd-version-family-and-unified-selector.md.
 */
import { useTranslation } from 'react-i18next'
import { History } from 'lucide-react'
import { cn } from '@/lib/utils'

interface VersionCountBadgeProps {
  count?: number
  className?: string
  onClick?: (e: React.MouseEvent) => void
}

export function VersionCountBadge({ count, className, onClick }: VersionCountBadgeProps) {
  const { t } = useTranslation('common')

  if (!count || count <= 1) return null

  const label = t('versionFamily.countBadge', { count, defaultValue: '{{count}} versions' })

  return (
    <button
      type="button"
      onClick={(e) => {
        // Stop the row-click handler from also firing. The badge owns this
        // click; the row navigates separately.
        e.stopPropagation()
        onClick?.(e)
      }}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
        className,
      )}
      title={label}
      aria-label={label}
    >
      <History className="h-3 w-3" />
      {count}
    </button>
  )
}

export default VersionCountBadge
