import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, Loader2, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useApi, type ApiResponse } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { DataProductType } from '@/types/data-product-type';
import { dataProductTypeLabel } from '@/lib/data-product-types';

export const DATA_PRODUCT_TYPES_PERMISSION = 'settings-data-product-types';

// Same rule as the backend's KEY_PATTERN: lower-case words joined by hyphens.
const KEY_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const COLOR_OPTIONS = ['slate', 'blue', 'green', 'emerald', 'amber', 'purple', 'red'];

const COLOR_CLASSES: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  blue: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  green: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  red: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
};

const colorClass = (color?: string | null) => COLOR_CLASSES[color || 'slate'] || COLOR_CLASSES.slate;

/** Turns a label into a key suggestion: "Golden Record" -> "golden-record". */
const keyFromLabel = (label: string) =>
  label
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100);

/**
 * Shows `reason` in a tooltip around a control. A disabled button gets no
 * pointer events (and `title` never shows), so the tooltip hangs on a
 * focusable wrapper instead. Without a reason the control is returned as is.
 */
function WithReason({ reason, children }: { reason: string | null; children: ReactElement }) {
  if (!reason) return children;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex" aria-label={reason}>
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

interface FormState {
  key: string;
  label: string;
  description: string;
  color: string;
}

const EMPTY_FORM: FormState = { key: '', label: '', description: '', color: 'slate' };

export default function DataProductTypesSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { get, post, put, delete: apiDelete } = useApi();
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission(DATA_PRODUCT_TYPES_PERMISSION, FeatureAccessLevel.READ_WRITE);

  const [types, setTypes] = useState<DataProductType[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DataProductType | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [keyTouched, setKeyTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<DataProductType | null>(null);
  // Bumped after every change to load the list again
  const [reloadKey, setReloadKey] = useState(0);
  const fetchTypes = useCallback(() => setReloadKey((key) => key + 1), []);

  // A refused change in the user's language, from the API's error code.
  const errorText = useCallback(
    (response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>) =>
      response.errorCode
        ? t(`settings:dataProductTypes.errors.${response.errorCode}`, {
            ...(response.errorParams || {}),
            defaultValue: response.error || t('common:errors.saveFailed'),
          })
        : response.error || t('common:errors.saveFailed'),
    [t],
  );

  const showError = useCallback(
    (response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>) =>
      toast({ title: t('common:status.error'), description: errorText(response), variant: 'destructive' }),
    [toast, t, errorText],
  );

  useEffect(() => {
    let cancelled = false;
    get<DataProductType[]>('/api/data-product-types').then((response) => {
      if (cancelled) return;
      if (response.error) {
        showError(response);
      } else {
        setTypes(Array.isArray(response.data) ? response.data : []);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [get, showError, reloadKey]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setKeyTouched(false);
    setDialogOpen(true);
  };

  const openEdit = (type: DataProductType) => {
    setEditing(type);
    setForm({
      key: type.key,
      label: type.label,
      description: type.description || '',
      color: type.color || 'slate',
    });
    setKeyTouched(true);
    setDialogOpen(true);
  };

  const keyValid = KEY_PATTERN.test(form.key);
  const canSave = form.label.trim() !== '' && (editing !== null || keyValid);

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    const body = {
      label: form.label.trim(),
      description: form.description.trim() || null,
      color: form.color,
    };
    const response = editing
      ? await put(`/api/data-product-types/${editing.id}`, body)
      : await post('/api/data-product-types', { ...body, key: form.key });
    setSaving(false);
    if (response.error) {
      showError(response);
      return;
    }
    toast({
      title: editing ? t('common:toast.updated') : t('common:toast.created'),
      description: t(
        editing ? 'settings:dataProductTypes.messages.updated' : 'settings:dataProductTypes.messages.created',
        { name: body.label },
      ),
    });
    setDialogOpen(false);
    fetchTypes();
  };

  const update = async (type: DataProductType, changes: Partial<DataProductType>) => {
    const response = await put(`/api/data-product-types/${type.id}`, changes);
    if (response.error) {
      showError(response);
    }
    fetchTypes();
  };

  const move = async (index: number, offset: -1 | 1) => {
    const other = index + offset;
    if (other < 0 || other >= types.length) return;
    const reordered = [...types];
    [reordered[index], reordered[other]] = [reordered[other], reordered[index]];
    const response = await put('/api/data-product-types/reorder', {
      types: reordered.map((type, position) => ({ id: type.id, sort_order: position + 1 })),
    });
    if (response.error) {
      toast({
        title: t('common:status.error'),
        description: t('settings:dataProductTypes.messages.reorderFailed'),
        variant: 'destructive',
      });
    }
    fetchTypes();
  };

  const handleDelete = async () => {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    const response = await apiDelete(`/api/data-product-types/${target.id}`);
    if (response.error) {
      showError(response);
    } else {
      toast({
        title: t('common:toast.deleted'),
        description: t('settings:dataProductTypes.messages.deleted', { name: dataProductTypeLabel(target, t) }),
      });
    }
    fetchTypes();
  };

  // Why a type can't be deleted, or null when it can.
  const deleteBlockedReason = (type: DataProductType): string | null => {
    if (type.is_seeded) return t('settings:dataProductTypes.deleteBlocked.seeded');
    if (type.usage_count > 0) {
      return t('settings:dataProductTypes.deleteBlocked.inUse', { count: type.usage_count });
    }
    return null;
  };

  if (loading) {
    return <ListItemSkeleton count={5} height="h-12" className="space-y-2" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t('settings:dataProductTypes.title')}</h2>
          <p className="text-sm text-muted-foreground">{t('settings:dataProductTypes.description')}</p>
        </div>
        {canEdit && (
          <Button onClick={openCreate} size="sm">
            <Plus className="h-4 w-4 mr-1" /> {t('settings:dataProductTypes.addType')}
          </Button>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            {canEdit && <TableHead className="w-12" />}
            <TableHead>{t('settings:dataProductTypes.table.label')}</TableHead>
            <TableHead>{t('settings:dataProductTypes.table.key')}</TableHead>
            <TableHead>{t('common:labels.description')}</TableHead>
            <TableHead className="w-24 text-right">{t('settings:dataProductTypes.table.products')}</TableHead>
            <TableHead className="w-20">{t('settings:dataProductTypes.table.active')}</TableHead>
            {canEdit && <TableHead className="w-32">{t('common:labels.actions')}</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {types.map((type, index) => {
            const label = dataProductTypeLabel(type, t);
            const blocked = deleteBlockedReason(type);
            return (
              <TableRow key={type.id} data-testid={`data-product-type-${type.key}`}>
                {canEdit && (
                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <button
                        type="button"
                        onClick={() => move(index, -1)}
                        disabled={index === 0}
                        aria-label={t('settings:dataProductTypes.actions.moveUp', { name: label })}
                        className="text-muted-foreground hover:text-foreground disabled:opacity-20"
                      >
                        <ChevronUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => move(index, 1)}
                        disabled={index === types.length - 1}
                        aria-label={t('settings:dataProductTypes.actions.moveDown', { name: label })}
                        className="text-muted-foreground hover:text-foreground disabled:opacity-20"
                      >
                        <ChevronDown className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </TableCell>
                )}
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className={colorClass(type.color)}>
                      {label}
                    </Badge>
                    {type.is_default && <Badge>{t('settings:dataProductTypes.badges.default')}</Badge>}
                    {type.is_seeded && (
                      <Badge variant="secondary">{t('settings:dataProductTypes.badges.builtIn')}</Badge>
                    )}
                    {type.is_imported && (
                      <Badge variant="secondary">{t('settings:dataProductTypes.badges.imported')}</Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{type.key}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{type.description || '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{type.usage_count}</TableCell>
                <TableCell>
                  <WithReason
                    reason={canEdit && type.is_default ? t('settings:dataProductTypes.defaultCannotBeInactive') : null}
                  >
                    <Switch
                      checked={type.is_active}
                      disabled={!canEdit || type.is_default}
                      aria-label={t('settings:dataProductTypes.actions.toggleActive', { name: label })}
                      onCheckedChange={(checked) => update(type, { is_active: checked })}
                    />
                  </WithReason>
                </TableCell>
                {canEdit && (
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        disabled={type.is_default || !type.is_active}
                        title={t('settings:dataProductTypes.actions.makeDefault')}
                        aria-label={t('settings:dataProductTypes.actions.makeDefaultFor', { name: label })}
                        onClick={() => update(type, { is_default: true })}
                      >
                        <Star className={`h-3.5 w-3.5 ${type.is_default ? 'fill-current' : ''}`} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={t('settings:dataProductTypes.actions.edit', { name: label })}
                        onClick={() => openEdit(type)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <WithReason reason={blocked}>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive"
                          disabled={blocked !== null}
                          aria-label={t('settings:dataProductTypes.actions.delete', { name: label })}
                          onClick={() => setDeleting(type)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </WithReason>
                    </div>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
          {types.length === 0 && (
            <TableRow>
              <TableCell colSpan={canEdit ? 7 : 5} className="text-center text-muted-foreground py-8">
                {t('settings:dataProductTypes.emptyState')}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? t('settings:dataProductTypes.dialog.editTitle') : t('settings:dataProductTypes.dialog.createTitle')}
            </DialogTitle>
            <DialogDescription>
              {editing
                ? t('settings:dataProductTypes.dialog.editDescription')
                : t('settings:dataProductTypes.dialog.createDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="dpt-label">{t('settings:dataProductTypes.form.label')}</Label>
              <Input
                id="dpt-label"
                value={form.label}
                placeholder={t('settings:dataProductTypes.form.labelPlaceholder')}
                onChange={(e) => {
                  const label = e.target.value;
                  setForm((prev) => ({ ...prev, label, key: keyTouched ? prev.key : keyFromLabel(label) }));
                }}
              />
              {editing?.has_seeded_label && (
                <p className="text-xs text-muted-foreground">{t('settings:dataProductTypes.form.seededLabelHint')}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="dpt-key">{t('settings:dataProductTypes.form.key')}</Label>
              <Input
                id="dpt-key"
                className="font-mono"
                value={form.key}
                disabled={editing !== null}
                onChange={(e) => {
                  setKeyTouched(true);
                  setForm((prev) => ({ ...prev, key: e.target.value }));
                }}
              />
              <p className={`text-xs ${!editing && form.key && !keyValid ? 'text-destructive' : 'text-muted-foreground'}`}>
                {editing ? t('settings:dataProductTypes.form.keyImmutable') : t('settings:dataProductTypes.form.keyHint')}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="dpt-description">{t('common:labels.description')}</Label>
              <Textarea
                id="dpt-description"
                rows={2}
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('settings:dataProductTypes.form.color')}</Label>
              <div className="flex flex-wrap gap-2">
                {COLOR_OPTIONS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    aria-pressed={form.color === color}
                    onClick={() => setForm((prev) => ({ ...prev, color }))}
                    className={`px-3 py-1 rounded text-xs font-medium border-2 transition-colors ${colorClass(color)} ${
                      form.color === color ? 'border-foreground' : 'border-transparent'
                    }`}
                  >
                    {form.label.trim() || t('settings:dataProductTypes.form.labelPlaceholder')}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleSave} disabled={saving || !canSave}>
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {editing ? t('common:actions.update') : t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings:dataProductTypes.delete.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings:dataProductTypes.delete.description', {
                name: deleting ? dataProductTypeLabel(deleting, t) : '',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">
              {t('common:actions.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
