import { useCallback, useEffect, useMemo, useState } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import {
  AlertCircle,
  Activity,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
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
import { DataTable } from '@/components/ui/data-table';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Toaster } from '@/components/ui/toaster';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';

import RunConfigDialog from '@/components/term-mapping/run-config-dialog';
import SuggestionQueueTable from '@/components/term-mapping/suggestion-queue-table';
import ApplyDialog from '@/components/term-mapping/apply-dialog';

import type {
  Run,
  RunStats,
  RunStatus,
  RunSummary,
  Suggestion,
  SuggestionStatus,
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
  const { get, post } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();

  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const isAdmin = hasPermission(FEATURE_ID, FeatureAccessLevel.ADMIN);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<SuggestionStatus | 'all'>('pending');

  const [isNewRunOpen, setIsNewRunOpen] = useState(false);
  const [isApplyOpen, setIsApplyOpen] = useState(false);

  // -------- runs list ----------

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const res = await get<RunSummary[]>('/api/term-mappings/runs?limit=50');
      if (res.error) throw new Error(res.error);
      setRuns(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      setRunsError(e instanceof Error ? e.message : 'Failed to load runs');
    } finally {
      setRunsLoading(false);
    }
  }, [get]);

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  // -------- selected run + suggestions ----------

  const fetchRunDetail = useCallback(
    async (id: string) => {
      setRunDetailLoading(true);
      try {
        const res = await get<Run>(`/api/term-mappings/runs/${id}`);
        if (res.error) throw new Error(res.error);
        setSelectedRun(res.data);
      } catch (e) {
        toast({
          title: 'Failed to load run',
          description: e instanceof Error ? e.message : 'Unknown error',
          variant: 'destructive',
        });
        setSelectedRun(null);
      } finally {
        setRunDetailLoading(false);
      }
    },
    [get, toast],
  );

  const fetchSuggestions = useCallback(
    async (id: string, status: SuggestionStatus | 'all') => {
      setSuggestionsLoading(true);
      try {
        const qs = status === 'all' ? '' : `?status=${status}`;
        const res = await get<Suggestion[]>(
          `/api/term-mappings/runs/${id}/suggestions${qs}`,
        );
        if (res.error) throw new Error(res.error);
        setSuggestions(Array.isArray(res.data) ? res.data : []);
      } catch (e) {
        toast({
          title: 'Failed to load suggestions',
          description: e instanceof Error ? e.message : 'Unknown error',
          variant: 'destructive',
        });
        setSuggestions([]);
      } finally {
        setSuggestionsLoading(false);
      }
    },
    [get, toast],
  );

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      setSuggestions([]);
      return;
    }
    void fetchRunDetail(selectedRunId);
    void fetchSuggestions(selectedRunId, statusFilter);
  }, [selectedRunId, statusFilter, fetchRunDetail, fetchSuggestions]);

  // -------- actions ----------

  const handleRunCreated = (run: Run) => {
    setRuns((prev) => [
      { ...run } as RunSummary,
      ...prev.filter((r) => r.id !== run.id),
    ]);
    setSelectedRunId(run.id);
    setStatusFilter('pending');
  };

  const handleSuggestionDecided = () => {
    if (selectedRunId) {
      void fetchRunDetail(selectedRunId);
      void fetchSuggestions(selectedRunId, statusFilter);
      void fetchRuns(); // stats on the run list move too
    }
  };

  const handleRefresh = () => {
    void fetchRuns();
    if (selectedRunId) {
      void fetchRunDetail(selectedRunId);
      void fetchSuggestions(selectedRunId, statusFilter);
    }
  };

  const handleUndo = async () => {
    if (!selectedRun) return;
    if (
      !confirm(
        `Undo run ${selectedRun.id.slice(0, 8)}? This deletes all semantic links the run created and reverts accepted/applied suggestions back to pending.`,
      )
    ) {
      return;
    }
    try {
      const res = await post<UndoResult>(
        `/api/term-mappings/runs/${selectedRun.id}/undo`,
        {},
      );
      if (res.error) throw new Error(res.error);
      const result = res.data;
      toast({
        title: 'Undone',
        description: `${result.links_removed} link${result.links_removed === 1 ? '' : 's'} removed, ${result.suggestions_reverted} suggestions reverted.`,
      });
      handleRefresh();
    } catch (e) {
      toast({
        title: 'Undo failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      });
    }
  };

  // -------- runs table ----------

  const runColumns = useMemo<ColumnDef<RunSummary>[]>(
    () => [
      {
        accessorKey: 'id',
        header: 'Run',
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.id.slice(0, 8)}</span>
        ),
      },
      {
        accessorKey: 'status',
        header: ({ column }) => (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          >
            Status <ChevronDown className="ml-1 h-3 w-3" />
          </Button>
        ),
        cell: ({ row }) => (
          <Badge variant={RUN_STATUS_VARIANT[row.original.status]}>
            {row.original.status}
          </Badge>
        ),
      },
      {
        id: 'totals',
        header: 'Suggestions',
        cell: ({ row }) => {
          const s = row.original.stats ?? {};
          return (
            <div className="text-xs">
              <span title="total">{(s.suggestions_total as number) ?? 0}</span>{' '}
              <span className="text-muted-foreground">
                ({(s.suggestions_pending as number) ?? 0} pending,{' '}
                {(s.suggestions_accepted as number) ?? 0} accepted)
              </span>
            </div>
          );
        },
      },
      {
        id: 'links',
        header: 'Links',
        cell: ({ row }) => {
          const s = row.original.stats ?? {};
          const created = (s.links_created as number) ?? 0;
          return created > 0 ? (
            <Badge variant="default">{created}</Badge>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          );
        },
      },
      {
        accessorKey: 'created_by',
        header: 'By',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground truncate max-w-[180px]" title={row.original.created_by ?? ''}>
            {row.original.created_by ?? 'system'}
          </span>
        ),
      },
      {
        accessorKey: 'created_at',
        header: ({ column }) => (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          >
            Created <ChevronDown className="ml-1 h-3 w-3" />
          </Button>
        ),
        cell: ({ row }) => <RelativeDate date={row.original.created_at} />,
      },
    ],
    [],
  );

  // -------- render ----------

  const stats: RunStats = selectedRun?.stats ?? {};
  const canApply = selectedRun?.status === 'suggested' || selectedRun?.status === 'applied';
  const canUndo =
    isAdmin &&
    selectedRun?.status === 'applied' &&
    (selectedRun.applied_link_ids?.length ?? 0) > 0;
  const queueReadonly = !canWrite || selectedRun?.status === 'undone';

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Sparkles className="w-8 h-8" />
          Term Mapping
        </h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleRefresh} disabled={runsLoading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${runsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {canWrite && (
            <Button onClick={() => setIsNewRunOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              New run
            </Button>
          )}
        </div>
      </div>

      {!selectedRunId ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Recent runs</CardTitle>
          </CardHeader>
          <CardContent>
            {runsError && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{runsError}</AlertDescription>
              </Alert>
            )}
            {runsLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : runs.length === 0 ? (
              <div className="text-center py-12">
                <Activity className="h-12 w-12 text-muted-foreground mx-auto mb-3" />
                <p className="text-muted-foreground mb-4">
                  No term mapping runs yet.
                </p>
                {canWrite && (
                  <Button onClick={() => setIsNewRunOpen(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Create your first run
                  </Button>
                )}
              </div>
            ) : (
              <DataTable
                columns={runColumns}
                data={runs}
                onRowClick={(row) => setSelectedRunId(row.original.id)}
                defaultSortColumn="created_at"
                defaultSortDirection="desc"
              />
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <Button variant="ghost" size="sm" onClick={() => setSelectedRunId(null)}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to runs
          </Button>

          {runDetailLoading || !selectedRun ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : (
            <>
              {/* Run summary card */}
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <CardTitle className="text-lg flex items-center gap-3">
                        <Badge variant={RUN_STATUS_VARIANT[selectedRun.status]}>
                          {selectedRun.status}
                        </Badge>
                        <span className="font-mono text-sm text-muted-foreground">
                          {selectedRun.id}
                        </span>
                      </CardTitle>
                      {selectedRun.comment && (
                        <p className="text-sm text-muted-foreground">{selectedRun.comment}</p>
                      )}
                      {selectedRun.error && (
                        <Alert variant="destructive">
                          <AlertCircle className="h-4 w-4" />
                          <AlertDescription>{selectedRun.error}</AlertDescription>
                        </Alert>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {canWrite && canApply && (
                        <Button onClick={() => setIsApplyOpen(true)}>
                          <CheckCircle2 className="h-4 w-4 mr-2" />
                          Apply…
                        </Button>
                      )}
                      {canUndo && (
                        <Button variant="destructive" onClick={handleUndo}>
                          <Undo2 className="h-4 w-4 mr-2" />
                          Undo
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                    <Stat label="Targets" value={(stats.targets as number) ?? 0} />
                    <Stat label="Total" value={(stats.suggestions_total as number) ?? 0} />
                    <Stat
                      label="Pending"
                      value={(stats.suggestions_pending as number) ?? 0}
                    />
                    <Stat
                      label="Accepted"
                      value={(stats.suggestions_accepted as number) ?? 0}
                    />
                    <Stat
                      label="Rejected"
                      value={(stats.suggestions_rejected as number) ?? 0}
                      tone="muted"
                    />
                    <Stat
                      label="Links created"
                      value={(stats.links_created as number) ?? 0}
                      tone="success"
                    />
                  </div>
                  <Separator className="my-4" />
                  <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                    <div>
                      <span className="font-medium">Customer ontologies:</span>{' '}
                      {selectedRun.ontology_contexts.length === 0
                        ? 'all enabled'
                        : selectedRun.ontology_contexts.join(', ')}
                    </div>
                    <div>
                      <span className="font-medium">Shipped:</span>{' '}
                      {selectedRun.include_shipped.length === 0
                        ? '—'
                        : selectedRun.include_shipped.join(', ')}
                    </div>
                    <div>
                      <span className="font-medium">Entity types:</span>{' '}
                      {(selectedRun.target_filter?.entity_types ?? []).join(', ') || '—'}
                    </div>
                    <div>
                      <span className="font-medium">Engines:</span>{' '}
                      {selectedRun.engines.join(', ')}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Suggestion queue */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Suggestions</CardTitle>
                </CardHeader>
                <CardContent>
                  <Tabs
                    value={statusFilter}
                    onValueChange={(v) => setStatusFilter(v as SuggestionStatus | 'all')}
                  >
                    <TabsList>
                      <TabsTrigger value="pending">
                        Pending
                        <Badge variant="secondary" className="ml-2 text-[10px]">
                          {(stats.suggestions_pending as number) ?? 0}
                        </Badge>
                      </TabsTrigger>
                      <TabsTrigger value="accepted">
                        Accepted
                        <Badge variant="secondary" className="ml-2 text-[10px]">
                          {(stats.suggestions_accepted as number) ?? 0}
                        </Badge>
                      </TabsTrigger>
                      <TabsTrigger value="rejected">
                        Rejected
                        <Badge variant="secondary" className="ml-2 text-[10px]">
                          {(stats.suggestions_rejected as number) ?? 0}
                        </Badge>
                      </TabsTrigger>
                      <TabsTrigger value="applied">Applied</TabsTrigger>
                      <TabsTrigger value="all">All</TabsTrigger>
                    </TabsList>
                    <TabsContent value={statusFilter} className="mt-4">
                      <SuggestionQueueTable
                        runId={selectedRun.id}
                        suggestions={suggestions}
                        loading={suggestionsLoading}
                        readonly={queueReadonly}
                        onChanged={handleSuggestionDecided}
                      />
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      )}

      <RunConfigDialog
        isOpen={isNewRunOpen}
        onOpenChange={setIsNewRunOpen}
        onCreated={handleRunCreated}
      />

      <ApplyDialog
        isOpen={isApplyOpen}
        onOpenChange={setIsApplyOpen}
        run={selectedRun}
        onApplied={() => handleRefresh()}
      />

      <Toaster />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'success' | 'muted';
}) {
  const toneClass =
    tone === 'success'
      ? 'text-emerald-600'
      : tone === 'muted'
        ? 'text-muted-foreground'
        : 'text-foreground';
  return (
    <div className="rounded-md border p-3">
      <div className={`text-xl font-bold ${toneClass}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
