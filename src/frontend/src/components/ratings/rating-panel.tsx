import { useState, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
// StarRating commented out - not currently used in panel
// import { StarRating } from './star-rating';
import { StarRatingInput } from './star-rating-input';
import { RatingSummary } from './rating-summary';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Loader2, Send, MessageSquare } from 'lucide-react';
import { useComments } from '@/hooks/use-comments';
import type { RatingAggregation } from '@/types/comments';

export interface RatingPanelProps {
  /** Entity type (data_product, dataset, etc.) */
  entityType: string;
  /** Entity ID */
  entityId: string;
  /** Panel title */
  title?: string;
  /** Show distribution breakdown */
  showDistribution?: boolean;
  /** Compact mode */
  compact?: boolean;
  /** Allow submitting ratings */
  allowSubmit?: boolean;
  /** Additional class names */
  className?: string;
}

/**
 * RatingPanel - Complete rating display and submission panel
 * 
 * Combines RatingSummary with StarRatingInput for a full rating experience.
 */
export function RatingPanel({
  entityType,
  entityId,
  title = 'Ratings',
  showDistribution = true,
  compact = false,
  allowSubmit = true,
  className,
}: RatingPanelProps) {
  const { createRating, fetchRatingAggregation, ratingAggregation, loading: _loading } = useComments();
  
  const [localAggregation, setLocalAggregation] = useState<RatingAggregation | null>(null);
  const [selectedRating, setSelectedRating] = useState<number>(0);
  const [reviewText, setReviewText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showReviewInput, setShowReviewInput] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Load rating aggregation on mount
  useEffect(() => {
    const loadRatings = async () => {
      setIsLoading(true);
      try {
        const data = await fetchRatingAggregation(entityType, entityId);
        if (data) {
          setLocalAggregation(data);
          // Pre-select user's current rating if they have one
          if (data.user_current_rating) {
            setSelectedRating(data.user_current_rating);
          }
        }
      } finally {
        setIsLoading(false);
      }
    };
    loadRatings();
  }, [entityType, entityId, fetchRatingAggregation]);

  // Sync with hook state
  useEffect(() => {
    if (ratingAggregation) {
      setLocalAggregation(ratingAggregation);
    }
  }, [ratingAggregation]);

  const handleRatingChange = useCallback((rating: number) => {
    setSelectedRating(rating);
    // Show review input when user selects a rating
    if (!showReviewInput) {
      setShowReviewInput(true);
    }
  }, [showReviewInput]);

  const handleSubmit = async () => {
    if (selectedRating === 0) return;

    setIsSubmitting(true);
    try {
      await createRating(entityType, entityId, selectedRating, reviewText || undefined);
      // Refresh aggregation after submission
      const updated = await fetchRatingAggregation(entityType, entityId);
      if (updated) {
        setLocalAggregation(updated);
      }
      // Reset form
      setReviewText('');
      setShowReviewInput(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const userHasRated = localAggregation?.user_current_rating != null;

  if (compact) {
    return (
      <div className={cn('flex items-center gap-2', className)}>
        <RatingSummary aggregation={localAggregation} loading={isLoading} compact />
      </div>
    );
  }

  return (
    <Card className={cn('', className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <span>{title}</span>
          {userHasRated && (
            <span className="text-xs font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded">
              You rated: {localAggregation?.user_current_rating}★
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Aggregated summary */}
        <RatingSummary
          aggregation={localAggregation}
          loading={isLoading}
          showDistribution={showDistribution}
        />

        {/* Rating input */}
        {allowSubmit && (
          <div className="pt-3 border-t space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
                {userHasRated ? 'Update your rating' : 'Rate this item'}
              </span>
              <StarRatingInput
                value={selectedRating}
                onChange={handleRatingChange}
                disabled={isSubmitting}
              />
            </div>

            {/* Review text input (shown after selecting stars) */}
            {showReviewInput && selectedRating > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span>Add a review (optional)</span>
                </div>
                <Textarea
                  value={reviewText}
                  onChange={(e) => setReviewText(e.target.value)}
                  placeholder="Share your experience..."
                  className="resize-none h-20"
                  disabled={isSubmitting}
                />
                <div className="flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowReviewInput(false);
                      setReviewText('');
                      setSelectedRating(localAggregation?.user_current_rating || 0);
                    }}
                    disabled={isSubmitting}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleSubmit}
                    disabled={isSubmitting || selectedRating === 0}
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin mr-1" />
                        Submitting...
                      </>
                    ) : (
                      <>
                        <Send className="h-4 w-4 mr-1" />
                        Submit Rating
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default RatingPanel;

