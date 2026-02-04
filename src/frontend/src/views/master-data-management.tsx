import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { RelativeDate } from '@/components/common/relative-date';
import { 
  GitCompare, Plus, Play, FileCheck, Link2, 
  Database, AlertCircle, Loader2,
  // CheckCircle2, // Available for future use
  Clock, Trash2, Settings2, RefreshCw, Users,
  Merge, Eye
} from 'lucide-react';

import MdmConfigDialog from '@/components/mdm/mdm-config-dialog';
import LinkSourceDialog from '@/components/mdm/link-source-dialog';
import CreateReviewDialog from '@/components/mdm/create-review-dialog';
import MatchingRulesEditor from '@/components/mdm/matching-rules-editor';
import {
  MdmConfig,
  MdmSourceLink,
  MdmMatchRun,
  MdmMatchCandidate,
  MdmConfigStatus,
  MdmMatchRunStatus,
  MdmMatchCandidateStatus,
  MdmMatchType,
} from '@/types/mdm';

export default function MasterDataManagement() {
  const { t } = useTranslation(['mdm', 'common']);
  const [configs, setConfigs] = useState<MdmConfig[]>([]);
  const [selectedConfig, setSelectedConfig] = useState<MdmConfig | null>(null);
  const [sourceLinks, setSourceLinks] = useState<MdmSourceLink[]>([]);
  const [matchRuns, setMatchRuns] = useState<MdmMatchRun[]>([]);
  const [candidates, setCandidates] = useState<MdmMatchCandidate[]>([]);
  const [selectedRun, setSelectedRun] = useState<MdmMatchRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isConfigDialogOpen, setIsConfigDialogOpen] = useState(false);
  const [isLinkDialogOpen, setIsLinkDialogOpen] = useState(false);
  const [isReviewDialogOpen, setIsReviewDialogOpen] = useState(false);
  const [isRulesEditorOpen, setIsRulesEditorOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  const { get, post, delete: deleteApi } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('mdm:title'));
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    fetchConfigs();
  }, []);

  const fetchConfigs = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await get<MdmConfig[]>('/api/mdm/configs');
      if (response.error) {
        setError(response.error);
        setConfigs([]);
        return;
      }
      if (response.data && Array.isArray(response.data)) {
        setConfigs(response.data);
        // If we had a selected config, refresh it
        if (selectedConfig) {
          const updated = response.data.find(c => c.id === selectedConfig.id);
          if (updated) {
            setSelectedConfig(updated);
          }
        }
      } else {
        setConfigs([]);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load MDM configurations');
      setConfigs([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchSourceLinks = async (configId: string) => {
    try {
      const response = await get<MdmSourceLink[]>(`/api/mdm/configs/${configId}/sources`);
      if (response.data) {
        setSourceLinks(response.data);
      }
    } catch (err: any) {
      console.error('Error fetching source links:', err);
    }
  };

  const fetchMatchRuns = async (configId: string) => {
    try {
      const response = await get<MdmMatchRun[]>(`/api/mdm/configs/${configId}/runs`);
      if (response.data) {
        setMatchRuns(response.data);
      }
    } catch (err: any) {
      console.error('Error fetching match runs:', err);
    }
  };

  const fetchCandidates = async (runId: string) => {
    try {
      const response = await get<MdmMatchCandidate[]>(`/api/mdm/runs/${runId}/candidates`);
      if (response.data) {
        setCandidates(response.data);
      }
    } catch (err: any) {
      console.error('Error fetching candidates:', err);
    }
  };

  const handleSelectConfig = (config: MdmConfig) => {
    setSelectedConfig(config);
    setSelectedRun(null);
    setCandidates([]);
    fetchSourceLinks(config.id);
    fetchMatchRuns(config.id);
  };

  const handleStartMatching = async (configId: string) => {
    try {
      const response = await post<MdmMatchRun>(`/api/mdm/configs/${configId}/start-run`, {});
      if (response.data) {
        toast({ title: t('common:toast.success'), description: t('mdm:toast.matchingStarted') });
        fetchMatchRuns(configId);
      }
    } catch (err: any) {
      toast({ title: t('common:toast.error'), description: err.message || t('mdm:errors.startMatchingFailed'), variant: 'destructive' });
    }
  };

  const handleMergeApproved = async (runId: string) => {
    try {
      const response = await post(`/api/mdm/runs/${runId}/merge-approved`, {});
      if (response.data) {
        toast({ 
          title: t('common:toast.success'), 
          description: (response.data as any).message || t('mdm:toast.mergeCompleted') 
        });
        if (selectedConfig) {
          fetchMatchRuns(selectedConfig.id);
        }
        if (selectedRun) {
          fetchCandidates(selectedRun.id);
        }
      }
    } catch (err: any) {
      toast({ title: t('common:toast.error'), description: err.message || t('mdm:errors.mergeFailed'), variant: 'destructive' });
    }
  };

  const handleDeleteConfig = async (configId: string) => {
    if (!confirm(t('mdm:confirm.deleteConfig'))) return;
    
    try {
      await deleteApi(`/api/mdm/configs/${configId}`);
      toast({ title: t('common:toast.success'), description: t('mdm:toast.configDeleted') });
      if (selectedConfig?.id === configId) {
        setSelectedConfig(null);
      }
      fetchConfigs();
    } catch (err: any) {
      toast({ title: t('common:toast.error'), description: err.message || t('mdm:errors.deleteFailed'), variant: 'destructive' });
    }
  };

  const handleDeleteSourceLink = async (linkId: string) => {
    if (!confirm(t('mdm:confirm.deleteSource'))) return;
    
    try {
      await deleteApi(`/api/mdm/sources/${linkId}`);
      toast({ title: t('common:toast.success'), description: t('mdm:toast.sourceRemoved') });
      if (selectedConfig) {
        fetchSourceLinks(selectedConfig.id);
        fetchConfigs(); // Refresh source count
      }
    } catch (err: any) {
      toast({ title: 'Error', description: err.message || 'Delete failed', variant: 'destructive' });
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      active: 'default',
      completed: 'default',
      running: 'secondary',
      pending: 'outline',
      approved: 'default',
      rejected: 'destructive',
      merged: 'default',
      failed: 'destructive',
      paused: 'outline',
      archived: 'outline',
    };
    return <Badge variant={variants[status] || 'outline'}>{status}</Badge>;
  };

  const getMatchTypeBadge = (matchType: MdmMatchType) => {
    const variants: Record<string, "default" | "secondary" | "outline"> = {
      exact: 'default',
      fuzzy: 'secondary',
      probabilistic: 'outline',
      new: 'secondary',
    };
    return <Badge variant={variants[matchType] || 'outline'}>{matchType}</Badge>;
  };

  const getConfidenceColor = (score: number) => {
    if (score >= 0.9) return 'text-green-600';
    if (score >= 0.8) return 'text-yellow-600';
    return 'text-orange-600';
  };

  // Calculate statistics for selected config
  const configStats = useMemo(() => {
    if (!matchRuns.length) return null;
    
    const completedRuns = matchRuns.filter(r => r.status === MdmMatchRunStatus.COMPLETED);
    const totalMatches = completedRuns.reduce((sum, r) => sum + r.matches_found, 0);
    const totalNew = completedRuns.reduce((sum, r) => sum + r.new_records, 0);
    const pendingReview = matchRuns.reduce((sum, r) => sum + r.pending_review_count, 0);
    
    return {
      totalRuns: matchRuns.length,
      completedRuns: completedRuns.length,
      totalMatches,
      totalNew,
      pendingReview,
    };
  }, [matchRuns]);

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <GitCompare className="w-8 h-8" />
            {t('mdm:title')}
          </h1>
          <p className="text-muted-foreground mt-1">
            {t('mdm:subtitle')}
          </p>
        </div>
        <Button onClick={() => setIsConfigDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          {t('mdm:newConfiguration')}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="flex justify-center items-center h-64">
          <Loader2 className="h-12 w-12 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          {/* MDM Configurations List */}
          <div className="col-span-4">
            <Card className="h-full">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Database className="h-5 w-5" />
                  {t('mdm:configurations')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[calc(100vh-320px)]">
                  <div className="space-y-3 pr-4">
                    {configs.map(config => (
                      <div
                        key={config.id}
                        className={`p-3 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
                          selectedConfig?.id === config.id 
                            ? 'border-primary bg-primary/5 shadow-sm' 
                            : 'hover:border-primary/50'
                        }`}
                        onClick={() => handleSelectConfig(config)}
                      >
                        <div className="flex justify-between items-start">
                          <div className="flex-1 min-w-0">
                            <h4 className="font-medium truncate">{config.name}</h4>
                            <p className="text-sm text-muted-foreground truncate">
                              {config.entity_type} • {config.source_count} sources
                            </p>
                          </div>
                          <div className="flex items-center gap-2 ml-2">
                            {getStatusBadge(config.status)}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteConfig(config.id);
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                        {config.last_run_at && (
                          <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                            <Clock className="h-3 w-3" />
                            Last run: <RelativeDate date={config.last_run_at} />
                            {config.last_run_status && (
                              <span className={
                                config.last_run_status === 'completed' 
                                  ? 'text-green-600' 
                                  : config.last_run_status === 'failed' 
                                    ? 'text-red-600' 
                                    : 'text-yellow-600'
                              }>
                                ({config.last_run_status})
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                    {configs.length === 0 && (
                      <div className="text-center py-12">
                        <Database className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                        <p className="text-muted-foreground">
                          No MDM configurations yet.
                        </p>
                        <p className="text-sm text-muted-foreground mt-1">
                          Create one to get started.
                        </p>
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>

          {/* Configuration Details */}
          <div className="col-span-8">
            {selectedConfig ? (
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <CardTitle className="text-xl">{selectedConfig.name}</CardTitle>
                      <CardDescription className="mt-1">
                        {selectedConfig.description || `Master contract for ${selectedConfig.entity_type} entities`}
                      </CardDescription>
                    </div>
                    <div className="flex gap-2">
                      <Button 
                        onClick={() => handleStartMatching(selectedConfig.id)}
                        disabled={selectedConfig.status !== MdmConfigStatus.ACTIVE}
                      >
                        <Play className="h-4 w-4 mr-2" />
                        Start Matching
                      </Button>
                      <Button variant="outline" onClick={() => setIsLinkDialogOpen(true)}>
                        <Link2 className="h-4 w-4 mr-2" />
                        Link Source
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <Tabs value={activeTab} onValueChange={setActiveTab}>
                    <TabsList className="mb-4">
                      <TabsTrigger value="overview">Overview</TabsTrigger>
                      <TabsTrigger value="sources">
                        Sources ({sourceLinks.length})
                      </TabsTrigger>
                      <TabsTrigger value="rules">Matching Rules</TabsTrigger>
                      <TabsTrigger value="runs">
                        Match Runs ({matchRuns.length})
                      </TabsTrigger>
                      {selectedRun && (
                        <TabsTrigger value="candidates">
                          Candidates ({candidates.length})
                        </TabsTrigger>
                      )}
                    </TabsList>

                    {/* Overview Tab */}
                    <TabsContent value="overview" className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="p-4 rounded-lg border bg-muted/30">
                          <p className="text-sm text-muted-foreground">Master Contract</p>
                          <p className="font-medium mt-1">{selectedConfig.master_contract_name || 'Not set'}</p>
                        </div>
                        <div className="p-4 rounded-lg border bg-muted/30">
                          <p className="text-sm text-muted-foreground">Entity Type</p>
                          <p className="font-medium capitalize mt-1">{selectedConfig.entity_type}</p>
                        </div>
                        <div className="p-4 rounded-lg border bg-muted/30">
                          <p className="text-sm text-muted-foreground">Linked Sources</p>
                          <p className="font-medium mt-1">{selectedConfig.source_count}</p>
                        </div>
                        <div className="p-4 rounded-lg border bg-muted/30">
                          <p className="text-sm text-muted-foreground">Status</p>
                          <div className="mt-1">{getStatusBadge(selectedConfig.status)}</div>
                        </div>
                      </div>

                      {configStats && (
                        <>
                          <Separator />
                          <div className="grid grid-cols-4 gap-4">
                            <div className="text-center p-4 rounded-lg border">
                              <p className="text-2xl font-bold text-primary">{configStats.totalRuns}</p>
                              <p className="text-sm text-muted-foreground">Total Runs</p>
                            </div>
                            <div className="text-center p-4 rounded-lg border">
                              <p className="text-2xl font-bold text-green-600">{configStats.totalMatches}</p>
                              <p className="text-sm text-muted-foreground">Matches Found</p>
                            </div>
                            <div className="text-center p-4 rounded-lg border">
                              <p className="text-2xl font-bold text-blue-600">{configStats.totalNew}</p>
                              <p className="text-sm text-muted-foreground">New Records</p>
                            </div>
                            <div className="text-center p-4 rounded-lg border">
                              <p className="text-2xl font-bold text-yellow-600">{configStats.pendingReview}</p>
                              <p className="text-sm text-muted-foreground">Pending Review</p>
                            </div>
                          </div>
                        </>
                      )}
                    </TabsContent>

                    {/* Sources Tab */}
                    <TabsContent value="sources">
                      {sourceLinks.length > 0 ? (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Source Contract</TableHead>
                              <TableHead>Table</TableHead>
                              <TableHead>Key Column</TableHead>
                              <TableHead>Priority</TableHead>
                              <TableHead>Status</TableHead>
                              <TableHead className="w-16"></TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {sourceLinks.map(link => (
                              <TableRow key={link.id}>
                                <TableCell className="font-medium">
                                  {link.source_contract_name || link.source_contract_id}
                                </TableCell>
                                <TableCell className="font-mono text-sm">
                                  {link.source_table_fqn || '-'}
                                </TableCell>
                                <TableCell>{link.key_column}</TableCell>
                                <TableCell>{link.priority}</TableCell>
                                <TableCell>{getStatusBadge(link.status)}</TableCell>
                                <TableCell>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8 text-destructive"
                                    onClick={() => handleDeleteSourceLink(link.id)}
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      ) : (
                        <div className="text-center py-12">
                          <Link2 className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                          <p className="text-muted-foreground">No source contracts linked yet.</p>
                          <Button 
                            variant="outline" 
                            className="mt-4"
                            onClick={() => setIsLinkDialogOpen(true)}
                          >
                            <Plus className="h-4 w-4 mr-2" />
                            Link Source Contract
                          </Button>
                        </div>
                      )}
                    </TabsContent>

                    {/* Matching Rules Tab */}
                    <TabsContent value="rules" className="space-y-4">
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="font-medium flex items-center gap-2">
                            <Settings2 className="h-4 w-4" />
                            Matching Rules
                          </h4>
                          <Button 
                            variant="outline" 
                            size="sm"
                            onClick={() => setIsRulesEditorOpen(true)}
                          >
                            Edit Rules
                          </Button>
                        </div>
                        {selectedConfig.matching_rules?.length > 0 ? (
                          <div className="space-y-2">
                            {selectedConfig.matching_rules.map((rule, idx) => (
                              <div key={idx} className="p-3 rounded-lg border">
                                <div className="flex justify-between items-center">
                                  <span className="font-medium">{rule.name}</span>
                                  <Badge variant="outline">{rule.type}</Badge>
                                </div>
                                <div className="mt-2 text-sm text-muted-foreground">
                                  Fields: {rule.fields.join(', ')} • 
                                  Weight: {rule.weight} • 
                                  Threshold: {rule.threshold}
                                  {rule.algorithm && ` • Algorithm: ${rule.algorithm}`}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-muted-foreground text-sm">No matching rules configured. Default rules will be used.</p>
                        )}
                      </div>

                      <Separator />

                      <div>
                        <h4 className="font-medium mb-3 flex items-center gap-2">
                          <Merge className="h-4 w-4" />
                          Survivorship Rules
                        </h4>
                        {selectedConfig.survivorship_rules?.length > 0 ? (
                          <div className="space-y-2">
                            {selectedConfig.survivorship_rules.map((rule, idx) => (
                              <div key={idx} className="p-3 rounded-lg border">
                                <div className="flex justify-between items-center">
                                  <span className="font-medium">{rule.field}</span>
                                  <Badge variant="secondary">{rule.strategy}</Badge>
                                </div>
                                {rule.priority && (
                                  <div className="mt-1 text-sm text-muted-foreground">
                                    Priority: {rule.priority.join(' > ')}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-muted-foreground text-sm">No survivorship rules configured. Source values will be preferred.</p>
                        )}
                      </div>
                    </TabsContent>

                    {/* Match Runs Tab */}
                    <TabsContent value="runs">
                      {matchRuns.length > 0 ? (
                        <div className="space-y-3">
                          {matchRuns.map(run => (
                            <div 
                              key={run.id} 
                              className={`p-4 rounded-lg border transition-colors cursor-pointer ${
                                selectedRun?.id === run.id 
                                  ? 'border-primary bg-primary/5' 
                                  : 'hover:border-primary/50'
                              }`}
                              onClick={() => {
                                setSelectedRun(run);
                                fetchCandidates(run.id);
                                setActiveTab('candidates');
                              }}
                            >
                              <div className="flex justify-between items-start">
                                <div>
                                  <p className="font-medium">
                                    Run {run.id.slice(0, 8)}...
                                  </p>
                                  <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
                                    <span className="flex items-center gap-1">
                                      <Clock className="h-3 w-3" />
                                      <RelativeDate date={run.started_at || ''} />
                                    </span>
                                    {run.triggered_by && (
                                      <span className="flex items-center gap-1">
                                        <Users className="h-3 w-3" />
                                        {run.triggered_by}
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {getStatusBadge(run.status)}
                                </div>
                              </div>

                              {run.status === MdmMatchRunStatus.RUNNING && (
                                <div className="mt-3">
                                  <Progress value={50} className="h-2" />
                                </div>
                              )}

                              {run.status === MdmMatchRunStatus.COMPLETED && (
                                <div className="mt-3 flex items-center justify-between">
                                  <div className="flex gap-4 text-sm">
                                    <span className="text-green-600">
                                      {run.matches_found} matches
                                    </span>
                                    <span className="text-blue-600">
                                      {run.new_records} new
                                    </span>
                                    {run.pending_review_count > 0 && (
                                      <span className="text-yellow-600">
                                        {run.pending_review_count} pending review
                                      </span>
                                    )}
                                    {run.approved_count > 0 && (
                                      <span className="text-emerald-600 font-medium">
                                        {run.approved_count} ready to merge
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex gap-2">
                                    {run.approved_count > 0 && (
                                      <Button 
                                        size="sm"
                                        variant="default"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          handleMergeApproved(run.id);
                                        }}
                                      >
                                        <Merge className="h-4 w-4 mr-1" />
                                        Merge ({run.approved_count})
                                      </Button>
                                    )}
                                    {run.pending_review_count > 0 && (
                                      <Button 
                                        size="sm"
                                        variant="outline"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setSelectedRun(run);
                                          setIsReviewDialogOpen(true);
                                        }}
                                      >
                                        <FileCheck className="h-4 w-4 mr-1" />
                                        Create Review
                                      </Button>
                                    )}
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setSelectedRun(run);
                                        fetchCandidates(run.id);
                                        setActiveTab('candidates');
                                      }}
                                    >
                                      <Eye className="h-4 w-4 mr-1" />
                                      View
                                    </Button>
                                  </div>
                                </div>
                              )}

                              {run.status === MdmMatchRunStatus.FAILED && run.error_message && (
                                <div className="mt-3 text-sm text-destructive">
                                  Error: {run.error_message}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-center py-12">
                          <RefreshCw className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                          <p className="text-muted-foreground">No match runs yet.</p>
                          <Button 
                            className="mt-4"
                            onClick={() => handleStartMatching(selectedConfig.id)}
                          >
                            <Play className="h-4 w-4 mr-2" />
                            Start First Matching Run
                          </Button>
                        </div>
                      )}
                    </TabsContent>

                    {/* Candidates Tab */}
                    {selectedRun && (
                      <TabsContent value="candidates">
                        <div className="space-y-4">
                          <div className="flex justify-between items-center">
                            <div>
                              <h4 className="font-medium">
                                Match Candidates for Run {selectedRun.id.slice(0, 8)}...
                              </h4>
                              <p className="text-sm text-muted-foreground">
                                {candidates.filter(c => c.status === MdmMatchCandidateStatus.PENDING).length} pending, 
                                {' '}{candidates.filter(c => c.status === MdmMatchCandidateStatus.APPROVED).length} approved,
                                {' '}{candidates.filter(c => c.status === MdmMatchCandidateStatus.MERGED).length} merged
                              </p>
                            </div>
                            <div className="flex gap-2">
                              {candidates.some(c => c.status === MdmMatchCandidateStatus.APPROVED) && (
                                <Button onClick={() => handleMergeApproved(selectedRun.id)}>
                                  <Merge className="h-4 w-4 mr-2" />
                                  Merge Approved
                                </Button>
                              )}
                            </div>
                          </div>

                          {candidates.length > 0 ? (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>Type</TableHead>
                                  <TableHead>Master ID</TableHead>
                                  <TableHead>Source ID</TableHead>
                                  <TableHead>Confidence</TableHead>
                                  <TableHead>Matched Fields</TableHead>
                                  <TableHead>Status</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {candidates.map(candidate => (
                                  <TableRow 
                                    key={candidate.id}
                                    className="cursor-pointer hover:bg-muted/50"
                                    onClick={() => {
                                      // Navigate to review or show detail modal
                                      if (candidate.review_request_id) {
                                        navigate(`/data-asset-reviews/${candidate.review_request_id}`);
                                      }
                                    }}
                                  >
                                    <TableCell>{getMatchTypeBadge(candidate.match_type)}</TableCell>
                                    <TableCell className="font-mono text-sm">
                                      {candidate.master_record_id || <span className="text-muted-foreground italic">New</span>}
                                    </TableCell>
                                    <TableCell className="font-mono text-sm">
                                      {candidate.source_record_id}
                                    </TableCell>
                                    <TableCell>
                                      <span className={`font-medium ${getConfidenceColor(candidate.confidence_score)}`}>
                                        {(candidate.confidence_score * 100).toFixed(1)}%
                                      </span>
                                    </TableCell>
                                    <TableCell>
                                      {candidate.matched_fields && candidate.matched_fields.length > 0 ? (
                                        <div className="flex flex-wrap gap-1">
                                          {candidate.matched_fields.slice(0, 3).map((field, idx) => (
                                            <Badge key={idx} variant="outline" className="text-xs">
                                              {field}
                                            </Badge>
                                          ))}
                                          {candidate.matched_fields.length > 3 && (
                                            <Badge variant="outline" className="text-xs">
                                              +{candidate.matched_fields.length - 3}
                                            </Badge>
                                          )}
                                        </div>
                                      ) : (
                                        <span className="text-muted-foreground">-</span>
                                      )}
                                    </TableCell>
                                    <TableCell>{getStatusBadge(candidate.status)}</TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          ) : (
                            <div className="text-center py-8 text-muted-foreground">
                              No candidates found for this run.
                            </div>
                          )}
                        </div>
                      </TabsContent>
                    )}
                  </Tabs>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="py-16 text-center">
                  <GitCompare className="h-16 w-16 mx-auto text-muted-foreground mb-6" />
                  <h3 className="text-lg font-medium mb-2">Select an MDM Configuration</h3>
                  <p className="text-muted-foreground mb-6">
                    Choose a configuration from the list to view details and manage matching runs.
                  </p>
                  <Button onClick={() => setIsConfigDialogOpen(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Create New Configuration
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* Dialogs */}
      <MdmConfigDialog
        isOpen={isConfigDialogOpen}
        onClose={() => setIsConfigDialogOpen(false)}
        onSuccess={() => {
          fetchConfigs();
          setIsConfigDialogOpen(false);
        }}
      />

      {selectedConfig && (
        <LinkSourceDialog
          isOpen={isLinkDialogOpen}
          configId={selectedConfig.id}
          masterContractId={selectedConfig.master_contract_id}
          onClose={() => setIsLinkDialogOpen(false)}
          onSuccess={() => {
            fetchSourceLinks(selectedConfig.id);
            fetchConfigs();
            setIsLinkDialogOpen(false);
          }}
        />
      )}

      {selectedRun && (
        <CreateReviewDialog
          isOpen={isReviewDialogOpen}
          runId={selectedRun.id}
          candidateCount={selectedRun.pending_review_count}
          onClose={() => setIsReviewDialogOpen(false)}
          onSuccess={(reviewId) => {
            setIsReviewDialogOpen(false);
            navigate(`/data-asset-reviews/${reviewId}`);
          }}
        />
      )}

      {selectedConfig && (
        <MatchingRulesEditor
          isOpen={isRulesEditorOpen}
          onClose={() => setIsRulesEditorOpen(false)}
          onSuccess={() => {
            fetchConfigs();
            // Refresh selectedConfig with new rules
            if (selectedConfig) {
              get<MdmConfig>(`/api/mdm/configs/${selectedConfig.id}`).then((response) => {
                if (response.data) {
                  setSelectedConfig(response.data);
                }
              });
            }
          }}
          config={selectedConfig}
        />
      )}
    </div>
  );
}
