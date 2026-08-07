import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Check, ExternalLink, Info, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import TermMappingSuggestionReview from '@/components/term-mapping/suggestion-review';

// ---------------------------------------------------------------------------
// Inline "Review suggested matches" surface for the Map lane.
//
// Per the wireframe, review happens IN A MODAL — we do NOT route away to the
// Review Board. The accept/reject surface is the SAME shared component the
// term-mapping / MDM flows use (TermMappingSuggestionReview), embedded here.
//
// Two rendering paths:
//   1. When we have real suggestion FQNs (term-mapping://{runId}/{suggestionId})
//      we mount the shared reviewer, which talks to the live
//      /api/term-mappings decision endpoints. Accept/reject happens in-place.
//   2. When no run/suggestion context is available (the common case until the
//      coverage read-model wires a run id per scheme), we render a clearly
//      labelled placeholder list mirroring the same accept/reject affordance.
//      The placeholder rows are inert.
//
// TODO(cb-v2): the coverage read-model endpoint (see coverage-matrix.tsx) must
//   also return the term-mapping run id + pending suggestion ids per scheme so
//   we can hand real FQNs to the shared reviewer here. No endpoint returns that
//   mapping today — do NOT fabricate one.
// ---------------------------------------------------------------------------

export interface PendingSuggestionRef {
  /** FQN: term-mapping://{runId}/{suggestionId} — feeds the shared reviewer. */
  fqn: string;
}

/** Inert sample rows shown when no live run context exists yet. */
export interface PlaceholderSuggestion {
  id: string;
  concept: string;
  target: string;
  reason: string;
  confidence: 'high' | 'medium' | 'low';
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  schemeName: string;
  /** Live suggestion refs; when present the shared reviewer is embedded. */
  suggestionRefs?: PendingSuggestionRef[];
  /** Sample rows rendered when no live refs are available. */
  placeholders?: PlaceholderSuggestion[];
  /** Count of schema-drift items to resolve (placeholder metric). */
  driftCount?: number;
  /** Optional escape hatch to the full Review Board. */
  reviewBoardHref?: string;
}

const CONF_CLASS: Record<PlaceholderSuggestion['confidence'], string> = {
  high: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100',
  medium: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100',
  low: 'bg-rose-100 text-rose-900 dark:bg-rose-900/50 dark:text-rose-100',
};

export default function ReviewSuggestionsDialog({
  open,
  onOpenChange,
  schemeName,
  suggestionRefs,
  placeholders = [],
  driftCount = 0,
  reviewBoardHref,
}: Props) {
  const { t } = useTranslation(['concepts', 'term-mapping', 'common']);
  const [activeIndex, setActiveIndex] = useState(0);

  const hasLive = Array.isArray(suggestionRefs) && suggestionRefs.length > 0;
  const liveRef = hasLive ? suggestionRefs![Math.min(activeIndex, suggestionRefs!.length - 1)] : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {t('enrich.review.title', 'Review suggested matches')}
            <span className="text-sm font-normal text-muted-foreground">· {schemeName}</span>
          </DialogTitle>
          <DialogDescription className="flex items-center gap-1.5">
            {t(
              'enrich.review.subtitle',
              'Accept or reject each concept-to-Asset match. Nothing syncs until you accept it.',
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" aria-label="about" className="text-muted-foreground">
                    <Info className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="max-w-[280px]">
                  {t(
                    'enrich.review.sharedTip',
                    'This is the shared Review Board surface, embedded here. It is the same side-by-side accept/reject MDM and table functions use, so it behaves identically everywhere. Accepted links sync on next delivery.',
                  )}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[62vh] space-y-3 overflow-y-auto">
          {hasLive && liveRef ? (
            // Real accept/reject via the shared reviewer, in-place.
            <TermMappingSuggestionReview
              key={liveRef.fqn}
              assetFqn={liveRef.fqn}
              currentIndex={activeIndex + 1}
              totalCount={suggestionRefs!.length}
              hasNext={activeIndex < suggestionRefs!.length - 1}
              onNext={() => setActiveIndex((i) => Math.min(i + 1, suggestionRefs!.length - 1))}
            />
          ) : (
            <>
              <p className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                {t(
                  'enrich.review.placeholderNote',
                  'Sample matches. Live review activates once the coverage read-model returns a term-mapping run id per scheme; these rows are then served by the shared reviewer and accept/reject writes through.',
                )}
              </p>
              {placeholders.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-3 rounded-md border px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 text-sm">
                      <span className="font-medium">{s.concept}</span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {s.target}
                      </span>
                    </div>
                    <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{s.reason}</p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${CONF_CLASS[s.confidence]}`}
                  >
                    {s.confidence}
                  </span>
                  <div className="flex shrink-0 gap-1.5">
                    <Button variant="outline" size="sm" className="h-7 px-2 text-xs" disabled>
                      <X className="mr-1 h-3.5 w-3.5" />
                      {t('enrich.review.reject', 'Reject')}
                    </Button>
                    <Button size="sm" className="h-7 px-2 text-xs" disabled>
                      <Check className="mr-1 h-3.5 w-3.5" />
                      {t('enrich.review.accept', 'Accept')}
                    </Button>
                  </div>
                </div>
              ))}
              {driftCount > 0 && (
                <div className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
                  <span>{t('enrich.review.drift', 'Schema drift to resolve')}</span>
                  <Badge variant="outline">{driftCount}</Badge>
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="items-center justify-between sm:justify-between">
          {reviewBoardHref ? (
            <a
              href={reviewBoardHref}
              className="mr-auto inline-flex items-center gap-1 text-xs text-sky-700 hover:underline dark:text-sky-400"
            >
              {t('enrich.review.openFull', 'Open full Review Board')}
              <ExternalLink className="h-3 w-3" />
            </a>
          ) : (
            <span className="mr-auto" />
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.close', 'Close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
