import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  PackageCheck,
  RefreshCw,
  Send,
  ShieldAlert,
  Truck,
  Radar,
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import ReleaseStatusBadge from '@/components/access-policies/release-status-badge';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type {
  AccessRelease,
  CompileIssue,
  DeliveryModeKey,
  LiveDiffReport,
  ReleaseStatus,
  ReleaseTargets,
  UcGrant,
} from '@/types/access-policy';

const FEATURE_ID = 'access-policies';
const ISSUE_VARIANT: Record<CompileIssue['severity'], 'destructive' | 'secondary' | 'outline'> = {
  error: 'destructive',
  warning: 'secondary',
  info: 'outline',
};

function GrantTable({ grants, empty }: { grants: UcGrant[]; empty: string }) {
  const { t } = useTranslation(['access-policies']);
  if (!grants.length) return <p className="py-2 text-sm text-muted-foreground">{empty}</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('access-policies:ledger.principal')}</TableHead>
          <TableHead>{t('access-policies:ledger.securable')}</TableHead>
          <TableHead>{t('access-policies:ledger.privilege')}</TableHead>
          <TableHead>{t('access-policies:ledger.expires')}</TableHead>
          <TableHead>{t('access-policies:ledger.sources')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {grants.map((g) => (
          <TableRow key={`${g.principal}|${g.securable_type}|${g.securable_name}|${g.privilege}`}>
            <TableCell className="text-sm">{g.principal}</TableCell>
            <TableCell className="font-mono text-xs">
              <Badge variant="outline" className="mr-1 text-[10px]">
                {g.securable_type}
              </Badge>
              {g.securable_name}
            </TableCell>
            <TableCell className="text-xs">
              {g.privilege.replace(/_/g, ' ')}
              {g.implied && (
                <Badge variant="secondary" className="ml-1 text-[10px]" title={t('access-policies:ledger.impliedTitle')}>
                  {t('access-policies:ledger.implied')}
                </Badge>
              )}
            </TableCell>
            <TableCell className="text-xs">{g.expires_at ? new Date(g.expires_at).toLocaleString() : '—'}</TableCell>
            <TableCell className="text-xs text-muted-foreground">
              {(g.sources || []).map((s) => `${s.policy_name} · ${s.rule_kind} #${s.rule_index + 1}`).join('; ')}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function KV({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm">{value || '—'}</div>
    </div>
  );
}

export default function AccessPolicyReleaseDetails() {
  const { releaseId } = useParams<{ releaseId: string }>();
  const { t } = useTranslation(['access-policies', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const canAdmin = hasPermission(FEATURE_ID, FeatureAccessLevel.ADMIN);
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [release, setRelease] = useState<AccessRelease | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [statusTarget, setStatusTarget] = useState<ReleaseStatus | null>(null);
  const [comment, setComment] = useState('');
  const [deliverOpen, setDeliverOpen] = useState(false);
  const [enabledModes, setEnabledModes] = useState<DeliveryModeKey[]>([]);
  const [modes, setModes] = useState<DeliveryModeKey[]>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const base = `/api/access-policies/releases/${releaseId}`;

  const load = useCallback(async () => {
    const res = await get<AccessRelease>(base);
    if (res.data && !res.error) {
      setRelease(res.data);
      setDynamicTitle(res.data.name);
    }
    setLoading(false);
  }, [base, get, setDynamicTitle]);

  useEffect(() => {
    setStaticSegments([
      { label: t('access-policies:title'), path: '/access-policies' },
      { label: t('access-policies:tabs.releases'), path: '/access-policies?tab=releases' },
    ]);
    load();
    return () => setDynamicTitle(null);
  }, [load, setStaticSegments, setDynamicTitle, t]);

  const act = async (path: string, body: unknown, done: string) => {
    setBusy(true);
    const res = await post<AccessRelease>(`${base}/${path}`, body);
    setBusy(false);
    if (res.error || !res.data) {
      toast({ title: t('access-policies:releases.actionFailed'), description: res.error || '', variant: 'destructive' });
      return false;
    }
    setRelease(res.data);
    toast({ title: done });
    return true;
  };

  const openDeliver = async () => {
    const res = await get<ReleaseTargets>('/api/access-policies/targets');
    const enabled = res.data?.delivery_modes || [];
    setEnabledModes(enabled);
    setModes(enabled);
    setDeliverOpen(true);
  };

  const runLiveDiff = async () => {
    setBusy(true);
    const res = await post<LiveDiffReport>(`${base}/live-diff`, {});
    setBusy(false);
    if (res.error || !res.data) {
      toast({ title: t('access-policies:releases.liveDiffFailed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    setRelease((r) => (r ? { ...r, live_diff: res.data } : r));
  };

  const copySql = async () => {
    await navigator.clipboard.writeText((release?.changes.sql || []).join('\n'));
    toast({ title: t('access-policies:releases.sqlCopied') });
  };

  if (loading) return <DetailViewSkeleton />;
  if (!release) {
    return (
      <Alert variant="destructive" className="mt-6">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('access-policies:releases.notFound')}</AlertDescription>
      </Alert>
    );
  }

  const errors = release.issues.filter((i) => i.severity === 'error');
  const gated = release.plan.gated || [];
  const live = release.live_diff;

  return (
    <div className="space-y-6 py-6">
      {/* Header actions */}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canWrite && release.status === 'draft' && release.release_kind === 'policy' && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => act('recompile', {}, t('access-policies:releases.recompiled'))}>
            <RefreshCw className="mr-1 h-4 w-4" /> {t('access-policies:releases.recompile')}
          </Button>
        )}
        {canWrite &&
          release.allowed_transitions.map((s) => (
            <Button key={s} size="sm" variant={s === 'discarded' ? 'outline' : 'default'} disabled={busy} onClick={() => setStatusTarget(s)}>
              {s === 'under_review' && <Send className="mr-1 h-4 w-4" />}
              {s === 'approved' && <CheckCircle2 className="mr-1 h-4 w-4" />}
              {t(`access-policies:releases.transition.${s}`)}
            </Button>
          ))}
        {canAdmin && release.deliverable && (
          <Button size="sm" disabled={busy} onClick={openDeliver}>
            <Truck className="mr-1 h-4 w-4" /> {t('access-policies:releases.deliver')}
          </Button>
        )}
        {canAdmin && release.confirmable && (
          <Button size="sm" disabled={busy} onClick={() => setConfirmOpen(true)}>
            <PackageCheck className="mr-1 h-4 w-4" /> {t('access-policies:releases.confirmApplied')}
          </Button>
        )}
        {canWrite && (
          <Button size="sm" variant="outline" disabled={busy} onClick={runLiveDiff}>
            <Radar className="mr-1 h-4 w-4" /> {t('access-policies:releases.liveDiff')}
          </Button>
        )}
        <CommentSidebar
          entityType="access_policy_release"
          entityId={release.id}
          isOpen={commentsOpen}
          onToggle={() => setCommentsOpen(!commentsOpen)}
          className="h-8"
        />
      </div>

      {release.status === 'delivered' && (
        <Alert className="border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950">
          <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          <AlertDescription className="text-amber-800 dark:text-amber-200">{t('access-policies:releases.awaitingConfirmation')}</AlertDescription>
        </Alert>
      )}

      {/* Info panel */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <CardTitle className="flex items-center text-2xl font-bold">
                <Truck className="mr-3 h-7 w-7 shrink-0 text-primary" />
                <span className="truncate">{release.name}</span>
              </CardTitle>
              <CardDescription className="pt-1">{release.notes || t('access-policies:releases.description')}</CardDescription>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <ReleaseStatusBadge status={release.status} />
              <Badge variant="outline">{t(`access-policies:releases.kind.${release.release_kind}`)}</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KV label={t('access-policies:releases.target')} value="Unity Catalog" />
            <KV
              label={t('access-policies:releases.changes')}
              value={t('access-policies:releases.changeSummary', {
                add: release.counts.add,
                remove: release.counts.remove,
                update: release.counts.update,
              })}
            />
            <KV label={t('access-policies:releases.desiredGrants')} value={release.counts.grants} />
            <KV label={t('access-policies:releases.compiledAt')} value={release.plan.compiled_at && new Date(release.plan.compiled_at).toLocaleString()} />
            <KV label={t('access-policies:releases.createdBy')} value={release.created_by} />
            <KV label={t('access-policies:releases.submittedBy')} value={release.submitted_by} />
            <KV label={t('access-policies:releases.approvedBy')} value={release.approved_by} />
            <KV
              label={t('access-policies:releases.deliveredVia')}
              value={release.delivery_modes.map((m) => t(`access-policies:releases.modes.${m}`)).join(', ')}
            />
            <KV
              label={t('access-policies:releases.applied')}
              value={release.applied_at && `${new Date(release.applied_at).toLocaleString()} · ${release.applied_by}`}
            />
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">{t('access-policies:releases.sourcePolicies')}</div>
            <div className="flex flex-wrap gap-1">
              {release.source_policies.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
              {release.source_policies.map((p) => (
                <Link key={p.id} to={`/access-policies/policies/${p.id}`}>
                  <Badge variant="secondary" className="hover:bg-secondary/70">
                    {p.name} v{p.version}
                  </Badge>
                </Link>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Compile issues */}
      {release.issues.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ShieldAlert className="h-5 w-5" /> {t('access-policies:releases.issues')}
            </CardTitle>
            {errors.length > 0 && <CardDescription className="text-red-700 dark:text-red-400">{t('access-policies:releases.errorsBlock')}</CardDescription>}
          </CardHeader>
          <CardContent className="space-y-2">
            {release.issues.map((i, n) => (
              <div key={n} className="flex items-start gap-2 text-sm">
                <Badge variant={ISSUE_VARIANT[i.severity]} className="shrink-0 text-[10px]">
                  {t(`access-policies:releases.severity.${i.severity}`)}
                </Badge>
                <span>{i.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Changes */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t('access-policies:releases.changes')}</CardTitle>
          <CardDescription>{t('access-policies:releases.changesHint', { unchanged: release.counts.unchanged })}</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="add">
            <TabsList>
              <TabsTrigger value="add">
                {t('access-policies:releases.toGrant')} ({release.counts.add})
              </TabsTrigger>
              <TabsTrigger value="remove">
                {t('access-policies:releases.toRevoke')} ({release.counts.remove})
              </TabsTrigger>
              <TabsTrigger value="update">
                {t('access-policies:releases.expiryUpdates')} ({release.counts.update})
              </TabsTrigger>
              {release.counts.untrack > 0 && (
                <TabsTrigger value="untrack">
                  {t('access-policies:releases.untrack')} ({release.counts.untrack})
                </TabsTrigger>
              )}
              <TabsTrigger value="sql">{t('access-policies:releases.sql')}</TabsTrigger>
              <TabsTrigger value="desired">
                {t('access-policies:releases.desiredGrants')} ({release.counts.grants})
              </TabsTrigger>
            </TabsList>
            <TabsContent value="add">
              <GrantTable grants={release.changes.add || []} empty={t('access-policies:releases.none')} />
            </TabsContent>
            <TabsContent value="remove">
              <GrantTable grants={release.changes.remove || []} empty={t('access-policies:releases.none')} />
            </TabsContent>
            <TabsContent value="update">
              <GrantTable grants={release.changes.update || []} empty={t('access-policies:releases.none')} />
            </TabsContent>
            <TabsContent value="untrack">
              <p className="py-2 text-sm text-muted-foreground">{t('access-policies:releases.untrackHint')}</p>
              <GrantTable grants={release.changes.untrack || []} empty={t('access-policies:releases.none')} />
            </TabsContent>
            <TabsContent value="sql">
              <div className="mb-2 flex justify-end">
                <Button size="sm" variant="outline" onClick={copySql} disabled={!release.changes.sql?.length}>
                  <Copy className="mr-1 h-4 w-4" /> {t('access-policies:releases.copySql')}
                </Button>
              </div>
              <pre className="max-h-[400px] overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
                {(release.changes.sql || []).join('\n') || t('access-policies:releases.none')}
              </pre>
            </TabsContent>
            <TabsContent value="desired">
              <GrantTable grants={release.plan.grants || []} empty={t('access-policies:releases.none')} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Gated rules */}
      {gated.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{t('access-policies:releases.gated')}</CardTitle>
            <CardDescription>{t('access-policies:releases.gatedHint')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {gated.map((g, n) => (
              <div key={n} className="flex items-start gap-2 text-sm">
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  {t(`access-policies:releases.gate.${g.gate}`)}
                </Badge>
                <span>
                  <span className="font-medium">
                    {g.source.policy_name} · {g.source.rule_kind} #{g.source.rule_index + 1}
                  </span>
                  : {g.reason}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Live state */}
      {live && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Radar className="h-5 w-5" /> {t('access-policies:releases.liveState')}
              <Badge variant={live.in_sync ? 'secondary' : 'destructive'}>
                {live.in_sync ? t('access-policies:releases.inSync') : t('access-policies:releases.drift')}
              </Badge>
            </CardTitle>
            <CardDescription>
              {t('access-policies:releases.liveHint', {
                count: live.securables_checked,
                at: new Date(live.checked_at).toLocaleString(),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {live.errors.length > 0 && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{live.errors.join('; ')}</AlertDescription>
              </Alert>
            )}
            <div>
              <div className="mb-1 text-sm font-medium">{t('access-policies:releases.liveMissing')}</div>
              <GrantTable grants={live.missing} empty={t('access-policies:releases.none')} />
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">{t('access-policies:releases.liveStale')}</div>
              <GrantTable grants={live.stale} empty={t('access-policies:releases.none')} />
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">{t('access-policies:releases.liveUnmanaged')}</div>
              <GrantTable grants={live.unmanaged} empty={t('access-policies:releases.none')} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Delivery history */}
      {release.delivery_results.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{t('access-policies:releases.deliveryHistory')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {release.delivery_results.map((a, n) => (
              <div key={n} className="rounded-md border p-3 text-sm">
                <div className="mb-1 text-xs text-muted-foreground">
                  {new Date(a.at).toLocaleString()} · {a.by}
                </div>
                {a.results.map((r, m) => (
                  <div key={m} className="flex items-start gap-2">
                    <Badge variant={r.success ? 'secondary' : 'destructive'} className="shrink-0 text-[10px]">
                      {t(`access-policies:releases.modes.${r.mode}`)}
                    </Badge>
                    <span>
                      {r.success ? r.message : r.error}
                      {r.details?.filename && <span className="ml-1 font-mono text-xs">{`${r.details.subdir}/${r.details.filename}`}</span>}
                      {typeof r.details?.failed === 'number' && r.details.failed > 0 && (
                        <span className="ml-1 text-red-700 dark:text-red-400">
                          {t('access-policies:releases.itemsFailed', { count: r.details.failed })}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <EntityMetadataPanel entityId={release.id} entityType="access_policy_release" />

      {/* Status change dialog */}
      <Dialog open={!!statusTarget} onOpenChange={(o) => !o && setStatusTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{statusTarget && t(`access-policies:releases.transition.${statusTarget}`)}</DialogTitle>
            <DialogDescription>{t('access-policies:releases.statusDialog', { name: release.name })}</DialogDescription>
          </DialogHeader>
          <Label htmlFor="rel-status-comment">{t('access-policies:details.statusComment')}</Label>
          <Textarea id="rel-status-comment" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusTarget(null)}>
              {t('common:actions.cancel')}
            </Button>
            <Button
              disabled={busy}
              onClick={async () => {
                if (statusTarget && (await act('status', { status: statusTarget, comment: comment || undefined }, t('access-policies:releases.statusChanged')))) {
                  setStatusTarget(null);
                  setComment('');
                }
              }}
            >
              {t('common:actions.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deliver dialog */}
      <Dialog open={deliverOpen} onOpenChange={setDeliverOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('access-policies:releases.deliverTitle')}</DialogTitle>
            <DialogDescription>{t('access-policies:releases.deliverDescription')}</DialogDescription>
          </DialogHeader>
          {enabledModes.length === 0 ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{t('access-policies:releases.noModes')}</AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-3">
              {enabledModes.map((m) => (
                <div key={m} className="flex items-start gap-2">
                  <Checkbox
                    id={`mode-${m}`}
                    checked={modes.includes(m)}
                    onCheckedChange={(c) => setModes((cur) => (c ? [...cur, m] : cur.filter((x) => x !== m)))}
                  />
                  <div>
                    <Label htmlFor={`mode-${m}`}>{t(`access-policies:releases.modes.${m}`)}</Label>
                    <p className="text-xs text-muted-foreground">{t(`access-policies:releases.modeHint.${m}`)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeliverOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button
              disabled={busy || modes.length === 0}
              onClick={async () => {
                if (await act('deliver', { modes }, t('access-policies:releases.delivered'))) setDeliverOpen(false);
              }}
            >
              <Truck className="mr-1 h-4 w-4" /> {t('access-policies:releases.deliver')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm applied dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('access-policies:releases.confirmApplied')}</DialogTitle>
            <DialogDescription>{t('access-policies:releases.confirmDescription')}</DialogDescription>
          </DialogHeader>
          <Label htmlFor="rel-confirm-comment">{t('access-policies:details.statusComment')}</Label>
          <Textarea id="rel-confirm-comment" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button
              disabled={busy}
              onClick={async () => {
                if (await act('confirm-applied', { comment: comment || undefined }, t('access-policies:releases.appliedDone'))) {
                  setConfirmOpen(false);
                  setComment('');
                }
              }}
            >
              {t('common:actions.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
