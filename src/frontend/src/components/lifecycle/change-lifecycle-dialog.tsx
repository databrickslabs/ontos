import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import StageBadge from '@/components/lifecycle/stage-badge';
import { initialStage } from '@/components/lifecycle/lifecycle-group-picker';
import { useApi } from '@/hooks/use-api';
import { groupName, lifecycleErrorText } from '@/lib/lifecycle-stages';
import type {
  EntityLifecycle,
  LifecycleEntityType,
  LifecycleStageGroup,
} from '@/types/lifecycle-stage-groups';

interface ChangeLifecycleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: LifecycleEntityType;
  entityId: string;
  /** The entity's lifecycle (its current group and stage). */
  lifecycle: EntityLifecycle;
  /** The groups of the entity type. */
  groups: LifecycleStageGroup[];
  onChanged: (lifecycle: EntityLifecycle) => void;
}

/**
 * Move an entity to another Lifecycle Stage Group of its type. Confirms that
 * its status resets to the new group's first stage (and that a published
 * entity is unpublished); the backend refuses it while a request is pending.
 */
export default function ChangeLifecycleDialog({
  open, onOpenChange, entityType, entityId, lifecycle, groups, onChanged,
}: ChangeLifecycleDialogProps) {
  const { t } = useTranslation(['lifecycle', 'common']);
  const { post } = useApi();
  const others = groups.filter((g) => g.id && g.id !== lifecycle.group.id);
  const [target, setTarget] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTarget(others.length === 1 ? others[0].id! : '');
      setError(null);
    }
    // Only when the dialog opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const targetGroup = others.find((g) => g.id === target) ?? null;
  const first = initialStage(targetGroup);

  const confirm = async () => {
    if (!target) return;
    setSaving(true);
    setError(null);
    const response = await post<EntityLifecycle>(
      `/api/lifecycle/${entityType}/${encodeURIComponent(entityId)}/change-group`,
      { group_id: target },
    );
    setSaving(false);
    if (response.error) {
      setError(lifecycleErrorText(response, t));
      return;
    }
    onChanged(response.data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('lifecycle:change.title')}</DialogTitle>
          <DialogDescription>
            {t('lifecycle:change.description', {
              group: groupName({ ...lifecycle.group }, t),
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="change-lifecycle-group">{t('lifecycle:change.newGroup')}</Label>
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger id="change-lifecycle-group"
                aria-label={t('lifecycle:change.newGroup')}>
                <SelectValue placeholder={t('lifecycle:change.chooseGroup')} />
              </SelectTrigger>
              <SelectContent>
                {others.map((g) => (
                  <SelectItem key={g.id!} value={g.id!}>{groupName(g, t)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {targetGroup && first && (
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription className="space-y-1">
                <p>
                  {t('lifecycle:change.reset')}{' '}
                  <StageBadge stage={first} />
                </p>
                <p className="text-xs text-muted-foreground">{t('lifecycle:change.resetHint')}</p>
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={confirm} disabled={!target || saving}>
            {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            {t('lifecycle:change.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
