import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Info } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';

// ---------------------------------------------------------------------------
// Suggest matches — the Enrich Map lane's real entry to the term-mapping
// suggester. Exposes what was previously hidden: which asset layer to match
// against (target type) and which engine to use. It then:
//   1. POST /api/term-mappings/runs        -> runs the suggester (sync)
//   2. POST /api/term-mappings/runs/{id}/review -> spawns a Review Board request
//   3. navigate to /data-asset-reviews/{review_request_id}
//
// Scope note: the suggester's concept source is CUSTOMER ONTOLOGIES
// (urn:semantic-model:* contexts), validated server-side. Glossary-type schemes
// (urn:glossary:*) are NOT valid `ontology_contexts`, so we intentionally OMIT
// ontology_contexts and let the backend default to all enabled customer
// ontologies, rather than 422 by passing a glossary scheme. The target filter +
// engine are the real knobs. TODO(cb-v2): once schemes map 1:1 to customer
// ontologies, pass ontology_contexts to scope per-scheme.
// ---------------------------------------------------------------------------

type TargetType = 'asset' | 'data_contract' | 'data_product';
type Engine = 'heuristic' | 'llm_judge';

// Concept source for the suggester. Customer ontologies are the default source;
// when none are uploaded, the steward can opt into a shipped taxonomy so the
// run has concepts to match. These URNs are the backend's SHIPPED_OPT_IN set.
type Source = 'customer' | 'databricks' | 'odcs';
const SHIPPED_URN: Record<Exclude<Source, 'customer'>, string> = {
  databricks: 'urn:taxonomy:databricks_ontology',
  odcs: 'urn:taxonomy:odcs-ontology',
};

interface SuggestMatchesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Scheme label, for display only (context is not scoped — see note above). */
  schemeName?: string;
  canWrite: boolean;
}

export default function SuggestMatchesDialog({
  open,
  onOpenChange,
  schemeName,
  canWrite,
}: SuggestMatchesDialogProps) {
  const { t } = useTranslation(['concepts', 'term-mapping', 'common']);
  const navigate = useNavigate();
  const { toast } = useToast();

  const [targetType, setTargetType] = useState<TargetType>('asset');
  const [engine, setEngine] = useState<Engine>('heuristic');
  const [source, setSource] = useState<Source>('customer');
  const [busy, setBusy] = useState(false);

  // Reviewer = the current user (the review is assigned to whoever runs it).
  // Fetched here so the dialog is self-contained.
  const [reviewerEmail, setReviewerEmail] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/user/details');
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setReviewerEmail(data?.email ?? null);
      } catch {
        /* leave null — run() surfaces a clear error */
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  const run = async () => {
    if (!reviewerEmail) {
      toast({
        title: t('common:toast.error', 'Error'),
        description: t('enrich.map.noReviewer', 'Cannot determine your email to assign the review.'),
        variant: 'destructive',
      });
      return;
    }
    setBusy(true);
    try {
      // 1. Create + execute the suggester run. Concept source: customer
      //    ontologies (default) or an opted-in shipped taxonomy. ontology_contexts
      //    is left to the backend default (all customer ontologies) since
      //    glossary schemes are not valid contexts (see note above).
      const body: Record<string, unknown> = {
        target_filter: { entity_types: [targetType] }, // assets default to Column-level
        engines: [engine],
        comment: schemeName ? `Suggest matches from Enrich (${schemeName})` : 'Suggest matches from Enrich',
      };
      if (source !== 'customer') {
        body.include_shipped = [SHIPPED_URN[source]];
      }
      const runRes = await fetch('/api/term-mappings/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!runRes.ok) {
        const err = await runRes.json().catch(() => ({}));
        // 422 with the "No ontology contexts" detail means no customer ontology
        // is uploaded — surface it as guidance, not a generic failure.
        throw new Error(err?.detail || 'Failed to run the match suggester');
      }
      const runData = await runRes.json();
      const runId = runData.id;

      // 2. Spawn a Review Board request for the run's pending suggestions.
      const reviewRes = await fetch(`/api/term-mappings/runs/${encodeURIComponent(runId)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_email: reviewerEmail }),
      });
      if (!reviewRes.ok) {
        const err = await reviewRes.json().catch(() => ({}));
        const detail = String(err?.detail || '');
        // "No suggestions eligible" is an expected outcome (the run ran but
        // matched nothing), not a failure — report it plainly and stop.
        if (detail.toLowerCase().includes('no suggestions')) {
          toast({
            title: t('enrich.map.noMatches', 'No matches found'),
            description: t(
              'enrich.map.noMatchesDesc',
              'The suggester ran but found no candidate matches for this source and target.',
            ),
          });
          onOpenChange(false);
          return;
        }
        throw new Error(detail || 'Failed to create the review');
      }
      const reviewData = await reviewRes.json();

      toast({
        title: t('enrich.map.suggestDone', 'Suggestions ready'),
        description: t(
          'enrich.map.suggestDoneDesc',
          '{{count}} suggestions sent to the Review Board.',
          { count: reviewData.suggestion_count ?? 0 },
        ),
      });
      onOpenChange(false);
      // 3. Open the Review Board request.
      if (reviewData.review_request_id) {
        navigate(`/data-asset-reviews/${reviewData.review_request_id}`);
      }
    } catch (e: any) {
      toast({
        title: t('common:toast.error', 'Error'),
        description: e?.message || 'Failed to suggest matches',
        variant: 'destructive',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t('enrich.map.suggestTitle', 'Suggest matches')}</DialogTitle>
          <DialogDescription>
            {t(
              'enrich.map.suggestSubtitle',
              'Run the match suggester over your concepts, then review the candidates on the Review Board before anything is linked.',
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          <div className="grid gap-1.5">
            <Label className="flex items-center gap-1.5">
              {t('enrich.map.source', 'Concepts from')}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[260px]">
                    {t(
                      'enrich.map.sourceTip',
                      'Which concepts to match from. Use your customer ontologies, or opt into a shipped taxonomy if you have not uploaded one yet.',
                    )}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </Label>
            <Select value={source} onValueChange={(v) => setSource(v as Source)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="customer">{t('enrich.map.source.customer', 'My customer ontologies')}</SelectItem>
                <SelectItem value="databricks">{t('enrich.map.source.databricks', 'Databricks ontology (shipped)')}</SelectItem>
                <SelectItem value="odcs">{t('enrich.map.source.odcs', 'ODCS ontology (shipped)')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label>{t('enrich.map.targetType', 'Match against')}</Label>
            <Select value={targetType} onValueChange={(v) => setTargetType(v as TargetType)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="asset">{t('enrich.map.target.asset', 'Platform assets (columns)')}</SelectItem>
                <SelectItem value="data_contract">{t('enrich.map.target.contract', 'Data contracts')}</SelectItem>
                <SelectItem value="data_product">{t('enrich.map.target.product', 'Data products')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label className="flex items-center gap-1.5">
              {t('enrich.map.engine', 'Engine')}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[260px]">
                    {t(
                      'enrich.map.engineTip',
                      'Heuristic matches on labels and synonyms (fast). LLM judge scores candidates with a model (slower, broader).',
                    )}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </Label>
            <Select value={engine} onValueChange={(v) => setEngine(v as Engine)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="heuristic">{t('enrich.map.engine.heuristic', 'Heuristic')}</SelectItem>
                <SelectItem value="llm_judge">{t('enrich.map.engine.llm', 'LLM judge')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <p className="text-xs text-muted-foreground">
            {t(
              'enrich.map.scopeNote',
              'Candidates come from your customer ontologies. Results go to the Review Board; nothing is linked until you approve it there.',
            )}
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={run} disabled={busy || !canWrite}>
            {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {t('enrich.map.runSuggester', 'Run suggester')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
