import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { groupName, orderedStages } from '@/lib/lifecycle-stages';
import type { LifecycleStage, LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

/** The group `id` names, else the type's default (the first group the API lists). */
export function selectedGroup(
  groups: LifecycleStageGroup[],
  id: string | null | undefined,
): LifecycleStageGroup | null {
  return groups.find((g) => g.id && g.id === id)
    ?? groups.find((g) => g.is_default_for_type)
    ?? groups[0]
    ?? null;
}

/** The stage a new entity in `group` starts in: its first stage. */
export function initialStage(group: LifecycleStageGroup | null): LifecycleStage | null {
  if (!group) return null;
  const stages = orderedStages(group);
  return stages.find((s) => s.is_initial) ?? stages[0] ?? null;
}

interface LifecycleGroupPickerProps {
  /** The groups of the entity type (default first), as the API lists them. */
  groups: LifecycleStageGroup[];
  value: string | null | undefined;
  onChange: (groupId: string) => void;
  disabled?: boolean;
  id?: string;
}

/**
 * The Lifecycle Stage Group of a new entity. Shown only when the entity type
 * has more than one group; preselects the type's default.
 */
export default function LifecycleGroupPicker({
  groups, value, onChange, disabled, id = 'lifecycle-group',
}: LifecycleGroupPickerProps) {
  const { t } = useTranslation(['lifecycle']);
  const fallback = selectedGroup(groups, null);

  useEffect(() => {
    if (!value && fallback?.id) onChange(fallback.id);
  }, [value, fallback?.id, onChange]);

  if (groups.filter((g) => g.id).length <= 1) return null;
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t('lifecycle:picker.label')}</Label>
      <Select value={value ?? fallback?.id ?? ''} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id} aria-label={t('lifecycle:picker.label')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {groups.filter((g) => g.id).map((g) => (
            <SelectItem key={g.id!} value={g.id!}>
              {groupName(g, t)}
              {g.is_default_for_type ? ` (${t('lifecycle:settings.default')})` : ''}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground">{t('lifecycle:picker.hint')}</p>
    </div>
  );
}
