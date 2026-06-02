import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  ArrowRight,
  Check,
  ChevronRight,
  HelpCircle,
  Loader2,
  Sparkles,
  X,
} from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { bucketConfidence, type Suggestion } from '@/types/term-mapping';

interface Props {
  /** FQN format: term-mapping://{run_id}/{suggestion_id} */
  assetFqn: string;
  /** Called once decided so the parent (asset-review-editor) can advance the
   *  underlying ReviewedAsset status in its in-memory list. */
  onReviewComplete?: (status: 'approved' | 'rejected') => void;
  onNext?: () => void;
  hasNext?: boolean;
  currentIndex?: number;
  totalCount?: number;
  readOnly?: boolean;
}

function parseFqn(fqn: string): { runId: string; suggestionId: string } | null {
  // term-mapping://{run_id}/{suggestion_id}
  const m = fqn.match(/^term-mapping:\/\/([^/]+)\/(.+)$/);
  if (!m) return null;
  return { runId: m[1], suggestionId: m[2] };
}

const CONFIDENCE_BADGE: Record<string, string> = {
  high: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100',
  medium: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100',
  low: 'bg-rose-100 text-rose-900 dark:bg-rose-900/50 dark:text-rose-100',
};

export default function TermMappingSuggestionReview({
  assetFqn,
  onReviewComplete,
  onNext,
  hasNext = false,
  currentIndex,
  totalCount,
  readOnly = false,
}: Props) {
  const { t } = useTranslation(['term-mapping', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const parsed = parseFqn(assetFqn);

  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [customIri, setCustomIri] = useState('');
  const [comment, setComment] = useState('');

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!parsed) {
        setError(t('suggestion.errors.unparseable', { fqn: assetFqn }));
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        // No dedicated GET-by-id endpoint yet; list suggestions for the run
        // and find ours. Lists are paginated to 500 by default which more
        // than covers a typical run.
        const res = await get<Suggestion[]>(
          `/api/term-mappings/runs/${parsed.runId}/suggestions?limit=5000`,
        );
        if (res.error) throw new Error(res.error);
        if (cancelled) return;
        const found = (res.data ?? []).find((s) => s.id === parsed.suggestionId);
        if (!found) throw new Error(t('suggestion.errors.notFound'));
        setSuggestion(found);
        setCustomIri(found.custom_iri ?? '');
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : t('suggestion.errors.loadFailed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [assetFqn, get, t]);

  if (!parsed) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('suggestion.invalidFqn')}</AlertDescription>
      </Alert>
    );
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!suggestion) {
    return null;
  }

  const isTerminal =
    suggestion.status === 'applied' ||
    suggestion.status === 'rejected' ||
    suggestion.status === 'accepted' ||
    suggestion.status === 'superseded';
  const disabled = readOnly || isTerminal;

  const submitDecision = async (
    decision: 'accept' | 'reject' | 'clarify',
  ): Promise<boolean> => {
    if (!suggestion) return false;
    setSubmitting(true);
    try {
      const body = {
        decisions: [
          {
            id: suggestion.id,
            decision,
            custom_iri:
              decision === 'accept' && customIri.trim() && customIri.trim() !== suggestion.target_concept_iri
                ? customIri.trim()
                : undefined,
            comment: comment.trim() || undefined,
          },
        ],
      };
      const res = await post<{ accepted: number; rejected: number; skipped: number; errors: string[] }>(
        `/api/term-mappings/runs/${suggestion.run_id}/decisions`,
        body,
      );
      if (res.error) throw new Error(res.error);
      const result = res.data!;
      if (result.errors?.length) {
        toast({
          title: t('suggestion.toast.savedWithWarnings'),
          description: result.errors[0],
          variant: 'destructive',
        });
      } else {
        toast({
          title:
            decision === 'accept'
              ? t('suggestion.toast.approved')
              : decision === 'reject'
                ? t('suggestion.toast.rejected')
                : t('suggestion.toast.clarified'),
        });
      }
      onReviewComplete?.(decision === 'accept' ? 'approved' : 'rejected');
      return true;
    } catch (e) {
      toast({
        title: t('suggestion.toast.decisionFailed'),
        description: e instanceof Error ? e.message : t('toast.unknownError'),
        variant: 'destructive',
      });
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  const handleAcceptAndNext = async () => {
    const ok = await submitDecision('accept');
    if (ok && onNext) onNext();
  };

  const sourceTypeLabel = suggestion.source_entity_type.replace(/_/g, ' ');
  const bucket = bucketConfidence(suggestion.confidence);

  return (
    <div className="space-y-4">
      {/* Header with progress + status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-purple-500" />
          <div>
            <h3 className="text-base font-semibold leading-tight">
              {t('suggestion.header')}
            </h3>
            {typeof currentIndex === 'number' && typeof totalCount === 'number' && (
              <p className="text-xs text-muted-foreground">
                {t('suggestion.progress', { current: currentIndex, total: totalCount })}
              </p>
            )}
          </div>
        </div>
        <Badge
          variant={isTerminal ? 'secondary' : 'outline'}
          className="capitalize"
        >
          {suggestion.status.replace(/_/g, ' ')}
        </Badge>
      </div>

      {/* Mapping card: source → target */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
            <Badge variant="secondary" className="text-xs">{sourceTypeLabel}</Badge>
            <span className="font-mono text-xs text-muted-foreground truncate" title={suggestion.source_entity_id}>
              {suggestion.source_label || suggestion.source_entity_id}
            </span>
            <ArrowRight className="h-4 w-4 mx-1 shrink-0" />
            <Badge variant="default" className="text-xs">{t('suggestion.concept')}</Badge>
            <span className="text-sm font-medium">
              {suggestion.target_concept_label ?? suggestion.target_concept_iri}
            </span>
          </CardTitle>
          <CardDescription className="font-mono text-xs break-all">
            {suggestion.target_concept_iri}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">{t('suggestion.confidence')}</span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${CONFIDENCE_BADGE[bucket]}`}>
              {t('suggestion.confidenceValue', {
                value: (suggestion.confidence * 100).toFixed(0),
                bucket,
              })}
            </span>
            {suggestion.auto_apply && (
              <Badge variant="outline" className="text-xs">{t('suggestion.autoApply')}</Badge>
            )}
            <Badge variant="outline" className="text-xs capitalize">{suggestion.engine}</Badge>
          </div>
          <Separator />
          <div>
            <Label className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('suggestion.whyMatch')}
            </Label>
            <p className="text-sm mt-1 whitespace-pre-wrap">
              {suggestion.reason || t('suggestion.noReason')}
            </p>
          </div>
          {suggestion.warnings && suggestion.warnings.length > 0 && (
            <Alert variant="destructive" className="py-2">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="text-xs">
                {suggestion.warnings.join(', ')}
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Decision form: custom IRI override + comment */}
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="custom-iri" className="text-sm">
            {t('suggestion.overrideIri')}
          </Label>
          <Input
            id="custom-iri"
            value={customIri}
            onChange={(e) => setCustomIri(e.target.value)}
            placeholder={suggestion.target_concept_iri}
            disabled={disabled}
            className="font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground">{t('suggestion.overrideIriHelp')}</p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="decision-comment" className="text-sm">
            {t('suggestion.comment')}
          </Label>
          <Textarea
            id="decision-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t('suggestion.commentPlaceholder')}
            className="min-h-[60px]"
            disabled={disabled}
          />
        </div>
      </div>

      {/* Action bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => submitDecision('clarify')}
          disabled={disabled || submitting}
        >
          <HelpCircle className="mr-1 h-4 w-4" /> {t('suggestion.needsClarification')}
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => submitDecision('reject')}
            disabled={disabled || submitting}
          >
            {submitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <X className="mr-1 h-4 w-4" />}
            {t('suggestion.reject')}
          </Button>
          <Button
            size="sm"
            onClick={() => submitDecision('accept')}
            disabled={disabled || submitting}
          >
            {submitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Check className="mr-1 h-4 w-4" />}
            {t('suggestion.acceptApply')}
          </Button>
          {hasNext && (
            <Button
              variant="default"
              size="sm"
              onClick={handleAcceptAndNext}
              disabled={disabled || submitting}
            >
              {t('suggestion.acceptNext')}
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
