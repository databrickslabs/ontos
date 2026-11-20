import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { HoverCard, HoverCardTrigger, HoverCardContent } from '@/components/ui/hover-card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ArrowLeft, Play, CheckCircle2, FlaskConical, Trash2, Loader2, AlertCircle, Pencil, KeyRound, Workflow, ExternalLink, History, Database, GitBranch } from 'lucide-react';
import { formatDna } from './authority-resolution';
import { RelativeDate } from '@/components/common/relative-date';
import CreateAuthorityRelationDialog from '@/components/authority-resolution/create-authority-relation-dialog';
import RequestAuthorityActionDialog from '@/components/authority-resolution/request-authority-action-dialog';
import AuthorityRelationReview from '@/components/authority-resolution/authority-relation-review';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import ArConceptLinks from '@/components/authority-resolution/ar-concept-links';
import { MaturityInline } from '@/components/common/maturity-inline';
import VersionNavigator from '@/components/common/version-navigator';
import { DetailHeaderSkeleton, PanelSkeleton, SkeletonLine } from '@/components/common/list-view-skeleton';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AuthorityRelation, ResolveResponse, AuthorityReviewTracking, AuthorityDnaRun, AuthorityDecision } from '@/types/authority-resolution';

/** Human-readable label for a stored 5-field recompute cron. */
function cronLabel(cron?: string | null, i18nFn?: (key: string, opts?: any) => string): string {
  const t = i18nFn || ((k) => k);
  if (!cron || !cron.trim()) return t('details.cronManualOnly');
  const p = cron.trim().split(/\s+/);
  if (p.length !== 5) return t('details.cronCustom', { cron });
  const [min, hr, dom, mon, dow] = p;
  const time = `${String(parseInt(hr, 10) || 0).padStart(2, '0')}:${String(parseInt(min, 10) || 0).padStart(2, '0')}`;
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  if (mon === '*' && hr === '*' && dom === '*' && dow === '*') return t('details.cronHourly', { min: String(parseInt(min, 10) || 0).padStart(2, '0') });
  if (mon === '*' && dom === '*' && dow === '*') return t('details.cronDaily', { time });
  if (mon === '*' && dom === '*' && dow !== '*') return t('details.cronWeekly', { day: days[parseInt(dow, 10)] || dow, time });
  if (mon === '*' && dom === '1') return t('details.cronMonthly', { time });
  return t('details.cronCustom', { cron });
}

function reviewStatusVariant(s?: string): 'default' | 'secondary' | 'outline' {
  switch ((s || 'na').toLowerCase()) {
    case 'completed': return 'default';
    case 'in_review': return 'secondary';
    default: return 'outline';
  }
}

const FEATURE_ID = 'authority-resolution';

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs uppercase text-muted-foreground">{label}</div>
        <div className="text-2xl font-bold mt-1">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </CardContent>
    </Card>
  );
}

/** Divergence colour bands: green (≤0.3), amber (≤0.6), red. */
function dnaScoreColor(v: number): string {
  return v <= 0.3 ? '#16a34a' : v <= 0.6 ? '#d97706' : '#dc2626';
}

function DnaGauge({ label, value }: { label: string; value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div
        className="relative flex items-center justify-center shrink-0"
        style={{
          width: 40, height: 40, borderRadius: '50%',
          background: `conic-gradient(${dnaScoreColor(value)} 0% ${pct}%, hsl(var(--muted)) ${pct}% 100%)`,
        }}
      >
        <div className="absolute inset-[5px] rounded-full bg-background flex items-center justify-center text-[10px] font-semibold">
          {value.toFixed(2)}
        </div>
      </div>
      <div className="text-xs capitalize">{label}</div>
    </div>
  );
}

/** DNA-Coefficient tile with a per-dimension gauge breakdown on hover. */
function DnaTile({ relation, t }: { relation: AuthorityRelation; t: (key: string, opts?: any) => string }) {
  const dims = relation.dna_dimensions || null;
  const value = formatDna(relation.dna_magnitude, relation.dna_direction);
  if (!dims || Object.keys(dims).length === 0) {
    return <Tile label={t('details.tileDnaco')} value={value} hint={t('details.tileDnacoHint')} />;
  }
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <div className="cursor-help">
          <Tile label={t('details.tileDnaco')} value={value} hint={t('details.tileDnacoHintHover')} />
        </div>
      </HoverCardTrigger>
      <HoverCardContent className="w-72" align="start">
        <div className="text-xs font-semibold mb-2">{t('details.dnacoDimensions')}</div>
        <div className="space-y-2">
          {Object.entries(dims).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => (
            <DnaGauge key={k} label={k} value={Number(v)} />
          ))}
        </div>
        <div className="text-[11px] text-muted-foreground mt-2">
          {t('details.dnacoFormula', { value: (relation.dna_magnitude ?? 0).toFixed(2) })}
          <span className="block opacity-80">{t('details.dnacoFormulaDescription')}</span>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

function JsonBlock({ data }: { data: any }) {
  if (data === null || data === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <pre className="text-xs bg-muted rounded p-3 overflow-x-auto">{JSON.stringify(data, null, 2)}</pre>
  );
}

export default function AuthorityRelationDetails() {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { relationId } = useParams<{ relationId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { get, post, delete: del } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWrite = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);

  const [relation, setRelation] = useState<AuthorityRelation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [newVersion, setNewVersion] = useState('');
  const [changeSummary, setChangeSummary] = useState('');
  const [requestOpen, setRequestOpen] = useState(false);
  const [reviewFor, setReviewFor] = useState<string | null>(null);
  const [tracking, setTracking] = useState<AuthorityReviewTracking | null>(null);
  const [dnaRuns, setDnaRuns] = useState<AuthorityDnaRun[]>([]);
  const [decisions, setDecisions] = useState<AuthorityDecision[]>([]);
  const [trackingLoading, setTrackingLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  // `initial` shows the page skeleton; refreshes after a mutation keep the
  // current content on screen instead of flashing back to the skeleton.
  const fetchRelation = useCallback(async (initial = false) => {
    if (!relationId) return;
    if (initial) setLoading(true);
    let res = await get<AuthorityRelation>(`/api/authority/relations/${relationId}`);
    if (res.error) {
      // A just-created relation can 404 briefly: the request session commits after
      // the create response is sent, so a navigation-triggered read may race it.
      // Retry once after a short delay before surfacing the error.
      await new Promise((r) => setTimeout(r, 600));
      res = await get<AuthorityRelation>(`/api/authority/relations/${relationId}`);
    }
    if (res.error) toast({ title: t('common:toast.error'), description: res.error, variant: 'destructive' });
    else setRelation(res.data);
    setLoading(false);
  }, [relationId, get, toast, t]);

  const fetchTracking = useCallback(async () => {
    if (!relationId) return;
    const { data } = await get<AuthorityReviewTracking>(`/api/authority/relations/${relationId}/review-tracking`);
    if (data) setTracking(data);
    setTrackingLoading(false);
  }, [relationId, get]);

  const fetchHistory = useCallback(async () => {
    if (!relationId) return;
    const [runs, decs] = await Promise.all([
      get<AuthorityDnaRun[]>(`/api/authority/relations/${relationId}/dna-runs`),
      get<AuthorityDecision[]>(`/api/authority/relations/${relationId}/decisions`),
    ]);
    if (Array.isArray(runs.data)) setDnaRuns(runs.data);
    if (Array.isArray(decs.data)) setDecisions(decs.data);
    setHistoryLoading(false);
  }, [relationId, get]);

  useEffect(() => { fetchRelation(true); fetchTracking(); fetchHistory(); }, [fetchRelation, fetchTracking, fetchHistory]);

  // Breadcrumb: Home > Authority Resolution > <name>
  useEffect(() => {
    setStaticSegments([{ label: t('title.main'), path: '/authority-resolution' }]);
    setDynamicTitle(relation?.name ?? t('details.defaultTitle'));
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [relation?.name, setStaticSegments, setDynamicTitle, t]);

  const computeDna = async () => {
    setBusy('compute');
    const { data, error } = await post<any>(`/api/authority/relations/${relationId}/compute-dnaco`, {});
    setBusy(null);
    if (error) toast({ title: t('details.dnaComputeFailed'), description: error, variant: 'destructive' });
    else {
      toast({ title: t('details.dnaComputed'), description: t('details.dnaComputedMsg', { magnitude: data.magnitude, divergent: data.divergent_count, total: data.sampled_count }) });
      fetchRelation();
      fetchHistory();
    }
  };

  const activate = async () => {
    setBusy('activate');
    const { error } = await post<any>(`/api/authority/relations/${relationId}/status`, { status: 'active' });
    setBusy(null);
    if (error) toast({ title: t('details.activateFailed'), description: error, variant: 'destructive' });
    else { toast({ title: t('details.activated') }); fetchRelation(); }
  };

  const affirm = async (affirmationId: string) => {
    setBusy(affirmationId);
    const { error } = await post<any>(`/api/authority/affirmations/${affirmationId}/affirm`, {});
    setBusy(null);
    if (error) toast({ title: t('details.affirmFailed'), description: error, variant: 'destructive' });
    else fetchRelation();
  };

  const remove = async () => {
    if (!confirm(t('details.confirmDelete'))) return;
    const { error } = await del(`/api/authority/relations/${relationId}`);
    if (error) toast({ title: t('common:toast.error'), description: error, variant: 'destructive' });
    else { toast({ title: t('common:toast.deleted') }); navigate('/authority-resolution'); }
  };

  // Suggest the next version by bumping the minor of a semantic version.
  const suggestNextVersion = (v?: string): string => {
    const parts = (v || '1.0.0').split('.').map((p) => parseInt(p, 10));
    if (parts.length < 2 || parts.some((n) => Number.isNaN(n))) return `${v || '1.0.0'}-2`;
    parts[1] += 1;
    for (let i = 2; i < parts.length; i++) parts[i] = 0;
    return parts.join('.');
  };

  const openVersionDialog = () => {
    setNewVersion(suggestNextVersion(relation?.version));
    setChangeSummary('');
    setVersionOpen(true);
  };

  const createVersion = async () => {
    if (!newVersion.trim()) return;
    setBusy('version');
    const { data, error } = await post<AuthorityRelation>(
      `/api/authority/relations/${relationId}/versions`,
      { new_version: newVersion.trim(), change_summary: changeSummary.trim() || undefined },
    );
    setBusy(null);
    if (error) { toast({ title: t('common:toast.error'), description: error, variant: 'destructive' }); return; }
    setVersionOpen(false);
    toast({ title: t('details.versionCreated'), description: t('details.versionCreatedMsg', { version: newVersion.trim() }) });
    if (data?.id) navigate(`/authority-resolution/${data.id}`);
  };

  if (loading || permissionsLoading) {
    return (
      <div className="py-6 space-y-6">
        <DetailHeaderSkeleton actionButtons={6} leftControls={2} />
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <SkeletonLine height="h-9" width="w-9" className="rounded" />
            <SkeletonLine height="h-8" width="w-80" />
            <SkeletonLine height="h-5" width="w-20" />
          </div>
          <SkeletonLine height="h-4" width="w-2/3" />
        </div>
        <PanelSkeleton rows={4} rowHeight="h-12" />
        <PanelSkeleton rows={3} rowHeight="h-10" />
        <PanelSkeleton rows={2} rowHeight="h-10" />
      </div>
    );
  }
  if (!relation) return (
    <div className="py-6">
      <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{t('details.notFound')}</AlertDescription></Alert>
    </div>
  );

  const participants = relation.affirmations || [];
  const approvers = participants.filter((a) => a.is_approver !== false);
  const reviewers = participants.filter((a) => a.is_reviewer === true);
  const hasReviewers = reviewers.length > 0;

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => navigate('/authority-resolution')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('details.backButton')}
        </Button>
        {canWrite && (
          <div className="flex gap-2 flex-wrap justify-end">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4 mr-1" /> {t('common:actions.edit')}
            </Button>
            <Button variant="outline" size="sm" onClick={openVersionDialog}>
              <GitBranch className="h-4 w-4 mr-1" /> {t('details.buttonNewVersion')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setRequestOpen(true)}>
              <KeyRound className="h-4 w-4 mr-1" /> {t('details.buttonRequest')}
            </Button>
            <Button variant="outline" size="sm" onClick={computeDna} disabled={busy === 'compute'}>
              {busy === 'compute' ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
              {t('details.buttonComputeDnaco')}
            </Button>
            {relation.status !== 'active' && (
              <Button variant="outline" size="sm" onClick={activate} disabled={busy === 'activate'}>
                <CheckCircle2 className="h-4 w-4 mr-1" /> {t('details.buttonActivate')}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setTestOpen(true)}>
              <FlaskConical className="h-4 w-4 mr-1" /> {t('details.buttonTest')}
            </Button>
            <CommentSidebar
              entityType="authority_relation"
              entityId={relationId!}
              isOpen={commentsOpen}
              onToggle={() => setCommentsOpen(!commentsOpen)}
              className="h-8"
            />
            <Button variant="destructive" size="sm" onClick={remove}>
              <Trash2 className="mr-2 h-4 w-4" /> {t('common:actions.delete')}
            </Button>
          </div>
        )}
      </div>

      <div>
        <h1 className="text-2xl font-bold">{relation.name}</h1>
        <div className="flex items-center gap-3 mt-2">
          <Badge>{t(`status.${relation.status}`, { defaultValue: relation.status })}</Badge>
          <MaturityInline entityType="AuthorityRelation" entityId={relationId!} compact />
          {(relation.family_slug || relation.slug) && (
            <span className="text-sm text-muted-foreground" title={t('details.familySlugHint')}>
              {relation.family_slug || relation.slug}
            </span>
          )}
          <span className="text-sm text-muted-foreground">v{relation.version}</span>
          <VersionNavigator
            entityKind="authority_relation"
            currentEntityId={relationId!}
            currentVersion={relation.version}
            onVersionChange={(id) => navigate(`/authority-resolution/${id}`)}
          />
        </div>
        {relation.description && <p className="text-muted-foreground mt-2 max-w-2xl">{relation.description}</p>}
        {(relation.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {(relation.tags || []).map((tag, i) => (
              <Badge key={i} variant="secondary" className="text-xs">
                {tag.fully_qualified_name}{tag.assigned_value ? `: ${tag.assigned_value}` : ''}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <DnaTile relation={relation} t={t} />
        <Tile label={t('details.tileUsage')} value={relation.usage_count ?? 0} />
        <Tile label={t('details.tileApproved')} value={relation.approved_count ?? 0} />
        <Tile label={t('details.tileDenied')} value={relation.denied_count ?? 0} />
      </div>

      {relation.status !== 'active' && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {t('details.activationRequires', {
              threshold: relation.dna_max_threshold,
              affirmed: relation.fully_affirmed ? '' : ` ${t('details.notYetFullyAffirmed')}`
            })}
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">{t('details.cardApprovers')}</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {approvers.length === 0 && <div className="text-sm text-muted-foreground">{t('details.noApprovers')}</div>}
          {approvers.map((a) => (
            <div key={a.id} className="flex items-center justify-between border-b py-2 last:border-0">
              <div className="text-sm">
                <Badge variant="outline" className="mr-2">{a.role}</Badge>
                {a.principal} <span className="text-muted-foreground">({a.principal_type})</span>
                {a.is_reviewer && <Badge variant="secondary" className="ml-2">{t('details.alsoReviewer')}</Badge>}
              </div>
              <div className="flex items-center gap-2">
                {a.affirmed ? (
                  <Badge><CheckCircle2 className="h-3 w-3 mr-1" /> {t('details.affirmed')}{a.affirmed_by ? ` · ${a.affirmed_by}` : ''}</Badge>
                ) : canWrite ? (
                  <Button size="sm" variant="outline" onClick={() => affirm(a.id)} disabled={busy === a.id}>{t('details.buttonAffirm')}</Button>
                ) : (
                  <Badge variant="secondary">{t('details.pending')}</Badge>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {hasReviewers && (
        <Card>
          <CardHeader><CardTitle className="text-base">{t('details.cardReviewers')}</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {reviewers.map((a) => (
              <div key={a.id} className="flex items-center justify-between border-b py-2 last:border-0">
                <div className="text-sm">
                  <Badge variant="outline" className="mr-2">{a.role}</Badge>
                  {a.principal} <span className="text-muted-foreground">({a.principal_type})</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={reviewStatusVariant(a.review_status)}>
                    {a.review_status === 'completed' && <CheckCircle2 className="h-3 w-3 mr-1" />}
                    {t(`reviewStatus.${a.review_status || 'na'}`, { defaultValue: a.review_status || 'na' })}
                  </Badge>
                  {canWrite && (
                    <Button size="sm" variant="outline" onClick={() => setReviewFor(a.principal)}>
                      {a.review_status === 'completed' ? t('common:actions.view') : t('details.buttonReview')}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {trackingLoading && !tracking && <PanelSkeleton rows={2} rowHeight="h-8" withDescription={false} />}
      {tracking && (tracking.workflows.length > 0 || tracking.reviews.some((r) => r.review_request_id)) && (
        <Card>
          <CardHeader><CardTitle className="text-base">{t('details.cardReviewProcess')}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {tracking.workflows.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs uppercase text-muted-foreground">{t('details.workflowsSection')}</div>
                {tracking.workflows.map((w) => (
                  <div key={w.execution_id} className="flex items-center justify-between border-b py-2 last:border-0">
                    <div className="text-sm flex items-center gap-2">
                      <Workflow className="h-4 w-4 text-muted-foreground" />
                      {w.workflow_name || w.workflow_id}
                      {w.current_step && <span className="text-muted-foreground">· {w.current_step}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{t(`workflowStatus.${w.status}`, { defaultValue: w.status })}</Badge>
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate(`/workflows/${w.workflow_id}`)}>
                        {t('details.linkWorkflow')} <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="space-y-2">
              <div className="text-xs uppercase text-muted-foreground">{t('details.assetReviewsSection')}</div>
              {tracking.reviews.length === 0 && <div className="text-sm text-muted-foreground">{t('details.noReviewersAssigned')}</div>}
              {tracking.reviews.map((r) => (
                <div key={r.participant_id} className="flex items-center justify-between border-b py-2 last:border-0">
                  <div className="text-sm">
                    <Badge variant="outline" className="mr-2">{r.role}</Badge>
                    {r.principal}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={reviewStatusVariant(r.review_status)}>{t(`reviewStatus.${r.review_status || 'na'}`, { defaultValue: r.review_status || 'na' })}</Badge>
                    {r.request_status && <Badge variant="secondary">{t('details.reviewStatus', { status: r.request_status })}</Badge>}
                    {r.review_request_id ? (
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate(`/data-asset-reviews/${r.review_request_id}`)}>
                        {t('details.linkOpenReview')} <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">{t('details.notStarted')}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {historyLoading && dnaRuns.length === 0 && decisions.length === 0 && (
        <PanelSkeleton rows={3} rowHeight="h-8" withDescription={false} />
      )}
      {(dnaRuns.length > 0 || decisions.length > 0) && (
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><History className="h-4 w-4" /> {t('details.cardHistory')}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {dnaRuns.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs uppercase text-muted-foreground">{t('details.dnaRunsSection')}</div>
                {dnaRuns.slice(0, 8).map((r) => (
                  <div key={r.id} className="flex items-center justify-between border-b py-2 last:border-0 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant={r.status === 'succeeded' ? 'default' : r.status === 'failed' ? 'destructive' : 'secondary'}>{t(`dnaRunStatus.${r.status}`, { defaultValue: r.status })}</Badge>
                      {r.status === 'succeeded' && (
                        <span>{formatDna(r.magnitude, r.direction)} · {t('details.dnaRunResult', { divergent: r.divergent_count ?? 0, total: r.sampled_count ?? 0 })}</span>
                      )}
                      {r.error_message && <span className="text-muted-foreground">{r.error_message}</span>}
                    </div>
                    {r.started_at && <span className="text-muted-foreground"><RelativeDate date={r.started_at} /></span>}
                  </div>
                ))}
              </div>
            )}
            {decisions.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs uppercase text-muted-foreground">{t('details.decisionsSection')}</div>
                {decisions.slice(0, 10).map((d) => (
                  <div key={d.id} className="flex items-center justify-between border-b py-2 last:border-0 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{t(`decisionSource.${d.source}`, { defaultValue: d.source })}</Badge>
                      {d.verdict && (
                        <Badge variant={d.verdict === 'approved' ? 'default' : d.verdict === 'denied' ? 'destructive' : 'secondary'}>{t(`verdict.${d.verdict}`, { defaultValue: d.verdict })}</Badge>
                      )}
                      <span className="text-muted-foreground">
                        {d.actor_identity || '—'}{d.action ? ` · ${d.action}` : ''}{d.object_id ? ` · ${d.object_id}` : ''}
                        {d.reason ? ` — ${d.reason}` : ''}
                      </span>
                    </div>
                    {d.created_at && <span className="text-muted-foreground whitespace-nowrap"><RelativeDate date={d.created_at} /></span>}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">{t('details.cardRelation')}</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div><span className="text-muted-foreground">{t('details.labelActorRole')}:</span> {relation.actor_role || '—'}</div>
            <div><span className="text-muted-foreground">{t('details.labelActorIdentity')}:</span> {relation.actor_identity || '—'}</div>
            <div><span className="text-muted-foreground">{t('details.labelAction')}:</span> {relation.action || '—'}</div>
            <div><span className="text-muted-foreground">{t('details.labelObject')}:</span> {relation.object_type || '—'} {relation.object_id ? `· ${relation.object_id}` : ''}</div>
            <div className="pt-2 text-muted-foreground">{t('details.labelDomainContext')}</div>
            <JsonBlock data={relation.domain_context} />
            <div className="pt-2 text-muted-foreground">{t('details.labelJustificationChain')}</div>
            <JsonBlock data={relation.justification_chain} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">{t('details.cardRuntimeEvidence')}</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="text-muted-foreground">{t('details.labelDecisionCriteria')}</div>
            {(relation.criteria || []).length > 0 ? (
              <div className="space-y-2">
                {(relation.criteria || []).map((c) => (
                  <div key={c.id} className="rounded border p-2 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{c.name || t('details.criterion')}</span>
                      {!c.enabled && <Badge variant="outline" className="text-xs">{t('common:labels.disabled')}</Badge>}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {t(`direction.${c.direction}`, { defaultValue: c.direction })} · w{c.weight}
                      </span>
                    </div>
                    <div className="font-mono text-xs break-all">{c.rule}</div>
                    {c.failure_message && (
                      <div className="text-xs text-muted-foreground">↳ {c.failure_message}</div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-muted-foreground text-xs">{t('details.noCriteria')}</div>
            )}
            <div className="pt-2 text-muted-foreground">{t('details.labelEvidenceSources')}</div>
            {(relation.evidence_sources || []).length > 0 ? (
              <div className="space-y-1">
                {(relation.evidence_sources || []).map((s, i) => {
                  // delta_table / asset sources resolve to a UC table FQN — link to
                  // Catalog Commander to preview it. data_product refs aren't a table FQN.
                  const linkable = (s.type === 'delta_table' || s.type === 'asset')
                    && (s.ref || '').split('.').length >= 3;
                  return (
                    <div key={i} className="text-xs">
                      <Badge variant="outline" className="mr-1">{t(`sourceType.${s.type}`, { defaultValue: s.type })}</Badge>
                      {linkable ? (
                        <a
                          href={`/catalog-commander?table=${encodeURIComponent(s.ref)}`}
                          className="font-mono text-primary hover:underline inline-flex items-center gap-1"
                          target="_blank"
                          rel="noopener noreferrer"
                          title={t('details.linkCatalogCommander', { ref: s.ref })}
                        >
                          <Database className="h-3 w-3" />{s.ref}
                        </a>
                      ) : (
                        <span className="font-mono">{s.ref}</span>
                      )}
                      {s.label ? ` — ${s.label}` : ''}
                    </div>
                  );
                })}
              </div>
            ) : (
              <JsonBlock data={relation.evidence_binding} />
            )}
            <div className="pt-2 text-muted-foreground">{t('details.labelGovernsConceptsHint')}</div>
            <ArConceptLinks familyId={relation.version_family_id || relation.id} />
            <div className="pt-2 text-muted-foreground">{t('details.labelPrerequisites')}</div>
            {(relation.prerequisites || []).length > 0 ? (
              <div className="space-y-1">
                {(relation.prerequisites || []).map((p) => (
                  <div key={p.prerequisite_family_slug} className="text-xs flex items-center gap-2">
                    <Badge variant={p.required ? 'default' : 'outline'}>
                      {p.required ? t('details.required') : t('details.optional')}
                    </Badge>
                    <span className="font-mono">{p.prerequisite_family_slug}</span>
                    <span className="text-muted-foreground">
                      {p.name ? `· ${p.name}` : ''} {p.status ? `(${t(`status.${p.status}`, { defaultValue: p.status })})` : ''}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-muted-foreground text-xs">
                {t('details.noPrerequisites')}
              </div>
            )}
            <div className="pt-2 text-muted-foreground">
              {t('details.labelResourceRefs')}
              {(relation.resource_refs || []).some((r) => r.ref_type === 'mcp_tool') && (
                <Badge variant={relation.resolver_auth === 'app_sp' ? 'destructive' : 'outline'} className="ml-2">
                  {t('details.mcpAuth', { auth: t(`resolverAuth.${relation.resolver_auth}`, { defaultValue: relation.resolver_auth }) })}
                </Badge>
              )}
            </div>
            {(relation.resource_refs || []).length > 0 ? (
              <div className="space-y-1">
                {(relation.resource_refs || []).map((r) => (
                  <div key={r.id || r.field_path} className="text-xs flex items-center gap-2 flex-wrap">
                    <Badge variant="outline">{t(`refType.${r.ref_type}`, { defaultValue: r.ref_type })}</Badge>
                    <span className="font-mono">{r.field_path}</span>
                    <span className="text-muted-foreground">
                      {r.ref_type === 'literal' && r.literal_value ? `→ ${r.literal_value}` : ''}
                      {r.ref_type === 'ontos_entity' && r.entity_type ? `→ ${r.entity_type}:` : ''}
                      {r.ref_type === 'ontos_entity' && r.entity_id ? ` ${r.cached_label || r.entity_id}` : ''}
                      {r.ref_type === 'mcp_tool' && r.mcp_service_name ? `→ ${r.mcp_service_name} / ${r.mcp_tool_name}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-muted-foreground text-xs">
                {t('details.noResourceRefs')}
              </div>
            )}
            <div className="pt-2"><span className="text-muted-foreground">{t('details.labelRecomputeSchedule')}:</span> {cronLabel(relation.schedule_cron, t)}</div>
            <div className="pt-2 text-muted-foreground">{t('common:labels.domain')}</div>
            <div className="flex flex-wrap gap-1">
              {(relation.domains || []).map((d) => (
                <Badge key={d.domain_id} variant={d.is_primary ? 'default' : 'outline'}>{d.domain_name}</Badge>
              ))}
              {(relation.domains || []).length === 0 && <span className="text-muted-foreground">—</span>}
            </div>
            <div className="pt-2"><span className="text-muted-foreground">{t('editor.fields.ownerTeam')}:</span> {relation.owner_team_name || '—'}</div>
            <div><span className="text-muted-foreground">{t('editor.fields.project')}:</span> {relation.project_name || '—'}</div>
          </CardContent>
        </Card>
      </div>

      <OwnershipPanel
        objectType="authority_relation"
        objectId={relationId!}
        canAssign={canWrite}
        ownerTeamId={relation.owner_team_id || undefined}
      />

      <EntityMetadataPanel entityId={relationId!} entityType="authority_relation" />

      <TestResolveDialog
        open={testOpen}
        onOpenChange={setTestOpen}
        relationId={relationId!}
      />

      <CreateAuthorityRelationDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        relation={relation}
        onCreated={(updated) => {
          setEditOpen(false);
          toast({ title: 'Authority Relation updated', description: updated.name });
          fetchRelation();
        }}
      />

      <RequestAuthorityActionDialog
        isOpen={requestOpen}
        onOpenChange={setRequestOpen}
        relationId={relationId!}
        relationName={relation.name}
        relationStatus={relation.status}
        onSuccess={() => { fetchRelation(); fetchTracking(); }}
      />

      <Dialog open={!!reviewFor} onOpenChange={(o) => !o && setReviewFor(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{t('details.dialogTitleReview')}</DialogTitle></DialogHeader>
          {reviewFor && (
            <AuthorityRelationReview
              relationId={relationId!}
              reviewer={reviewFor}
              onCompleted={() => { fetchRelation(); fetchTracking(); }}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={versionOpen} onOpenChange={setVersionOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('details.dialogTitleVersion')}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {t('details.versionDialogDescription')}
            </p>
            <div className="space-y-1">
              <Label htmlFor="ar-new-version">{t('details.labelNewVersion')}</Label>
              <Input
                id="ar-new-version"
                value={newVersion}
                onChange={(e) => setNewVersion(e.target.value)}
                placeholder="2.0.0"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ar-change-summary">{t('details.labelChangeSummary')}</Label>
              <Input
                id="ar-change-summary"
                value={changeSummary}
                onChange={(e) => setChangeSummary(e.target.value)}
                placeholder={t('details.placeholderChangeSummary')}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setVersionOpen(false)}>{t('common:actions.cancel')}</Button>
              <Button size="sm" onClick={createVersion} disabled={busy === 'version' || !newVersion.trim()}>
                {busy === 'version' ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <GitBranch className="h-4 w-4 mr-1" />}
                {t('details.buttonCreateVersion')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TestResolveDialog({ open, onOpenChange, relationId }: { open: boolean; onOpenChange: (o: boolean) => void; relationId: string }) {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { post } = useApi();
  const [actorIdentity, setActorIdentity] = useState('');
  const [action, setAction] = useState('approve');
  const [value, setValue] = useState('');
  const [cosign, setCosign] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const [result, setResult] = useState<ResolveResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    const body: any = { actor_identity: actorIdentity || undefined, action, cosign_present: cosign, escalated };
    if (value.trim()) body.value = parseFloat(value);
    const { data, error } = await post<ResolveResponse>(`/api/authority/relations/${relationId}/test`, body);
    setBusy(false);
    if (error) setResult({ verdict: 'error' as any, reason: error });
    else setResult(data);
  };

  const verdictColor = result?.verdict === 'approved' ? 'default'
    : result?.verdict === 'denied' ? 'destructive' : 'secondary';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('details.dialogTitleTest')}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {t('details.testDialogDescription')}
          </p>
          <div className="space-y-1">
            <Label>{t('details.labelSigner')}</Label>
            <Input value={actorIdentity} onChange={(e) => setActorIdentity(e.target.value)} placeholder="rsm-east@example.com" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('details.labelAction')}</Label>
              <Input value={action} onChange={(e) => setAction(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t('details.labelValue')}</Label>
              <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="0.22" />
            </div>
          </div>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cosign} onChange={(e) => setCosign(e.target.checked)} /> {t('details.testCosignLabel')}</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={escalated} onChange={(e) => setEscalated(e.target.checked)} /> {t('details.testEscalatedLabel')}</label>
          </div>
          {result && (
            <Alert>
              <AlertDescription>
                <Badge variant={verdictColor as any} className="mr-2">{t(`verdict.${result.verdict}`, { defaultValue: result.verdict })}</Badge>
                {result.reason}
                {(result.prerequisite_chain || []).length > 0 && (
                  <div className="pt-2 space-y-1">
                    <div className="text-xs text-muted-foreground">{t('details.testPrerequisiteChain')}</div>
                    {(result.prerequisite_chain || []).map((entry, i) => (
                      <div key={i} className="text-xs flex items-center gap-2">
                        <Badge
                          variant={entry.verdict === 'approved' ? 'default' : 'destructive'}
                          className="text-xs"
                        >
                          {t(`verdict.${entry.verdict}`, { defaultValue: entry.verdict })}
                        </Badge>
                        <span className="font-mono">{entry.slug}</span>
                        {entry.version ? <span className="text-muted-foreground">v{entry.version}</span> : null}
                        {!entry.required && <Badge variant="outline" className="text-xs">{t('details.optional')}</Badge>}
                        {entry.reason && <span className="text-muted-foreground">— {entry.reason}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {(result.resolved_refs || []).length > 0 && (
                  <div className="pt-2 space-y-1">
                    <div className="text-xs text-muted-foreground">{t('details.testResolvedRefs')}</div>
                    {(result.resolved_refs || []).map((entry, i) => (
                      <div key={i} className="text-xs flex items-center gap-2 flex-wrap">
                        <Badge variant="outline" className="text-xs">{t(`sourceType.${entry.source}`, { defaultValue: entry.source })}</Badge>
                        <span className="font-mono">{entry.field_path}</span>
                        {entry.value != null && <span>→ {entry.value}</span>}
                        {entry.iri && <span className="text-muted-foreground">({entry.iri})</span>}
                        {entry.error && (
                          <span className="text-destructive">
                            — {entry.error_kind ? `${entry.error_kind}: ` : ''}{entry.error}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common:actions.close')}</Button>
          <Button onClick={run} disabled={busy}>{busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{t('details.buttonTestResolve')}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
