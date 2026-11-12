import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import NativeSelect from '@/components/ui/native-select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertCircle, ArrowLeft, Ban, CheckCircle2, FileText, GitBranch, Loader2, Pencil, Trash2 } from 'lucide-react';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import VersionNavigator from '@/components/common/version-navigator';
import { DetailHeaderSkeleton, PanelSkeleton } from '@/components/common/list-view-skeleton';
import AuthorityPolicyDialog from '@/components/authority-resolution/authority-policy-dialog';
import { PolicyStatusBadge, ShortHash } from '@/components/authority-resolution/policy-citation-view';
import { formatDay } from './authority-policies';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AuthorityPolicy, PolicyDependent } from '@/types/authority-resolution';

const FEATURE_ID = 'authority-resolution';

const today = () => new Date().toISOString().slice(0, 10);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}:</span> {children}
    </div>
  );
}

export default function AuthorityPolicyDetails() {
  const { policyId } = useParams<{ policyId: string }>();
  const { t } = useTranslation(['authority-resolution', 'common']);
  const navigate = useNavigate();
  const { toast } = useToast();
  const { get, post, delete: del } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWrite = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);

  const [policy, setPolicy] = useState<AuthorityPolicy | null>(null);
  const [dependents, setDependents] = useState<PolicyDependent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  // Dialog fields
  const [approver, setApprover] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [evidenceId, setEvidenceId] = useState('');
  const [reason, setReason] = useState('');
  const [newVersion, setNewVersion] = useState('');
  const [changeSummary, setChangeSummary] = useState('');

  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [reloadKey, setReloadKey] = useState(0);
  const fetchPolicy = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    if (!policyId) return;
    let cancelled = false;
    (async () => {
      const [p, deps] = await Promise.all([
        get<AuthorityPolicy>(`/api/authority/policies/${policyId}`),
        get<PolicyDependent[]>(`/api/authority/policies/${policyId}/dependents`),
      ]);
      if (cancelled) return;
      if (p.error) toast({ title: t('common:toast.error'), description: p.error, variant: 'destructive' });
      else setPolicy(p.data);
      if (Array.isArray(deps.data)) setDependents(deps.data);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [policyId, get, toast, t, reloadKey]);

  useEffect(() => {
    setStaticSegments([
      { label: t('title.main'), path: '/authority-resolution' },
      { label: t('policy.list.title'), path: '/authority-resolution/policies' },
    ]);
    setDynamicTitle(policy ? `${policy.policy_key} v${policy.version}` : t('policy.details.defaultTitle'));
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [policy, setStaticSegments, setDynamicTitle, t]);

  const changeStatus = async (body: Record<string, any>, done: () => void) => {
    setBusy('status');
    const { error } = await post<AuthorityPolicy>(`/api/authority/policies/${policyId}/status`, body);
    setBusy(null);
    if (error) { toast({ title: t('common:toast.failed'), description: error, variant: 'destructive' }); return; }
    done();
    fetchPolicy();
  };

  const openApprove = () => {
    setApprover('');
    setFrom(policy?.effective_from?.slice(0, 10) || today());
    setTo(policy?.effective_to?.slice(0, 10) || '');
    setEvidenceId(policy?.approval_evidence_document_id || '');
    setApproveOpen(true);
  };

  const approve = () => changeStatus({
    status: 'approved',
    approved_by: approver.trim() || undefined,
    effective_from: from ? `${from}T00:00:00Z` : undefined,
    effective_to: to ? `${to}T00:00:00Z` : null,  // blank clears an end date the draft carries
    approval_evidence_document_id: evidenceId || undefined,
  }, () => { setApproveOpen(false); toast({ title: t('policy.details.approved') }); });

  const withdraw = () => changeStatus({ status: 'withdrawn', reason: reason.trim() || undefined }, () => {
    setWithdrawOpen(false);
    toast({ title: t('policy.details.withdrawn'), description: t('policy.details.withdrawnMsg') });
  });

  const openVersion = () => {
    const n = parseInt(policy?.version || '', 10);
    setNewVersion(Number.isFinite(n) ? String(n + 1) : `${policy?.version || '1'}-2`);
    setChangeSummary('');
    setVersionOpen(true);
  };

  const createVersion = async () => {
    setBusy('version');
    const { data, error } = await post<AuthorityPolicy>(`/api/authority/policies/${policyId}/versions`, {
      new_version: newVersion.trim(), change_summary: changeSummary.trim() || undefined,
    });
    setBusy(null);
    if (error) { toast({ title: t('common:toast.failed'), description: error, variant: 'destructive' }); return; }
    setVersionOpen(false);
    toast({ title: t('policy.details.versionCreated', { version: newVersion.trim() }) });
    if (data?.id) navigate(`/authority-resolution/policies/${data.id}`);
  };

  const remove = async () => {
    if (!policy || !confirm(t('policy.list.confirmDelete', { key: policy.policy_key, version: policy.version }))) return;
    const { error } = await del(`/api/authority/policies/${policyId}`);
    if (error) toast({ title: t('common:toast.error'), description: error, variant: 'destructive' });
    else { toast({ title: t('common:toast.deleted') }); navigate('/authority-resolution/policies'); }
  };

  if (loading || permissionsLoading) {
    return (
      <div className="py-6 space-y-6">
        <DetailHeaderSkeleton actionButtons={5} leftControls={1} />
        <PanelSkeleton rows={4} rowHeight="h-8" />
        <PanelSkeleton rows={3} rowHeight="h-12" />
      </div>
    );
  }
  if (!policy) {
    return (
      <div className="py-6">
        <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{t('policy.details.notFound')}</AlertDescription></Alert>
      </div>
    );
  }

  const isDraft = policy.status === 'draft';
  const evidenceDoc = policy.documents.find((d) => d.id === policy.approval_evidence_document_id);

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => navigate('/authority-resolution/policies')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('policy.details.backButton')}
        </Button>
        {canWrite && (
          <div className="flex gap-2 flex-wrap justify-end">
            {isDraft && (
              <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                <Pencil className="h-4 w-4 mr-1" /> {t('common:actions.edit')}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={openVersion}>
              <GitBranch className="h-4 w-4 mr-1" /> {t('policy.details.buttonNewVersion')}
            </Button>
            {isDraft && (
              <Button variant="outline" size="sm" onClick={openApprove}>
                <CheckCircle2 className="h-4 w-4 mr-1" /> {t('policy.details.buttonApprove')}
              </Button>
            )}
            {(policy.status === 'approved' || policy.status === 'superseded') && (
              <Button variant="outline" size="sm" onClick={() => { setReason(''); setWithdrawOpen(true); }}>
                <Ban className="h-4 w-4 mr-1" /> {t('policy.details.buttonWithdraw')}
              </Button>
            )}
            <CommentSidebar entityType="authority_policy" entityId={policyId!} isOpen={commentsOpen}
                            onToggle={() => setCommentsOpen(!commentsOpen)} className="h-8" />
            {(policy.status === 'draft' || policy.status === 'withdrawn') && (
              <Button variant="destructive" size="sm" onClick={remove}>
                <Trash2 className="mr-2 h-4 w-4" /> {t('common:actions.delete')}
              </Button>
            )}
          </div>
        )}
      </div>

      <div>
        <h1 className="text-2xl font-bold">{policy.title}</h1>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <PolicyStatusBadge status={policy.status} />
          <span className="text-sm font-mono text-muted-foreground">{policy.policy_key}</span>
          <span className="text-sm text-muted-foreground">v{policy.version}</span>
          <VersionNavigator
            entityKind="authority_policy"
            currentEntityId={policyId!}
            currentVersion={policy.version}
            onVersionChange={(id) => navigate(`/authority-resolution/policies/${id}`)}
          />
        </div>
        {policy.summary && <p className="text-muted-foreground mt-2 max-w-2xl">{policy.summary}</p>}
        {(policy.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {(policy.tags || []).map((tag, i) => (
              <Badge key={i} variant="secondary" className="text-xs">{tag.fully_qualified_name}</Badge>
            ))}
          </div>
        )}
      </div>

      {policy.root_problem && (
        <Alert variant={policy.status === 'draft' ? 'default' : 'destructive'}>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t('policy.details.rootProblem', { problem: policy.root_problem })}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">{t('policy.details.cardBasis')}</CardTitle></CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <Field label={t('policy.fields.type')}>{t(`policy.type.${policy.policy_type}`)}</Field>
          <Field label={t('policy.fields.owner')}>{policy.owner_team_name || '—'}</Field>
          <Field label={t('policy.fields.effective')}>
            {formatDay(policy.effective_from)} → {policy.effective_to ? formatDay(policy.effective_to) : t('policy.openEnded')}
          </Field>
          <Field label={t('policy.fields.jurisdiction')}>
            {policy.jurisdiction ? <span className="font-mono text-xs">{JSON.stringify(policy.jurisdiction)}</span> : '—'}
          </Field>
          <Field label={t('policy.fields.approvedBy')}>
            {policy.approved_by ? `${policy.approved_by} · ${formatDay(policy.approved_at)}` : '—'}
          </Field>
          <Field label={t('policy.fields.approvalEvidence')}>
            {evidenceDoc ? (
              <a href={`/api/documents/${evidenceDoc.id}/content`} className="hover:underline" target="_blank" rel="noopener noreferrer">
                {evidenceDoc.filename}
              </a>
            ) : '—'}
          </Field>
          <Field label={t('policy.fields.derivedFrom')}>
            {policy.parent_policy_id ? (
              <Link to={`/authority-resolution/policies/${policy.parent_policy_id}`} className="text-primary hover:underline">
                v{policy.parent_version || '?'}
              </Link>
            ) : '—'}
            {policy.change_summary && <span className="text-muted-foreground"> — {policy.change_summary}</span>}
          </Field>
          {policy.withdrawn_reason && <Field label={t('policy.fields.withdrawnReason')}>{policy.withdrawn_reason}</Field>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">{t('policy.clauses.title')}</CardTitle></CardHeader>
        <CardContent>
          {policy.clauses.length === 0 ? (
            <div className="text-sm text-muted-foreground">{t('policy.clauses.none')}</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">{t('policy.clauses.ref')}</TableHead>
                  <TableHead>{t('policy.clauses.clause')}</TableHead>
                  <TableHead className="w-40">{t('policy.clauses.limit')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {policy.clauses.map((c) => (
                  <TableRow key={c.ref}>
                    <TableCell className="font-mono align-top">{c.ref}</TableCell>
                    <TableCell className="space-y-1">
                      {c.title && <div className="font-medium">{c.title}</div>}
                      {c.text && <div className="text-sm text-muted-foreground">{c.text}</div>}
                      {(c.conditions || []).length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {(c.conditions || []).map((cond, i) => <Badge key={i} variant="outline" className="text-xs">{cond}</Badge>)}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="align-top text-sm">
                      {c.limits?.amount != null ? `${c.limits.amount.toLocaleString()} ${c.limits.currency || ''}` : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">{t('policy.details.cardDocuments')}</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {policy.documents.length === 0 && (
            <div className="text-muted-foreground">{isDraft ? t('policy.details.noDocumentsDraft') : t('policy.details.noDocuments')}</div>
          )}
          {policy.documents.map((d) => (
            <div key={d.id} className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              <a href={`/api/documents/${d.id}/content`} className="hover:underline" target="_blank" rel="noopener noreferrer">{d.filename}</a>
              {d.title && d.title !== d.filename && <span className="text-muted-foreground">{d.title}</span>}
              <span className="ml-auto text-xs text-muted-foreground">SHA-256</span>
              <ShortHash sha256={d.sha256} />
            </div>
          ))}
          {!isDraft && <div className="text-xs text-muted-foreground pt-1">{t('policy.details.documentsImmutable')}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">{t('policy.details.cardDependents', { count: dependents.length })}</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {dependents.length === 0 && <div className="text-muted-foreground">{t('policy.details.noDependents')}</div>}
          {dependents.map((d) => (
            <div key={d.id} className="flex items-center gap-2">
              <Link to={`/authority-resolution/${d.id}`} className="text-primary hover:underline">{d.name}</Link>
              <span className="text-muted-foreground">v{d.version}</span>
              <Badge variant="outline">{t(`status.${d.status}`, { defaultValue: d.status })}</Badge>
              <span className="ml-auto flex gap-1">
                {d.clause_refs.map((r) => <Badge key={r} variant="secondary" className="font-mono text-xs">{r}</Badge>)}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <EntityMetadataPanel entityId={policyId!} entityType="authority_policy" />

      <AuthorityPolicyDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        policy={policy}
        onSaved={() => { setEditOpen(false); toast({ title: t('common:toast.updated') }); fetchPolicy(); }}
      />

      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('policy.approve.title', { key: policy.policy_key, version: policy.version })}</DialogTitle>
            <DialogDescription>{t('policy.approve.description')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t('policy.fields.approvedBy')}</Label>
              <Input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder={t('policy.approve.approverPlaceholder')} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t('policy.fields.effectiveFrom')} *</Label>
                <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>{t('policy.fields.effectiveTo')}</Label>
                <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.approvalEvidence')}</Label>
              <NativeSelect value={evidenceId} onChange={(e) => setEvidenceId(e.target.value)}>
                <option value="">{t('policy.approve.noEvidence')}</option>
                {policy.documents.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
              </NativeSelect>
            </div>
            {policy.parent_policy_id && (
              <p className="text-xs text-muted-foreground">{t('policy.approve.supersedesHint', { version: policy.parent_version || '?' })}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveOpen(false)}>{t('common:actions.cancel')}</Button>
            <Button onClick={approve} disabled={busy === 'status' || !from}>
              {busy === 'status' && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {t('policy.details.buttonApprove')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={withdrawOpen} onOpenChange={setWithdrawOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('policy.withdraw.title', { key: policy.policy_key, version: policy.version })}</DialogTitle>
            <DialogDescription>{t('policy.withdraw.description', { count: dependents.length })}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label>{t('policy.fields.withdrawnReason')}</Label>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWithdrawOpen(false)}>{t('common:actions.cancel')}</Button>
            <Button variant="destructive" onClick={withdraw} disabled={busy === 'status'}>
              {busy === 'status' && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {t('policy.details.buttonWithdraw')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={versionOpen} onOpenChange={setVersionOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('policy.newVersion.title')}</DialogTitle>
            <DialogDescription>{t('policy.newVersion.description')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t('policy.fields.version')}</Label>
              <Input value={newVersion} onChange={(e) => setNewVersion(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.changeSummary')}</Label>
              <Textarea value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)} rows={2} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setVersionOpen(false)}>{t('common:actions.cancel')}</Button>
            <Button onClick={createVersion} disabled={busy === 'version' || !newVersion.trim()}>
              {busy === 'version' && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
