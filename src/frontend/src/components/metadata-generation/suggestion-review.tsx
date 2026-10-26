import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Check, ChevronRight, Columns3, HelpCircle, Loader2, Sparkles, Table as TableIcon, X } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  DescriptionSuggestion,
  SuggestionDecisionKind,
  SuggestionDecisionResult,
} from '@/types/metadata-generation';

export type SuggestionReviewOutcome = 'approved' | 'rejected' | 'needs_clarification';

interface Props {
  /** FQN format: metagen://{run_id}/{suggestion_id} */
  assetFqn: string;
  /** Called once decided so the parent (asset-review-editor) can update the
   *  ReviewedAsset in its list; the backend has already synced it. */
  onReviewComplete?: (status: SuggestionReviewOutcome) => void;
  onNext?: () => void;
  hasNext?: boolean;
  currentIndex?: number;
  totalCount?: number;
  readOnly?: boolean;
  /** The review was approved, denied or cancelled: nothing can be decided in it any more */
  reviewClosed?: boolean;
}

function parseMetagenFqn(fqn: string): { runId: string; suggestionId: string } | null {
  const m = fqn.match(/^metagen:\/\/([^/]+)\/(.+)$/);
  return m ? { runId: m[1], suggestionId: m[2] } : null;
}

const OUTCOME: Record<SuggestionDecisionKind, SuggestionReviewOutcome> = {
  accept: 'approved',
  reject: 'rejected',
  clarify: 'needs_clarification',
};

// Accepted and rejected suggestions can be decided again until they're applied
const DECIDABLE = new Set(['pending', 'accepted', 'rejected']);

export default function MetadataSuggestionReview({
  assetFqn,
  onReviewComplete,
  onNext,
  hasNext = false,
  currentIndex,
  totalCount,
  readOnly = false,
  reviewClosed = false,
}: Props) {
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const parsed = parseMetagenFqn(assetFqn);
  const runId = parsed?.runId;
  const suggestionId = parsed?.suggestionId;

  const [suggestion, setSuggestion] = useState<DescriptionSuggestion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [text, setText] = useState('');
  const [comment, setComment] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!runId || !suggestionId) {
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      const res = await get<DescriptionSuggestion>(
        `/api/metadata-generation/runs/${runId}/suggestions/${suggestionId}`,
      );
      if (cancelled) return;
      if (res.error || !res.data) {
        setError(res.error || t('review.loadFailed'));
      } else {
        setSuggestion(res.data);
        setText(res.data.edited_text || res.data.proposed_text);
        setComment(res.data.review_comment ?? '');
      }
      setLoading(false);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId, suggestionId, get, t]);

  if (!parsed) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('review.invalidFqn', { fqn: assetFqn })}</AlertDescription>
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
  if (error || !suggestion) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error || t('review.loadFailed')}</AlertDescription>
      </Alert>
    );
  }

  const inReview = Boolean(suggestion.review_request_id) && DECIDABLE.has(suggestion.status);
  const disabled = readOnly || reviewClosed || !inReview || submitting;
  const edited = text.trim() !== suggestion.proposed_text.trim();

  const decide = async (decision: SuggestionDecisionKind): Promise<boolean> => {
    if (decision === 'accept' && !text.trim()) {
      toast({ title: t('review.emptyText'), variant: 'destructive' });
      return false;
    }
    setSubmitting(true);
    try {
      const res = await post<SuggestionDecisionResult>(
        `/api/metadata-generation/runs/${suggestion.run_id}/decisions`,
        {
          decisions: [
            {
              id: suggestion.id,
              decision,
              edited_text: decision === 'accept' ? text.trim() : undefined,
              comment: comment.trim() || undefined,
            },
          ],
        },
      );
      if (res.error) throw new Error(res.error);
      if (res.data?.errors?.length) throw new Error(res.data.errors[0]);
      toast({ title: t(`review.toast.${decision}`) });
      setSuggestion({
        ...suggestion,
        status: decision === 'accept' ? 'accepted' : decision === 'reject' ? 'rejected' : 'pending',
        edited_text: decision === 'accept' && edited ? text.trim() : suggestion.edited_text,
        review_comment: comment.trim() || null,
        // Sent back for clarification, it leaves this review
        review_request_id: decision === 'clarify' ? null : suggestion.review_request_id,
      });
      onReviewComplete?.(OUTCOME[decision]);
      return true;
    } catch (e) {
      toast({
        title: t('review.toast.failed'),
        description: e instanceof Error ? e.message : undefined,
        variant: 'destructive',
      });
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  const acceptAndNext = async () => {
    if ((await decide('accept')) && onNext) onNext();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-purple-500" />
          <div>
            <h3 className="text-base font-semibold leading-tight">{t('review.header')}</h3>
            {typeof currentIndex === 'number' && typeof totalCount === 'number' && (
              <p className="text-xs text-muted-foreground">
                {t('review.progress', { current: currentIndex, total: totalCount })}
              </p>
            )}
          </div>
        </div>
        <Badge variant={inReview ? 'outline' : 'secondary'}>
          {inReview || suggestion.status !== 'pending'
            ? t(`suggestionStatus.${suggestion.status}`)
            : t('review.sentBack')}
        </Badge>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
            {suggestion.column_name ? (
              <Columns3 className="h-4 w-4 text-muted-foreground" />
            ) : (
              <TableIcon className="h-4 w-4 text-muted-foreground" />
            )}
            <Badge variant="secondary" className="text-xs">
              {t(`objectType.${suggestion.object_type}`)}
            </Badge>
            <span className="font-mono text-xs break-all">
              {suggestion.table_fqn}
              {suggestion.column_name ? `.${suggestion.column_name}` : ''}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>
            <Label className="text-xs uppercase text-muted-foreground tracking-wide">{t('detail.current')}</Label>
            <p className={suggestion.base_text ? 'mt-1 whitespace-pre-wrap' : 'mt-1 italic text-muted-foreground'}>
              {suggestion.base_text || t('detail.noDescription')}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="metagen-proposed" className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('detail.proposed')}
              {edited && <span className="ml-2 normal-case text-amber-600">{t('review.edited')}</span>}
            </Label>
            <Textarea
              id="metagen-proposed"
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="min-h-[90px]"
              disabled={disabled}
            />
            {edited && (
              <p className="text-xs text-muted-foreground">
                {t('review.generated')}: <span className="italic">{suggestion.proposed_text}</span>
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-1">
        <Label htmlFor="metagen-comment" className="text-sm">
          {t('review.comment')}
        </Label>
        <Textarea
          id="metagen-comment"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t('review.commentPlaceholder')}
          className="min-h-[60px]"
          disabled={disabled}
        />
      </div>

      {reviewClosed ? (
        <p className="text-xs text-muted-foreground">{t('review.reviewClosedHint')}</p>
      ) : (
        !inReview && (
          <p className="text-xs text-muted-foreground">
            {suggestion.status === 'pending' ? t('review.sentBackHint') : t('review.closedHint')}
          </p>
        )
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t">
        <Button variant="ghost" size="sm" onClick={() => void decide('clarify')} disabled={disabled}>
          <HelpCircle className="mr-1 h-4 w-4" /> {t('review.clarify')}
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void decide('reject')} disabled={disabled}>
            {submitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <X className="mr-1 h-4 w-4" />}
            {t('review.reject')}
          </Button>
          <Button size="sm" onClick={() => void decide('accept')} disabled={disabled}>
            {submitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Check className="mr-1 h-4 w-4" />}
            {t('review.accept')}
          </Button>
          {hasNext && (
            <Button size="sm" onClick={() => void acceptAndNext()} disabled={disabled}>
              {t('review.acceptNext')}
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
