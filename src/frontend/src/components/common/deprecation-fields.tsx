/**
 * Deprecation details asked for when a data product or data contract is
 * moved to `deprecated`: a required reason, an optional sunset date and an
 * optional replacement of the same type (not deprecated or retired, not the
 * entity itself).
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';

export interface DeprecationValues {
  deprecationReason: string;
  sunsetDate: string;
  replacementId: string;
}

export const EMPTY_DEPRECATION: DeprecationValues = {
  deprecationReason: '',
  sunsetDate: '',
  replacementId: '',
};

/** Today in UTC (YYYY-MM-DD), the date the backend checks sunset dates against. */
export function utcToday(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/**
 * Request body fields of a status change *request* to `deprecated`: the
 * justification is the reason, so only the sunset date and the replacement.
 */
export function requestedDeprecationPayload(values: DeprecationValues): Record<string, string | undefined> {
  return {
    sunset_date: values.sunsetDate || undefined,
    replacement_id: values.replacementId || undefined,
  };
}

/** Request body fields for the change-status endpoints. */
export function deprecationPayload(values: DeprecationValues): Record<string, string | undefined> {
  return {
    deprecation_reason: values.deprecationReason.trim(),
    sunset_date: values.sunsetDate || undefined,
    replacement_id: values.replacementId || undefined,
  };
}

interface Candidate {
  id: string;
  name?: string;
  version?: string;
  status?: string;
}

interface DeprecationFieldsProps {
  entityType: 'data_product' | 'data_contract';
  entityId: string;
  value: DeprecationValues;
  onChange: (value: DeprecationValues) => void;
  disabled?: boolean;
  /** Hide the reason (a status change request's justification is the reason). */
  hideReason?: boolean;
}

const NO_REPLACEMENT = '__none__';

export default function DeprecationFields({
  entityType,
  entityId,
  value,
  onChange,
  disabled = false,
  hideReason = false,
}: DeprecationFieldsProps) {
  const { t } = useTranslation(['common']);
  const { get } = useApi();
  const [candidates, setCandidates] = useState<Candidate[]>([]);

  useEffect(() => {
    let cancelled = false;
    const endpoint = entityType === 'data_product' ? '/api/data-products' : '/api/data-contracts';
    get<Candidate[]>(endpoint).then((res) => {
      if (cancelled || !Array.isArray(res.data)) return;
      setCandidates(
        res.data.filter(
          (c) =>
            c.id !== entityId &&
            !['deprecated', 'retired'].includes((c.status || '').toLowerCase()),
        ),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [entityType, entityId, get]);

  // The UTC date, as the backend checks it: near midnight it can differ from
  // the local date, and both sides must agree on which dates are in the past
  const today = utcToday();

  return (
    <div className="space-y-4">
      {!hideReason && (
        <div className="space-y-2">
          <Label htmlFor="deprecation-reason">{t('common:deprecation.reason')} *</Label>
          <Textarea
            id="deprecation-reason"
            value={value.deprecationReason}
            onChange={(e) => onChange({ ...value, deprecationReason: e.target.value })}
            placeholder={t('common:deprecation.reasonPlaceholder')}
            className="min-h-[80px] resize-none"
            disabled={disabled}
          />
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor="deprecation-sunset-date">{t('common:deprecation.sunsetDate')}</Label>
        <Input
          id="deprecation-sunset-date"
          type="date"
          min={today}
          value={value.sunsetDate}
          onChange={(e) => onChange({ ...value, sunsetDate: e.target.value })}
          disabled={disabled}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="deprecation-replacement">{t('common:deprecation.replacement')}</Label>
        <Select
          value={value.replacementId || NO_REPLACEMENT}
          onValueChange={(id) =>
            onChange({ ...value, replacementId: id === NO_REPLACEMENT ? '' : id })
          }
          disabled={disabled}
        >
          <SelectTrigger id="deprecation-replacement">
            <SelectValue placeholder={t('common:deprecation.noReplacement')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_REPLACEMENT}>{t('common:deprecation.noReplacement')}</SelectItem>
            {candidates.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name || c.id}
                {c.version ? ` (${c.version})` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
