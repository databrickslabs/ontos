import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ArrowLeft, Play, CheckCircle2, FlaskConical, Trash2, Loader2, AlertCircle, Pencil, KeyRound, Workflow, ExternalLink, History } from 'lucide-react';
import { formatDna } from './authority-resolution';
import { RelativeDate } from '@/components/common/relative-date';
import CreateAuthorityRelationDialog from '@/components/authority-resolution/create-authority-relation-dialog';
import RequestAuthorityActionDialog from '@/components/authority-resolution/request-authority-action-dialog';
import AuthorityRelationReview from '@/components/authority-resolution/authority-relation-review';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import type { AuthorityRelation, ResolveResponse, AuthorityReviewTracking, AuthorityDnaRun, AuthorityDecision } from '@/types/authority-resolution';

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

function JsonBlock({ data }: { data: any }) {
  if (data === null || data === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <pre className="text-xs bg-muted rounded p-3 overflow-x-auto">{JSON.stringify(data, null, 2)}</pre>
  );
}

export default function AuthorityRelationDetails() {
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
  const [requestOpen, setRequestOpen] = useState(false);
  const [reviewFor, setReviewFor] = useState<string | null>(null);
  const [tracking, setTracking] = useState<AuthorityReviewTracking | null>(null);
  const [dnaRuns, setDnaRuns] = useState<AuthorityDnaRun[]>([]);
  const [decisions, setDecisions] = useState<AuthorityDecision[]>([]);
  const [commentsOpen, setCommentsOpen] = useState(false);

  const fetchRelation = useCallback(async () => {
    if (!relationId) return;
    setLoading(true);
    let res = await get<AuthorityRelation>(`/api/authority/relations/${relationId}`);
    if (res.error) {
      // A just-created relation can 404 briefly: the request session commits after
      // the create response is sent, so a navigation-triggered read may race it.
      // Retry once after a short delay before surfacing the error.
      await new Promise((r) => setTimeout(r, 600));
      res = await get<AuthorityRelation>(`/api/authority/relations/${relationId}`);
    }
    if (res.error) toast({ title: 'Failed to load', description: res.error, variant: 'destructive' });
    else setRelation(res.data);
    setLoading(false);
  }, [relationId, get, toast]);

  const fetchTracking = useCallback(async () => {
    if (!relationId) return;
    const { data } = await get<AuthorityReviewTracking>(`/api/authority/relations/${relationId}/review-tracking`);
    if (data) setTracking(data);
  }, [relationId, get]);

  const fetchHistory = useCallback(async () => {
    if (!relationId) return;
    const [runs, decs] = await Promise.all([
      get<AuthorityDnaRun[]>(`/api/authority/relations/${relationId}/dna-runs`),
      get<AuthorityDecision[]>(`/api/authority/relations/${relationId}/decisions`),
    ]);
    if (Array.isArray(runs.data)) setDnaRuns(runs.data);
    if (Array.isArray(decs.data)) setDecisions(decs.data);
  }, [relationId, get]);

  useEffect(() => { fetchRelation(); fetchTracking(); fetchHistory(); }, [fetchRelation, fetchTracking, fetchHistory]);

  const computeDna = async () => {
    setBusy('compute');
    const { data, error } = await post<any>(`/api/authority/relations/${relationId}/compute-dnaco`, {});
    setBusy(null);
    if (error) toast({ title: 'DNAco computation failed', description: error, variant: 'destructive' });
    else {
      toast({ title: 'DNAco computed', description: `magnitude ${data.magnitude} · ${data.divergent_count}/${data.sampled_count} divergent` });
      fetchRelation();
      fetchHistory();
    }
  };

  const activate = async () => {
    setBusy('activate');
    const { error } = await post<any>(`/api/authority/relations/${relationId}/status`, { status: 'active' });
    setBusy(null);
    if (error) toast({ title: 'Cannot activate', description: error, variant: 'destructive' });
    else { toast({ title: 'Authority Relation activated' }); fetchRelation(); }
  };

  const affirm = async (affirmationId: string) => {
    setBusy(affirmationId);
    const { error } = await post<any>(`/api/authority/affirmations/${affirmationId}/affirm`, {});
    setBusy(null);
    if (error) toast({ title: 'Affirm failed', description: error, variant: 'destructive' });
    else fetchRelation();
  };

  const remove = async () => {
    if (!confirm('Delete this Authority Relation?')) return;
    const { error } = await del(`/api/authority/relations/${relationId}`);
    if (error) toast({ title: 'Delete failed', description: error, variant: 'destructive' });
    else { toast({ title: 'Deleted' }); navigate('/authority-resolution'); }
  };

  if (loading) return <div className="container mx-auto px-4 py-8 text-muted-foreground">Loading…</div>;
  if (!relation) return (
    <div className="container mx-auto px-4 py-8">
      <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>Authority Relation not found.</AlertDescription></Alert>
    </div>
  );

  const participants = relation.affirmations || [];
  const approvers = participants.filter((a) => a.is_approver !== false);
  const reviewers = participants.filter((a) => a.is_reviewer === true);
  const hasReviewers = reviewers.length > 0;

  return (
    <div className="container mx-auto px-4 py-8 space-y-6">
      <Button variant="ghost" size="sm" onClick={() => navigate('/authority-resolution')}>
        <ArrowLeft className="h-4 w-4 mr-1" /> Back
      </Button>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">{relation.name}</h1>
          <div className="flex items-center gap-2 mt-2">
            <Badge>{relation.status}</Badge>
            <Badge variant="outline">{relation.maturity_level}</Badge>
            {relation.slug && <span className="text-sm text-muted-foreground">{relation.slug}</span>}
            <span className="text-sm text-muted-foreground">v{relation.version}</span>
          </div>
          {relation.description && <p className="text-muted-foreground mt-2 max-w-2xl">{relation.description}</p>}
          {(relation.tags || []).length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {(relation.tags || []).map((t, i) => (
                <Badge key={i} variant="secondary" className="text-xs">
                  {t.fully_qualified_name}{t.assigned_value ? `: ${t.assigned_value}` : ''}
                </Badge>
              ))}
            </div>
          )}
        </div>
        {canWrite && (
          <div className="flex gap-2 flex-wrap justify-end">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4 mr-1" /> Edit
            </Button>
            <Button variant="outline" size="sm" onClick={() => setRequestOpen(true)}>
              <KeyRound className="h-4 w-4 mr-1" /> Request...
            </Button>
            <Button variant="outline" size="sm" onClick={computeDna} disabled={busy === 'compute'}>
              {busy === 'compute' ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
              Compute DNAco
            </Button>
            {relation.status !== 'active' && (
              <Button variant="outline" size="sm" onClick={activate} disabled={busy === 'activate'}>
                <CheckCircle2 className="h-4 w-4 mr-1" /> Activate
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setTestOpen(true)}>
              <FlaskConical className="h-4 w-4 mr-1" /> Test
            </Button>
            <CommentSidebar
              entityType="authority_relation"
              entityId={relationId!}
              isOpen={commentsOpen}
              onToggle={() => setCommentsOpen(!commentsOpen)}
              className="h-8"
            />
            <Button variant="ghost" size="sm" onClick={remove}><Trash2 className="h-4 w-4" /></Button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile label="DNA-Coefficient" value={formatDna(relation.dna_magnitude, relation.dna_direction)} hint="0.0 is best" />
        <Tile label="Usage" value={relation.usage_count ?? 0} />
        <Tile label="Approved" value={relation.approved_count ?? 0} />
        <Tile label="Denied" value={relation.denied_count ?? 0} />
      </div>

      {relation.status !== 'active' && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Activation requires the DNA-Coefficient to be measured and within its ceiling
            ({relation.dna_max_threshold}), and every required affirmation completed
            {relation.fully_affirmed ? '' : ' (not yet fully affirmed)'}.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Approvers (N-functional gate)</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {approvers.length === 0 && <div className="text-sm text-muted-foreground">No approvers defined.</div>}
          {approvers.map((a) => (
            <div key={a.id} className="flex items-center justify-between border-b py-2 last:border-0">
              <div className="text-sm">
                <Badge variant="outline" className="mr-2">{a.role}</Badge>
                {a.principal} <span className="text-muted-foreground">({a.principal_type})</span>
                {a.is_reviewer && <Badge variant="secondary" className="ml-2">also reviewer</Badge>}
              </div>
              <div className="flex items-center gap-2">
                {a.affirmed ? (
                  <Badge><CheckCircle2 className="h-3 w-3 mr-1" /> affirmed{a.affirmed_by ? ` · ${a.affirmed_by}` : ''}</Badge>
                ) : canWrite ? (
                  <Button size="sm" variant="outline" onClick={() => affirm(a.id)} disabled={busy === a.id}>Affirm</Button>
                ) : (
                  <Badge variant="secondary">pending</Badge>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {hasReviewers && (
        <Card>
          <CardHeader><CardTitle className="text-base">Reviewers (interviewed to confirm the relation reflects reality)</CardTitle></CardHeader>
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
                    {a.review_status || 'na'}
                  </Badge>
                  {canWrite && (
                    <Button size="sm" variant="outline" onClick={() => setReviewFor(a.principal)}>
                      {a.review_status === 'completed' ? 'View' : 'Review'}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {tracking && (tracking.workflows.length > 0 || tracking.reviews.some((r) => r.review_request_id)) && (
        <Card>
          <CardHeader><CardTitle className="text-base">Review process</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {tracking.workflows.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs uppercase text-muted-foreground">Workflows</div>
                {tracking.workflows.map((w) => (
                  <div key={w.execution_id} className="flex items-center justify-between border-b py-2 last:border-0">
                    <div className="text-sm flex items-center gap-2">
                      <Workflow className="h-4 w-4 text-muted-foreground" />
                      {w.workflow_name || w.workflow_id}
                      {w.current_step && <span className="text-muted-foreground">· {w.current_step}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{w.status}</Badge>
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate(`/workflows/${w.workflow_id}`)}>
                        Workflow <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="space-y-2">
              <div className="text-xs uppercase text-muted-foreground">Asset Reviews</div>
              {tracking.reviews.length === 0 && <div className="text-sm text-muted-foreground">No reviewers assigned.</div>}
              {tracking.reviews.map((r) => (
                <div key={r.participant_id} className="flex items-center justify-between border-b py-2 last:border-0">
                  <div className="text-sm">
                    <Badge variant="outline" className="mr-2">{r.role}</Badge>
                    {r.principal}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={reviewStatusVariant(r.review_status)}>{r.review_status || 'na'}</Badge>
                    {r.request_status && <Badge variant="secondary">review: {r.request_status}</Badge>}
                    {r.review_request_id ? (
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate(`/data-asset-reviews/${r.review_request_id}`)}>
                        Open review <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">not started</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {(dnaRuns.length > 0 || decisions.length > 0) && (
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><History className="h-4 w-4" /> History</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {dnaRuns.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs uppercase text-muted-foreground">DNA-Coefficient runs</div>
                {dnaRuns.slice(0, 8).map((r) => (
                  <div key={r.id} className="flex items-center justify-between border-b py-2 last:border-0 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant={r.status === 'succeeded' ? 'default' : r.status === 'failed' ? 'destructive' : 'secondary'}>{r.status}</Badge>
                      {r.status === 'succeeded' && (
                        <span>{formatDna(r.magnitude, r.direction)} · {r.divergent_count ?? 0}/{r.sampled_count ?? 0} divergent</span>
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
                <div className="text-xs uppercase text-muted-foreground">Recent decisions</div>
                {decisions.slice(0, 10).map((d) => (
                  <div key={d.id} className="flex items-center justify-between border-b py-2 last:border-0 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{d.source}</Badge>
                      {d.verdict && (
                        <Badge variant={d.verdict === 'approved' ? 'default' : d.verdict === 'denied' ? 'destructive' : 'secondary'}>{d.verdict}</Badge>
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
          <CardHeader><CardTitle className="text-base">Authority Relation</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div><span className="text-muted-foreground">Actor role:</span> {relation.actor_role || '—'}</div>
            <div><span className="text-muted-foreground">Actor identity:</span> {relation.actor_identity || '—'}</div>
            <div><span className="text-muted-foreground">Action:</span> {relation.action || '—'}</div>
            <div><span className="text-muted-foreground">Object:</span> {relation.object_type || '—'} {relation.object_id ? `· ${relation.object_id}` : ''}</div>
            <div className="pt-2 text-muted-foreground">Domain-Context</div>
            <JsonBlock data={relation.domain_context} />
            <div className="pt-2 text-muted-foreground">Justification chain</div>
            <JsonBlock data={relation.justification_chain} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Runtime & evidence</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="text-muted-foreground">Decision logic (compiled, deterministic)</div>
            <JsonBlock data={relation.decision_logic} />
            <div className="pt-2 text-muted-foreground">Evidence binding</div>
            <JsonBlock data={relation.evidence_binding} />
            <div className="pt-2 text-muted-foreground">Domains</div>
            <div className="flex flex-wrap gap-1">
              {(relation.domains || []).map((d) => (
                <Badge key={d.domain_id} variant={d.is_primary ? 'default' : 'outline'}>{d.domain_name}</Badge>
              ))}
              {(relation.domains || []).length === 0 && <span className="text-muted-foreground">—</span>}
            </div>
          </CardContent>
        </Card>
      </div>

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
          <DialogHeader><DialogTitle>Authority Relation review</DialogTitle></DialogHeader>
          {reviewFor && (
            <AuthorityRelationReview
              relationId={relationId!}
              reviewer={reviewFor}
              onCompleted={() => { fetchRelation(); fetchTracking(); }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TestResolveDialog({ open, onOpenChange, relationId }: { open: boolean; onOpenChange: (o: boolean) => void; relationId: string }) {
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
    const { data, error } = await post<ResolveResponse>(`/api/authority/relations/${relationId}/resolve`, body);
    setBusy(false);
    if (error) setResult({ verdict: 'error', reason: error });
    else setResult(data);
  };

  const verdictColor = result?.verdict === 'approved' ? 'default'
    : result?.verdict === 'denied' ? 'destructive' : 'secondary';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Test authority resolution</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>Signer (actor identity)</Label>
            <Input value={actorIdentity} onChange={(e) => setActorIdentity(e.target.value)} placeholder="rsm-east@example.com" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Action</Label>
              <Input value={action} onChange={(e) => setAction(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Value</Label>
              <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="0.22" />
            </div>
          </div>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cosign} onChange={(e) => setCosign(e.target.checked)} /> co-sign present</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={escalated} onChange={(e) => setEscalated(e.target.checked)} /> escalated</label>
          </div>
          {result && (
            <Alert>
              <AlertDescription>
                <Badge variant={verdictColor as any} className="mr-2">{result.verdict}</Badge>
                {result.reason}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={run} disabled={busy}>{busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Resolve</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
