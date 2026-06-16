import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation, Trans } from 'react-i18next';
import {
  AlertCircle,
  ChevronRight,
  Inbox,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Undo2,
} from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import { FeatureAccessLevel } from '@/types/settings';

import RunConfigDialog from '@/components/term-mapping/run-config-dialog';
import GenerateReviewDialog from '@/components/term-mapping/generate-review-dialog';

import type {
  ApplyResult,
  Run,
  RunStatus,
  RunSummary,
  UndoResult,
} from '@/types/term-mapping';

const FEATURE_ID = 'term-mapping';

const RUN_STATUS_VARIANT: Record<
  RunStatus,
  'default' | 'secondary' | 'destructive' | 'outline'
> = {
  pending: 'outline',
  suggesting: 'secondary',
  suggested: 'secondary',
  applying: 'secondary',
  applied: 'default',
  undone: 'outline',
  failed: 'destructive',
};

export default function TermMappingView() {
  const { t } = useTranslation(['term-mapping', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const currentUser = useUserStore((s) => s.userInfo);

  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const isAdmin = hasPermission(FEATURE_ID, FeatureAccessLevel.ADMIN);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);

  const [isNewRunOpen, setIsNewRunOpen] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [actionPending, setActionPending] = useState(false);

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const res = await get<RunSummary[]>('/api/term-mappings/runs?limit=50');
      if (res.error) throw new Error(res.error);
      setRuns(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      setRunsError(e instanceof Error ? e.message : t('errors.loadRunsFailed'));
    } finally {
      setRunsLoading(false);
    }
  }, [get, t]);

  const fetchRunDetail = useCallback(
    async (runId: string) => {
      setRunDetailLoading(true);
      try {
        const res = await get<Run>(`/api/term-mappings/runs/${runId}`);
        if (res.error) throw new Error(res.error);
        setSelectedRun(res.data ?? null);
      } catch (e) {
        toast({
          title: t('toast.loadRunFailed'),
          description: e instanceof Error ? e.message : t('toast.unknownError'),
          variant: 'destructive',
        });
        setSelectedRun(null);
      } finally {
        setRunDetailLoading(false);
      }
    },
    [get, toast, t],
  );

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  useEffect(() => {
    if (selectedRunId) void fetchRunDetail(selectedRunId);
    else setSelectedRun(null);
  }, [selectedRunId, fetchRunDetail]);

  const handleRunCreated = useCallback(
    (created: Run) => {
      // RunConfigDialog calls onCreated with the freshly persisted run, so we
      // can avoid the round-trip and immediately drill into it.
      setRuns((prev) => [
        {
          id: created.id,
          status: created.status,
          comment: created.comment ?? null,
          stats: created.stats,
          created_by: created.created_by ?? null,
          created_at: created.created_at,
          finished_at: created.finished_at ?? null,
          applied_at: created.applied_at ?? null,
        },
        ...prev,
      ]);
      setSelectedRunId(created.id);
    },
    [],
  );

  const handleApplyAuto = async () => {
    if (!selectedRun) return;
    setActionPending(true);
    try {
      const res = await post<ApplyResult>(
        `/api/term-mappings/runs/${selectedRun.id}/apply?apply_auto=true`,
        {},
      );
      if (res.error) throw new Error(res.error);
      const r = res.data!;
      toast({
        title: t('toast.applied'),
        description: t('toast.appliedDescription', {
          created: r.links_created,
          skipped: r.links_skipped,
        }),
      });
      await Promise.all([fetchRuns(), fetchRunDetail(selectedRun.id)]);
    } catch (e) {
      toast({
        title: t('toast.applyFailed'),
        description: e instanceof Error ? e.message : t('toast.unknownError'),
        variant: 'destructive',
      });
    } finally {
      setActionPending(false);
    }
  };

  const handleUndo = async () => {
    if (!selectedRun) return;
    if (!confirm(t('confirm.undo', { id: selectedRun.id }))) return;
    setActionPending(true);
    try {
      const res = await post<UndoResult>(
        `/api/term-mappings/runs/${selectedRun.id}/undo`,
        {},
      );
      if (res.error) throw new Error(res.error);
      const r = res.data!;
      toast({
        title: t('toast.undone'),
        description: t('toast.undoneDescription', {
          removed: r.links_removed,
          reverted: r.suggestions_reverted,
        }),
      });
      await Promise.all([fetchRuns(), fetchRunDetail(selectedRun.id)]);
    } catch (e) {
      toast({
        title: t('toast.undoFailed'),
        description: e instanceof Error ? e.message : t('toast.unknownError'),
        variant: 'destructive',
      });
    } finally {
      setActionPending(false);
    }
  };

  const totalsRow = (stats: Run['stats']) => (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
      <Stat label={t('stats.targets')} value={stats.targets ?? 0} />
      <Stat label={t('stats.suggestions')} value={stats.suggestions_total ?? 0} />
      <Stat label={t('stats.pending')} value={stats.suggestions_pending ?? 0} />
      <Stat label={t('stats.autoApply')} value={stats.suggestions_auto_apply ?? 0} />
      <Stat label={t('stats.accepted')} value={stats.suggestions_accepted ?? 0} />
      <Stat label={t('stats.rejected')} value={stats.suggestions_rejected ?? 0} />
      <Stat label={t('stats.linksCreated')} value={stats.links_created ?? 0} />
      <Stat label={t('stats.linksSkipped')} value={stats.links_skipped ?? 0} />
    </div>
  );

  const detailPane = useMemo(() => {
    if (!selectedRunId) {
      return (
        <Card className="h-full flex items-center justify-center">
          <CardContent className="text-center py-12 text-muted-foreground">
            <Inbox className="h-10 w-10 mx-auto mb-3 opacity-40" />
            <p>{t('actions.selectRunHint')}</p>
          </CardContent>
        </Card>
      );
    }
    if (runDetailLoading || !selectedRun) {
      return (
        <div className="flex justify-center items-center h-full">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      );
    }
    const stats = selectedRun.stats;
    const pending = (stats.suggestions_pending as number | undefined) ?? 0;
    const accepted = (stats.suggestions_accepted as number | undefined) ?? 0;
    const autoApply = (stats.suggestions_auto_apply as number | undefined) ?? 0;
    return (
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <CardTitle className="text-base flex items-center gap-2">
                  <Sparkles className="h-4 w-4" />
                  {t('detail.runLabel')}{' '}
                  <span className="font-mono text-xs">{selectedRun.id.slice(0, 8)}</span>
                  <Badge variant={RUN_STATUS_VARIANT[selectedRun.status]}>{selectedRun.status}</Badge>
                </CardTitle>
                <p className="text-xs text-muted-foreground mt-1">
                  {t('detail.createdAt')} <RelativeDate date={selectedRun.created_at} />{' '}
                  {selectedRun.created_by
                    ? t('detail.createdBy', { email: selectedRun.created_by })
                    : ''}
                </p>
                {selectedRun.comment && (
                  <p className="text-sm mt-2 italic">{selectedRun.comment}</p>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchRunDetail(selectedRun.id)}
                  disabled={runDetailLoading}
                >
                  <RefreshCw className="h-4 w-4 mr-1" /> {t('actions.refresh')}
                </Button>
                {canWrite && autoApply > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleApplyAuto}
                    disabled={actionPending}
                  >
                    {actionPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                    {t('actions.applyAuto', { count: autoApply })}
                  </Button>
                )}
                {canWrite && (pending > 0 || accepted > 0) && (
                  <Button
                    size="sm"
                    onClick={() => setIsReviewOpen(true)}
                    disabled={actionPending}
                  >
                    {t('actions.generateReview')}
                    <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                )}
                {isAdmin && selectedRun.status === 'applied' && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleUndo}
                    disabled={actionPending}
                  >
                    <Undo2 className="h-4 w-4 mr-1" /> {t('actions.undo')}
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {totalsRow(stats)}
            {selectedRun.error && (
              <Alert variant="destructive" className="mt-3">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{selectedRun.error}</AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t('detail.sourcesTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <Label>{t('detail.customerOntologies')}</Label>
              <ContextList items={selectedRun.ontology_contexts} />
            </div>
            <div>
              <Label>{t('detail.shippedTaxonomies')}</Label>
              <ContextList items={selectedRun.include_shipped} />
            </div>
            <Separator />
            <div className="text-xs text-muted-foreground">
              {t('detail.reviewsLinkPrefix')}{' '}
              <Link to="/data-asset-reviews" className="underline">
                {t('detail.reviewsLinkText')}
              </Link>{' '}
              {t('detail.reviewsLinkSuffix')}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }, [selectedRunId, selectedRun, runDetailLoading, actionPending, canWrite, isAdmin, fetchRunDetail, t]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Sparkles className="h-5 w-5" /> {t('title')}
          </h2>
          <p className="text-sm text-muted-foreground">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void fetchRuns()} disabled={runsLoading}>
            <RefreshCw className="h-4 w-4 mr-1" /> {t('actions.refresh')}
          </Button>
          {canWrite && (
            <Button size="sm" onClick={() => setIsNewRunOpen(true)}>
              <Plus className="h-4 w-4 mr-1" /> {t('actions.newRun')}
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('recent.title')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 p-2">
            {runsError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{runsError}</AlertDescription>
              </Alert>
            )}
            {runsLoading && runs.length === 0 && (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
            {!runsLoading && runs.length === 0 && !runsError && (
              <p className="text-xs text-muted-foreground text-center py-6">
                <Trans
                  i18nKey="term-mapping:recent.empty"
                  components={{ strong: <strong /> }}
                />
              </p>
            )}
            {runs.map((run) => {
              const stats = (run.stats ?? {}) as Record<string, number | undefined>;
              const isSelected = run.id === selectedRunId;
              return (
                <button
                  key={run.id}
                  type="button"
                  className={`block w-full text-left rounded-md border px-3 py-2 text-sm transition-colors ${
                    isSelected
                      ? 'border-primary bg-accent'
                      : 'border-transparent hover:bg-accent/50'
                  }`}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs truncate">{run.id.slice(0, 8)}</span>
                    <Badge variant={RUN_STATUS_VARIANT[run.status]} className="shrink-0">
                      {run.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 truncate" title={run.comment ?? undefined}>
                    {run.comment || t('recent.noComment')}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    <RelativeDate date={run.created_at} />
                    {typeof stats.suggestions_total === 'number' &&
                      ` · ${t('recent.suggestionsCount', { count: stats.suggestions_total })}`}
                  </p>
                </button>
              );
            })}
          </CardContent>
        </Card>

        <div>{detailPane}</div>
      </div>

      <RunConfigDialog
        isOpen={isNewRunOpen}
        onOpenChange={setIsNewRunOpen}
        onCreated={handleRunCreated}
      />

      <GenerateReviewDialog
        isOpen={isReviewOpen}
        onOpenChange={setIsReviewOpen}
        run={selectedRun}
        currentUserEmail={currentUser?.email ?? undefined}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-muted/30 p-2">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-base font-semibold">{value}</div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-xs uppercase text-muted-foreground tracking-wide mb-1">{children}</div>
  );
}

function ContextList({ items }: { items: string[] }) {
  if (!items || items.length === 0) {
    return <p className="text-xs text-muted-foreground">—</p>;
  }
  return (
    <ul className="space-y-0.5">
      {items.map((it) => (
        <li key={it} className="font-mono text-xs break-all">{it}</li>
      ))}
    </ul>
  );
}
