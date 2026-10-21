/**
 * Trigger picker — drives the workflow trigger dropdown in the workflow
 * authoring form.
 *
 * Why a dedicated component (vs inline <Select>)?
 *  - We need to fetch the trigger catalog from GET /api/workflows/trigger-types
 *    (so labels + entity_types + groups stay in sync with the backend enum
 *    in one place).
 *  - We filter by workflow_type (approval/process) — authors only see the
 *    half of the catalog that matches the workflow they are building.
 *  - We group entries with <SelectGroup> instead of a flat list, so the
 *    25-ish triggers stop reading as duplicates ("on_subscribe" /
 *    "for_subscribe" now sit under the same group with disambiguated labels).
 *
 * The grouping/filtering logic is exported separately as
 * `partitionTriggers` so it can be unit-tested without dragging Radix into
 * jsdom (which has known hang issues with <Select>).
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { getTriggerLabel, getRequiredPermission } from '@/lib/workflow-labels';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Info } from 'lucide-react';

/** Field-label constants for the trigger picker. Exported so the parent
 * form and tests can reference the same source of truth. */
export const TRIGGER_PICKER_LABEL = 'Fires on';
export const TRIGGER_PICKER_HELPER = 'What action makes this workflow run';

/**
 * Wire-format entry from GET /api/workflows/trigger-types.
 * One per TriggerType enum member.
 */
export interface TriggerTypeOption {
  value: string;
  label: string;
  workflow_type: 'approval' | 'process';
  entity_types: string[];
  group: 'lifecycle' | 'request_flow' | 'validation_gates' | 'system_scheduled';
}

/**
 * Group ordering and human labels. Approval workflows only ever have
 * request_flow, so this ordering is harmless for them.
 */
export const TRIGGER_GROUP_ORDER: Array<TriggerTypeOption['group']> = [
  'lifecycle',
  'request_flow',
  'validation_gates',
  'system_scheduled',
];

export const TRIGGER_GROUP_LABELS: Record<TriggerTypeOption['group'], string> = {
  lifecycle: 'Lifecycle events',
  request_flow: 'Request flow',
  validation_gates: 'Validation gates',
  system_scheduled: 'System & scheduled',
};

/**
 * Pure logic: filter the catalog to the workflow being authored and
 * partition the visible entries into ordered groups. Exported for tests.
 */
export function partitionTriggers(
  options: TriggerTypeOption[],
  args: {
    workflowType: 'approval' | 'process';
  },
): Array<{ group: TriggerTypeOption['group']; label: string; items: TriggerTypeOption[] }> {
  const visible = options.filter((o) => o.workflow_type === args.workflowType);
  return TRIGGER_GROUP_ORDER
    .map((g) => ({
      group: g,
      label: TRIGGER_GROUP_LABELS[g],
      items: visible.filter((o) => o.group === g),
    }))
    .filter((bucket) => bucket.items.length > 0);
}

export interface TriggerPickerProps {
  /** Currently selected trigger value (e.g. "on_create"). */
  value: string;
  /** Called when the user picks a different trigger. */
  onChange: (value: string) => void;
  /** Which half of the catalog to show. */
  workflowType: 'approval' | 'process';
  /** Optional: pre-loaded options (used in tests / SSR). */
  options?: TriggerTypeOption[];
}

export function TriggerPicker({
  value,
  onChange,
  workflowType,
  options: optionsProp,
}: TriggerPickerProps) {
  const { t } = useTranslation(['workflows', 'common']);
  const { get } = useApi();
  const [options, setOptions] = useState<TriggerTypeOption[]>(optionsProp ?? []);

  useEffect(() => {
    if (optionsProp) {
      setOptions(optionsProp);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await get<TriggerTypeOption[]>('/api/workflows/trigger-types');
        if (!cancelled && res.data) {
          setOptions(res.data);
        }
      } catch (err) {
        // Soft-fail: the SelectItem fallback uses getTriggerLabel(), so
        // the picker still renders something sensible if the API is down.
        console.error('Failed to load trigger types:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [get, optionsProp]);

  const groups = useMemo(
    () => partitionTriggers(options, { workflowType }),
    [options, workflowType],
  );

  return (
    <div className="space-y-1">
      <Label>{t('workflows:triggerPicker.label', TRIGGER_PICKER_LABEL)}</Label>
      <p className="text-xs text-muted-foreground">{t('workflows:triggerPicker.helper', TRIGGER_PICKER_HELPER)}</p>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger>
          <SelectValue>
            {value ? getTriggerLabel(value) : t('workflows:triggerPicker.placeholder')}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {groups.map(({ group, label, items }) => (
            <SelectGroup key={group}>
              <SelectLabel>{t(`workflows:triggerPicker.groups.${group}`, label)}</SelectLabel>
              {items.map((opt) => (
                <TooltipProvider key={opt.value} delayDuration={400}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <SelectItem value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      <code className="text-xs">{opt.value}</code>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ))}
            </SelectGroup>
          ))}
          {groups.length === 0 && (
            <div className="px-2 py-1.5 text-sm text-muted-foreground">
              {t('workflows:triggerPicker.noTypes')}
            </div>
          )}
        </SelectContent>
      </Select>
      {value && (() => {
        const required = getRequiredPermission(value);
        return (
          <Alert className="mt-2" data-testid="trigger-required-permission">
            <Info className="h-4 w-4" />
            <AlertDescription className="text-xs">
              {required ? (
                <>
                  <strong>{t('workflows:triggerPicker.requiredPermission.label')}</strong>{' '}
                  {t('workflows:triggerPicker.requiredPermission.prefix')}{' '}
                  <code className="text-xs">
                    {required.feature}: {required.level}
                  </code>{' '}
                  {t('workflows:triggerPicker.requiredPermission.suffix')}
                </>
              ) : (
                <>{t('workflows:triggerPicker.availableToAny')}</>
              )}
            </AlertDescription>
          </Alert>
        );
      })()}
    </div>
  );
}
