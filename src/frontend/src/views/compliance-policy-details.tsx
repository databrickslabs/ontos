import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/ui/data-table';
import { ColumnDef } from '@tanstack/react-table';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { AlertCircle, ArrowLeft, PlayCircle, Scale, Pencil } from 'lucide-react';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';

type Policy = {
  id: string; // UUID
  name: string;
  description?: string;
  failure_message?: string;  // Human-readable message shown when policy fails
  rule: string;
  category?: string;
  severity?: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  examples?: { pass?: any[]; fail?: any[] } | null;
};

type Run = {
  id: string;
  policy_id: string;
  status: string;
  started_at: string;
  finished_at?: string;
  success_count: number;
  failure_count: number;
  score: number;
  error_message?: string;
};

type Result = {
  id: string;
  run_id: string;
  object_type: string;
  object_id: string;
  object_name?: string;
  passed: boolean;
  message?: string;
  details_json?: string;
  created_at: string;
};

export default function CompliancePolicyDetails() {
  const { t } = useTranslation(['compliance', 'common']);
  const { policyId } = useParams<{ policyId: string }>();
  const navigate = useNavigate();
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const resultsColumns: ColumnDef<Result>[] = useMemo(() => [
    { accessorKey: 'object_type', header: 'Type' },
    { accessorKey: 'object_name', header: 'Name', cell: ({ row }) => (
      <code className="text-xs bg-muted px-2 py-1 rounded">{row.original.object_name || row.original.object_id}</code>
    ) },
    { accessorKey: 'passed', header: 'Status', cell: ({ row }) => (
      <Badge variant={row.original.passed ? 'secondary' : 'destructive'}>
        {row.original.passed ? 'Passed' : 'Failed'}
      </Badge>
    ) },
    { accessorKey: 'message', header: 'Message', cell: ({ row }) => (
      <span className="text-sm text-muted-foreground break-words">{row.original.message || '-'}</span>
    ) },
  ], []);

  const fetchRuns = useCallback(async (pid: string) => {
    const runsRes = await get<Run[]>(`/api/compliance/policies/${pid}/runs`);
    const items = runsRes.data && Array.isArray(runsRes.data) ? runsRes.data : [];
    setRuns(items);
    if (items.length > 0) {
      setActiveRun(items[0]);
    } else {
      setActiveRun(null);
    }
  }, [get]);

  const fetchResults = useCallback(async (runId?: string, failedOnly?: boolean) => {
    if (!runId) { setResults([]); return; }
    const res = await get<any>(`/api/compliance/runs/${runId}/results?only_failed=${failedOnly ? 'true' : 'false'}`);
    if (res.data) {
      setResults(Array.isArray(res.data.results) ? res.data.results : []);
    } else {
      setResults([]);
    }
  }, [get]);

  const load = useCallback(async () => {
    if (!policyId) return;
    setLoading(true);
    setError(null);
    try {
      const policyRes = await get<Policy>(`/api/compliance/policies/${policyId}`);
      if (!policyRes.data) throw new Error(policyRes.error || 'Failed to load policy');
      setPolicy(policyRes.data);
      setDynamicTitle(policyRes.data.name);
      await fetchRuns(policyId);
    } catch (e: any) {
      setError(e.message || 'Failed to load');
      setPolicy(null);
      setDynamicTitle('Error');
    } finally {
      setLoading(false);
    }
  }, [get, policyId, fetchRuns, setDynamicTitle]);

  useEffect(() => {
    setStaticSegments([{ label: 'Compliance', path: '/compliance' }]);
    load();
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [load, setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    if (activeRun) {
      fetchResults(activeRun.id, onlyFailed);
    } else {
      setResults([]);
    }
  }, [activeRun, onlyFailed, fetchResults]);

  const runNow = async () => {
    if (!policyId) return;
    setLoading(true);
    try {
      const res = await post<Run>(`/api/compliance/policies/${policyId}/runs`, { mode: 'inline' });
      if (res.data) {
        await fetchRuns(policyId);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!policyId || !policy) return;
    
    setIsSaving(true);
    try {
      const form = event.target as HTMLFormElement;
      const updatedPolicy = {
        ...policy,
        name: (form.querySelector('#edit-name') as HTMLInputElement).value,
        description: (form.querySelector('#edit-description') as HTMLTextAreaElement).value,
        failure_message: (form.querySelector('#edit-failure-message') as HTMLTextAreaElement)?.value || undefined,
        category: (form.querySelector('[name="edit-category"]') as HTMLInputElement)?.value || policy.category,
        severity: (form.querySelector('[name="edit-severity"]') as HTMLInputElement)?.value || policy.severity,
        rule: (form.querySelector('#edit-rule') as HTMLTextAreaElement).value,
        updated_at: new Date().toISOString(),
      };

      const response = await put<Policy>(`/api/compliance/policies/${policyId}`, updatedPolicy);
      
      if (response.error || !response.data) {
        throw new Error(response.error || 'Failed to save policy');
      }
      
      setPolicy(response.data);
      setDynamicTitle(response.data.name);
      toast({
        title: t('common:toast.success'),
        description: t('compliance:toast.policySaved', { name: response.data.name })
      });
      
      setIsEditDialogOpen(false);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save policy';
      toast({
        variant: 'destructive',
        title: t('compliance:errors.savingPolicy'),
        description: errorMessage
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (loading) {
    return <DetailViewSkeleton cards={4} actionButtons={3} />;
  }
  if (error || !policy) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error || 'Compliance policy not found.'}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate('/compliance')} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to List
        </Button>
        <div className="flex items-center gap-2">
          <CommentSidebar
            entityType="compliance_policy"
            entityId={policyId!}
            isOpen={isCommentSidebarOpen}
            onToggle={() => setIsCommentSidebarOpen(!isCommentSidebarOpen)}
            className="h-8"
          />
          <Button variant="outline" onClick={() => setIsEditDialogOpen(true)} size="sm">
            <Pencil className="mr-2 h-4 w-4" /> Edit
          </Button>
          <Button variant="outline" onClick={runNow} size="sm"><PlayCircle className="mr-2 h-4 w-4" /> Run</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <Scale className="mr-3 h-7 w-7 text-primary" />{policy.name}
          </CardTitle>
          <CardDescription className="pt-1">{policy.description}</CardDescription>
        </CardHeader>
        <CardContent className="grid md:grid-cols-3 gap-4">
          <div>
            <div className="text-sm text-muted-foreground">ID</div>
            <code className="text-xs bg-muted px-2 py-1 rounded">{policy.id}</code>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">Category</div>
            <Badge variant="outline">{policy.category || 'General'}</Badge>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">Severity</div>
            <Badge>{policy.severity || 'medium'}</Badge>
          </div>
          <div className="md:col-span-3">
            <div className="text-sm text-muted-foreground">Rule</div>
            <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-48 whitespace-pre-wrap">{policy.rule}</pre>
          </div>
          {policy.examples && (policy.examples.pass?.length || policy.examples.fail?.length) ? (
            <div className="md:col-span-3">
              <div className="text-sm font-semibold mb-2">Examples</div>
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <div className="mb-2">
                    <Badge variant="secondary">Should Pass</Badge>
                  </div>
                  {policy.examples.pass && policy.examples.pass.length > 0 ? (
                    <ul className="list-disc pl-5 space-y-1">
                      {policy.examples.pass.map((ex, i) => (
                        <li key={`pass-${i}`} className="text-sm text-muted-foreground break-words">
                          <code className="text-xs bg-muted px-1 py-0.5 rounded">{typeof ex === 'string' ? ex : JSON.stringify(ex)}</code>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-sm text-muted-foreground">No examples</div>
                  )}
                </div>
                <div>
                  <div className="mb-2">
                    <Badge variant="destructive">Should Fail</Badge>
                  </div>
                  {policy.examples.fail && policy.examples.fail.length > 0 ? (
                    <ul className="list-disc pl-5 space-y-1">
                      {policy.examples.fail.map((ex, i) => (
                        <li key={`fail-${i}`} className="text-sm text-muted-foreground break-words">
                          <code className="text-xs bg-muted px-1 py-0.5 rounded">{typeof ex === 'string' ? ex : JSON.stringify(ex)}</code>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-sm text-muted-foreground">No examples</div>
                  )}
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {activeRun && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Run Summary</CardTitle>
            <CardDescription>
              Last run started {new Date(activeRun.started_at).toLocaleString()} • Status: <span className="font-medium">{activeRun.status}</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-3 gap-4 mb-4">
              <div>
                <div className="text-sm text-muted-foreground">Score</div>
                <div className="text-2xl font-semibold">{activeRun.score}%</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">Passed</div>
                <div className="text-2xl font-semibold text-green-600">{activeRun.success_count}</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">Failed</div>
                <div className="text-2xl font-semibold text-red-600">{activeRun.failure_count}</div>
              </div>
            </div>
            <div className="grid md:grid-cols-2 gap-6">
              <div>
                <div className="mb-2">
                  <Badge variant="secondary">Passed examples</Badge>
                </div>
                <ul className="list-disc pl-5 space-y-1">
                  {results.filter(r => r.passed).slice(0, 5).map((r) => (
                    <li key={`pass-prev-${r.id}`} className="text-sm text-muted-foreground break-words">
                      <code className="text-xs bg-muted px-1 py-0.5 rounded">{r.object_name || r.object_id}</code>
                    </li>
                  ))}
                  {results.filter(r => r.passed).length === 0 && (
                    <li className="text-sm text-muted-foreground">No passed examples in this run</li>
                  )}
                </ul>
              </div>
              <div>
                <div className="mb-2">
                  <Badge variant="destructive">Failed examples</Badge>
                </div>
                <ul className="list-disc pl-5 space-y-1">
                  {results.filter(r => !r.passed).slice(0, 5).map((r) => (
                    <li key={`fail-prev-${r.id}`} className="text-sm text-muted-foreground break-words">
                      <code className="text-xs bg-muted px-1 py-0.5 rounded">{r.object_name || r.object_id}</code>
                      {r.message ? <span className="ml-2">— {r.message}</span> : null}
                    </li>
                  ))}
                  {results.filter(r => !r.passed).length === 0 && (
                    <li className="text-sm text-muted-foreground">No failures in this run</li>
                  )}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Runs</CardTitle>
          <CardDescription>Most recent first</CardDescription>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <div className="text-sm text-muted-foreground">No runs yet</div>
          ) : (
            <div className="flex flex-col gap-2">
              {runs.map(r => (
                <button key={r.id} onClick={() => setActiveRun(r)} className={`text-left p-2 rounded border ${activeRun?.id === r.id ? 'bg-muted' : ''}`}>
                  <div className="flex items-center gap-3">
                    <Badge variant="outline">{r.status}</Badge>
                    <div className="text-sm">{new Date(r.started_at).toLocaleString()}</div>
                    <div className="ml-auto text-sm">Score: <span className="font-semibold">{r.score}%</span> • {r.success_count} passed / {r.failure_count} failed</div>
                  </div>
                  <div className="mt-2 text-xs">
                    <a href={`/compliance/runs/${r.id}`} className="text-primary hover:underline">Open run details</a>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {activeRun && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Results</CardTitle>
            <CardDescription>Filtered to {onlyFailed ? 'failed only' : 'all'} — latest run {new Date(activeRun.started_at).toLocaleString()}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between mb-3">
              <div />
              <div className="flex items-center gap-2">
                <Button size="sm" variant={onlyFailed ? 'default' : 'outline'} onClick={() => setOnlyFailed(true)}>Show Failed</Button>
                <Button size="sm" variant={!onlyFailed ? 'default' : 'outline'} onClick={() => setOnlyFailed(false)}>Show All</Button>
              </div>
            </div>
            <DataTable columns={resultsColumns} data={results} searchColumn="object_name" />
          </CardContent>
        </Card>
      )}

      <EntityMetadataPanel entityId={policyId!} entityType="compliance_policy" />

      {/* Edit Policy Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('compliance:editRule')}</DialogTitle>
            <DialogDescription>
              {t('common:labels.editDescription', { name: policy.name })}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">{t('common:labels.name')}</Label>
              <Input
                id="edit-name"
                defaultValue={policy.name}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-description">{t('common:labels.description')}</Label>
              <Textarea
                id="edit-description"
                defaultValue={policy.description}
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t('common:labels.category')}</Label>
                <Select name="edit-category" defaultValue={policy.category || 'General'}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('common:placeholders.selectCategory')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Security">{t('compliance:categories.security')}</SelectItem>
                    <SelectItem value="Data Quality">{t('compliance:categories.dataQuality')}</SelectItem>
                    <SelectItem value="Privacy">{t('compliance:categories.privacy')}</SelectItem>
                    <SelectItem value="Governance">{t('compliance:categories.governance')}</SelectItem>
                    <SelectItem value="Maturity">{t('compliance:categories.maturity', 'Maturity')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t('common:labels.severity')}</Label>
                <Select name="edit-severity" defaultValue={policy.severity || 'medium'}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('common:placeholders.selectSeverity')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-rule">{t('compliance:form.ruleCode')}</Label>
              <Textarea
                id="edit-rule"
                defaultValue={policy.rule}
                className="font-mono text-sm"
                rows={8}
                required
                placeholder={t('compliance:form.rulePlaceholder')}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-failure-message">{t('compliance:form.failureMessage')}</Label>
              <Textarea
                id="edit-failure-message"
                defaultValue={policy.failure_message}
                rows={3}
                placeholder={t('compliance:form.failureMessagePlaceholder')}
              />
              <p className="text-xs text-muted-foreground">
                {t('compliance:form.failureMessageHint')}
              </p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setIsEditDialogOpen(false)} disabled={isSaving}>
                {t('common:actions.cancel')}
              </Button>
              <Button type="submit" disabled={isSaving}>
                {isSaving ? t('common:states.saving') : t('common:actions.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}


