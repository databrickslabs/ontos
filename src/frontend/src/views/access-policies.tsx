import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { FileDown, FileUp, Plus, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import DomainBadgeList from '@/components/ui/domain-badge-list';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import AccessEntityFormDialog from '@/components/access-policies/access-entity-form-dialog';
import AccessStatusBadge from '@/components/access-policies/access-status-badge';
import CheckAccessPanel from '@/components/access-policies/check-access-panel';
import GrantLedgerPanel from '@/components/access-policies/grant-ledger-panel';
import ReleasesPanel from '@/components/access-policies/releases-panel';
import type { AccessCollection, AccessEntity, AccessKind, AccessPolicy, AccessTarget } from '@/types/access-policy';
import { KIND_SEGMENT } from '@/types/access-policy';

const FEATURE_ID = 'access-policies';
const TABS = ['policies', 'audiences', 'asset-collections', 'check', 'releases', 'ledger', 'targets'] as const;
type Tab = (typeof TABS)[number];

export default function AccessPolicies() {
  const { t } = useTranslation(['access-policies', 'common']);
  const navigate = useNavigate();
  const { get, post } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const canAdmin = hasPermission(FEATURE_ID, FeatureAccessLevel.ADMIN);
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get('tab') || '') ? (params.get('tab') as Tab) : 'policies';

  const [policies, setPolicies] = useState<AccessPolicy[]>([]);
  const [audiences, setAudiences] = useState<AccessCollection[]>([]);
  const [collections, setCollections] = useState<AccessCollection[]>([]);
  const [targets, setTargets] = useState<AccessTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [createKind, setCreateKind] = useState<AccessKind | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('access-policies:title'));
    return () => setDynamicTitle(null);
  }, [setStaticSegments, setDynamicTitle, t]);

  const load = useCallback(async () => {
    setLoading(true);
    const [p, a, c, tg] = await Promise.all([
      get<AccessPolicy[]>('/api/access-policies/policies'),
      get<AccessCollection[]>('/api/access-policies/audiences'),
      get<AccessCollection[]>('/api/access-policies/asset-collections'),
      get<AccessTarget[]>('/api/access-policies/targets'),
    ]);
    setPolicies(Array.isArray(p.data) ? p.data : []);
    setAudiences(Array.isArray(a.data) ? a.data : []);
    setCollections(Array.isArray(c.data) ? c.data : []);
    setTargets(Array.isArray(tg.data) ? tg.data : []);
    setLoading(false);
  }, [get]);

  useEffect(() => {
    load();
  }, [load]);

  const commonColumns = useCallback(
    <T extends AccessEntity>(): ColumnDef<T>[] => [
      {
        accessorKey: 'name',
        header: t('common:labels.name'),
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            {row.original.description && (
              <div className="line-clamp-1 text-xs text-muted-foreground">{row.original.description}</div>
            )}
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: t('common:labels.status'),
        cell: ({ row }) => <AccessStatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'version',
        header: t('common:labels.version'),
        cell: ({ row }) => (
          <span className="flex items-center gap-1 text-sm">
            {row.original.version}
            {(row.original.version_count || 1) > 1 && (
              <Badge variant="secondary" className="text-[10px]" title={t('access-policies:list.versionsTitle')}>
                {row.original.version_count}
              </Badge>
            )}
            {row.original.draft_owner_id && (
              <Badge variant="outline" className="text-[10px]">
                {t('access-policies:list.personalDraft')}
              </Badge>
            )}
          </span>
        ),
      },
      {
        id: 'domains',
        header: t('access-policies:list.domains'),
        cell: ({ row }) => <DomainBadgeList domains={row.original.domains as any} />,
      },
    ],
    [t],
  );

  const policyColumns = useMemo<ColumnDef<AccessPolicy>[]>(
    () => [
      ...commonColumns<AccessPolicy>().slice(0, 3),
      {
        accessorKey: 'policy_type',
        header: t('access-policies:list.type'),
        cell: ({ row }) => <Badge variant="outline">{t(`access-policies:policyTypes.${row.original.policy_type}`)}</Badge>,
      },
      {
        id: 'rules',
        header: t('access-policies:list.rules'),
        cell: ({ row }) => {
          const c = row.original.rule_counts;
          return (
            <span className="text-xs text-muted-foreground">
              <span className="text-emerald-700 dark:text-emerald-400">{c.permission}✓</span>{' '}
              <span className="text-red-700 dark:text-red-400">{c.prohibition}✗</span>{' '}
              <span className="text-amber-700 dark:text-amber-400">{c.obligation}!</span>
            </span>
          );
        },
      },
      commonColumns<AccessPolicy>()[3],
    ],
    [commonColumns, t],
  );

  const collectionColumns = useMemo<ColumnDef<AccessCollection>[]>(
    () => [
      ...commonColumns<AccessCollection>().slice(0, 3),
      {
        id: 'membership',
        header: t('access-policies:list.membership'),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {t('access-policies:list.membershipSummary', {
              members: row.original.members.length,
              refinements: row.original.refinement.length,
            })}
          </span>
        ),
      },
      {
        id: 'used_by',
        header: t('access-policies:list.usedBy'),
        cell: ({ row }) => <span className="text-xs">{row.original.used_by.length}</span>,
      },
      commonColumns<AccessCollection>()[3],
    ],
    [commonColumns, t],
  );

  const targetColumns = useMemo<ColumnDef<AccessTarget>[]>(
    () => [
      ...commonColumns<AccessTarget>().slice(0, 3),
      {
        accessorKey: 'key',
        header: t('access-policies:targets.key'),
        cell: ({ row }) => <code className="text-xs">{row.original.key}</code>,
      },
      {
        accessorKey: 'system',
        header: t('access-policies:targets.system'),
        cell: ({ row }) => <Badge variant="outline">{row.original.system_label}</Badge>,
      },
      {
        id: 'scope',
        header: t('access-policies:targets.scope'),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {row.original.scope.length ? row.original.scope.join(', ') : t('access-policies:targets.scopeAll')}
          </span>
        ),
      },
      {
        accessorKey: 'tracked_grants',
        header: t('access-policies:targets.tracked'),
        cell: ({ row }) => <span className="text-xs">{row.original.tracked_grants}</span>,
      },
    ],
    [commonColumns, t],
  );

  const openDetail = (kind: AccessKind, id: string) => navigate(`/access-policies/${KIND_SEGMENT[kind]}/${id}`);

  const doImport = async () => {
    let doc: unknown;
    try {
      doc = JSON.parse(importText);
    } catch (e: any) {
      toast({ title: t('access-policies:import.invalidJson'), description: e.message, variant: 'destructive' });
      return;
    }
    const res = await post<AccessPolicy>('/api/access-policies/policies/import', { document: doc });
    if (res.error || !res.data) {
      toast({ title: t('access-policies:import.failed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    toast({ title: t('access-policies:import.done') });
    setImportOpen(false);
    setImportText('');
    openDetail('policy', res.data.id);
  };

  // Targets decide where grants get pushed: admin only (mirrors the API).
  const newButton = (kind: AccessKind) =>
    (kind === 'target' ? canAdmin : canWrite) ? (
      <Button size="sm" onClick={() => setCreateKind(kind)}>
        <Plus className="mr-1 h-4 w-4" /> {t(`access-policies:list.new.${kind}`)}
      </Button>
    ) : null;

  return (
    <div className="space-y-6 py-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <ShieldCheck className="h-8 w-8" /> {t('access-policies:title')}
          </h1>
          <p className="mt-1 max-w-3xl text-muted-foreground">{t('access-policies:subtitle')}</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v })}>
        <TabsList>
          <TabsTrigger value="policies">
            {t('access-policies:tabs.policies')} ({policies.length})
          </TabsTrigger>
          <TabsTrigger value="audiences">
            {t('access-policies:tabs.audiences')} ({audiences.length})
          </TabsTrigger>
          <TabsTrigger value="asset-collections">
            {t('access-policies:tabs.assetCollections')} ({collections.length})
          </TabsTrigger>
          <TabsTrigger value="check">{t('access-policies:tabs.check')}</TabsTrigger>
          <TabsTrigger value="releases">{t('access-policies:tabs.releases')}</TabsTrigger>
          <TabsTrigger value="ledger">{t('access-policies:tabs.ledger')}</TabsTrigger>
          <TabsTrigger value="targets">
            {t('access-policies:tabs.targets')} ({targets.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="policies" className="pt-4">
          <DataTable
            columns={policyColumns}
            data={policies}
            searchColumn="name"
            isLoading={loading}
            storageKey="access-policies-list"
            onRowClick={(row) => openDetail('policy', row.original.id)}
            toolbarActions={
              <div className="flex gap-2">
                <Button size="sm" variant="outline" asChild>
                  <a href="/api/access-policies/profile/shacl" download="ontos-odrl-shapes.ttl" title={t('access-policies:list.shaclHint')}>
                    <FileDown className="mr-1 h-4 w-4" /> {t('access-policies:list.shacl')}
                  </a>
                </Button>
                {canWrite && (
                  <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}>
                    <FileUp className="mr-1 h-4 w-4" /> {t('access-policies:list.import')}
                  </Button>
                )}
                {newButton('policy')}
              </div>
            }
          />
        </TabsContent>
        <TabsContent value="audiences" className="pt-4">
          <p className="mb-3 text-sm text-muted-foreground">{t('access-policies:list.audiencesHint')}</p>
          <DataTable
            columns={collectionColumns}
            data={audiences}
            searchColumn="name"
            isLoading={loading}
            storageKey="access-audiences-list"
            onRowClick={(row) => openDetail('audience', row.original.id)}
            toolbarActions={newButton('audience')}
          />
        </TabsContent>
        <TabsContent value="asset-collections" className="pt-4">
          <p className="mb-3 text-sm text-muted-foreground">{t('access-policies:list.collectionsHint')}</p>
          <DataTable
            columns={collectionColumns}
            data={collections}
            searchColumn="name"
            isLoading={loading}
            storageKey="access-asset-collections-list"
            onRowClick={(row) => openDetail('asset_collection', row.original.id)}
            toolbarActions={newButton('asset_collection')}
          />
        </TabsContent>
        <TabsContent value="check" className="pt-4">
          <CheckAccessPanel />
        </TabsContent>
        <TabsContent value="releases" className="pt-4">
          <ReleasesPanel canWrite={canWrite} />
        </TabsContent>
        <TabsContent value="ledger" className="pt-4">
          <GrantLedgerPanel canAdmin={canAdmin} />
        </TabsContent>
        <TabsContent value="targets" className="pt-4">
          <p className="mb-3 text-sm text-muted-foreground">{t('access-policies:targets.hint')}</p>
          <DataTable
            columns={targetColumns}
            data={targets}
            searchColumn="name"
            isLoading={loading}
            storageKey="access-targets-list"
            onRowClick={(row) => openDetail('target', row.original.id)}
            toolbarActions={newButton('target')}
          />
        </TabsContent>
      </Tabs>

      {createKind && (
        <AccessEntityFormDialog
          kind={createKind}
          open={!!createKind}
          onOpenChange={(o) => !o && setCreateKind(null)}
          onSaved={(e) => openDetail(e.kind, e.id)}
        />
      )}

      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('access-policies:import.title')}</DialogTitle>
            <DialogDescription>{t('access-policies:import.description')}</DialogDescription>
          </DialogHeader>
          <Textarea
            className="min-h-[300px] font-mono text-xs"
            value={importText}
            aria-label={t('access-policies:import.title')}
            placeholder={'{\n  "@context": "http://www.w3.org/ns/odrl.jsonld",\n  "@type": "Set",\n  "uid": "http://example.com/policy:1",\n  "permission": [{ "target": "uc:main.sales", "action": "read" }]\n}'}
            onChange={(e) => setImportText(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={doImport} disabled={!importText.trim()}>
              {t('access-policies:import.submit')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
