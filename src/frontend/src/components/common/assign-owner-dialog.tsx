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
import { Loader2, AlertCircle } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { PrincipalPicker } from '@/components/common/principal-picker';
import type { OwnerObjectType } from '@/types/business-owner';
import type { BusinessRoleRead } from '@/types/business-role';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

// Business role names that make their holder an owner for owner-routed approvals and
// notifications (compared lowercased; mirrors the backend's owner resolution).
const OWNER_ROLE_NAMES = ['data owner', 'owner'];

/** Whether owners holding this role are resolved as the entity's owners. */
export function isOwnerRole(role: Pick<BusinessRoleRead, 'name'>): boolean {
  return OWNER_ROLE_NAMES.includes(role.name.trim().toLowerCase());
}

/**
 * The role the dialog preselects: Data Owner, else Owner, else the first approver role,
 * else the first role. Never silently a role that doesn't own the entity when one exists.
 */
export function defaultOwnerRole(roles: BusinessRoleRead[]): BusinessRoleRead | undefined {
  const byName = (name: string) => roles.find((r) => r.name.trim().toLowerCase() === name);
  return byName('data owner') ?? byName('owner') ?? roles.find((r) => r.is_approver) ?? roles[0];
}

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
  const [submitting, setSubmitting] = useState(false);
  const [noRolesError, setNoRolesError] = useState(false);

  const [userEmail, setUserEmail] = useState('');
  const [userName, setUserName] = useState('');
  const [roleId, setRoleId] = useState<string | null>(null);

  useEffect(() => {
    if (open && roles.length === 0) {
      apiGet<BusinessRoleRead[]>('/api/business-roles')
        .then((res) => {
          if (res.data && Array.isArray(res.data)) {
            const active = res.data.filter((r) => r.status === 'active');
            setRoles(active);
            if (active.length === 0) {
              setNoRolesError(true);
            } else {
              setRoleId(defaultOwnerRole(active)?.id ?? null);
              setNoRolesError(false);
            }
          }
        });
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reopened with the roles already loaded: preselect the default role again
  useEffect(() => {
    if (open && roles.length > 0 && roleId == null) {
      setRoleId(defaultOwnerRole(roles)?.id ?? null);
    }
  }, [open, roles, roleId]);

  useEffect(() => {
    if (open) {
      if (initialEmail) setUserEmail(initialEmail);
      if (initialName) setUserName(initialName);
    } else {
      setUserEmail('');
      setUserName('');
      setRoleId(null);
      setNoRolesError(false);
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

  const isValid = userEmail.trim().length > 0 && !noRolesError && roleId != null;
  const selectedRole = roles.find((r) => r.id === roleId);

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
          {noRolesError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                {t('common:assignOwnerRole.noRoles')}
              </AlertDescription>
            </Alert>
          )}
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

          {roles.length > 0 && (
            <div className="grid gap-2">
              <Label htmlFor="owner-role">{t('common:assignOwner.roleLabel')} *</Label>
              <Select value={roleId ?? undefined} onValueChange={setRoleId}>
                <SelectTrigger id="owner-role" aria-label={t('common:assignOwner.roleLabel')}>
                  <SelectValue placeholder={t('common:assignOwner.rolePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.id} value={role.id}>
                      <span className="flex items-center gap-2">
                        {role.name}
                        {isOwnerRole(role) && (
                          <Badge variant="secondary" className="text-xs">
                            {t('common:assignOwnerRole.ownerBadge')}
                          </Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedRole?.description && (
                <p className="text-xs text-muted-foreground">{selectedRole.description}</p>
              )}
              {selectedRole && !isOwnerRole(selectedRole) && objectType !== 'data_domain' && (
                <p className="text-xs text-amber-700 dark:text-amber-400" role="note">
                  {t('common:assignOwnerRole.notOwnerHint')}
                </p>
              )}
            </div>
          )}
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
