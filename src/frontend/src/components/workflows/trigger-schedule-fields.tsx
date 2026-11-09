/**
 * Schedule and timezone of a `scheduled` trigger (#1310): a Quartz cron expression
 * (`sec min hour day-of-month month day-of-week [year]`) and an IANA timezone (empty = UTC).
 * The backend checks both on save and answers with coded errors (common/quartz_cron.py,
 * `schedule_required` in workflows_manager.py); `scheduleIssueText` translates them.
 */
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { WorkflowValidationIssue } from './step-config-checks';

export const DEFAULT_SCHEDULE_TIMEZONE = 'UTC';

/** Whether a workflow validation error is about the schedule or its timezone. */
export function isScheduleIssue(code: string): boolean {
  return code === 'schedule_required' || code === 'timezone_invalid' || code.startsWith('cron_');
}

/** The translated text of a schedule error (the backend's English text as fallback). */
export function scheduleIssueText(issue: WorkflowValidationIssue, t: TFunction): string {
  const params = issue.params || {};
  const field = typeof params.field === 'string'
    ? t(`workflows:triggerSchedule.fields.${params.field}`, { defaultValue: params.field })
    : undefined;
  return t(`workflows:triggerSchedule.errors.${issue.code}`, {
    ...params,
    ...(field !== undefined ? { field } : {}),
    defaultValue: issue.message || issue.code,
  });
}

function timezoneNames(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    return intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : [];
  } catch {
    return [];
  }
}

export interface TriggerScheduleFieldsProps {
  schedule: string;
  timezone: string;
  onScheduleChange: (value: string) => void;
  onTimezoneChange: (value: string) => void;
  /** The backend's error about the schedule or timezone from the last save */
  issue?: WorkflowValidationIssue | null;
}

export function TriggerScheduleFields({
  schedule, timezone, onScheduleChange, onTimezoneChange, issue,
}: TriggerScheduleFieldsProps) {
  const { t } = useTranslation(['workflows']);
  const timezoneIssue = issue?.code === 'timezone_invalid' ? issue : null;
  const scheduleIssue = issue && !timezoneIssue ? issue : null;
  return (
    <div className="space-y-3" data-testid="trigger-schedule-fields">
      <div className="space-y-1">
        <Label htmlFor="trigger-schedule">{t('workflows:triggerSchedule.cronLabel')}</Label>
        <Input
          id="trigger-schedule"
          className="font-mono"
          value={schedule}
          onChange={(e) => onScheduleChange(e.target.value)}
          placeholder="0 0 6 * * ?"
          aria-invalid={!!scheduleIssue}
          aria-describedby="trigger-schedule-hint"
        />
        <p id="trigger-schedule-hint" className="text-xs text-muted-foreground">
          {t('workflows:triggerSchedule.cronHint', { example: '0 0 6 * * ?' })}
        </p>
        {scheduleIssue && (
          <p className="text-xs text-destructive" role="alert" data-testid="schedule-error">
            {scheduleIssueText(scheduleIssue, t)}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Label htmlFor="trigger-timezone">{t('workflows:triggerSchedule.timezoneLabel')}</Label>
        <Input
          id="trigger-timezone"
          list="trigger-timezone-options"
          value={timezone}
          onChange={(e) => onTimezoneChange(e.target.value)}
          placeholder={DEFAULT_SCHEDULE_TIMEZONE}
          aria-invalid={!!timezoneIssue}
        />
        <datalist id="trigger-timezone-options">
          {timezoneNames().map((name) => <option key={name} value={name} />)}
        </datalist>
        <p className="text-xs text-muted-foreground">
          {t('workflows:triggerSchedule.timezoneHint')}
        </p>
        {timezoneIssue && (
          <p className="text-xs text-destructive" role="alert" data-testid="timezone-error">
            {scheduleIssueText(timezoneIssue, t)}
          </p>
        )}
      </div>
    </div>
  );
}
