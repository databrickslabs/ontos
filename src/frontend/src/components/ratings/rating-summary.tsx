import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { StarRating } from './star-rating';
import { Progress } from '@/components/ui/progress';
import type { RatingAggregation } from '@/types/comments';

export interface RatingSummaryProps {
  /** Rating aggregation data */
  aggregation: RatingAggregation | null;
  /** Whether data is loading */
  loading?: boolean;
  /** Show distribution bars */
  showDistribution?: boolean;
  /** Compact mode for inline display */
  compact?: boolean;
  /** Additional class names */
  className?: string;
}

/**
 * RatingSummary - Display aggregated rating statistics
 * 
 * Shows average rating, total count, and optionally a distribution breakdown.
 */
export function RatingSummary({
  aggregation,
  loading = false,
  showDistribution = false,
  compact = false,
  className,
}: RatingSummaryProps) {
  // Calculate max count for distribution scaling (may be used in future features)
  // @ts-ignore - Kept for future use
  const maxCount = useMemo(() => {
    if (!aggregation?.distribution) return 0;
    return Math.max(...Object.values(aggregation.distribution), 1);
  }, [aggregation?.distribution]);
  void maxCount; // Suppress unused warning

  if (loading) {
    return (
      <div className={cn('animate-pulse', className)}>
        <div className="flex items-center gap-2">
          <div className="h-4 w-20 bg-muted rounded" />
          <div className="h-4 w-12 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (!aggregation || aggregation.total_ratings === 0) {
    return (
      <div className={cn('text-sm text-muted-foreground', className)}>
        No ratings yet
      </div>
    );
  }

  if (compact) {
    return (
      <div className={cn('inline-flex items-center gap-1.5', className)}>
        <StarRating value={aggregation.average_rating} size="sm" />
        <span className="text-xs text-muted-foreground">
          ({aggregation.total_ratings})
        </span>
      </div>
    );
  }

  return (
    <div className={cn('space-y-3', className)}>
      {/* Main rating display */}
      <div className="flex items-center gap-3">
        <div className="text-3xl font-bold tabular-nums">
          {aggregation.average_rating.toFixed(1)}
        </div>
        <div className="flex flex-col">
          <StarRating value={aggregation.average_rating} size="md" />
          <span className="text-xs text-muted-foreground mt-0.5">
            {aggregation.total_ratings} {aggregation.total_ratings === 1 ? 'rating' : 'ratings'}
          </span>
        </div>
      </div>

      {/* Distribution breakdown */}
      {showDistribution && (
        <div className="space-y-1.5">
          {[5, 4, 3, 2, 1].map((stars) => {
            const count = aggregation.distribution[stars] || 0;
            const percentage = aggregation.total_ratings > 0
              ? (count / aggregation.total_ratings) * 100
              : 0;

            return (
              <div key={stars} className="flex items-center gap-2 text-xs">
                <span className="w-3 text-right text-muted-foreground">{stars}</span>
                <StarRating value={1} max={1} size="sm" />
                <Progress
                  value={percentage}
                  className="h-2 flex-1"
                />
                <span className="w-8 text-right text-muted-foreground tabular-nums">
                  {count}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default RatingSummary;

