import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Wand2, Loader2, Copy, Download, Save, XCircle, Clock, CheckCircle2, AlertCircle, History, ChevronDown, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { HoverCard, HoverCardTrigger, HoverCardContent } from '@/components/ui/hover-card';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import type { Connection } from '@/types/connections';
import SchemaBrowser from '@/components/schema-importer/schema-browser';

// -- Types --

interface AgentStep {
  step_type: string;
  content: string;
  tool_name: string;
  duration_ms: number;
}

interface GenerateResponse {
  success: boolean;
  owl_content: string;
  classes: { uri: string; name: string; label: string; comment: string; emoji: string; parent: string; dataProperties: { name: string; label: string; uri: string }[] }[];
  properties: { uri: string; name: string; label: string; comment: string; type: string; domain: string; range: string }[];
  ontology_info: { uri: string; label: string; comment: string; namespace: string };
  constraints: Record<string, unknown>[];
  axioms: Record<string, unknown>[];
  steps: AgentStep[];
  iterations: number;
  error: string;
  usage: { prompt_tokens: number; completion_tokens: number };
}

interface RunParams {
  connection_id?: string;
  connection_name?: string;
  path_count: number;
  guidelines: string;
  base_uri: string;
  options: Record<string, unknown>;
}

interface RunSummary {
  run_id: string;
  status: string;
  progress_message?: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  completed_at?: string;
  params: RunParams;
  step_count: number;
}

interface RunDetail extends Omit<RunSummary, 'step_count'> {
  steps: AgentStep[];
  result?: GenerateResponse;
}

const POLL_INTERVAL_MS = 2000;

const STATUS_CONFIG: Record<string, { icon: typeof Loader2; variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  pending: { icon: Clock, variant: 'outline', label: 'Pending' },
  running: { icon: Loader2, variant: 'default', label: 'Running' },
  completed: { icon: CheckCircle2, variant: 'secondary', label: 'Completed' },
  failed: { icon: AlertCircle, variant: 'destructive', label: 'Failed' },
  cancelled: { icon: XCircle, variant: 'outline', label: 'Cancelled' },
};

export default function OntologyGeneratorView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { get: apiGet, post, delete: apiDelete } = useApi();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);

  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoadingConnections, setIsLoadingConnections] = useState(true);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  // Generation options
  const [guidelines, setGuidelines] = useState('');
  const [baseUri, setBaseUri] = useState('http://ontos.example.org/ontology#');
  const [includeDataProperties, setIncludeDataProperties] = useState(true);
  const [includeRelationships, setIncludeRelationships] = useState(true);
  const [includeInheritance, setIncludeInheritance] = useState(true);

  // Async run state
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [liveSteps, setLiveSteps] = useState<AgentStep[]>([]);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);

  // Save to collection
  const [isSaveDialogOpen, setIsSaveDialogOpen] = useState(false);
  const [collectionName, setCollectionName] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // Recent runs panel visibility
  const [showRecentRuns, setShowRecentRuns] = useState(false);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('semantic-models:ontologyGenerator.title'));
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle, t]);

  // -- Connections --

  const fetchConnections = useCallback(async () => {
    setIsLoadingConnections(true);
    try {
      const resp = await apiGet<Connection[]>('/api/connections');
      if (resp.data) {
        const enabled = resp.data.filter((c) => c.enabled);
        setConnections(enabled);
        if (enabled.length === 1) setSelectedConnectionId(enabled[0].id);
      }
    } catch (err) {
      console.error('Failed to fetch connections:', err);
    } finally {
      setIsLoadingConnections(false);
    }
  }, [apiGet]);

  useEffect(() => { fetchConnections(); }, [fetchConnections]);

  // -- Runs list fetch --

  const fetchRuns = useCallback(async () => {
    try {
      const resp = await apiGet<{ runs: RunSummary[] }>('/api/ontology/runs?limit=20');
      if (resp.data?.runs) {
        setRuns(resp.data.runs);
        // If there's a running run and we're not already polling, resume
        const running = resp.data.runs.find((r) => r.status === 'running' || r.status === 'pending');
        if (running && !activeRunId) {
          setActiveRunId(running.run_id);
          setProgressMessage(running.progress_message || null);
        }
      }
    } catch (err) {
      console.error('Failed to fetch runs:', err);
    }
  }, [apiGet, activeRunId]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  // -- Polling for active run --

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const pollRun = useCallback(async (runId: string) => {
    try {
      const resp = await apiGet<RunDetail>(`/api/ontology/runs/${runId}`);
      if (!resp.data) return;

      const run = resp.data;
      setProgressMessage(run.progress_message || null);

      // Only update the detail pane if the user is viewing this run (or no run selected)
      const viewing = selectedRunIdRef.current;
      const isViewingActiveRun = !viewing || viewing === runId;

      if (isViewingActiveRun) {
        setLiveSteps(run.steps || []);
      }

      if (run.status === 'completed') {
        stopPolling();
        setActiveRunId(null);
        if (run.result && isViewingActiveRun) {
          setResult(run.result);
          setSelectedRunId(runId);
          selectedRunIdRef.current = runId;
        }
        toast({
          title: t('semantic-models:ontologyGenerator.toasts.generatedTitle'),
          description: run.result
            ? t('semantic-models:ontologyGenerator.toasts.generatedDescription', {
                classes: run.result.classes.length,
                properties: run.result.properties.length,
              })
            : t('semantic-models:ontologyGenerator.toasts.generatedFallback'),
        });
        fetchRuns();
      } else if (run.status === 'failed' || run.status === 'cancelled') {
        stopPolling();
        setActiveRunId(null);
        toast({
          title: run.status === 'cancelled'
            ? t('semantic-models:ontologyGenerator.toasts.cancelledTitle')
            : t('semantic-models:ontologyGenerator.toasts.failedTitle'),
          description: run.error || t('semantic-models:ontologyGenerator.toasts.unknownError'),
          variant: 'destructive',
        });
        fetchRuns();
      }
    } catch (err) {
      console.error('Poll error:', err);
    }
  }, [apiGet, stopPolling, toast, fetchRuns, t]);

  useEffect(() => {
    if (!activeRunId) return;
    pollRun(activeRunId);
    pollingRef.current = setInterval(() => pollRun(activeRunId), POLL_INTERVAL_MS);
    return stopPolling;
  }, [activeRunId, pollRun, stopPolling]);

  // Cleanup on unmount
  useEffect(() => stopPolling, [stopPolling]);

  // -- Generate --

  const handleConnectionChange = (id: string) => {
    setSelectedConnectionId(id);
    setSelectedPaths(new Set());
  };

  const selectedConnection = connections.find((c) => c.id === selectedConnectionId);
  const isRunning = !!activeRunId;
  const canGenerate = selectedPaths.size > 0 && !isRunning && !isStarting;

  const handleGenerate = async () => {
    if (!selectedConnectionId || selectedPaths.size === 0) return;

    setIsStarting(true);
    setResult(null);
    setLiveSteps([]);
    setSelectedRunId(null);
    selectedRunIdRef.current = null;

    try {
      const response = await post<{ run_id: string; status: string }>('/api/ontology/generate-from-connection', {
        connection_id: selectedConnectionId,
        selected_paths: Array.from(selectedPaths),
        guidelines,
        base_uri: baseUri,
        include_data_properties: includeDataProperties,
        include_relationships: includeRelationships,
        include_inheritance: includeInheritance,
      });

      if (response.error) {
        toast({ title: t('semantic-models:ontologyGenerator.toasts.startFailed'), description: response.error, variant: 'destructive' });
        return;
      }

      if (response.data?.run_id) {
        setActiveRunId(response.data.run_id);
        setProgressMessage(t('semantic-models:ontologyGenerator.progress.starting'));
        toast({ title: t('semantic-models:ontologyGenerator.toasts.startedTitle'), description: t('semantic-models:ontologyGenerator.toasts.startedDescription') });
      }
    } catch (err) {
      toast({ title: t('common:toast.error'), description: String(err), variant: 'destructive' });
    } finally {
      setIsStarting(false);
    }
  };

  // -- Cancel --

  const handleCancel = async () => {
    if (!activeRunId) return;
    try {
      await apiDelete(`/api/ontology/runs/${activeRunId}`);
      stopPolling();
      setActiveRunId(null);
      setProgressMessage(null);
      fetchRuns();
    } catch (err) {
      toast({ title: t('semantic-models:ontologyGenerator.toasts.cancelFailed'), description: String(err), variant: 'destructive' });
    }
  };

  // -- Load past run result --

  const loadRunResult = async (runId: string) => {
    try {
      const resp = await apiGet<RunDetail>(`/api/ontology/runs/${runId}`);
      if (resp.data?.result) {
        setResult(resp.data.result);
        setSelectedRunId(runId);
        selectedRunIdRef.current = runId;
        setLiveSteps(resp.data.steps || []);
      } else {
        toast({ title: t('semantic-models:ontologyGenerator.toasts.noResultTitle'), description: t('semantic-models:ontologyGenerator.toasts.noResultDescription'), variant: 'destructive' });
      }
    } catch (err) {
      toast({ title: t('common:toast.error'), description: String(err), variant: 'destructive' });
    }
  };

  const deleteRun = async (runId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await apiDelete(`/api/ontology/runs/${runId}`);
      if (selectedRunId === runId) {
        setResult(null);
        setSelectedRunId(null);
        selectedRunIdRef.current = null;
        setLiveSteps([]);
      }
      fetchRuns();
    } catch (err) {
      toast({ title: t('semantic-models:ontologyGenerator.toasts.deleteFailed'), description: String(err), variant: 'destructive' });
    }
  };

  // -- Turtle helpers --

  const copyTurtle = () => {
    if (result?.owl_content) {
      navigator.clipboard.writeText(result.owl_content);
      toast({ title: t('common:copied'), description: t('semantic-models:ontologyGenerator.toasts.turtleCopied') });
    }
  };

  const downloadTurtle = () => {
    if (result?.owl_content) {
      const blob = new Blob([result.owl_content], { type: 'text/turtle' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ontology.ttl';
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  // -- Save to collection --

  const handleSaveToCollection = async () => {
    if (!result?.owl_content || !collectionName.trim()) return;

    setIsSaving(true);
    try {
      const response = await post<{
        success: boolean;
        collection_iri: string;
        triples_imported: number;
        error: string;
      }>('/api/ontology/save-to-collection', {
        owl_content: result.owl_content,
        collection_name: collectionName.trim(),
        collection_description: collectionDescription.trim(),
      });

      if (response.error) {
        toast({ title: t('semantic-models:ontologyGenerator.toasts.saveFailed'), description: response.error, variant: 'destructive' });
        return;
      }

      if (response.data?.success) {
        toast({
          title: t('semantic-models:ontologyGenerator.toasts.savedTitle'),
          description: t('semantic-models:ontologyGenerator.toasts.savedDescription', {
            count: response.data.triples_imported,
            name: collectionName,
          }),
        });
        setIsSaveDialogOpen(false);
        setCollectionName('');
        setCollectionDescription('');
        bumpKnowledgeGraphRefresh('ontology-save');
      } else {
        toast({ title: t('semantic-models:ontologyGenerator.toasts.saveFailed'), description: response.data?.error || t('semantic-models:ontologyGenerator.toasts.unknownError'), variant: 'destructive' });
      }
    } catch (err) {
      toast({ title: t('common:toast.error'), description: String(err), variant: 'destructive' });
    } finally {
      setIsSaving(false);
    }
  };

  // -- Render helpers --

  const formatTime = (iso?: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const StatusIcon = ({ status }: { status: string }) => {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
    const Icon = cfg.icon;
    const colorMap: Record<string, string> = {
      pending: 'text-muted-foreground',
      running: 'text-primary',
      completed: 'text-green-600',
      failed: 'text-destructive',
      cancelled: 'text-muted-foreground',
    };
    return (
      <Icon className={`h-4 w-4 shrink-0 ${colorMap[status] || 'text-muted-foreground'} ${status === 'running' ? 'animate-spin' : ''}`} />
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">{t('semantic-models:ontologyGenerator.title')}</h2>
        <p className="text-muted-foreground">
          {t('semantic-models:ontologyGenerator.subtitle')}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Left panel */}
        <div className="space-y-4">
          {/* Connection selector */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">{t('common:labels.connection')}</CardTitle>
              <CardDescription className="text-xs">{t('semantic-models:ontologyGenerator.connectionDescription')}</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingConnections ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> {t('common:states.loading')}
                </div>
              ) : connections.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t('semantic-models:ontologyGenerator.noConnections')}
                </p>
              ) : (
                <Select value={selectedConnectionId || ''} onValueChange={handleConnectionChange}>
                  <SelectTrigger><SelectValue placeholder={t('semantic-models:ontologyGenerator.chooseConnection')} /></SelectTrigger>
                  <SelectContent>
                    {connections.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        <div className="flex items-center gap-2">
                          <span>{c.name}</span>
                          <Badge variant="outline" className="text-[10px] px-1 py-0">{c.connector_type}</Badge>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </CardContent>
          </Card>

          {/* Generation options */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">{t('semantic-models:ontologyGenerator.generationOptions')}</CardTitle>
              <CardDescription className="text-xs">{t('semantic-models:ontologyGenerator.generationOptionsDescription')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label htmlFor="guidelines" className="text-xs">{t('semantic-models:ontologyGenerator.guidelines')}</Label>
                <Textarea id="guidelines" placeholder={t('semantic-models:ontologyGenerator.guidelinesPlaceholder')} value={guidelines} onChange={(e) => setGuidelines(e.target.value)} rows={3} className="mt-1 text-sm" />
              </div>
              <div>
                <Label htmlFor="baseUri" className="text-xs">{t('semantic-models:ontologyGenerator.baseUri')}</Label>
                <Input id="baseUri" value={baseUri} onChange={(e) => setBaseUri(e.target.value)} className="mt-1 font-mono text-xs" />
              </div>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="incDataProps" className="text-xs">{t('semantic-models:ontologyGenerator.dataProperties')}</Label>
                  <Switch id="incDataProps" checked={includeDataProperties} onCheckedChange={setIncludeDataProperties} />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="incRels" className="text-xs">{t('semantic-models:ontologyGenerator.relationships')}</Label>
                  <Switch id="incRels" checked={includeRelationships} onCheckedChange={setIncludeRelationships} />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="incInherit" className="text-xs">{t('semantic-models:ontologyGenerator.inheritance')}</Label>
                  <Switch id="incInherit" checked={includeInheritance} onCheckedChange={setIncludeInheritance} />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Generate / Cancel buttons */}
          <div className="space-y-2">
            {isRunning ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-muted-foreground px-1">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  <span className="truncate">{progressMessage || t('semantic-models:ontologyGenerator.progress.working')}</span>
                </div>
                <Button variant="destructive" onClick={handleCancel} className="w-full">
                  <XCircle className="h-4 w-4 mr-2" /> {t('semantic-models:ontologyGenerator.cancelGeneration')}
                </Button>
              </div>
            ) : (
              <Button onClick={handleGenerate} disabled={!canGenerate} className="w-full">
                {isStarting ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> {t('semantic-models:ontologyGenerator.progress.starting')}</>
                ) : (
                  <><Wand2 className="h-4 w-4 mr-2" /> {t('semantic-models:ontologyGenerator.generateOntology', { count: selectedPaths.size })}</>
                )}
              </Button>
            )}
          </div>

          {/* Recent Runs */}
          <Card>
            <CardHeader
              className="py-3 cursor-pointer select-none hover:bg-muted/50 transition-colors rounded-t-lg"
              onClick={() => setShowRecentRuns(!showRecentRuns)}
            >
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <History className="h-4 w-4" /> {t('semantic-models:ontologyGenerator.recentRuns')}
                  {runs.length > 0 && <Badge variant="secondary" className="text-xs">{runs.length}</Badge>}
                </CardTitle>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${showRecentRuns ? 'rotate-180' : ''}`} />
              </div>
            </CardHeader>
            {showRecentRuns && (
              <CardContent className="pt-0 pb-3">
                <ScrollArea className="max-h-[300px]">
                  {runs.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-4">{t('semantic-models:ontologyGenerator.noRuns')}</p>
                  ) : (
                    <div className="space-y-0.5">
                      {runs.map((run) => (
                        <HoverCard key={run.run_id} openDelay={300} closeDelay={100}>
                          <HoverCardTrigger asChild>
                            <div
                              className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-xs cursor-pointer hover:bg-muted transition-colors ${selectedRunId === run.run_id ? 'bg-muted ring-1 ring-primary/20' : ''}`}
                              onClick={() => {
                                if (run.status === 'completed') loadRunResult(run.run_id);
                              }}
                            >
                              <StatusIcon status={run.status} />
                              <span className="flex-1 truncate font-medium">
                                {run.params.connection_name || t('semantic-models:ontologyGenerator.direct')}
                              </span>
                              <span className="text-muted-foreground shrink-0">{formatTime(run.created_at)}</span>
                              {run.status !== 'running' && run.status !== 'pending' && (
                                <button
                                  className="p-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                                  onClick={(e) => deleteRun(run.run_id, e)}
                                  title={t('semantic-models:ontologyGenerator.deleteRun')}
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              )}
                            </div>
                          </HoverCardTrigger>
                          <HoverCardContent side="right" align="start" className="w-72 text-xs">
                            <div className="space-y-2">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold">{run.params.connection_name || t('semantic-models:ontologyGenerator.directGeneration')}</span>
                                <Badge variant={STATUS_CONFIG[run.status]?.variant || 'outline'} className="text-[10px]">
                                  {t(`semantic-models:ontologyGenerator.runStatus.${run.status}`, run.status)}
                                </Badge>
                              </div>
                              <Separator />
                              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-muted-foreground">
                                <span>{t('semantic-models:ontologyGenerator.paths')}</span><span className="font-mono">{run.params.path_count}</span>
                                <span>{t('semantic-models:ontologyGenerator.steps')}</span><span className="font-mono">{run.step_count}</span>
                                <span>{t('semantic-models:ontologyGenerator.started')}</span><span>{run.created_at ? new Date(run.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' }) : '—'}</span>
                                {run.completed_at && (<><span>{t('semantic-models:ontologyGenerator.finished')}</span><span>{new Date(run.completed_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' })}</span></>)}
                              </div>
                              {run.params.guidelines && (
                                <>
                                  <Separator />
                                  <div>
                                    <span className="text-muted-foreground">{t('semantic-models:ontologyGenerator.guidelines')}:</span>
                                    <p className="mt-0.5 line-clamp-2">{run.params.guidelines}</p>
                                  </div>
                                </>
                              )}
                              {run.error && (
                                <>
                                  <Separator />
                                  <p className="text-destructive line-clamp-2">{run.error}</p>
                                </>
                              )}
                            </div>
                          </HoverCardContent>
                        </HoverCard>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            )}
          </Card>
        </div>

        {/* Right panel */}
        <div className="space-y-4">
          {/* Schema tree browser */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-medium">
                    {selectedConnection
                      ? t('semantic-models:ontologyGenerator.resourcesWithName', { name: selectedConnection.name })
                      : t('semantic-models:ontologyGenerator.resources')}
                  </CardTitle>
                  <CardDescription className="text-xs">{t('semantic-models:ontologyGenerator.resourcesDescription')}</CardDescription>
                </div>
                {selectedPaths.size > 0 && <Badge variant="secondary">{t('semantic-models:ontologyGenerator.selectedCount', { count: selectedPaths.size })}</Badge>}
              </div>
            </CardHeader>
            <CardContent>
              <SchemaBrowser connectionId={selectedConnectionId} selectedPaths={selectedPaths} onSelectionChange={setSelectedPaths} />
            </CardContent>
          </Card>

          {/* Live progress while running */}
          {isRunning && liveSteps.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> {t('semantic-models:ontologyGenerator.agentProgress')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[200px]">
                  <div className="space-y-1">
                    {liveSteps.map((step, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs py-1">
                        <Badge variant={step.step_type === 'tool_call' ? 'default' : step.step_type === 'tool_result' ? 'secondary' : 'outline'} className="text-[10px] shrink-0">
                          {step.step_type}
                        </Badge>
                        {step.tool_name && <span className="font-mono text-muted-foreground">{step.tool_name}</span>}
                        <span className="truncate text-muted-foreground">{step.content.slice(0, 80)}</span>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          )}

          {/* Results tabs */}
          {result && (
            <Tabs defaultValue="classes">
              <TabsList className="w-full">
                <TabsTrigger value="classes">{t('semantic-models:ontologyGenerator.tabs.classes', { count: result.classes.length })}</TabsTrigger>
                <TabsTrigger value="properties">{t('semantic-models:ontologyGenerator.tabs.properties', { count: result.properties.length })}</TabsTrigger>
                <TabsTrigger value="turtle">{t('semantic-models:ontologyGenerator.tabs.turtle')}</TabsTrigger>
                <TabsTrigger value="agent">{t('semantic-models:ontologyGenerator.tabs.agentLog')}</TabsTrigger>
              </TabsList>

              <TabsContent value="classes">
                <Card>
                  <CardContent className="pt-4">
                    <ScrollArea className="h-[400px]">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>{t('semantic-models:ontologyGenerator.table.class')}</TableHead>
                            <TableHead>{t('semantic-models:ontologyGenerator.table.parent')}</TableHead>
                            <TableHead>{t('semantic-models:ontologyGenerator.table.attributes')}</TableHead>
                            <TableHead>{t('common:labels.description')}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.classes.map((cls) => (
                            <TableRow key={cls.uri}>
                              <TableCell className="font-mono font-medium">
                                {cls.emoji && <span className="mr-1">{cls.emoji}</span>}
                                {cls.name}
                              </TableCell>
                              <TableCell className="font-mono text-muted-foreground">{cls.parent || '—'}</TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1">
                                  {cls.dataProperties.map((dp) => (
                                    <Badge key={dp.name} variant="secondary" className="text-xs font-mono">{dp.name}</Badge>
                                  ))}
                                  {cls.dataProperties.length === 0 && <span className="text-muted-foreground text-xs">{t('semantic-models:ontologyGenerator.table.none')}</span>}
                                </div>
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">{cls.comment || '—'}</TableCell>
                            </TableRow>
                          ))}
                          {result.classes.length === 0 && (
                            <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">{t('semantic-models:ontologyGenerator.noClasses')}</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="properties">
                <Card>
                  <CardContent className="pt-4">
                    <ScrollArea className="h-[400px]">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>{t('semantic-models:ontologyGenerator.table.property')}</TableHead>
                            <TableHead>{t('common:labels.type')}</TableHead>
                            <TableHead>{t('common:labels.domain')}</TableHead>
                            <TableHead>{t('semantic-models:ontologyGenerator.table.range')}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.properties.map((prop) => (
                            <TableRow key={prop.uri}>
                              <TableCell className="font-mono font-medium">{prop.name}</TableCell>
                              <TableCell>
                                <Badge variant={prop.type === 'ObjectProperty' ? 'default' : 'secondary'} className="text-xs">
                                  {prop.type === 'ObjectProperty' ? t('semantic-models:ontologyGenerator.table.objectType') : t('semantic-models:ontologyGenerator.table.dataType')}
                                </Badge>
                              </TableCell>
                              <TableCell className="font-mono text-sm">{prop.domain || '—'}</TableCell>
                              <TableCell className="font-mono text-sm">{prop.range || '—'}</TableCell>
                            </TableRow>
                          ))}
                          {result.properties.length === 0 && (
                            <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">{t('semantic-models:ontologyGenerator.noProperties')}</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="turtle">
                <Card>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm">{t('semantic-models:ontologyGenerator.generatedTurtle')}</CardTitle>
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={copyTurtle}><Copy className="h-3.5 w-3.5 mr-1" /> {t('common:actions.copy')}</Button>
                        <Button variant="outline" size="sm" onClick={downloadTurtle}><Download className="h-3.5 w-3.5 mr-1" /> {t('common:actions.download')}</Button>
                        <Button size="sm" onClick={() => setIsSaveDialogOpen(true)}><Save className="h-3.5 w-3.5 mr-1" /> {t('semantic-models:ontologyGenerator.saveToCollection')}</Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[400px]">
                      <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-4 rounded-md">{result.owl_content || t('semantic-models:ontologyGenerator.empty')}</pre>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="agent">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t('semantic-models:ontologyGenerator.agentExecutionLog')}</CardTitle>
                    <CardDescription>
                      {t('semantic-models:ontologyGenerator.agentLogSummary', {
                        iterations: result.iterations,
                        promptTokens: result.usage?.prompt_tokens ?? 0,
                        completionTokens: result.usage?.completion_tokens ?? 0,
                      })}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[400px]">
                      <div className="space-y-2">
                        {result.steps.map((step, i) => (
                          <div key={i} className="border rounded-md p-3">
                            <div className="flex items-center gap-2 mb-1">
                              <Badge variant={step.step_type === 'tool_call' ? 'default' : step.step_type === 'tool_result' ? 'secondary' : 'outline'} className="text-xs">{step.step_type}</Badge>
                              {step.tool_name && <span className="text-xs font-mono text-muted-foreground">{step.tool_name}</span>}
                              {step.duration_ms > 0 && <span className="text-xs text-muted-foreground ml-auto">{step.duration_ms}ms</span>}
                            </div>
                            <pre className="text-xs font-mono whitespace-pre-wrap text-muted-foreground mt-1 max-h-32 overflow-auto">{step.content}</pre>
                          </div>
                        ))}
                        {result.steps.length === 0 && (
                          <p className="text-center text-muted-foreground text-sm">{t('semantic-models:ontologyGenerator.noAgentSteps')}</p>
                        )}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          )}

          {result && !result.success && result.error && (
            <Card className="border-destructive">
              <CardContent className="pt-4">
                <p className="text-sm text-destructive">{result.error}</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Save to Collection dialog */}
      <Dialog open={isSaveDialogOpen} onOpenChange={setIsSaveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('semantic-models:ontologyGenerator.saveDialog.title')}</DialogTitle>
            <DialogDescription>{t('semantic-models:ontologyGenerator.saveDialog.description')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label htmlFor="collName">{t('semantic-models:ontologyGenerator.saveDialog.nameLabel')}</Label>
              <Input id="collName" placeholder={t('semantic-models:ontologyGenerator.saveDialog.namePlaceholder')} value={collectionName} onChange={(e) => setCollectionName(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label htmlFor="collDesc">{t('semantic-models:ontologyGenerator.saveDialog.descriptionLabel')}</Label>
              <Textarea id="collDesc" placeholder={t('semantic-models:ontologyGenerator.saveDialog.descriptionPlaceholder')} value={collectionDescription} onChange={(e) => setCollectionDescription(e.target.value)} rows={3} className="mt-1" />
            </div>
            {result && (
              <p className="text-xs text-muted-foreground">
                {t('semantic-models:ontologyGenerator.saveDialog.importSummary', {
                  classes: result.classes.length,
                  properties: result.properties.length,
                })}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsSaveDialogOpen(false)} disabled={isSaving}>{t('common:actions.cancel')}</Button>
            <Button onClick={handleSaveToCollection} disabled={isSaving || !collectionName.trim()}>
              {isSaving ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> {t('common:actions.saving')}</> : <><Save className="h-4 w-4 mr-2" /> {t('common:actions.save')}</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
