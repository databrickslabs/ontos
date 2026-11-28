import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, Plus, RefreshCw, Trash2, XCircle } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DetailHeaderSkeleton } from '@/components/common/list-view-skeleton';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { modelImportStatusVariant } from '@/lib/model-import-status';
import type {
  ContractAction,
  ContractGrouping,
  ModelImportOptions,
  ModelImportRunDetail,
  TableDrift,
  UdpTarget,
} from '@/types/model-import';

const POLL_MS = 2000;
const NEW_COLLECTION = '__new__';
const AUTO_DBMS = '__auto__';
const NO_DOMAIN = '__none__';
const DBMS = ['oracle', 'sqlserver', 'teradata', 'db2', 'postgresql', 'mysql', 'snowflake', 'databricks', 'other'];
const GROUPINGS: ContractGrouping[] = ['subject_area', 'schema', 'table', 'model'];
const UDP_TARGETS: UdpTarget[] = ['custom_property', 'tag', 'classification', 'critical_data_element', 'ignore'];

interface Collection { iri: string; label: string; is_editable?: boolean }
interface Domain { id: string; name: string }

const actionVariant = (a: ContractAction): 'default' | 'secondary' | 'outline' =>
  a === 'create' ? 'default' : a === 'unchanged' ? 'outline' : 'secondary';

function driftLines(d: TableDrift, t: TFunction): string[] {
  const out: string[] = [];
  if (d.missing_in_uc.length) out.push(t('uc.missing', { columns: d.missing_in_uc.join(', ') }));
  if (d.extra_in_uc.length) out.push(t('uc.extra', { columns: d.extra_in_uc.join(', ') }));
  d.type_mismatches.forEach((m) => out.push(t('uc.typeMismatch', { column: m.column, modeled: m.modeled, actual: m.actual })));
  d.nullability_mismatches.forEach((m) => out.push(t('uc.nullMismatch', {
    column: m.column, modeled: m.modeled_required ? 'NOT NULL' : 'NULL', actual: m.uc_nullable ? 'NULL' : 'NOT NULL',
  })));
  return out;
}

export default function ModelImportRunView() {
  const { t } = useTranslation(['model-import', 'common']);
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { get, post, patch } = useApi();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [run, setRun] = useState<ModelImportRunDetail | null>(null);
  const [options, setOptions] = useState<ModelImportOptions | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'confirm' | 'cancel' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    const res = await get<ModelImportRunDetail>(`/api/model-import/runs/${runId}`);
    if (res.error || !res.data) {
      setError(res.error || t('run.loadFailed'));
      return;
    }
    setRun(res.data);
    setDynamicTitle(res.data.source_model_name || res.data.source_filename || t('run.title'));
    if (!dirty && res.data.options) setOptions(res.data.options);
  }, [runId, get, t, dirty, setDynamicTitle]);

  useEffect(() => {
    setStaticSegments([{ label: t('history.title'), path: '/model-imports' }]);
    const first = window.setTimeout(load, 0);
    get<Collection[]>('/api/knowledge/collections').then((r) => {
      if (Array.isArray(r.data)) setCollections(r.data.filter((c) => c.is_editable !== false));
    });
    get<Domain[]>('/api/data-domains').then((r) => { if (Array.isArray(r.data)) setDomains(r.data); });
    return () => window.clearTimeout(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Poll while the run executes.
  useEffect(() => {
    if (run?.status === 'running') {
      timer.current = window.setTimeout(load, POLL_MS);
    }
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [run, load]);

  const set = <K extends keyof ModelImportOptions>(key: K, value: ModelImportOptions[K]) => {
    setOptions((o) => (o ? { ...o, [key]: value } : o));
    setDirty(true);
  };

  const preview = run?.preview ?? null;

  const refreshPreview = async () => {
    if (!run || !options) return;
    setBusy('preview');
    setError(null);
    const res = await patch<ModelImportRunDetail>(`/api/model-import/runs/${run.id}`, options);
    setBusy(null);
    if (res.error || !res.data) {
      setError(res.error || t('run.previewFailed'));
      return;
    }
    setRun(res.data);
    if (res.data.options) setOptions(res.data.options);
    setDirty(false);
  };

  const confirm = async () => {
    if (!run?.confirm_token) return;
    setBusy('confirm');
    setError(null);
    const res = await post<ModelImportRunDetail>(`/api/model-import/runs/${run.id}/confirm`, {
      confirm_token: run.confirm_token,
    });
    setBusy(null);
    if (res.error || !res.data) {
      setError(res.error || t('run.confirmFailed'));
      load();
      return;
    }
    setRun(res.data);
    toast({ title: t('run.started') });
  };

  const cancel = async () => {
    if (!run) return;
    setBusy('cancel');
    const res = await post<ModelImportRunDetail>(`/api/model-import/runs/${run.id}/cancel`, {});
    setBusy(null);
    if (res.error || !res.data) {
      setError(res.error || t('run.cancelFailed'));
      return;
    }
    setRun(res.data);
  };

  const owners = useMemo(() => ['*', ...(preview?.model.owners ?? [])], [preview]);

  if (!run) {
    return error ? (
      <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
    ) : <DetailHeaderSkeleton />;
  }

  const editable = run.status === 'previewed' && options !== null;
  const subjectAreas = preview?.model.subject_areas ?? [];
  const collectionValue = options?.collection_iri && collections.some((c) => c.iri === options.collection_iri)
    ? options.collection_iri : NEW_COLLECTION;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <Button variant="ghost" size="sm" className="-ml-2" onClick={() => navigate('/model-imports')}>
            <ArrowLeft className="h-4 w-4 mr-1" />{t('history.title')}
          </Button>
          <h1 className="text-2xl font-semibold">{run.source_model_name || run.source_filename}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant={modelImportStatusVariant(run.status)}>{t(`status.${run.status}`)}</Badge>
            <span>{run.source_filename}</span>
            {run.source_model_version && <span>· {t('run.version', { version: run.source_model_version })}</span>}
            {preview && <span>· {t(`modelType.${preview.model.model_type}`)}</span>}
            {preview?.model.target_dbms && <span>· {preview.model.target_dbms}</span>}
          </div>
        </div>
        <div className="flex gap-2">
          {(run.status === 'previewed' || run.status === 'running') && (
            <Button variant="outline" onClick={cancel} disabled={busy !== null}>
              {busy === 'cancel' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{t('run.cancel')}
            </Button>
          )}
          {run.status === 'previewed' && (
            <Button onClick={confirm} disabled={busy !== null || dirty || !run.confirm_token}
                    title={dirty ? t('run.updateFirst') : undefined}>
              {busy === 'confirm' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{t('run.confirm')}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription className="break-words">{error}</AlertDescription></Alert>
      )}
      {run.status === 'running' && (
        <Alert><Loader2 className="h-4 w-4 animate-spin" /><AlertDescription>{run.progress_message || t('run.running')}</AlertDescription></Alert>
      )}
      {run.status === 'failed' && run.error && (
        <Alert variant="destructive"><XCircle className="h-4 w-4" /><AlertDescription className="break-words">{run.error}</AlertDescription></Alert>
      )}
      {preview?.previous_run_id && run.status === 'previewed' && (
        <Alert><RefreshCw className="h-4 w-4" /><AlertDescription>
          {t('run.reimport')} <Link className="underline" to={`/model-imports/${preview.previous_run_id}`}>{t('run.previousRun')}</Link>
        </AlertDescription></Alert>
      )}

      {run.result && (run.status === 'completed' || run.status === 'cancelled' || run.status === 'failed') && (
        <ResultCard run={run} />
      )}

      {editable && options && (
        <Card>
          <CardHeader>
            <CardTitle>{t('options.title')}</CardTitle>
            <CardDescription>{t('options.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-6">
              <div className="flex items-center gap-2">
                <Switch id="mi-logical" checked={options.import_logical} onCheckedChange={(v) => set('import_logical', v)} />
                <Label htmlFor="mi-logical">{t('options.importLogical')}</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch id="mi-physical" checked={options.import_physical} onCheckedChange={(v) => set('import_physical', v)} />
                <Label htmlFor="mi-physical">{t('options.importPhysical')}</Label>
              </div>
            </div>

            {subjectAreas.length > 0 && (
              <div className="space-y-2">
                <Label>{t('options.subjectAreas')}</Label>
                <p className="text-xs text-muted-foreground">{t('options.subjectAreasHint')}</p>
                <div className="flex flex-wrap gap-4">
                  {subjectAreas.map((sa) => {
                    const checked = options.subject_area_ids.includes(sa.id);
                    return (
                      <label key={sa.id} className="flex items-center gap-2 text-sm">
                        <Checkbox checked={checked} onCheckedChange={(v) => set('subject_area_ids',
                          v ? [...options.subject_area_ids, sa.id] : options.subject_area_ids.filter((i) => i !== sa.id))} />
                        {sa.name} <span className="text-muted-foreground">({sa.entities})</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              {options.import_logical && (
                <div className="space-y-2">
                  <Label>{t('options.collection')}</Label>
                  <Select value={collectionValue} onValueChange={(v) => set('collection_iri', v === NEW_COLLECTION ? null : v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NEW_COLLECTION}>
                        {t('options.newCollection', { name: preview?.logical?.collection_label || preview?.model.name })}
                      </SelectItem>
                      {collections.map((c) => <SelectItem key={c.iri} value={c.iri}>{c.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {options.import_physical && (
                <>
                  <div className="space-y-2">
                    <Label>{t('options.grouping')}</Label>
                    <Select value={options.contract_grouping} onValueChange={(v) => set('contract_grouping', v as ContractGrouping)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {GROUPINGS.map((g) => <SelectItem key={g} value={g}>{t(`grouping.${g}`)}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>{t('options.dbms')}</Label>
                    <Select value={options.dbms ?? AUTO_DBMS} onValueChange={(v) => set('dbms', v === AUTO_DBMS ? null : v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value={AUTO_DBMS}>{t('options.dbmsAuto', { dbms: t(`dbms.${preview?.model.dbms ?? 'other'}`) })}</SelectItem>
                        {DBMS.map((d) => <SelectItem key={d} value={d}>{t(`dbms.${d}`)}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-center gap-2 pt-6">
                    <Switch id="mi-migration" checked={options.migration_mode} onCheckedChange={(v) => set('migration_mode', v)} />
                    <Label htmlFor="mi-migration">{t('options.migrationMode')}</Label>
                  </div>
                </>
              )}
            </div>

            {options.import_physical && (
              <div className="space-y-2">
                <Label>{t('options.catalogMapping')}</Label>
                <p className="text-xs text-muted-foreground">{t('options.catalogMappingHint')}</p>
                {options.catalog_mappings.map((m, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Select value={m.source} onValueChange={(v) => set('catalog_mappings',
                      options.catalog_mappings.map((x, j) => (j === i ? { ...x, source: v } : x)))}>
                      <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {owners.map((o) => <SelectItem key={o} value={o}>{o === '*' ? t('options.anyOwner') : o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <span className="text-muted-foreground">→</span>
                    <Input className="w-72" placeholder="catalog.schema" value={m.target}
                           onChange={(e) => set('catalog_mappings',
                             options.catalog_mappings.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)))} />
                    <Button variant="ghost" size="icon" aria-label={t('common:actions.delete')}
                            onClick={() => set('catalog_mappings', options.catalog_mappings.filter((_, j) => j !== i))}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => set('catalog_mappings',
                  [...options.catalog_mappings, { source: owners.find((o) => !options.catalog_mappings.some((m) => m.source === o)) ?? '*', target: '' }])}>
                  <Plus className="h-4 w-4 mr-1" />{t('options.addMapping')}
                </Button>
              </div>
            )}

            {options.import_physical && (preview?.model.udps.length ?? 0) > 0 && (
              <div className="space-y-2">
                <Label>{t('options.udps')}</Label>
                <div className="grid gap-2 md:grid-cols-2">
                  {preview!.model.udps.map((udp) => {
                    const current = options.udp_mappings.find((m) => m.udp === udp)?.target ?? 'custom_property';
                    return (
                      <div key={udp} className="flex items-center gap-2">
                        <span className="w-48 truncate text-sm" title={udp}>{udp}</span>
                        <Select value={current} onValueChange={(v) => set('udp_mappings', [
                          ...options.udp_mappings.filter((m) => m.udp !== udp), { udp, target: v as UdpTarget },
                        ])}>
                          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {UDP_TARGETS.map((u) => <SelectItem key={u} value={u}>{t(`udpTarget.${u}`)}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex items-center gap-3">
              <Button variant="secondary" onClick={refreshPreview} disabled={!dirty || busy !== null}>
                {busy === 'preview' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                {t('options.updatePreview')}
              </Button>
              {dirty && <span className="text-sm text-muted-foreground">{t('run.updateFirst')}</span>}
            </div>
          </CardContent>
        </Card>
      )}

      {preview && run.status === 'previewed' && (
        <Tabs defaultValue="summary">
          <TabsList>
            <TabsTrigger value="summary">{t('tabs.summary')}</TabsTrigger>
            {preview.logical && <TabsTrigger value="logical">{t('tabs.logical')}</TabsTrigger>}
            {preview.physical && <TabsTrigger value="physical">{t('tabs.physical')}</TabsTrigger>}
            {preview.physical && <TabsTrigger value="uc">{t('tabs.uc')}</TabsTrigger>}
            <TabsTrigger value="warnings">{t('tabs.warnings', { count: preview.warnings.length })}</TabsTrigger>
          </TabsList>

          <TabsContent value="summary">
            <Card><CardContent className="pt-6 grid gap-6 md:grid-cols-3 text-sm">
              <div className="space-y-1">
                <div className="font-medium">{t('summary.model')}</div>
                <div>{t('summary.entities', { count: preview.model.entities })}</div>
                <div>{t('summary.views', { count: preview.model.views })}</div>
                <div>{t('summary.attributes', { count: preview.model.attributes })}</div>
                <div>{t('summary.relationships', { count: preview.model.relationships })}</div>
                <div>{t('summary.domains', { count: preview.model.domains })}</div>
                <div className="text-muted-foreground">{t('summary.inScope', { count: preview.scope.entities })}</div>
              </div>
              {preview.logical && (
                <div className="space-y-1">
                  <div className="font-medium">{t('summary.concepts', { collection: preview.logical.collection_label })}</div>
                  <div>{t('summary.new', { count: preview.logical.summary.new })}</div>
                  <div>{t('summary.modified', { count: preview.logical.summary.modified })}</div>
                  <div>{t('summary.unchanged', { count: preview.logical.summary.unchanged })}</div>
                  <div>{t('summary.deprecated', { count: preview.logical.summary.removed })}</div>
                </div>
              )}
              {preview.physical && (
                <div className="space-y-1">
                  <div className="font-medium">{t('summary.contracts')}</div>
                  {(['create', 'update', 'new_version', 'unchanged'] as ContractAction[]).map((a) => (
                    <div key={a}>{t(`action.${a}`)}: {preview.physical!.counts[a] ?? 0}</div>
                  ))}
                  <div>{t('summary.flagged', { count: preview.physical.counts.removed ?? 0 })}</div>
                  <div className="text-muted-foreground">
                    {t('summary.ucResolved', { resolved: preview.physical.uc.resolved, total: preview.physical.uc.resolved + preview.physical.uc.unresolved })}
                  </div>
                </div>
              )}
            </CardContent></Card>
          </TabsContent>

          {preview.logical && (
            <TabsContent value="logical">
              <Card><CardContent className="pt-6 grid gap-6 md:grid-cols-3 text-sm">
                {(['new', 'modified', 'removed'] as const).map((bucket) => (
                  <div key={bucket} className="space-y-1">
                    <div className="font-medium">{t(`logical.${bucket}`, { count: preview.logical!.summary[bucket] })}</div>
                    <ul className="space-y-0.5 max-h-80 overflow-auto">
                      {preview.logical![bucket].map((c) => <li key={c.iri} title={c.iri}>{c.label}</li>)}
                    </ul>
                  </div>
                ))}
              </CardContent></Card>
            </TabsContent>
          )}

          {preview.physical && (
            <TabsContent value="physical">
              <div className="space-y-3">
                {preview.physical.contracts.map((c) => (
                  <Card key={c.group_key}>
                    <CardHeader className="pb-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <CardTitle className="text-base">{c.name}</CardTitle>
                        <div className="flex items-center gap-2">
                          <Badge variant={actionVariant(c.action)}>{t(`action.${c.action}`)}</Badge>
                          {c.existing_contract_id && (
                            <Link className="text-sm underline" to={`/data-contracts/${c.existing_contract_id}`}>
                              {t('physical.existing', { version: c.existing_version, status: c.existing_status })}
                            </Link>
                          )}
                        </div>
                      </div>
                      <CardDescription>{t('physical.tables', { count: c.table_count })}: {c.tables.join(', ')}</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3 text-sm">
                      {editable && options && c.action === 'create' && domains.length > 0 && (
                        <div className="flex items-center gap-2">
                          <Label className="w-24">{t('physical.domain')}</Label>
                          <Select value={options.domain_by_group[c.group_key] ?? NO_DOMAIN} onValueChange={(v) => {
                            const next = { ...options.domain_by_group };
                            if (v === NO_DOMAIN) delete next[c.group_key]; else next[c.group_key] = v;
                            set('domain_by_group', next);
                          }}>
                            <SelectTrigger className="w-72"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value={NO_DOMAIN}>{t('physical.noDomain')}</SelectItem>
                              {domains.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </div>
                      )}
                      {c.diff && (
                        <div className="space-y-1">
                          {c.diff.tables_added.length > 0 && <div>{t('physical.tablesAdded', { tables: c.diff.tables_added.join(', ') })}</div>}
                          {c.diff.tables_removed.length > 0 && <div>{t('physical.tablesRemoved', { tables: c.diff.tables_removed.join(', ') })}</div>}
                          {c.diff.tables_changed.map((tc) => (
                            <div key={tc.table}>
                              <span className="font-medium">{tc.table}</span>:{' '}
                              {[
                                ...tc.fields.map((f) => t(`field.${f}`, { defaultValue: f })),
                                ...tc.columns_added.map((col) => t('physical.columnAdded', { column: col })),
                                ...tc.columns_removed.map((col) => t('physical.columnRemoved', { column: col })),
                                ...tc.columns_changed.map((cc) => t('physical.columnChanged', {
                                  column: cc.column, fields: cc.fields.map((f) => t(`field.${f}`, { defaultValue: f })).join(', '),
                                })),
                              ].join('; ')}
                            </div>
                          ))}
                        </div>
                      )}
                      {c.warnings.map((w, i) => <div key={i} className="text-amber-600 dark:text-amber-400">{w}</div>)}
                    </CardContent>
                  </Card>
                ))}
                {preview.physical.removed.length > 0 && (
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      {t('physical.removedIntro')}{' '}
                      {preview.physical.removed.map((r, i) => (
                        <span key={r.contract_id}>{i > 0 && ', '}<Link className="underline" to={`/data-contracts/${r.contract_id}`}>{r.name}</Link></span>
                      ))}
                    </AlertDescription>
                  </Alert>
                )}
              </div>
            </TabsContent>
          )}

          {preview.physical && (
            <TabsContent value="uc">
              <Card><CardContent className="pt-6">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left border-b">
                        <th className="py-2 pr-4">{t('uc.table')}</th>
                        <th className="py-2 pr-4">{t('uc.owner')}</th>
                        <th className="py-2 pr-4">{t('uc.fqn')}</th>
                        <th className="py-2">{t('uc.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.physical.uc.tables.map((r) => (
                        <tr key={r.entity_id} className="border-b align-top">
                          <td className="py-2 pr-4 font-mono">{r.table}</td>
                          <td className="py-2 pr-4">{r.owner}</td>
                          <td className="py-2 pr-4">
                            {editable && options ? (
                              <Input className="h-8 w-full min-w-[12rem] max-w-xs font-mono text-xs" placeholder={r.fqn ?? 'catalog.schema.table'}
                                     value={options.table_overrides[r.entity_id] ?? ''}
                                     onChange={(e) => {
                                       const next = { ...options.table_overrides };
                                       if (e.target.value.trim()) next[r.entity_id] = e.target.value.trim(); else delete next[r.entity_id];
                                       set('table_overrides', next);
                                     }} />
                            ) : <span className="font-mono">{r.fqn}</span>}
                          </td>
                          <td className="py-2">
                            {r.asset_id ? (
                              <div className="space-y-1">
                                <Link to={`/assets/${r.asset_id}`} className="inline-flex items-center gap-1 underline">
                                  <CheckCircle2 className="h-4 w-4 text-green-600" />{t('uc.resolved')}
                                </Link>
                                {r.drift && driftLines(r.drift, t).map((l, i) => (
                                  <div key={i} className="text-amber-600 dark:text-amber-400">{l}</div>
                                ))}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">{r.fqn ? t('uc.notFound') : t('uc.noMapping')}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {t('uc.hint')} <Link className="underline" to="/schema-importer">{t('uc.schemaImporter')}</Link>
                </p>
              </CardContent></Card>
            </TabsContent>
          )}

          <TabsContent value="warnings">
            <Card><CardContent className="pt-6 text-sm">
              {preview.warnings.length === 0 ? (
                <span className="text-muted-foreground">{t('warnings.none')}</span>
              ) : (
                <ul className="list-disc pl-5 space-y-1">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              )}
            </CardContent></Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function ResultCard({ run }: { run: ModelImportRunDetail }) {
  const { t } = useTranslation('model-import');
  const r = run.result!;
  return (
    <Card>
      <CardHeader><CardTitle>{t('result.title')}</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        {r.logical && (
          <div className="space-y-1">
            <div className="font-medium">{t('result.concepts')}</div>
            <div>
              {t('summary.new', { count: r.logical.summary.new })} · {t('summary.modified', { count: r.logical.summary.modified })} ·{' '}
              {t('summary.unchanged', { count: r.logical.summary.unchanged })} · {t('summary.deprecated', { count: r.logical.summary.removed })}
            </div>
            <Link className="underline" to="/concepts/collections">{t('result.openCollection')}</Link>
          </div>
        )}
        {r.physical && (
          <div className="space-y-1">
            <div className="font-medium">{t('result.contracts')}</div>
            <ul className="space-y-1">
              {r.physical.contracts.map((c) => (
                <li key={c.group_key} className="flex flex-wrap items-center gap-2">
                  {c.status === 'ok' ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <XCircle className="h-4 w-4 text-destructive" />}
                  {c.contract_id ? <Link className="underline" to={`/data-contracts/${c.contract_id}`}>{c.name}</Link> : c.name}
                  <Badge variant={actionVariant(c.action)}>{t(`action.${c.action}`)}</Badge>
                  {c.error && <span className="text-destructive break-words">{c.error}</span>}
                </li>
              ))}
            </ul>
            {r.physical.removed.length > 0 && (
              <div>{t('result.flagged', { names: r.physical.removed.map((c) => c.name).join(', ') })}</div>
            )}
            <div className="text-muted-foreground">
              {t('summary.ucResolved', { resolved: r.physical.uc.resolved, total: r.physical.uc.resolved + r.physical.uc.unresolved })}
              {r.physical.uc.drift.length > 0 && ` · ${t('result.drift', { count: r.physical.uc.drift.length })}`}
            </div>
          </div>
        )}
        {r.warnings.length > 0 && (
          <ul className="list-disc pl-5 space-y-1 text-muted-foreground">{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        )}
      </CardContent>
    </Card>
  );
}
