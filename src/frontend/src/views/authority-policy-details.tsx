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
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertCircle, ArrowLeft, ExternalLink, GitBranch, Loader2, Pencil, Trash2 } from 'lucide-react';
import { CommentSidebar } from '@/components/comments';
import VersionNavigator from '@/components/common/version-navigator';
import { DetailHeaderSkeleton, PanelSkeleton } from '@/components/common/list-view-skeleton';
import AuthorityPolicyDialog from '@/components/authority-resolution/authority-policy-dialog';
import { ValidityLine, safeHttpUrl } from '@/components/authority-resolution/policy-citation-view';
import { authorityErrorMessage } from '@/components/authority-resolution/authority-errors';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AuthorityPolicy, PolicyDependent } from '@/types/authority-resolution';

const FEATURE_ID = 'authority-resolution';

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
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
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

  const openVersion = () => {
    const n = parseInt(policy?.version || '', 10);
    setNewVersion(Number.isFinite(n) ? String(n + 1) : `${policy?.version || '1'}-2`);
    setChangeSummary('');
    setVersionOpen(true);
  };

  const createVersion = async () => {
    setBusy(true);
    const { data, error, errorCode, errorParams } = await post<AuthorityPolicy>(`/api/authority/policies/${policyId}/versions`, {
      new_version: newVersion.trim(), change_summary: changeSummary.trim() || undefined,
    });
    setBusy(false);
    if (error) { toast({ title: t('common:toast.failed'), description: authorityErrorMessage(t, error, errorCode, errorParams), variant: 'destructive' }); return; }
    setVersionOpen(false);
    toast({ title: t('policy.details.versionCreated', { version: newVersion.trim() }) });
    if (data?.id) navigate(`/authority-resolution/policies/${data.id}`);
  };

  const remove = async () => {
    if (!policy || !confirm(t('policy.list.confirmDelete', { key: policy.policy_key, version: policy.version }))) return;
    const { error, errorCode, errorParams } = await del(`/api/authority/policies/${policyId}`);
    if (error) toast({ title: t('common:toast.error'), description: authorityErrorMessage(t, error, errorCode, errorParams), variant: 'destructive' });
    else { toast({ title: t('common:toast.deleted') }); navigate('/authority-resolution/policies'); }
  };

  if (loading || permissionsLoading) {
    return (
      <div className="py-6 space-y-6">
        <DetailHeaderSkeleton actionButtons={3} leftControls={1} />
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

  const link = safeHttpUrl(policy.url);

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => navigate('/authority-resolution/policies')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('policy.details.backButton')}
        </Button>
        {canWrite && (
          <div className="flex gap-2 flex-wrap justify-end">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4 mr-1" /> {t('common:actions.edit')}
            </Button>
            <Button variant="outline" size="sm" onClick={openVersion}>
              <GitBranch className="h-4 w-4 mr-1" /> {t('policy.details.buttonNewVersion')}
            </Button>
            <CommentSidebar entityType="authority_policy" entityId={policyId!} isOpen={commentsOpen}
                            onToggle={() => setCommentsOpen(!commentsOpen)} className="h-8" />
            <Button variant="destructive" size="sm" onClick={remove}>
              <Trash2 className="mr-2 h-4 w-4" /> {t('common:actions.delete')}
            </Button>
          </div>
        )}
      </div>

      <div>
        <h1 className="text-2xl font-bold">{policy.title}</h1>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
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

      {policy.expired && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t('policy.details.expiredNote')}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">{t('policy.details.cardReference')}</CardTitle></CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <Field label={t('policy.fields.owner')}>{policy.owner_team_name || '—'}</Field>
          <Field label={t('policy.fields.validity')}>
            <ValidityLine from={policy.valid_from} to={policy.valid_to} expired={policy.expired} />
          </Field>
          <Field label={t('policy.fields.url')}>
            {link ? (
              <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline break-all">
                <ExternalLink className="h-3 w-3 shrink-0" /> {link}
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {policy.clauses.map((c) => (
                  <TableRow key={c.ref}>
                    <TableCell className="font-mono align-top">{c.ref}</TableCell>
                    <TableCell className="space-y-1">
                      {c.title && <div className="font-medium">{c.title}</div>}
                      {c.text && <div className="text-sm text-muted-foreground">{c.text}</div>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
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

      <AuthorityPolicyDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        policy={policy}
        onSaved={() => { setEditOpen(false); toast({ title: t('common:toast.updated') }); fetchPolicy(); }}
      />

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
            <Button onClick={createVersion} disabled={busy || !newVersion.trim()}>
              {busy && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
