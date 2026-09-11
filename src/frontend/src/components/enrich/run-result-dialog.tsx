import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, CheckCircle2, SearchX } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import ReviewSuggestionsDialog from '@/components/enrich/review-suggestions-dialog';
import type { Run } from '@/types/term-mapping';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  run: Run | null;
  /** Live suggestion refs (term-mapping://{runId}/{suggestionId}). */
  suggestionRefs: { fqn: string }[];
  /** True while the run's suggestions are still being fetched. */
  loading?: boolean;
  /** Opt-in: hand the run's suggestions off to the Review Board via a request. */
  onRequestReview: () => void;
}

/**
 * Post-run RESULT SUMMARY. Shown after "Create run" completes instead of
 * force-opening the delegate-to-reviewer form. The user sees what the run
 * found, then chooses to:
 *   - Review matches in place (primary; opens the shared accept/reject reviewer)
 *   - Request a Review-Board handoff (secondary opt-in; onRequestReview)
 * A run with zero suggestions shows a clear "no matches" state, not a dead-end.
 */
export default function RunResultDialog({
  open,
  onOpenChange,
  run,
  suggestionRefs,
  loading = false,
  onRequestReview,
}: Props) {
  const { t } = useTranslation(['term-mapping', 'common']);
  const [reviewOpen, setReviewOpen] = useState(false);

  const count = suggestionRefs.length;
  const hasSuggestions = count > 0;

  return (
    <>
      <Dialog open={open && !reviewOpen} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {loading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : hasSuggestions ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              ) : (
                <SearchX className="h-5 w-5 text-muted-foreground" />
              )}
              {t('runResult.title', 'Run complete')}
            </DialogTitle>
            <DialogDescription>
              {loading
                ? t('runResult.loading', 'Gathering suggested matches…')
                : hasSuggestions
                  ? t('runResult.found', {
                      count,
                      defaultValue: 'Found {{count}} suggested match(es) to review.',
                    })
                  : t(
                      'runResult.none',
                      'No matches were found for this run. Nothing to review.',
                    )}
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t('common:actions.close', 'Close')}
            </Button>
            {!loading && hasSuggestions && (
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={onRequestReview}>
                  {t('runResult.requestReview', 'Request review')}
                </Button>
                <Button onClick={() => setReviewOpen(true)}>
                  {t('runResult.reviewMatches', 'Review matches')}
                </Button>
              </div>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* In-place accept/reject over this run's live suggestions. */}
      <ReviewSuggestionsDialog
        open={reviewOpen}
        onOpenChange={(o) => {
          setReviewOpen(o);
          if (!o) onOpenChange(false);
        }}
        schemeName={run?.comment || t('runResult.thisRun', 'this run')}
        suggestionRefs={suggestionRefs}
        reviewBoardHref="/data-asset-reviews"
      />
    </>
  );
}
