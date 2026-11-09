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
import { Loader2, Plus, RefreshCcw, Trash2, Pencil, ArrowLeft, ArrowRight } from 'lucide-react';
import type { EntityKind, CostItem, CostItemCreate, CostItemUpdate, CostCenter, CostSummary } from '@/types/costs';
import { formatCents } from '@/types/costs';
import { useToast } from '@/hooks/use-toast';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

type Props = { entityId: string; entityType: EntityKind };

const centers: CostCenter[] = ['INFRASTRUCTURE', 'HR', 'STORAGE', 'MAINTENANCE', 'OTHER'];

// Shared color palette for donut + rows
const centerColors: Record<string, string> = {
  INFRASTRUCTURE: '#3b82f6', // blue-500
  HR: '#22c55e',             // green-500
  STORAGE: '#8b5cf6',        // violet-500
  MAINTENANCE: '#f59e0b',    // amber-500
  OTHER: '#64748b',          // slate-500
};

function firstDay(year: number, month: number) { return `${year}-${String(month).padStart(2,'0')}-01`; }

const EntityCostsPanel: React.FC<Props> = ({ entityId, entityType }) => {
  const { t } = useTranslation(['metadata', 'common']);
  const [items, setItems] = React.useState<CostItem[]>([]);
  const [summary, setSummary] = React.useState<CostSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [month, setMonth] = React.useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
  });

  // Create/Edit states
  const [showForm, setShowForm] = React.useState(false);
  const [editing, setEditing] = React.useState<CostItem | null>(null);
  const [form, setForm] = React.useState<Partial<CostItemCreate>>({
    entity_id: entityId,
    entity_type: entityType,
    cost_center: 'INFRASTRUCTURE',
    currency: 'USD',
  });
  const [errors, setErrors] = React.useState<Record<string,string>>({});
  const { toast } = useToast();

  const fetchData = React.useCallback(async () => {
    setLoading(true);
    try {
      const list = await fetch(`/api/entities/${entityType}/${entityId}/cost-items?month=${month}`).then(r => r.json());
      const sum = await fetch(`/api/entities/${entityType}/${entityId}/cost-items/summary?month=${month}`).then(r => r.json());
      setItems(Array.isArray(list) ? list : []);
      setSummary(sum || null);
    } catch (e: any) {
      toast({ title: t('metadata:costs.messages.loadFailed'), description: e?.message || String(e), variant: 'destructive' });
    } finally { setLoading(false); }
  }, [entityId, entityType, month, toast]);

  React.useEffect(() => { fetchData(); }, [fetchData]);

  const monthToPrev = () => {
    const [y,m] = month.split('-').map(Number); const d = new Date(y, m-2, 1); setMonth(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);
  };
  const monthToNext = () => {
    const [y,m] = month.split('-').map(Number); const d = new Date(y, m, 1); setMonth(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);
  };

  const total = summary?.total_cents ?? 0;
  const currency = summary?.currency || 'USD';
  const byCenter = summary?.by_center || {};
  const percentages = Object.entries(byCenter).map(([k,v]) => [k, total>0 ? (v/total)*100 : 0] as const);

  // CSS donut via conic-gradient
  const donutStyle: React.CSSProperties = {
    width: 64, height: 64, borderRadius: '50%',
    background: (() => {
      let acc = 0; const parts: string[] = [];
      const minSlice = 0.5; // ensure visibility even for tiny values
      const normalized = percentages.map(([k,p]) => [k, p < minSlice && p > 0 ? minSlice : p] as const);
      const scale = normalized.reduce((s, [,p]) => s + p, 0) || 1;
      normalized.forEach(([k,p]) => { const slice = (p / scale) * 100; const start = acc; const end = acc + slice; parts.push(`${centerColors[k]||'#999'} ${start}% ${end}%`); acc = end; });
      parts.push(`#e5e7eb ${acc}% 100%`);
      return `conic-gradient(${parts.join(',')})`;
    })(),
  };

  const resetForm = () => {
    setEditing(null);
    setErrors({});
    // Default start month to currently selected panel month
    const [yy, mm] = month.split('-').map(Number);
    setForm({
      entity_id: entityId,
      entity_type: entityType,
      cost_center: 'INFRASTRUCTURE',
      currency: currency || 'USD',
      start_month: firstDay(yy, mm),
    });
  };

  const openCreate = () => { resetForm(); setShowForm(true); };
  const openEdit = (it: CostItem) => {
    setEditing(it);
    setErrors({});
    setForm({
      entity_id: entityId,
      entity_type: entityType,
      title: it.title,
      description: it.description,
      cost_center: it.cost_center,
      custom_center_name: it.custom_center_name || undefined,
      amount_cents: it.amount_cents,
      currency: it.currency,
      start_month: it.start_month,
      end_month: it.end_month || undefined,
    });
    setShowForm(true);
  };

  const validate = (payload: Partial<CostItemCreate>) => {
    const errs: Record<string,string> = {};
    if (!payload.cost_center) errs.cost_center = t('metadata:costs.validation.required');
    if (payload.amount_cents == null || Number.isNaN(payload.amount_cents)) errs.amount_cents = t('metadata:costs.validation.required');
    if (!payload.currency) errs.currency = t('metadata:costs.validation.required');
    if (!payload.start_month) errs.start_month = t('metadata:costs.validation.required');
    return errs;
  };

  const submit = async () => {
    const payload: any = { ...form } as CostItemCreate;
    if (!payload.start_month) {
      const [y,m] = month.split('-').map(Number); payload.start_month = firstDay(y,m);
    }

    const errs = validate(payload);
    if (Object.keys(errs).length > 0) { setErrors(errs); toast({ title: t('metadata:costs.messages.missingFields'), description: t('metadata:costs.messages.missingFieldsDescription'), variant: 'destructive' }); return; }

    try {
      if (editing) {
        const resp = await fetch(`/api/cost-items/${editing.id}`, { method: 'PUT', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload as CostItemUpdate) });
        if (!resp.ok) throw new Error(await resp.text());
      } else {
        const resp = await fetch(`/api/entities/${entityType}/${entityId}/cost-items`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload) });
        if (!resp.ok) throw new Error(await resp.text());
      }
      toast({ title: editing ? t('metadata:costs.messages.updated') : t('metadata:costs.messages.added') });
      setShowForm(false); resetForm(); fetchData();
    } catch (e: any) {
      toast({ title: t('metadata:costs.messages.saveFailed'), description: e?.message || String(e), variant: 'destructive' });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl flex items-center gap-2">{t('metadata:costs.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button size="icon" variant="outline" onClick={monthToPrev}><ArrowLeft className="h-4 w-4" /></Button>
            <div className="text-sm font-medium">{month}</div>
            <Button size="icon" variant="outline" onClick={monthToNext}><ArrowRight className="h-4 w-4" /></Button>
            <Button size="icon" variant="ghost" onClick={fetchData}><RefreshCcw className="h-4 w-4" /></Button>
          </div>
          <div className="flex items-center gap-4">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div style={donutStyle} aria-label={t('metadata:costs.donutAria')} className="border border-border" />
                </TooltipTrigger>
                <TooltipContent className="space-y-1">
                  <div className="text-xs font-medium mb-1">{t('metadata:costs.breakdown')}</div>
                  {Object.entries(byCenter).length === 0 ? (
                    <div className="text-xs text-muted-foreground">{t('metadata:costs.noItems')}</div>
                  ) : (
                    <div className="space-y-1">
                      {Object.entries(byCenter).map(([k,v]) => (
                        <div key={k} className="flex items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2">
                            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: centerColors[k] || '#999' }} />
                            <span>{k}</span>
                          </div>
                          <div className="font-medium">{formatCents(Number(v||0), currency)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">{t('metadata:costs.total')}</div>
              <div className="text-lg font-semibold">{formatCents(total, currency)}</div>
            </div>
            <Button size="sm" onClick={openCreate}><Plus className="h-4 w-4 mr-2" /> {t('metadata:costs.addExpense')}</Button>
          </div>
        </div>

        <Separator />

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> {t('metadata:costs.loading')}</div>
        ) : items.length === 0 ? (
          <div className="text-sm text-muted-foreground">{t('metadata:costs.noItemsForMonth')}</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('metadata:costs.table.title')}</TableHead>
                <TableHead>{t('metadata:costs.table.center')}</TableHead>
                <TableHead>{t('metadata:costs.table.monthRange')}</TableHead>
                <TableHead>{t('metadata:costs.table.amountMonth')}</TableHead>
                <TableHead className="w-24">{t('common:labels.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map(it => (
                <TableRow key={it.id}>
                  <TableCell className="font-medium">{it.title || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: centerColors[it.cost_center] || '#999' }} />
                      <span>
                        {it.cost_center}
                        {it.cost_center==='OTHER' && it.custom_center_name ? ` (${it.custom_center_name})` : ''}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{it.start_month}{it.end_month ? ` → ${it.end_month}` : ''}</TableCell>
                  <TableCell className="text-xs">{formatCents(it.amount_cents, it.currency)}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(it)}><Pencil className="h-4 w-4" /></Button>
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" onClick={async () => { const resp = await fetch(`/api/cost-items/${it.id}`, { method: 'DELETE' }); if (resp.ok) { toast({ title: t('metadata:costs.messages.deleted') }); fetchData(); } else { toast({ title: t('metadata:costs.messages.deleteFailed'), description: await resp.text(), variant: 'destructive' }); } }}><Trash2 className="h-4 w-4" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <Dialog open={showForm} onOpenChange={setShowForm}>
          <DialogContent className="max-w-xl">
            <DialogHeader><DialogTitle>{editing ? t('metadata:costs.editExpense') : t('metadata:costs.addExpense')}</DialogTitle></DialogHeader>
            <div className="grid gap-3">
              <div>
                <Label htmlFor="title">{t('metadata:costs.form.title')}</Label>
                <Input id="title" value={form.title || ''} onChange={e => setForm({ ...form, title: e.target.value })} />
              </div>
              <div>
                <Label htmlFor="desc">{t('common:labels.description')}</Label>
                <Input id="desc" value={form.description || ''} onChange={e => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>{t('metadata:costs.form.center')} <span className="text-destructive">*</span></Label>
                  <Select value={(form.cost_center as any) || 'INFRASTRUCTURE'} onValueChange={(v) => setForm({ ...form, cost_center: v as any })}>
                    <SelectTrigger><SelectValue placeholder={t('metadata:costs.form.center')} /></SelectTrigger>
                    <SelectContent>
                      {centers.map(c => (<SelectItem key={c} value={c}>{c}</SelectItem>))}
                    </SelectContent>
                  </Select>
                  {errors.cost_center && <div className="text-xs text-destructive mt-1">{errors.cost_center}</div>}
                </div>
                {form.cost_center === 'OTHER' && (
                  <div>
                    <Label htmlFor="custom">{t('metadata:costs.form.customCenter')}</Label>
                    <Input id="custom" value={form.custom_center_name || ''} onChange={e => setForm({ ...form, custom_center_name: e.target.value })} />
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label htmlFor="amount">{t('metadata:costs.form.amountCents')} <span className="text-destructive">*</span></Label>
                  <Input id="amount" type="number" value={form.amount_cents ?? ''} onChange={e => setForm({ ...form, amount_cents: Number(e.target.value) })} />
                  {errors.amount_cents && <div className="text-xs text-destructive mt-1">{errors.amount_cents}</div>}
                </div>
                <div>
                  <Label htmlFor="currency">{t('metadata:costs.form.currency')} <span className="text-destructive">*</span></Label>
                  <Input id="currency" value={form.currency || 'USD'} onChange={e => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
                  {errors.currency && <div className="text-xs text-destructive mt-1">{errors.currency}</div>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label htmlFor="start">{t('metadata:costs.form.startMonth')} <span className="text-destructive">*</span></Label>
                  <Input id="start" placeholder={t('metadata:costs.form.monthPlaceholder')} value={(form.start_month || '').slice(0,7)} onChange={e => setForm({ ...form, start_month: `${e.target.value}-01` })} />
                  {errors.start_month && <div className="text-xs text-destructive mt-1">{errors.start_month}</div>}
                </div>
                <div>
                  <Label htmlFor="end">{t('metadata:costs.form.endMonth')}</Label>
                  <Input id="end" placeholder={t('metadata:costs.form.monthPlaceholder')} value={(form.end_month || '').slice(0,7)} onChange={e => setForm({ ...form, end_month: e.target.value ? `${e.target.value}-01` : undefined })} />
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setShowForm(false)}>{t('common:actions.cancel')}</Button>
                <Button onClick={submit} disabled={!form.cost_center || !form.currency || (form.amount_cents ?? 0) < 0}>{t('common:actions.save')}</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
};

export default EntityCostsPanel;


