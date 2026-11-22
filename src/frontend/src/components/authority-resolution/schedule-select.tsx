import { useMemo } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/**
 * User-friendly DNAco recompute schedule picker. Presents a frequency (+ time /
 * weekday) and emits a standard 5-field cron string ("m h dom mon dow"), which is
 * what the backend stores in `schedule_cron`. Parses an existing cron back into
 * the friendly controls (best-effort; unrecognised expressions fall back to a
 * read-only "custom" display).
 */

type Frequency = 'off' | 'hourly' | 'daily' | 'weekly' | 'monthly' | 'custom';

interface Parsed {
  frequency: Frequency;
  hour: number;
  minute: number;
  dow: number; // 0-6
}

function parseCron(cron: string | null | undefined): Parsed {
  const def: Parsed = { frequency: 'off', hour: 3, minute: 0, dow: 1 };
  if (!cron || !cron.trim()) return def;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return { ...def, frequency: 'custom' };
  const [min, hr, dom, mon, dow] = parts;
  const m = parseInt(min, 10);
  const h = parseInt(hr, 10);
  if (mon !== '*') return { ...def, frequency: 'custom' };
  // Hourly: "0 * * * *"
  if (hr === '*' && dom === '*' && dow === '*' && !isNaN(m)) return { frequency: 'hourly', hour: 3, minute: m, dow: 1 };
  if (isNaN(m) || isNaN(h)) return { ...def, frequency: 'custom' };
  if (dom === '*' && dow === '*') return { frequency: 'daily', hour: h, minute: m, dow: 1 };
  if (dom === '*' && dow !== '*') return { frequency: 'weekly', hour: h, minute: m, dow: parseInt(dow, 10) || 0 };
  if (dom === '1' && dow === '*') return { frequency: 'monthly', hour: h, minute: m, dow: 1 };
  return { ...def, frequency: 'custom' };
}

function buildCron(p: Parsed): string | null {
  const m = Math.max(0, Math.min(59, p.minute));
  const h = Math.max(0, Math.min(23, p.hour));
  switch (p.frequency) {
    case 'off': return null;
    case 'hourly': return `${m} * * * *`;
    case 'daily': return `${m} ${h} * * *`;
    case 'weekly': return `${m} ${h} * * ${p.dow}`;
    case 'monthly': return `${m} ${h} 1 * *`;
    default: return null;
  }
}

interface Props {
  value: string | null;
  onChange: (cron: string | null) => void;
}

export default function ScheduleSelect({ value, onChange }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const parsed = useMemo(() => parseCron(value), [value]);
  const timeStr = `${String(parsed.hour).padStart(2, '0')}:${String(parsed.minute).padStart(2, '0')}`;

  const weekdays = [
    t('schedule.dayOfWeek.sunday'),
    t('schedule.dayOfWeek.monday'),
    t('schedule.dayOfWeek.tuesday'),
    t('schedule.dayOfWeek.wednesday'),
    t('schedule.dayOfWeek.thursday'),
    t('schedule.dayOfWeek.friday'),
    t('schedule.dayOfWeek.saturday'),
  ];

  const update = (patch: Partial<Parsed>) => {
    const next = { ...parsed, ...patch };
    onChange(buildCron(next));
  };

  const onTime = (time: string) => {
    const [hh, mm] = time.split(':');
    update({ hour: parseInt(hh, 10) || 0, minute: parseInt(mm, 10) || 0 });
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label>{t('schedule.frequency.label')}</Label>
          <Select
            value={parsed.frequency}
            onValueChange={(f) => {
              if (f === 'off') onChange(null);
              else update({ frequency: f as Frequency });
            }}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="off">{t('schedule.frequency.off')}</SelectItem>
              <SelectItem value="hourly">{t('schedule.frequency.hourly')}</SelectItem>
              <SelectItem value="daily">{t('schedule.frequency.daily')}</SelectItem>
              <SelectItem value="weekly">{t('schedule.frequency.weekly')}</SelectItem>
              <SelectItem value="monthly">{t('schedule.frequency.monthly')}</SelectItem>
              {parsed.frequency === 'custom' && <SelectItem value="custom">{t('schedule.frequency.custom')}</SelectItem>}
            </SelectContent>
          </Select>
        </div>

        {(parsed.frequency === 'daily' || parsed.frequency === 'weekly' || parsed.frequency === 'monthly') && (
          <div className="space-y-1">
            <Label>{t('schedule.time.label')}</Label>
            <Input type="time" value={timeStr} onChange={(e) => onTime(e.target.value)} />
          </div>
        )}
        {parsed.frequency === 'hourly' && (
          <div className="space-y-1">
            <Label>{t('schedule.minuteOfHour.label')}</Label>
            <Input type="number" min={0} max={59} value={parsed.minute} onChange={(e) => update({ minute: parseInt(e.target.value, 10) || 0 })} />
          </div>
        )}
      </div>

      {parsed.frequency === 'weekly' && (
        <div className="space-y-1">
          <Label>{t('schedule.dayOfWeek.label')}</Label>
          <Select value={String(parsed.dow)} onValueChange={(d) => update({ dow: parseInt(d, 10) })}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {weekdays.map((d, i) => <SelectItem key={i} value={String(i)}>{d}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {parsed.frequency === 'off'
          ? t('schedule.descriptions.off')
          : parsed.frequency === 'custom'
            ? <Trans i18nKey="schedule.descriptions.custom" ns="authority-resolution" values={{ cron: value }} shouldUnescape components={{ code: <code /> }} />
            : <Trans i18nKey="schedule.descriptions.scheduled" ns="authority-resolution" values={{ cron: value }} shouldUnescape components={{ code: <code /> }} />}
      </p>
    </div>
  );
}
