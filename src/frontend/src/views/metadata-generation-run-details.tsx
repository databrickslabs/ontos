import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Ban, ClipboardCheck, Columns3, ExternalLink, Layout, Loader2, MessageSquare, Table as TableIcon, Trash2 } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { RelativeDate } from '@/components/common/relative-date';
import RunStatusBadge from '@/components/metadata-generation/run-status-badge';
import SubmitReviewDialog from '@/components/metadata-generation/submit-review-dialog';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import {
  TERMINAL_RUN_STATUSES,
  type DescriptionSuggestion,
  type GenerationRunDetail,
  type SubmitReviewResponse,
  type SuggestionListResponse,
  type SuggestionStatus,
} from '@/types/metadata-generation';

const FEATURE_ID = 'metadata-generation';
const POLL_INTERVAL_MS = 2000;
const SUGGESTIONS_PAGE_SIZE = 1000;
const SUGGESTION_STATUSES: SuggestionStatus[] = [
  'pending',
  'accepted',
  'rejected',
  'applied',
  'conflict',
  'not_applicable',
  'superseded',
];

export default function MetadataGenerationRunDetails() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { get, post, delete: del } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [run, setRun] = useState<GenerationRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<DescriptionSuggestion[] | null>(null);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SuggestionStatus | 'all'>('all');
  const [actionPending, setActionPending] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);

  const isActive = run ? !TERMINAL_RUN_STATUSES.includes(run.status) : false;

  useEffect(() => {
    setStaticSegments([{ label: t('title'), path: '/metadata-generation' }]);
    setDynamicTitle(runId ? t('detail.runTitle', { id: runId.slice(0, 8) }) : null);
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [runId, setStaticSegments, setDynamicTitle, t]);

  const fetchRun = useCallback(async () => {
    if (!runId) return;
    const res = await get<GenerationRunDetail>(`/api/metadata-generation/runs/${runId}`);
    if (res.error) {
      setError(res.error);
      return;
    }
    setError(null);
    setRun(res.data);
  }, [get, runId]);

  const fetchSuggestions = useCallback(async () => {
    if (!runId) return;
    const status = statusFilter === 'all' ? '' : `&status=${statusFilter}`;
    // Page through: a large run has more suggestions than one page holds
    const all: DescriptionSuggestion[] = [];
    for (;;) {
      const res = await get<SuggestionListResponse>(
        `/api/metadata-generation/runs/${runId}/suggestions?limit=${SUGGESTIONS_PAGE_SIZE}&skip=${all.length}${status}`,
      );
      if (res.error) {
        // Don't present a partial list as the whole run
        setSuggestions([]);
        setSuggestionsError(res.error);
        return;
      }
      const page = res.data?.suggestions ?? [];
      all.push(...page);
      if (page.length === 0 || all.length >= (res.data?.total ?? 0)) break;
    }
    setSuggestionsError(null);
    setSuggestions(all);
  }, [get, runId, statusFilter]);

  useEffect(() => {
    void fetchRun();
  }, [fetchRun]);

  // GET /runs/{id} refreshes from the Jobs API, so polling drives completion.
  // Chained timeouts: the next poll starts only after the previous one returned.
  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await fetchRun();
      if (!cancelled) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };
    timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [isActive, fetchRun]);

  useEffect(() => {
    if (run?.status === 'completed') void fetchSuggestions();
  }, [run?.status, fetchSuggestions]);

  const grouped = useMemo(() => {
    const byTable = new Map<string, DescriptionSuggestion[]>();
    (suggestions ?? []).forEach((s) => {
      const list = byTable.get(s.table_fqn) ?? [];
      list.push(s);
      byTable.set(s.table_fqn, list);
    });
    return Array.from(byTable.entries());
  }, [suggestions]);

  const handleCancel = async () => {
    if (!run || !confirm(t('confirm.cancel'))) return;
    setActionPending(true);
    const res = await post(`/api/metadata-generation/runs/${run.run_id}/cancel`, {});
    setActionPending(false);
    if (res.error) {
      toast({ title: t('toast.cancelFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    void fetchRun();
  };

  const handleDelete = async () => {
    if (!run || !confirm(t('confirm.delete'))) return;
    setActionPending(true);
    const res = await del(`/api/metadata-generation/runs/${run.run_id}`);
    setActionPending(false);
    if (res.error) {
      toast({ title: t('toast.deleteFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    toast({ title: t('toast.deleted') });
    navigate('/metadata-generation');
  };

  const handleSubmitted = (result: SubmitReviewResponse) => {
    toast({
      title: t('review.toast.submitted', { count: result.suggestion_count }),
      description: t('review.toast.submittedTo', { reviewer: result.reviewer_email }),
    });
    void fetchRun();
    void fetchSuggestions();
  };

  if (error && !run) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!run) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="space-y-1">
              <CardTitle className="text-lg flex items-center gap-2">
                {t('detail.runTitle', { id: run.run_id.slice(0, 8) })}
                <RunStatusBadge status={run.status} />
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {t('detail.startedBy', { user: run.user_id })} · <RelativeDate date={run.created_at} />
              </p>
              {run.progress_message && <p className="text-sm">{run.progress_message}</p>}
            </div>
            {canWrite && (
              <div className="flex items-center gap-2">
                {run.status === 'completed' && (run.unsubmitted ?? 0) > 0 && (
                  <Button size="sm" onClick={() => setSubmitOpen(true)} disabled={actionPending}>
                    <ClipboardCheck className="h-4 w-4 mr-1" /> {t('review.submitButton', { count: run.unsubmitted })}
                  </Button>
                )}
                {isActive ? (
                  <Button variant="outline" size="sm" onClick={() => void handleCancel()} disabled={actionPending}>
                    <Ban className="h-4 w-4 mr-1" /> {t('actions.cancelRun')}
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => void handleDelete()} disabled={actionPending}>
                    <Trash2 className="h-4 w-4 mr-1" /> {t('actions.deleteRun')}
                  </Button>
                )}
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {run.error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{run.error}</AlertDescription>
            </Alert>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-muted-foreground">{t('detail.selection')}</div>
              <div className="flex flex-wrap gap-1 mt-1">
                {run.selection.map((s) => (
                  <Badge key={s.fqn} variant="outline" className="font-mono">
                    {s.fqn}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">{t('detail.options')}</div>
              <div className="mt-1">
                {t(`commentStyle.${run.options.comment_style ?? 'standard'}`)} · {run.options.model}
                {run.options.regenerate_existing ? ` · ${t('detail.regenerateExisting')}` : ''}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {SUGGESTION_STATUSES.filter((s) => (run.counts?.[s] ?? 0) > 0).map((s) => (
              <Badge key={s} variant="secondary">
                {t(`suggestionStatus.${s}`)}: {run.counts[s]}
              </Badge>
            ))}
          </div>
          {(run.review_request_ids ?? []).length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{t('review.reviews')}</span>
              {(run.review_request_ids ?? []).map((id, index) => (
                <Button key={id} variant="link" size="sm" className="h-auto p-0" asChild>
                  <Link to={`/data-asset-reviews/${id}`}>
                    {t('review.openReview', { number: index + 1 })}
                    <ExternalLink className="h-3 w-3 ml-1" />
                  </Link>
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <SubmitReviewDialog
        runId={run.run_id}
        count={run.unsubmitted ?? 0}
        isOpen={submitOpen}
        onOpenChange={setSubmitOpen}
        onSubmitted={handleSubmitted}
      />

      {run.status === 'completed' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <CardTitle className="text-base">{t('detail.suggestionsTitle')}</CardTitle>
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as SuggestionStatus | 'all')}>
                <SelectTrigger className="w-[200px]" aria-label={t('detail.statusFilter')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t('detail.allStatuses')}</SelectItem>
                  {SUGGESTION_STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {t(`suggestionStatus.${s}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {suggestionsError ? (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {t('detail.suggestionsLoadFailed')}: {suggestionsError}
                </AlertDescription>
              </Alert>
            ) : suggestions === null ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : grouped.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('detail.noSuggestions')}</p>
            ) : (
              grouped.map(([tableFqn, items]) => (
                <div key={tableFqn} className="border rounded-md">
                  <div className="px-3 py-2 border-b bg-muted/40 font-mono text-sm flex items-center gap-2">
                    {items.some((i) => i.object_type === 'view') ? (
                      <Layout className="h-4 w-4" />
                    ) : (
                      <TableIcon className="h-4 w-4" />
                    )}
                    {tableFqn}
                  </div>
                  <div className="divide-y">
                    {items.map((s) => (
                      <SuggestionRow key={s.id} suggestion={s} />
                    ))}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SuggestionRow({ suggestion }: { suggestion: DescriptionSuggestion }) {
  const { t } = useTranslation('metadata-generation');
  return (
    <div className="px-3 py-2 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {suggestion.column_name ? (
            <>
              <Columns3 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-mono">{suggestion.column_name}</span>
            </>
          ) : (
            <span>{t(`objectType.${suggestion.object_type}`)}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {suggestion.review_request_id && suggestion.status === 'pending' && (
            <Badge variant="secondary">{t('review.inReview')}</Badge>
          )}
          <Badge variant="outline">{t(`suggestionStatus.${suggestion.status}`)}</Badge>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">{t('detail.current')}</div>
          <p className={suggestion.base_text ? '' : 'italic text-muted-foreground'}>
            {suggestion.base_text || t('detail.noDescription')}
          </p>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">
            {t('detail.proposed')}
            {suggestion.edited_text && <span className="ml-2 text-amber-600">{t('review.editedByReviewer')}</span>}
          </div>
          <p>{suggestion.edited_text || suggestion.proposed_text}</p>
        </div>
      </div>
      {suggestion.review_comment && (
        <p className="text-xs text-muted-foreground flex items-start gap-1">
          <MessageSquare className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            {suggestion.decided_by ? `${suggestion.decided_by}: ` : ''}
            {suggestion.review_comment}
          </span>
        </p>
      )}
    </div>
  );
}
