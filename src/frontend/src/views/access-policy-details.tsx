import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  Download,
  GitBranch,
  Layers,
  Pencil,
  ShieldCheck,
  Trash2,
  Users,
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import DomainBadgeList from '@/components/ui/domain-badge-list';
import TagChip from '@/components/ui/tag-chip';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { CommentSidebar } from '@/components/comments';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import VersionNavigator from '@/components/common/version-navigator';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import type { EntitySemanticLink } from '@/types/semantic-link';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useTeams } from '@/hooks/use-teams';
import { useAccessCollections, useOdrlProfile } from '@/hooks/use-access-policies';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { useProjectContext } from '@/stores/project-store';
import { FeatureAccessLevel } from '@/types/settings';
import AccessEntityFormDialog from '@/components/access-policies/access-entity-form-dialog';
import AccessStatusBadge from '@/components/access-policies/access-status-badge';
import CheckAccessPanel from '@/components/access-policies/check-access-panel';
import { ENFORCEMENT_VARIANT } from '@/components/access-policies/constraint-editor';
import { RULE_KINDS, describeConstraint, describeRef } from '@/components/access-policies/odrl-helpers';
import type {
  AccessCollection,
  AccessEntity,
  AccessKind,
  AccessPolicy,
  AccessStatus,
  OdrlConstraint,
  OdrlRule,
  PolicyValidation,
  VersionRow,
} from '@/types/access-policy';
import { KIND_ENTITY_TYPE, KIND_SEGMENT, SEGMENT_KIND } from '@/types/access-policy';

const FEATURE_ID = 'access-policies';

function bumpMinor(v: string): string {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(v || '');
  return m ? `${m[1]}.${Number(m[2]) + 1}.0` : `${v}-next`;
}

const KIND_ICON = { policy: ShieldCheck, audience: Users, asset_collection: Layers } as const;

function InfoItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Label className="min-w-[4rem] shrink-0 text-xs text-muted-foreground">{label}:</Label>
      {children}
    </div>
  );
}

const Dash = () => <span className="text-xs text-muted-foreground">—</span>;

export default function AccessPolicyDetails() {
  const { t } = useTranslation(['access-policies', 'common']);
  const { segment = 'policies', entityId } = useParams<{ segment: string; entityId: string }>();
  const kind: AccessKind = SEGMENT_KIND[segment] || 'policy';
  const navigate = useNavigate();
  const { get, post, delete: del } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const { teams } = useTeams();
  const { availableProjects, fetchUserProjects } = useProjectContext();
  const profile = useOdrlProfile();
  const { nameForIri } = useAccessCollections();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [entity, setEntity] = useState<AccessEntity | null>(null);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [validation, setValidation] = useState<PolicyValidation | null>(null);
  const [jsonld, setJsonld] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [newVersion, setNewVersion] = useState('');
  const [changeSummary, setChangeSummary] = useState('');
  const [statusTarget, setStatusTarget] = useState<AccessStatus | null>(null);
  const [statusComment, setStatusComment] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [links, setLinks] = useState<EntitySemanticLink[]>([]);
  const [iriDialogOpen, setIriDialogOpen] = useState(false);
  const [policyNames, setPolicyNames] = useState<Record<string, string>>({});

  const base = `/api/access-policies/${KIND_SEGMENT[kind]}/${entityId}`;

  const load = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    setError(null);
    let res = await get<AccessEntity>(base);
    if (!res.data || res.error) {
      // Read-after-write: the create response can precede the commit.
      await new Promise((r) => setTimeout(r, 400));
      res = await get<AccessEntity>(base);
    }
    if (!res.data || res.error) {
      setError(res.error || t('access-policies:details.notFound'));
      setEntity(null);
      setLoading(false);
      return;
    }
    setEntity(res.data);
    setDynamicTitle(res.data.name);
    const [v, l] = await Promise.all([
      get<VersionRow[]>(`${base}/versions`),
      get<EntitySemanticLink[]>(`/api/semantic-links/entity/${KIND_ENTITY_TYPE[kind]}/${entityId}`),
    ]);
    setVersions(Array.isArray(v.data) ? v.data : []);
    setLinks(Array.isArray(l.data) ? l.data : []);
    if (kind === 'policy' && (res.data as AccessPolicy).inherit_from?.length) {
      const all = await get<AccessPolicy[]>('/api/access-policies/policies');
      setPolicyNames(Object.fromEntries((Array.isArray(all.data) ? all.data : []).map((p) => [p.uid, p.name])));
    }
    if (kind === 'policy') {
      const [val, doc] = await Promise.all([get<PolicyValidation>(`${base}/validation`), get<unknown>(`${base}/jsonld`)]);
      setValidation(val.data || null);
      setJsonld(doc.data || null);
    }
    setLoading(false);
  }, [entityId, base, get, kind, setDynamicTitle, t]);

  useEffect(() => {
    fetchUserProjects();
    setStaticSegments([
      { label: t('access-policies:title'), path: '/access-policies' },
      { label: t(`access-policies:tabs.${kind === 'asset_collection' ? 'assetCollections' : kind === 'audience' ? 'audiences' : 'policies'}`), path: `/access-policies?tab=${KIND_SEGMENT[kind]}` },
    ]);
    load();
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [load, kind, setStaticSegments, setDynamicTitle, fetchUserProjects, t]);

  const actionLabel = useCallback(
    (k: string | null | undefined) => profile?.actions.find((a) => a.key === k)?.label || k || '?',
    [profile],
  );
  const operandLabel = useCallback(
    (k: string) => profile?.left_operands.find((o) => o.key === k)?.label || k,
    [profile],
  );
  const enforcementOf = useCallback(
    (c: OdrlConstraint): string[] =>
      c.logical
        ? (c.constraints || []).flatMap(enforcementOf)
        : [profile?.left_operands.find((o) => o.key === c.leftOperand)?.enforcement || 'platform'],
    [profile],
  );

  const changeStatus = async () => {
    if (!statusTarget) return;
    const res = await post<AccessEntity>(`${base}/status`, { status: statusTarget, comment: statusComment || undefined });
    if (res.error || !res.data) {
      toast({ title: t('access-policies:details.statusFailed'), description: res.error || '', variant: 'destructive' });
    } else {
      toast({ title: t('access-policies:details.statusChanged', { status: t(`access-policies:status.${statusTarget}`) }) });
      setEntity(res.data);
      load();
    }
    setStatusTarget(null);
    setStatusComment('');
  };

  const createVersion = async () => {
    const res = await post<AccessEntity>(`${base}/versions`, { new_version: newVersion, change_summary: changeSummary || undefined });
    if (res.error || !res.data) {
      toast({ title: t('access-policies:details.versionFailed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    setVersionOpen(false);
    toast({ title: t('access-policies:details.versionCreated', { version: res.data.version }) });
    navigate(`/access-policies/${KIND_SEGMENT[kind]}/${res.data.id}`);
  };

  const addIri = async (iri: string) => {
    const res = await post<EntitySemanticLink>('/api/semantic-links/', {
      entity_id: entityId,
      entity_type: KIND_ENTITY_TYPE[kind],
      iri,
    });
    setIriDialogOpen(false);
    if (res.error) {
      toast({ title: t('access-policies:details.linkFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    load();
  };

  const removeLink = async (linkId: string) => {
    const res = await del(`/api/semantic-links/${linkId}`);
    if (res.error) {
      toast({ title: t('access-policies:details.linkFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    setLinks((cur) => cur.filter((x) => x.id !== linkId));
  };

  const nameForPolicy = (uid: string) => policyNames[uid] || uid;

  const doDelete = async () => {
    const res = await del(base);
    setDeleteOpen(false);
    if (res.error) {
      toast({ title: t('access-policies:details.deleteFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    toast({ title: t('access-policies:details.deleted') });
    navigate(`/access-policies?tab=${KIND_SEGMENT[kind]}`);
  };

  const downloadJsonld = () => {
    if (!jsonld || !entity) return;
    const blob = new Blob([JSON.stringify(jsonld, null, 2)], { type: 'application/ld+json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${entity.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${entity.version}.jsonld`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const teamName = useMemo(() => teams.find((x) => x.id === entity?.owner_team_id)?.name, [teams, entity]);
  const projectName = useMemo(
    () => availableProjects.find((x) => x.id === entity?.project_id)?.name,
    [availableProjects, entity],
  );

  if (loading && !entity) return <DetailViewSkeleton />;
  if (error || !entity) {
    return (
      <div className="space-y-4 py-6">
        <Button variant="outline" size="sm" onClick={() => navigate('/access-policies')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('access-policies:details.back')}
        </Button>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error || t('access-policies:details.notFound')}</AlertDescription>
        </Alert>
      </div>
    );
  }

  const policy = kind === 'policy' ? (entity as AccessPolicy) : null;
  const collection = kind !== 'policy' ? (entity as AccessCollection) : null;
  const canDelete = canWrite && (entity.status === 'draft' || entity.status === 'retired');
  const KindIcon = KIND_ICON[kind];

  const renderRule = (r: OdrlRule, kindName: string, idx: number) => {
    const enforcement = Array.from(new Set((r.constraint || []).flatMap(enforcementOf)));
    const subs = kindName === 'prohibition' ? r.remedy : r.duty;
    return (
      <div key={`${kindName}-${idx}`} className="rounded-md border p-3 text-sm" data-testid={`rule-view-${kindName}-${idx}`}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={kindName === 'prohibition' ? 'destructive' : kindName === 'obligation' ? 'outline' : 'secondary'}>
            {t(`access-policies:ruleKinds.${kindName}`)}
          </Badge>
          <span>
            <strong>{r.assignee ? describeRef(r.assignee, nameForIri) : t('access-policies:details.everyone')}</strong>{' '}
            {t(`access-policies:details.verb.${kindName}`)} <strong>{actionLabel(r.action)}</strong>
            {r.target ? (
              <>
                {' '}
                {t('access-policies:details.on')} <code className="rounded bg-muted px-1">{describeRef(r.target, nameForIri)}</code>
              </>
            ) : null}
          </span>
        </div>
        {(r.constraint || []).length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{t('access-policies:details.when')}</span>
            {(r.constraint || []).map((c, i) => (
              <code key={i} className="rounded bg-muted px-1">
                {describeConstraint(c, operandLabel)}
              </code>
            ))}
            {enforcement.map((e) => (
              <Badge key={e} variant={ENFORCEMENT_VARIANT[e]} className="text-[10px]">
                {t(`access-policies:enforcement.${e}`)}
              </Badge>
            ))}
          </div>
        )}
        {subs && subs.length > 0 && (
          <div className="mt-2 text-xs">
            <span className="text-muted-foreground">
              {kindName === 'prohibition' ? t('access-policies:details.remedy') : t('access-policies:details.duty')}:
            </span>{' '}
            {subs.map((d) => actionLabel(d.action)).join(', ')}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate(`/access-policies?tab=${KIND_SEGMENT[kind]}`)}>
            <ArrowLeft className="mr-2 h-4 w-4" /> {t('access-policies:details.back')}
          </Button>
          <VersionNavigator
            entityKind={KIND_ENTITY_TYPE[kind]}
            currentEntityId={entity.id}
            currentVersion={entity.version}
            onVersionChange={(id) => navigate(`/access-policies/${KIND_SEGMENT[kind]}/${id}`)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canWrite &&
            entity.allowed_transitions.map((s) => (
              <Button
                key={s}
                size="sm"
                variant={s === 'active' || s === 'approved' ? 'default' : 'outline'}
                onClick={() => setStatusTarget(s)}
                data-testid={`transition-${s}`}
              >
                {t(`access-policies:transitions.${s}`)}
              </Button>
            ))}
          {canWrite && (
            <Button size="sm" variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil className="mr-1 h-4 w-4" /> {t('common:actions.edit')}
            </Button>
          )}
          {canWrite && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setNewVersion(bumpMinor(entity.version));
                setChangeSummary('');
                setVersionOpen(true);
              }}
            >
              <GitBranch className="mr-1 h-4 w-4" /> {t('access-policies:details.newVersion')}
            </Button>
          )}
          <CommentSidebar
            entityType={KIND_ENTITY_TYPE[kind]}
            entityId={entity.id}
            isOpen={commentsOpen}
            onToggle={() => setCommentsOpen(!commentsOpen)}
            className="h-8"
          />
          {canDelete && (
            <Button size="sm" variant="destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="mr-1 h-4 w-4" /> {t('common:actions.delete')}
            </Button>
          )}
        </div>
      </div>

      {entity.draft_owner_id && (
        <Alert className="border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
          <AlertCircle className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          <AlertDescription className="text-blue-800 dark:text-blue-200">
            <strong>{t('access-policies:list.personalDraft')}</strong> — {t('access-policies:details.personalDraftMessage')}
          </AlertDescription>
        </Alert>
      )}
      {!entity.editable && (
        <Alert className="border-yellow-300 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-950">
          <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
          <AlertDescription className="text-yellow-800 dark:text-yellow-200">
            {t('access-policies:form.contentLocked', { status: t(`access-policies:status.${entity.status}`) })}
          </AlertDescription>
        </Alert>
      )}

      {/* Info panel: identity, lifecycle, ownership, classification */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <CardTitle className="flex items-center text-2xl font-bold">
                <KindIcon className="mr-3 h-7 w-7 shrink-0 text-primary" />
                <span className="truncate">{entity.name}</span>
              </CardTitle>
              <CardDescription className="pt-1">
                {entity.description || t('access-policies:details.noDescription')}
              </CardDescription>
            </div>
            <div className="flex shrink-0 items-end gap-5">
              <div className="flex flex-col items-center gap-1">
                <AccessStatusBadge status={entity.status} />
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{t('common:labels.status')}</span>
              </div>
              {policy && (
                <div className="flex flex-col items-center gap-1">
                  <Badge variant="outline">{t(`access-policies:policyTypes.${policy.policy_type}`)}</Badge>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{t('access-policies:list.type')}</span>
                </div>
              )}
              {policy && (
                <div className="flex flex-col items-center gap-1">
                  <span className="text-sm leading-none">
                    <span className="text-emerald-700 dark:text-emerald-400">{policy.rule_counts.permission}✓</span>{' '}
                    <span className="text-red-700 dark:text-red-400">{policy.rule_counts.prohibition}✗</span>{' '}
                    <span className="text-amber-700 dark:text-amber-400">{policy.rule_counts.obligation}!</span>
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{t('access-policies:list.rules')}</span>
                </div>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-x-6 gap-y-2 md:grid-cols-3">
            <InfoItem label={t('common:labels.version')}>
              <Badge variant="outline" className="text-xs">{entity.version}</Badge>
              {versions.length > 1 && (
                <span className="text-xs text-muted-foreground">{t('access-policies:details.versionsInFamily', { count: versions.length })}</span>
              )}
            </InfoItem>
            <InfoItem label={t('access-policies:form.ownerTeam')}>
              {entity.owner_team_id && teamName ? (
                <span className="cursor-pointer truncate text-xs text-primary hover:underline" onClick={() => navigate(`/teams/${entity.owner_team_id}`)}>
                  {teamName}
                </span>
              ) : (
                <Dash />
              )}
            </InfoItem>
            <InfoItem label={t('access-policies:form.project')}>
              {entity.project_id ? (
                <span className="cursor-pointer truncate text-xs text-primary hover:underline" onClick={() => navigate(`/projects/${entity.project_id}`)}>
                  {projectName || entity.project_id}
                </span>
              ) : (
                <Dash />
              )}
            </InfoItem>
            <InfoItem label={t('access-policies:form.domains')}>
              {entity.domains.length ? <DomainBadgeList domains={entity.domains as any} /> : <Dash />}
            </InfoItem>
            {policy && (
              <InfoItem label={t('access-policies:form.conflict')}>
                <span className="truncate text-xs">{t(`access-policies:conflicts.${policy.conflict}`)}</span>
              </InfoItem>
            )}
            {policy && (
              <InfoItem label={t('access-policies:form.inheritFrom')}>
                {policy.inherit_from.length ? (
                  <span className="truncate text-xs">{policy.inherit_from.map((p) => nameForPolicy(p)).join(', ')}</span>
                ) : (
                  <Dash />
                )}
              </InfoItem>
            )}
            <InfoItem label={t('access-policies:details.created')}>
              <span className="truncate text-xs text-muted-foreground">
                {entity.created_at ? new Date(entity.created_at).toLocaleString() : '—'}
                {entity.created_by ? ` · ${entity.created_by}` : ''}
              </span>
            </InfoItem>
            <InfoItem label={t('access-policies:details.updated')}>
              <span className="truncate text-xs text-muted-foreground">
                {entity.updated_at ? new Date(entity.updated_at).toLocaleString() : '—'}
              </span>
            </InfoItem>
            <InfoItem label={t('access-policies:details.iri')}>
              <code className="truncate text-xs" title={entity.uid}>{entity.uid}</code>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                aria-label={t('access-policies:details.copyIri')}
                onClick={() => navigator.clipboard?.writeText(entity.uid)}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </InfoItem>
          </div>
          {entity.change_summary && (
            <div className="text-xs">
              <span className="text-muted-foreground">{t('access-policies:details.changeSummary')}:</span> {entity.change_summary}
            </div>
          )}

          <div className="border-t pt-2">
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="min-w-0 flex-1">
                <Label className="mb-1.5 block text-xs text-muted-foreground">{t('access-policies:form.tags')}:</Label>
                <div className="flex flex-wrap gap-1">
                  {entity.tags.length ? (
                    entity.tags.map((tag, i) => <TagChip key={i} tag={tag} size="sm" />)
                  ) : (
                    <span className="text-xs text-muted-foreground">{t('access-policies:details.noTags')}</span>
                  )}
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <Label className="mb-1.5 block text-xs text-muted-foreground">{t('access-policies:details.linkedConcepts')}:</Label>
                <LinkedConceptChips
                  links={links}
                  onRemove={canWrite ? removeLink : undefined}
                  trailing={
                    canWrite ? (
                      <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => setIriDialogOpen(true)}>
                        {t('common:actions.add')}
                      </Button>
                    ) : undefined
                  }
                />
              </div>
            </div>
          </div>

          <div className="border-t pt-2">
            <OwnershipPanel
              objectType={KIND_ENTITY_TYPE[kind]}
              objectId={entity.id}
              canAssign={canWrite}
              ownerTeamId={entity.owner_team_id || undefined}
              ownerTeamName={teamName}
              className="border-0 bg-transparent shadow-none [&>div]:px-0"
            />
          </div>
        </CardContent>
      </Card>

      {policy && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('access-policies:details.rules')}</CardTitle>
            <CardDescription>{t('access-policies:details.rulesHint')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {RULE_KINDS.flatMap((k) => (policy.rules[k] || []).map((r, i) => renderRule(r, k, i)))}
            {RULE_KINDS.every((k) => !(policy.rules[k] || []).length) && (
              <p className="text-sm text-muted-foreground">{t('access-policies:rules.empty')}</p>
            )}
          </CardContent>
        </Card>
      )}

      {policy && validation && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('access-policies:details.validation')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm" data-testid="policy-validation">
            {validation.issues.length === 0 && (validation.activation_problems || []).length === 0 ? (
              <p className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
                <CheckCircle2 className="h-4 w-4" /> {t('access-policies:details.readyToActivate')}
              </p>
            ) : (
              <>
                {validation.issues.map((i, idx) => (
                  <p key={idx} className={i.severity === 'error' ? 'text-destructive' : 'text-amber-700 dark:text-amber-400'}>
                    <AlertTriangle className="mr-1 inline h-3 w-3" />
                    <code className="text-xs">{i.path || 'policy'}</code> — {i.message}
                  </p>
                ))}
                {(validation.activation_problems || [])
                  .filter((p) => !validation.issues.some((i) => i.message === p))
                  .map((p, idx) => (
                    <p key={`a${idx}`} className="text-amber-700 dark:text-amber-400">
                      <AlertTriangle className="mr-1 inline h-3 w-3" />
                      {p}
                    </p>
                  ))}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {collection && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {kind === 'audience' ? t('access-policies:details.audienceDefinition') : t('access-policies:details.collectionDefinition')}
            </CardTitle>
            <CardDescription>
              {kind === 'audience' ? t('access-policies:details.audienceSemantics') : t('access-policies:details.collectionSemantics')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">
                {kind === 'audience' ? t('access-policies:form.principals') : t('access-policies:form.assets')}
              </div>
              {collection.members.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {collection.members.map((m) => (
                    <Badge key={m} variant="secondary" className="font-mono text-xs">
                      {m}
                    </Badge>
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground">
                  {kind === 'audience' ? t('access-policies:details.allPrincipals') : t('access-policies:details.allAssets')}
                </div>
              )}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">{t('access-policies:form.refinement')}</div>
              {collection.refinement.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {collection.refinement.map((c, i) => (
                    <code key={i} className="rounded bg-muted px-1 text-xs">
                      {describeConstraint(c, operandLabel)}
                    </code>
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground">{t('access-policies:form.none')}</div>
              )}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">{t('access-policies:details.usedBy')}</div>
              {collection.used_by.length ? (
                <ul className="mt-1 space-y-1">
                  {collection.used_by.map((p) => (
                    <li key={p.id} className="flex items-center gap-2">
                      <Link to={`/access-policies/policies/${p.id}`} className="text-primary hover:underline">
                        {p.name}
                      </Link>
                      <span className="text-xs text-muted-foreground">v{p.version}</span>
                      <AccessStatusBadge status={p.status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-muted-foreground">{t('access-policies:details.notUsed')}</div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {policy && <CheckAccessPanel policyId={policy.id} />}

      {policy && jsonld != null && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">{t('access-policies:details.jsonld')}</CardTitle>
              <CardDescription>{t('access-policies:details.jsonldHint')}</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={downloadJsonld}>
              <Download className="mr-1 h-4 w-4" /> {t('access-policies:details.download')}
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs" data-testid="policy-jsonld">
              {JSON.stringify(jsonld, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      <EntityMetadataPanel entityId={entity.id} entityType={KIND_ENTITY_TYPE[kind]} />

      <AccessEntityFormDialog
        kind={kind}
        open={editOpen}
        onOpenChange={setEditOpen}
        entity={entity}
        onSaved={() => load()}
      />

      <Dialog open={!!statusTarget} onOpenChange={(o) => !o && setStatusTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {statusTarget ? t(`access-policies:transitions.${statusTarget}`) : ''}
            </DialogTitle>
            <DialogDescription>
              {statusTarget
                ? t('access-policies:details.statusConfirm', {
                    from: t(`access-policies:status.${entity.status}`),
                    to: t(`access-policies:status.${statusTarget}`),
                  })
                : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="ap-status-comment">{t('access-policies:details.statusComment')}</Label>
            <Textarea id="ap-status-comment" rows={3} value={statusComment} onChange={(e) => setStatusComment(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusTarget(null)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={changeStatus} data-testid="confirm-transition">
              {t('access-policies:details.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={versionOpen} onOpenChange={setVersionOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('access-policies:details.newVersion')}</DialogTitle>
            <DialogDescription>{t('access-policies:details.newVersionHint', { version: entity.version })}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="ap-new-version">{t('common:labels.version')}</Label>
              <Input id="ap-new-version" value={newVersion} onChange={(e) => setNewVersion(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ap-change-summary">{t('access-policies:details.changeSummary')}</Label>
              <Textarea id="ap-change-summary" rows={3} value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setVersionOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={createVersion} disabled={!newVersion.trim()}>
              {t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConceptSelectDialog isOpen={iriDialogOpen} onOpenChange={setIriDialogOpen} onSelect={addIri} />

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('access-policies:details.deleteTitle')}</DialogTitle>
            <DialogDescription>{t('access-policies:details.deleteConfirm', { name: entity.name, version: entity.version })}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button variant="destructive" onClick={doDelete}>
              {t('common:actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
