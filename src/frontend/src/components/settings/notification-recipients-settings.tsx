import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { useApi, type ApiResponse } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { AppRole } from '@/types/settings';
import type { NotificationRecipient } from '@/types/notification-recipients';

const ENDPOINT = '/api/settings/notification-recipients';

/** The error of saving a recipient, in the user's language when the backend sent a code for it. */
function recipientErrorText(t: (key: string, options?: Record<string, unknown>) => string, response: ApiResponse<unknown>): string {
  if (!response.errorCode) return response.error || '';
  return t(`settings:notificationRecipients.errors.${response.errorCode}`, {
    ...(response.errorParams ?? {}),
    defaultValue: response.error || response.errorCode,
  });
}

interface RecipientForm {
  name: string;
  description: string;
  /** Users and groups, from the PrincipalPicker */
  principals: string[];
  /** App roles the recipient notifies */
  roleTargets: string[];
  /** App roles whose members may use the recipient */
  allowedRoleIds: string[];
  isActive: boolean;
}

function toForm(recipient: NotificationRecipient | null, roleIds: Set<string>): RecipientForm {
  const targets = recipient?.targets ?? [];
  return {
    name: recipient?.name ?? '',
    description: recipient?.description ?? '',
    principals: targets.filter((target) => !roleIds.has(target)),
    roleTargets: targets.filter((target) => roleIds.has(target)),
    allowedRoleIds: recipient?.allowed_role_ids ?? [],
    isActive: recipient?.is_active ?? true,
  };
}

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

export default function NotificationRecipientsSettings() {
  const { t } = useTranslation(['settings']);
  const { toast } = useToast();
  const { get, post, put, delete: remove } = useApi();
  const [recipients, setRecipients] = useState<NotificationRecipient[]>([]);
  const [roles, setRoles] = useState<AppRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<NotificationRecipient | 'new' | null>(null);
  const [form, setForm] = useState<RecipientForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<NotificationRecipient | null>(null);

  const roleNames = new Map(roles.map((role) => [role.id, role.name]));

  const load = useCallback(async () => {
    const [recipientsResponse, rolesResponse] = await Promise.all([
      get<NotificationRecipient[]>(ENDPOINT),
      get<AppRole[]>('/api/settings/roles'),
    ]);
    if (recipientsResponse.error) {
      toast({ title: t('common:status.error'), description: recipientsResponse.error, variant: 'destructive' });
    } else {
      setRecipients(recipientsResponse.data ?? []);
    }
    if (!rolesResponse.error) setRoles(rolesResponse.data ?? []);
    setLoading(false);
  }, [get, toast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDialog = (recipient: NotificationRecipient | 'new') => {
    setEditing(recipient);
    setForm(toForm(recipient === 'new' ? null : recipient, new Set(roles.map((role) => role.id))));
  };

  const closeDialog = () => {
    setEditing(null);
    setForm(null);
  };

  const save = async () => {
    if (!form) return;
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      targets: [...form.principals, ...form.roleTargets],
      allowed_role_ids: form.allowedRoleIds,
      is_active: form.isActive,
    };
    setSaving(true);
    const response = editing === 'new'
      ? await post<NotificationRecipient>(ENDPOINT, body)
      : await put<NotificationRecipient>(`${ENDPOINT}/${(editing as NotificationRecipient).id}`, body);
    setSaving(false);
    if (response.error) {
      toast({
        title: t('settings:notificationRecipients.saveFailed'),
        description: recipientErrorText(t, response),
        variant: 'destructive',
      });
      return;
    }
    toast({ title: t('settings:notificationRecipients.saved') });
    closeDialog();
    await load();
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const response = await remove(`${ENDPOINT}/${pendingDelete.id}`);
    setPendingDelete(null);
    if (response.error) {
      toast({ title: t('common:status.error'), description: response.error, variant: 'destructive' });
      return;
    }
    toast({ title: t('settings:notificationRecipients.deleted') });
    await load();
  };

  const targetLabel = (target: string) => roleNames.get(target) ?? target;

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground max-w-2xl">{t('settings:notificationRecipients.description')}</p>
        <Button onClick={() => openDialog('new')}>
          <Plus className="mr-2 h-4 w-4" />
          {t('settings:notificationRecipients.add')}
        </Button>
      </div>

      {recipients.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6">{t('settings:notificationRecipients.empty')}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('settings:notificationRecipients.columns.name')}</TableHead>
              <TableHead>{t('settings:notificationRecipients.columns.targets')}</TableHead>
              <TableHead>{t('settings:notificationRecipients.columns.allowedRoles')}</TableHead>
              <TableHead>{t('settings:notificationRecipients.columns.status')}</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {recipients.map((recipient) => (
              <TableRow key={recipient.id}>
                <TableCell className="font-medium">{recipient.name}</TableCell>
                <TableCell className="text-sm">
                  {recipient.targets.length === 0
                    ? '—'
                    : recipient.targets.map((target) => targetLabel(target)).join(', ')}
                </TableCell>
                <TableCell className="text-sm">
                  {recipient.allowed_role_ids.length === 0
                    ? t('settings:notificationRecipients.noAllowedRoles')
                    : recipient.allowed_role_ids.map((id) => roleNames.get(id) ?? id).join(', ')}
                </TableCell>
                <TableCell>
                  <Badge variant={recipient.is_active ? 'default' : 'secondary'}>
                    {recipient.is_active
                      ? t('settings:notificationRecipients.status.active')
                      : t('settings:notificationRecipients.status.disabled')}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" aria-label={t('settings:notificationRecipients.edit')} onClick={() => openDialog(recipient)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label={t('settings:notificationRecipients.delete')} onClick={() => setPendingDelete(recipient)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) closeDialog(); }}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {editing === 'new' ? t('settings:notificationRecipients.add') : t('settings:notificationRecipients.edit')}
            </DialogTitle>
            <DialogDescription>{t('settings:notificationRecipients.dialogDescription')}</DialogDescription>
          </DialogHeader>
          {form && (
            <div className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="notification-recipient-name">{t('settings:notificationRecipients.fields.name')}</Label>
                <Input
                  id="notification-recipient-name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder={t('settings:notificationRecipients.fields.namePlaceholder')}
                />
                <p className="text-xs text-muted-foreground">{t('settings:notificationRecipients.fields.nameHint')}</p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="notification-recipient-description">{t('settings:notificationRecipients.fields.description')}</Label>
                <Textarea
                  id="notification-recipient-description"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="notification-recipient-principals">{t('settings:notificationRecipients.fields.principals')}</Label>
                <PrincipalPicker
                  id="notification-recipient-principals"
                  multiple
                  value={form.principals}
                  onChange={(next) => setForm({ ...form, principals: next })}
                  placeholder={t('settings:notificationRecipients.fields.principalsPlaceholder')}
                  aria-label={t('settings:notificationRecipients.fields.principals')}
                />
              </div>
              <div className="space-y-2">
                <Label>{t('settings:notificationRecipients.fields.roleTargets')}</Label>
                <div className="grid grid-cols-2 gap-2">
                  {roles.map((role) => (
                    <label key={role.id} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={form.roleTargets.includes(role.id)}
                        onCheckedChange={() => setForm({ ...form, roleTargets: toggle(form.roleTargets, role.id) })}
                      />
                      {role.name}
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>{t('settings:notificationRecipients.fields.allowedRoles')}</Label>
                <p className="text-xs text-muted-foreground">{t('settings:notificationRecipients.fields.allowedRolesHint')}</p>
                <div className="grid grid-cols-2 gap-2">
                  {roles.map((role) => (
                    <label key={role.id} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={form.allowedRoleIds.includes(role.id)}
                        onCheckedChange={() => setForm({ ...form, allowedRoleIds: toggle(form.allowedRoleIds, role.id) })}
                      />
                      {role.name}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <Label htmlFor="notification-recipient-active">{t('settings:notificationRecipients.fields.active')}</Label>
                  <p className="text-xs text-muted-foreground">{t('settings:notificationRecipients.fields.activeHint')}</p>
                </div>
                <Switch
                  id="notification-recipient-active"
                  checked={form.isActive}
                  onCheckedChange={(checked) => setForm({ ...form, isActive: checked })}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>{t('common:actions.cancel')}</Button>
            <Button onClick={save} disabled={saving || !form?.name.trim()}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('common:actions.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings:notificationRecipients.delete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings:notificationRecipients.deleteConfirm', { name: pendingDelete?.name ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>{t('settings:notificationRecipients.delete')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
