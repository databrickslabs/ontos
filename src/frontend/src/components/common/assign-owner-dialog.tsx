/**
 * Dialog for assigning a business owner to an object.
 * Used internally by OwnershipPanel.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2 } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { PrincipalPicker } from '@/components/common/principal-picker';
import type { OwnerObjectType } from '@/types/business-owner';
import type { BusinessRoleRead } from '@/types/business-role';

interface AssignOwnerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  objectType: OwnerObjectType;
  objectId: string;
  onSuccess: () => void;
  initialEmail?: string;
  initialName?: string;
}

export function AssignOwnerDialog({ open, onOpenChange, objectType, objectId, onSuccess, initialEmail, initialName }: AssignOwnerDialogProps) {
  const { t } = useTranslation('common');
  const { get: apiGet, post: apiPost } = useApi();
  const { toast } = useToast();

  const [roles, setRoles] = useState<BusinessRoleRead[]>([]);
  const [rolesLoading, setRolesLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [userEmail, setUserEmail] = useState('');
  const [userName, setUserName] = useState('');
  const [roleId, setRoleId] = useState('');

  useEffect(() => {
    if (open && roles.length === 0) {
      setRolesLoading(true);
      apiGet<BusinessRoleRead[]>('/api/business-roles')
        .then((res) => {
          if (res.data && Array.isArray(res.data)) {
            const active = res.data.filter((r) => r.status === 'active');
            setRoles(active);
          }
        })
        .finally(() => setRolesLoading(false));
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open) {
      if (initialEmail) setUserEmail(initialEmail);
      if (initialName) setUserName(initialName);
    } else {
      setUserEmail('');
      setUserName('');
      setRoleId('');
    }
  }, [open, initialEmail, initialName]);

  const handleSubmit = async () => {
    if (!userEmail.trim() || !roleId) return;
    setSubmitting(true);
    try {
      const res = await apiPost('/api/business-owners', {
        object_type: objectType,
        object_id: objectId,
        user_email: userEmail.trim(),
        user_name: userName.trim() || null,
        role_id: roleId,
      });
      if (res.error) throw new Error(res.error);
      toast({ title: t('common:assignOwner.title'), description: t('common:assignOwner.assignedSuccess') });
      onOpenChange(false);
      onSuccess();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('common:assignOwner.errorAssigning'), description: err.message });
    } finally {
      setSubmitting(false);
    }
  };

  const isValid = userEmail.trim().length > 0 && roleId.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t('common:assignOwner.title')}</DialogTitle>
          <DialogDescription>
            {t('common:assignOwner.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="owner-email">{t('common:assignOwner.emailLabel')} *</Label>
            <PrincipalPicker
              id="owner-email"
              accepts={['user']}
              value={userEmail || null}
              onChange={(next) => setUserEmail(next ?? '')}
              placeholder={t('common:assignOwner.emailPlaceholder')}
              aria-label={t('common:assignOwner.ownerUserAria')}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="owner-name">{t('common:assignOwner.nameLabel')}</Label>
            <Input
              id="owner-name"
              placeholder={t('common:assignOwner.namePlaceholder')}
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
            />
          </div>

          <div className="grid gap-2">
            <Label>{t('common:assignOwner.roleLabel')} *</Label>
            {rolesLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {t('common:actions.loading')}
              </div>
            ) : (
              <Select value={roleId} onValueChange={setRoleId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('common:assignOwner.rolePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.id} value={role.id}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={!isValid || submitting}>
            {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {t('common:assignOwner.title')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
