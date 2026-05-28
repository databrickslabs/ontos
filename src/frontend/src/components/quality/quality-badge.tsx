import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useApi } from '@/hooks/use-api';
import { scoreColor, type EntityKind, type QualitySummary } from '@/types/quality';

export interface QualityBadgeProps {
  /** Entity type (data_product, data_contract, asset, ...) */
  entityType: EntityKind;
  /** Entity ID */
  entityId: string;
  /** When true, uses the product aggregation endpoint (rolls up child contracts). */
  productAggregation?: boolean;
  /** Size variant */
  size?: 'sm' | 'md';
  /** Additional class names */
  className?: string;
  /** Click handler (optional) */
  onClick?: (e: React.MouseEvent) => void;
}

/**
 * QualityBadge - Compact inline data-quality indicator for cards.
 *
 * Fetches the quality summary for the given entity and renders a small
 * color-coded percentage chip. Returns null when there are no measurements,
 * so cards stay clean for entities without quality data.
 */
export function QualityBadge({
  entityType,
  entityId,
  productAggregation,
  size = 'sm',
  className,
  onClick,
}: QualityBadgeProps) {
  const { get } = useApi();
  const [summary, setSummary] = useState<QualitySummary | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!entityType || !entityId) return;
    let cancelled = false;

    const url = productAggregation
      ? `/api/data-products/${entityId}/quality-summary`
      : `/api/entities/${entityType}/${entityId}/quality-items/summary`;

    const fetchSummary = async () => {
      try {
        const response = await get<QualitySummary>(url);
        if (cancelled) return;
        if (!response.error && response.data) {
          setSummary(response.data);
        }
      } catch {
        // Silent fail - quality info is not critical for card render.
      } finally {
        if (!cancelled) setLoaded(true);
      }
    };

    fetchSummary();
    return () => {
      cancelled = true;
    };
  }, [entityType, entityId, productAggregation, get]);

  if (!loaded || !summary || summary.items_count === 0) {
    return null;
  }

  const pct = summary.overall_score_percent;
  const color = scoreColor(pct);

  const gaugePx = size === 'sm' ? 14 : 16;
  const innerPx = gaugePx - 4;
  const textSize = size === 'sm' ? 'text-xs' : 'text-sm';

  const measuredAtLabel = summary.measured_at
    ? `\nLast measured ${new Date(summary.measured_at).toLocaleString()}`
    : '';

  // Tint background lightly based on score band so the chip reads at a glance.
  const bandBg =
    pct >= 90
      ? 'bg-green-50 dark:bg-green-950/30 hover:bg-green-100 dark:hover:bg-green-900/40'
      : pct >= 70
        ? 'bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-900/40'
        : 'bg-red-50 dark:bg-red-950/30 hover:bg-red-100 dark:hover:bg-red-900/40';

  // Mini conic-gradient gauge — mirrors the large gauge in EntityQualityPanel.
  const gaugeStyle: React.CSSProperties = {
    width: gaugePx,
    height: gaugePx,
    borderRadius: '50%',
    background: `conic-gradient(${color} 0% ${pct}%, hsl(var(--muted-foreground) / 0.25) ${pct}% 100%)`,
    flexShrink: 0,
  };
  const gaugeInnerStyle: React.CSSProperties = {
    width: innerPx,
    height: innerPx,
    borderRadius: '50%',
    background: 'hsl(var(--background))',
  };

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full leading-none',
        bandBg,
        onClick && 'cursor-pointer transition-colors',
        className,
      )}
      onClick={onClick}
      title={`Data Quality: ${pct.toFixed(1)}% (${summary.items_count} measurement${summary.items_count === 1 ? '' : 's'})${measuredAtLabel}`}
    >
      <span style={gaugeStyle} aria-hidden>
        <span style={gaugeInnerStyle} className="block m-[2px]" />
      </span>
      <span
        className={cn(textSize, 'font-semibold tabular-nums leading-none')}
        style={{ color }}
      >
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

export default QualityBadge;
