import { useState, useEffect, useCallback } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Loader2,
  Eye,
  Play,
  CheckCircle2,
  AlertTriangle,
  Plus,
  Link2,
  Ban,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { DataDomain } from '@/types/data-domain';
import type {
  SyncDirection,
  DomainSyncPreview,
  DomainSyncResult,
  DomainSyncNode,
  SyncAction,
} from '@/types/domain-sync';

const TOP_LEVEL = '__top__';

const actionMeta: Record<SyncAction, { className: string; icon: JSX.Element }> = {
  create: { className: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300', icon: <Plus className="h-3 w-3" /> },
  match: { className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300', icon: <Link2 className="h-3 w-3" /> },
  skip: { className: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300', icon: <Ban className="h-3 w-3" /> },
  error: { className: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300', icon: <AlertTriangle className="h-3 w-3" /> },
};

/**
 * The toast text after a sync: one whole sentence with every count, errors
 * only when there were any. Pure.
 */
export function syncSummaryText(
  result: Pick<DomainSyncResult, 'created' | 'matched' | 'skipped' | 'errors'>,
  t: TFunction,
): string {
  const counts = {
    created: result.created, matched: result.matched, skipped: result.skipped, errors: result.errors,
  };
  return result.errors
    ? t('data-domains:sync.summaryWithErrors', counts)
    : t('data-domains:sync.summary', counts);
}

function NodeRow({ node }: { node: DomainSyncNode }) {
  const { t } = useTranslation('data-domains');
  const meta = actionMeta[node.action];
  const indent = Math.max(0, node.level - 1) * 20;
  return (
    <div className="flex items-center gap-2 py-1.5 border-b last:border-0 text-sm">
      <div style={{ paddingLeft: indent }} className="flex-1 flex items-center gap-2 min-w-0">
        <span className="truncate font-medium">{node.name}</span>
        <span className="text-xs text-muted-foreground shrink-0">{t('sync.level', { level: node.level })}</span>
        {node.reason && (
          <span className="text-xs text-muted-foreground truncate">— {node.reason}</span>
        )}
      </div>
      <Badge variant="outline" className={`gap-1 border-0 ${meta.className}`}>
        {meta.icon}
        {t(`sync.actionLabels.${node.action}`)}
      </Badge>
    </div>
  );
}

export default function SyncDomainsView() {
  const { t } = useTranslation(['data-domains', 'common']);
  const { get: apiGet, post: apiPost } = useApi();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [direction, setDirection] = useState<SyncDirection>('import_from_uc');
  const [domains, setDomains] = useState<DataDomain[]>([]);
  const [targetId, setTargetId] = useState<string>(TOP_LEVEL); // import root / export anchor
  const [preview, setPreview] = useState<DomainSyncPreview | null>(null);
  const [result, setResult] = useState<DomainSyncResult | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('data-domains:sync.title'));
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle, t]);

  const fetchDomains = useCallback(async () => {
    try {
      const resp = await apiGet<DataDomain[]>('/api/data-domains?limit=1000');
      if (resp.data) setDomains(resp.data);
    } catch (err) {
      console.error('Failed to fetch domains:', err);
    }
  }, [apiGet]);

  useEffect(() => {
    fetchDomains();
  }, [fetchDomains]);

  // Reset the plan whenever the direction or anchor changes — it no longer applies.
  const resetPlan = () => {
    setPreview(null);
    setResult(null);
  };

  const isImport = direction === 'import_from_uc';
  const selectedId = targetId === TOP_LEVEL ? null : targetId;

  const runPreview = async () => {
    setIsPreviewing(true);
    setResult(null);
    try {
      const url = isImport ? '/api/domain-sync/import/preview' : '/api/domain-sync/export/preview';
      const body = isImport ? { target_root_id: selectedId } : { anchor_domain_id: selectedId };
      const resp = await apiPost<DomainSyncPreview>(url, body);
      if (resp.error) {
        toast({ title: t('data-domains:sync.toasts.previewFailed'), description: resp.error, variant: 'destructive' });
      } else if (resp.data) {
        setPreview(resp.data);
      }
    } catch (err) {
      toast({ title: t('data-domains:sync.toasts.previewFailed'), description: String(err), variant: 'destructive' });
    } finally {
      setIsPreviewing(false);
    }
  };

  const runApply = async () => {
    setIsApplying(true);
    try {
      const url = isImport ? '/api/domain-sync/import/execute' : '/api/domain-sync/export/execute';
      const body = isImport ? { target_root_id: selectedId } : { anchor_domain_id: selectedId };
      const resp = await apiPost<DomainSyncResult>(url, body);
      if (resp.error) {
        toast({ title: t('data-domains:sync.toasts.syncFailed'), description: resp.error, variant: 'destructive' });
      } else if (resp.data) {
        setResult(resp.data);
        setPreview(null);
        toast({
          title: t('data-domains:sync.toasts.syncComplete'),
          description: syncSummaryText(resp.data, t),
        });
        fetchDomains();
      }
    } catch (err) {
      toast({ title: t('data-domains:sync.toasts.syncFailed'), description: String(err), variant: 'destructive' });
    } finally {
      setIsApplying(false);
    }
  };

  const nothingToDo = preview && preview.to_create === 0 && preview.to_match === 0 && preview.to_skip === 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <RefreshCw className="h-6 w-6" />
          {t('data-domains:sync.title')}
        </h2>
        <p className="text-muted-foreground">{t('data-domains:sync.description')}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        {/* Left: options */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">{t('data-domains:sync.direction.title')}</CardTitle>
              <CardDescription className="text-xs">{t('data-domains:sync.direction.description')}</CardDescription>
            </CardHeader>
            <CardContent>
              <RadioGroup
                value={direction}
                onValueChange={(v) => {
                  setDirection(v as SyncDirection);
                  setTargetId(TOP_LEVEL);
                  resetPlan();
                }}
                className="space-y-2"
              >
                <div className="flex items-start gap-2">
                  <RadioGroupItem value="import_from_uc" id="dir-import" />
                  <Label htmlFor="dir-import" className="text-sm font-normal leading-tight cursor-pointer">
                    <span className="font-medium flex items-center gap-1">
                      <ArrowDownToLine className="h-3.5 w-3.5" /> {t('data-domains:sync.direction.importLabel')}
                    </span>
                    <span className="text-xs text-muted-foreground">{t('data-domains:sync.direction.importHint')}</span>
                  </Label>
                </div>
                <div className="flex items-start gap-2">
                  <RadioGroupItem value="export_to_uc" id="dir-export" />
                  <Label htmlFor="dir-export" className="text-sm font-normal leading-tight cursor-pointer">
                    <span className="font-medium flex items-center gap-1">
                      <ArrowUpFromLine className="h-3.5 w-3.5" /> {t('data-domains:sync.direction.exportLabel')}
                    </span>
                    <span className="text-xs text-muted-foreground">{t('data-domains:sync.direction.exportHint')}</span>
                  </Label>
                </div>
              </RadioGroup>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">
                {isImport ? t('data-domains:sync.target.importTitle') : t('data-domains:sync.target.exportTitle')}
              </CardTitle>
              <CardDescription className="text-xs">
                {isImport
                  ? t('data-domains:sync.target.importHint')
                  : t('data-domains:sync.target.exportHint')}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Select
                value={targetId}
                onValueChange={(v) => {
                  setTargetId(v);
                  resetPlan();
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={TOP_LEVEL}>
                    {isImport ? t('data-domains:sync.target.importTopLevel') : t('data-domains:sync.target.exportTopLevel')}
                  </SelectItem>
                  {domains.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>

          <div className="flex flex-col gap-2">
            <Button onClick={runPreview} disabled={isPreviewing || isApplying} variant="outline" className="w-full">
              {isPreviewing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Eye className="mr-2 h-4 w-4" />}
              {t('data-domains:sync.actions.preview')}
            </Button>
            <Button
              onClick={runApply}
              disabled={!preview || !!nothingToDo || isApplying || isPreviewing}
              className="w-full"
            >
              {isApplying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              {t('data-domains:sync.actions.apply')}
            </Button>
          </div>
        </div>

        {/* Right: preview / result */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              {result ? t('data-domains:sync.panel.resultTitle') : t('data-domains:sync.panel.previewTitle')}
            </CardTitle>
            <CardDescription className="text-xs">
              {isImport ? t('data-domains:sync.panel.importFlow') : t('data-domains:sync.panel.exportFlow')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!preview && !result && (
              <p className="text-sm text-muted-foreground py-8 text-center">
                <Trans
                  t={t}
                  i18nKey="data-domains:sync.emptyHint"
                  components={{ b: <span className="font-medium" /> }}
                />
              </p>
            )}

            {preview && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{t('data-domains:sync.plan.toCreate', { count: preview.to_create })}</Badge>
                  <Badge variant="secondary">{t('data-domains:sync.plan.toMatch', { count: preview.to_match })}</Badge>
                  {preview.to_skip > 0 && (
                    <Badge variant="secondary">{t('data-domains:sync.plan.toSkip', { count: preview.to_skip })}</Badge>
                  )}
                </div>
                {preview.warnings.length > 0 && (
                  <Alert>
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle className="text-sm">{t('data-domains:sync.warnings')}</AlertTitle>
                    <AlertDescription className="text-xs">
                      <ul className="list-disc pl-4">
                        {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
                      </ul>
                    </AlertDescription>
                  </Alert>
                )}
                {nothingToDo ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">{t('data-domains:sync.nothingToSync')}</p>
                ) : (
                  <div className="rounded-md border px-3">
                    {preview.nodes.map((n, i) => <NodeRow key={`${n.name}-${i}`} node={n} />)}
                  </div>
                )}
              </div>
            )}

            {result && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className="gap-1 border-0 bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">
                    <CheckCircle2 className="h-3 w-3" /> {t('data-domains:sync.result.created', { count: result.created })}
                  </Badge>
                  <Badge variant="outline" className="gap-1 border-0 bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
                    <Link2 className="h-3 w-3" /> {t('data-domains:sync.result.matched', { count: result.matched })}
                  </Badge>
                  {result.skipped > 0 && (
                    <Badge variant="outline" className="gap-1 border-0 bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                      <Ban className="h-3 w-3" /> {t('data-domains:sync.result.skipped', { count: result.skipped })}
                    </Badge>
                  )}
                  {result.errors > 0 && (
                    <Badge variant="outline" className="gap-1 border-0 bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">
                      <AlertTriangle className="h-3 w-3" /> {t('data-domains:sync.result.errors', { count: result.errors })}
                    </Badge>
                  )}
                </div>
                {result.error_messages.length > 0 && (
                  <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle className="text-sm">{t('data-domains:sync.errorsTitle')}</AlertTitle>
                    <AlertDescription className="text-xs">
                      <ul className="list-disc pl-4">
                        {result.error_messages.map((m, i) => <li key={i}>{m}</li>)}
                      </ul>
                    </AlertDescription>
                  </Alert>
                )}
                <div className="rounded-md border px-3">
                  {result.nodes.map((n, i) => <NodeRow key={`${n.name}-${i}`} node={n} />)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
