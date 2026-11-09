import React from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/table';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { Loader2, Plus, RefreshCcw, Trash2, Pencil } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import type {
  EntityKind,
  QualityItem,
  QualityItemCreate,
  QualitySummary,
  QualityDimension,
  QualitySource,
} from '@/types/quality';
import {
  QUALITY_DIMENSIONS,
  QUALITY_SOURCES,
  dimensionColors,
  scoreColor,
} from '@/types/quality';

type Props = {
  entityId: string;
  entityType: EntityKind;
  /** If set, uses the product aggregation endpoint instead of the per-entity one. */
  productAggregation?: boolean;
};

function fmtDate(iso: string) {
  try { return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
}

const EntityQualityPanel: React.FC<Props> = ({ entityId, entityType, productAggregation }) => {
  const { t } = useTranslation(['metadata', 'common']);
  const [items, setItems] = React.useState<QualityItem[]>([]);
  const [summary, setSummary] = React.useState<QualitySummary | null>(null);
  const [loading, setLoading] = React.useState(true);

  const [showForm, setShowForm] = React.useState(false);
  const [editing, setEditing] = React.useState<QualityItem | null>(null);
  const [form, setForm] = React.useState<Partial<QualityItemCreate>>({
    entity_id: entityId,
    entity_type: entityType,
    dimension: 'completeness',
    source: 'manual',
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { toast } = useToast();

  const fetchData = React.useCallback(async () => {
    setLoading(true);
    try {
      const listP = fetch(`/api/entities/${entityType}/${entityId}/quality-items?limit=50`).then(r => r.json());
      const sumUrl = productAggregation
        ? `/api/data-products/${entityId}/quality-summary`
        : `/api/entities/${entityType}/${entityId}/quality-items/summary`;
      const sumP = fetch(sumUrl).then(r => r.json());
      const [list, sum] = await Promise.all([listP, sumP]);
      setItems(Array.isArray(list) ? list : []);
      setSummary(sum || null);
    } catch (e: any) {
      toast({ title: t('metadata:quality.messages.loadFailed'), description: e?.message || String(e), variant: 'destructive' });
    } finally { setLoading(false); }
  }, [entityId, entityType, productAggregation, toast]);

  React.useEffect(() => { fetchData(); }, [fetchData]);

  const overallPct = summary?.overall_score_percent ?? 0;
  const byDim = summary?.by_dimension || {};

  // Circular gauge via conic-gradient (score portion colored, rest grey)
  const gaugeStyle: React.CSSProperties = {
    width: 64, height: 64, borderRadius: '50%',
    background: `conic-gradient(${scoreColor(overallPct)} 0% ${overallPct}%, #e5e7eb ${overallPct}% 100%)`,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  };

  const resetForm = () => {
    setEditing(null);
    setErrors({});
    setForm({
      entity_id: entityId,
      entity_type: entityType,
      dimension: 'completeness',
      source: 'manual',
    });
  };

  const openCreate = () => { resetForm(); setShowForm(true); };
  const openEdit = (it: QualityItem) => {
    setEditing(it);
    setErrors({});
    setForm({
      entity_id: entityId,
      entity_type: entityType,
      title: it.title ?? undefined,
      description: it.description ?? undefined,
      dimension: it.dimension,
      source: it.source,
      score_percent: it.score_percent,
      checks_passed: it.checks_passed ?? undefined,
      checks_total: it.checks_total ?? undefined,
      measured_at: it.measured_at,
    });
    setShowForm(true);
  };

  const validate = (payload: Partial<QualityItemCreate>) => {
    const errs: Record<string, string> = {};
    if (!payload.dimension) errs.dimension = t('metadata:quality.validation.required');
    if (payload.score_percent == null || Number.isNaN(payload.score_percent)) errs.score_percent = t('metadata:quality.validation.required');
    else if (payload.score_percent < 0 || payload.score_percent > 100) errs.score_percent = t('metadata:quality.validation.range');
    return errs;
  };

  const submit = async () => {
    const payload = { ...form } as QualityItemCreate;
    const errs = validate(payload);
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      toast({ title: t('metadata:quality.messages.missingFields'), variant: 'destructive' });
      return;
    }

    try {
      if (editing) {
        const resp = await fetch(`/api/quality-items/${editing.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(await resp.text());
      } else {
        const resp = await fetch(`/api/entities/${entityType}/${entityId}/quality-items`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(await resp.text());
      }
      toast({ title: editing ? t('metadata:quality.messages.updated') : t('metadata:quality.messages.added') });
      setShowForm(false); resetForm(); fetchData();
    } catch (e: any) {
      toast({ title: t('metadata:quality.messages.saveFailed'), description: e?.message || String(e), variant: 'destructive' });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl flex items-center gap-2">{t('metadata:quality.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button size="icon" variant="ghost" onClick={fetchData}><RefreshCcw className="h-4 w-4" /></Button>
            {summary?.measured_at && (
              <span className="text-xs text-muted-foreground">{t('metadata:quality.lastMeasured', { date: fmtDate(summary.measured_at) })}</span>
            )}
          </div>
          <div className="flex items-center gap-4">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div style={gaugeStyle} aria-label={t('metadata:quality.gaugeAria')} className="border border-border">
                    <div className="bg-background rounded-full w-10 h-10 flex items-center justify-center text-xs font-bold"
                      style={{ color: scoreColor(overallPct) }}>
                      {overallPct.toFixed(0)}%
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="space-y-1">
                  <div className="text-xs font-medium mb-1">{t('metadata:quality.byDimension')}</div>
                  {Object.entries(byDim).length === 0 ? (
                    <div className="text-xs text-muted-foreground">{t('metadata:quality.noMeasurements')}</div>
                  ) : (
                    <div className="space-y-1">
                      {Object.entries(byDim).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2">
                            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: dimensionColors[k as QualityDimension] || '#999' }} />
                            <span className="capitalize">{k}</span>
                          </div>
                          <div className="font-medium">{v.toFixed(1)}%</div>
                        </div>
                      ))}
                    </div>
                  )}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">{t('metadata:quality.overallScore')}</div>
              <div className="text-lg font-semibold" style={{ color: scoreColor(overallPct) }}>
                {overallPct.toFixed(1)}%
              </div>
            </div>
            <Button size="sm" onClick={openCreate}><Plus className="h-4 w-4 mr-2" /> {t('metadata:quality.addMeasurement')}</Button>
          </div>
        </div>

        <Separator />

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> {t('metadata:quality.loading')}</div>
        ) : items.length === 0 ? (
          <div className="text-sm text-muted-foreground">{t('metadata:quality.noMeasurementsRecorded')}</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('metadata:quality.table.title')}</TableHead>
                <TableHead>{t('metadata:quality.table.dimension')}</TableHead>
                <TableHead>{t('metadata:quality.table.source')}</TableHead>
                <TableHead>{t('metadata:quality.table.score')}</TableHead>
                <TableHead>{t('metadata:quality.table.measured')}</TableHead>
                <TableHead className="w-24">{t('common:labels.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map(it => (
                <TableRow key={it.id}>
                  <TableCell className="font-medium">{it.title || '—'}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: dimensionColors[it.dimension] || '#999' }} />
                      <span className="capitalize">{it.dimension}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground capitalize">{it.source}</TableCell>
                  <TableCell>
                    <span className="text-xs font-medium" style={{ color: scoreColor(it.score_percent) }}>
                      {it.score_percent.toFixed(1)}%
                      {it.checks_total != null && <span className="text-muted-foreground ml-1">({it.checks_passed ?? 0}/{it.checks_total})</span>}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{fmtDate(it.measured_at)}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(it)}><Pencil className="h-4 w-4" /></Button>
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive"
                        onClick={async () => {
                          const resp = await fetch(`/api/quality-items/${it.id}`, { method: 'DELETE' });
                          if (resp.ok) { toast({ title: t('metadata:quality.messages.deleted') }); fetchData(); }
                          else { toast({ title: t('metadata:quality.messages.deleteFailed'), description: await resp.text(), variant: 'destructive' }); }
                        }}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {/* Create / Edit dialog */}
        <Dialog open={showForm} onOpenChange={setShowForm}>
          <DialogContent className="max-w-xl">
            <DialogHeader><DialogTitle>{editing ? t('metadata:quality.editMeasurement') : t('metadata:quality.addMeasurement')}</DialogTitle></DialogHeader>
            <div className="grid gap-3">
              <div>
                <Label htmlFor="q-title">{t('metadata:quality.form.title')}</Label>
                <Input id="q-title" value={form.title || ''} onChange={e => setForm({ ...form, title: e.target.value })} />
              </div>
              <div>
                <Label htmlFor="q-desc">{t('common:labels.description')}</Label>
                <Input id="q-desc" value={form.description || ''} onChange={e => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>{t('metadata:quality.form.dimension')} <span className="text-destructive">*</span></Label>
                  <Select value={form.dimension || 'completeness'} onValueChange={v => setForm({ ...form, dimension: v as QualityDimension })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {QUALITY_DIMENSIONS.map(d => <SelectItem key={d} value={d} className="capitalize">{d}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {errors.dimension && <div className="text-xs text-destructive mt-1">{errors.dimension}</div>}
                </div>
                <div>
                  <Label>{t('metadata:quality.form.source')}</Label>
                  <Select value={form.source || 'manual'} onValueChange={v => setForm({ ...form, source: v as QualitySource })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {QUALITY_SOURCES.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <Label htmlFor="q-score">{t('metadata:quality.form.score')} <span className="text-destructive">*</span></Label>
                  <Input id="q-score" type="number" min={0} max={100} step={0.1}
                    value={form.score_percent ?? ''} onChange={e => setForm({ ...form, score_percent: Number(e.target.value) })} />
                  {errors.score_percent && <div className="text-xs text-destructive mt-1">{errors.score_percent}</div>}
                </div>
                <div>
                  <Label htmlFor="q-passed">{t('metadata:quality.form.checksPassed')}</Label>
                  <Input id="q-passed" type="number" min={0}
                    value={form.checks_passed ?? ''} onChange={e => setForm({ ...form, checks_passed: e.target.value ? Number(e.target.value) : undefined })} />
                </div>
                <div>
                  <Label htmlFor="q-total">{t('metadata:quality.form.checksTotal')}</Label>
                  <Input id="q-total" type="number" min={0}
                    value={form.checks_total ?? ''} onChange={e => setForm({ ...form, checks_total: e.target.value ? Number(e.target.value) : undefined })} />
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setShowForm(false)}>{t('common:actions.cancel')}</Button>
                <Button onClick={submit} disabled={form.score_percent == null}>{t('common:actions.save')}</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
};

export default EntityQualityPanel;
