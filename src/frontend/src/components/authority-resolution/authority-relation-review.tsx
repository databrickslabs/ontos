import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useUserStore } from '@/stores/user-store';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import { DialogSkeleton, SkeletonLine } from '@/components/common/list-view-skeleton';
import type { AuthorityReviewContext } from '@/types/authority-resolution';

interface Props {
  relationId: string;
  /** Reviewer principal; defaults to the current user's email. */
  reviewer?: string | null;
  onCompleted?: () => void;
}

function DetailBlock({ label, data }: { label: string; data: any }) {
  return (
    <div>
      <div className="text-xs uppercase text-muted-foreground mb-1">{label}</div>
      {data === null || data === undefined || (typeof data === 'object' && Object.keys(data).length === 0) ? (
        <span className="text-sm text-muted-foreground">—</span>
      ) : typeof data === 'object' ? (
        <pre className="text-xs bg-muted rounded p-3 overflow-x-auto">{JSON.stringify(data, null, 2)}</pre>
      ) : (
        <span className="text-sm">{String(data)}</span>
      )}
    </div>
  );
}

/**
 * Role-specific Authority Relation review editor. Business/interviewee reviewers
 * answer a structured-elicitation questionnaire; technical/governance reviewers
 * additionally inspect the compiled rule + bound evidence. Reused inline on the
 * AR detail view and by the Asset Review editor (asset_type = authority_relation).
 */
export default function AuthorityRelationReview({ relationId, reviewer, onCompleted }: Props) {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const currentEmail = useUserStore((s) => s.userInfo?.email);
  const principal = reviewer || currentEmail || null;

  const [ctx, setCtx] = useState<AuthorityReviewContext | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchContext = useCallback(async () => {
    if (!principal) { setError(t('review.errors.noReviewerIdentity')); setLoading(false); return; }
    setLoading(true);
    const { data, error } = await get<AuthorityReviewContext>(
      `/api/authority/relations/${relationId}/review-context?reviewer=${encodeURIComponent(principal)}`,
    );
    if (error || !data) {
      setError(error || t('review.errors.noReviewFound'));
      setCtx(null);
    } else {
      setError(null);
      setCtx(data);
      setAnswers(data.existing_answers || {});
    }
    setLoading(false);
  }, [get, relationId, principal, t]);

  useEffect(() => { fetchContext(); }, [fetchContext]);

  const submit = async () => {
    if (!ctx) return;
    setSaving(true);
    const { error } = await post<any>(
      `/api/authority/participants/${ctx.participant_id}/submit-review`,
      { answers },
    );
    setSaving(false);
    if (error) {
      toast({ title: t('review.toasts.submitFailed'), description: error, variant: 'destructive' });
      return;
    }
    toast({ title: t('review.toasts.submitSuccess') });
    fetchContext();
    onCompleted?.();
  };

  if (loading) return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <SkeletonLine className="h-6 w-24" />
        <SkeletonLine className="h-6 w-32" />
      </div>
      <DialogSkeleton />
    </div>
  );
  if (error || !ctx) return (
    <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
  );

  const completed = ctx.review_status === 'completed';

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Badge variant="outline">{ctx.role}</Badge>
        {completed
          ? <Badge><CheckCircle2 className="h-3 w-3 mr-1" /> {t('review.statuses.completed')}</Badge>
          : <Badge variant="secondary">{t(`review.statuses.${ctx.review_status}`, { defaultValue: ctx.review_status })}</Badge>}
        <span className="text-sm text-muted-foreground">{ctx.ar_name}</span>
      </div>

      {ctx.details && (
        <div className="space-y-3 rounded-md border p-3">
          <div className="text-sm font-semibold text-muted-foreground">{t('review.details.title')}</div>
          <div className="grid md:grid-cols-2 gap-3">
            <DetailBlock label={t('review.details.actorIdentity')} data={ctx.details.actor_identity} />
            <DetailBlock label={t('review.details.action')} data={ctx.details.action} />
          </div>
          <DetailBlock label={t('review.details.domainContext')} data={ctx.details.domain_context} />
          <div>
            <div className="text-xs uppercase text-muted-foreground mb-1">{t('review.details.decisionCriteria')}</div>
            {(ctx.details.criteria || []).length > 0 ? (
              <div className="space-y-1">
                {(ctx.details.criteria || []).map((c, i) => (
                  <div key={i} className="text-xs rounded border p-2">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{c.name || t('review.details.criterion')}</span>
                      <span className="ml-auto text-muted-foreground">{c.direction} · w{c.weight}</span>
                    </div>
                    <div className="font-mono break-all">{c.rule}</div>
                  </div>
                ))}
              </div>
            ) : <span className="text-sm text-muted-foreground">{t('review.details.empty')}</span>}
          </div>
          <DetailBlock label={t('review.details.evidenceSources')} data={ctx.details.evidence_sources} />
          <DetailBlock label={t('review.details.evidenceBinding')} data={ctx.details.evidence_binding} />
          <DetailBlock label={t('review.details.justificationChain')} data={ctx.details.justification_chain} />
        </div>
      )}

      <div className="space-y-3">
        <div className="text-sm font-semibold text-muted-foreground">
          {ctx.details ? t('review.questionnaire.confirmation') : t('review.questionnaire.elicitation')}
        </div>
        {ctx.questionnaire.map((q) => (
          <div key={q.id} className="space-y-1">
            <Label>{q.text}</Label>
            <Textarea
              value={answers[q.id] || ''}
              onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
              rows={2}
              disabled={completed}
              placeholder={t('review.questionnaire.placeholder')}
            />
          </div>
        ))}
      </div>

      {!completed && (
        <div className="flex justify-end">
          <Button onClick={submit} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {t('review.actions.submitReview')}
          </Button>
        </div>
      )}
    </div>
  );
}
