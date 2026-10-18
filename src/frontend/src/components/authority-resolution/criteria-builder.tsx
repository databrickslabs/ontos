import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import NativeSelect from '@/components/ui/native-select';
import { useApi } from '@/hooks/use-api';
import { Plus, Trash2, CheckCircle2, XCircle } from 'lucide-react';
import {
  ARF_DIRECTIONS,
  type AuthorityCriterion,
  type CriterionInput,
  type ReusableCheck,
} from '@/types/authority-resolution';

/**
 * Author-configurable decision criteria. Each row is a Compliance Check attached
 * to the AR — authored with a structured builder (the ASSERT rule is generated),
 * a raw ASSERT escape-hatch, or by reusing an existing check. `direction`/`weight`
 * are the ARF divergence facets carried on the link. The gate needs only pass/fail,
 * so one row can be a whole compound rule; split rows only when you want per-reason
 * divergence attribution with distinct direction/weight.
 */

type Mode = 'builder' | 'raw' | 'existing';
type Predicate = 'allowlist' | 'ceiling' | 'required_flag' | 'action_match';

export interface CriterionRow {
  mode: Mode;
  // builder fields
  predicate: Predicate;
  field: string;
  values: string;        // comma list (allowlist) / single value (action_match)
  max: string;           // ceiling
  allowEscalation: boolean;
  // raw / existing
  rawRule: string;
  policyId: string;
  // shared
  name: string;
  failureMessage: string;
  direction: string;
  weight: string;
  dimension: string;   // DNAco dimension (people|policy|…)
}

const getPREDICATE_DEFAULTS = (t: (key: string, options?: any) => string): Record<Predicate, { field: string; direction: string; name: string; fail: string }> => ({
  allowlist: { field: 'actor_identity', direction: 'actual-exceeds-documented', name: t('criteria.predicateDefaults.allowlistName'), fail: t('criteria.predicateDefaults.allowlistFailure') },
  ceiling: { field: 'value', direction: 'actual-exceeds-documented', name: t('criteria.predicateDefaults.ceilingName'), fail: t('criteria.predicateDefaults.ceilingFailure') },
  required_flag: { field: 'cosign_present', direction: 'documented-exceeds-actual', name: t('criteria.predicateDefaults.requiredFlagName'), fail: t('criteria.predicateDefaults.requiredFlagFailure') },
  action_match: { field: 'action', direction: 'neutral', name: t('criteria.predicateDefaults.actionMatchName'), fail: t('criteria.predicateDefaults.actionMatchFailure') },
});

export const emptyCriterionRow = (t: (key: string, options?: any) => string): CriterionRow => ({
  mode: 'builder', predicate: 'allowlist', field: 'actor_identity', values: '', max: '0.15',
  allowEscalation: true, rawRule: '', policyId: '',
  name: getPREDICATE_DEFAULTS(t).allowlist.name, failureMessage: getPREDICATE_DEFAULTS(t).allowlist.fail,
  direction: 'actual-exceeds-documented', weight: '1.0', dimension: 'people',
});

/** Existing criteria round-trip into raw rows (no rule parsing). */
export const rowsFromCriteria = (criteria?: AuthorityCriterion[] | null): CriterionRow[] =>
  (criteria || []).map((c) => ({
    mode: 'raw' as Mode,
    predicate: 'allowlist' as Predicate, field: '', values: '', max: '', allowEscalation: false,
    rawRule: c.rule || '', policyId: '',
    name: c.name || '', failureMessage: c.failure_message || '',
    direction: c.direction || 'neutral', weight: String(c.weight ?? 1.0),
    dimension: c.dimension || 'people',
  }));

/** Build the ASSERT condition from a builder row (without the ASSERT keyword). */
function builderRule(r: CriterionRow): string {
  const f = (r.field || '').trim() || 'value';
  switch (r.predicate) {
    case 'allowlist': {
      const list = r.values.split(',').map((v) => v.trim()).filter(Boolean).map((v) => `'${v}'`).join(', ');
      return `obj.${f} IN [${list}]`;
    }
    case 'ceiling':
      return `obj.${f} <= ${(r.max || '0').trim()}${r.allowEscalation ? ' OR obj.escalated = True' : ''}`;
    case 'required_flag':
      return `obj.${f} = True`;
    case 'action_match':
      return `obj.${f} = '${(r.values || '').trim()}'`;
    default:
      return '';
  }
}

/** The rule a row will submit (builder-generated or raw). */
export function ruleForRow(r: CriterionRow): string {
  return r.mode === 'raw' ? r.rawRule.trim() : builderRule(r);
}

/** Convert editor rows into the API payload (skips empty rows). */
export function rowsToPayload(rows: CriterionRow[]): CriterionInput[] {
  const out: CriterionInput[] = [];
  rows.forEach((r, idx) => {
    const weight = parseFloat(r.weight) || 1.0;
    const dimension = (r.dimension || 'people').trim() || 'people';
    if (r.mode === 'existing') {
      if (!r.policyId) return;
      out.push({ policy_id: r.policyId, direction: r.direction, weight, dimension, order: idx, enabled: true });
      return;
    }
    const rule = ruleForRow(r);
    if (!rule) return;
    out.push({
      name: r.name.trim() || `Criterion ${idx + 1}`,
      rule,
      failure_message: r.failureMessage.trim() || undefined,
      direction: r.direction, weight, dimension, order: idx, enabled: true,
    });
  });
  return out;
}

interface Props {
  rows: CriterionRow[];
  onChange: (rows: CriterionRow[]) => void;
}

export default function CriteriaBuilder({ rows, onChange }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const { get, post } = useApi();
  const [checks, setChecks] = useState<ReusableCheck[]>([]);
  const [checksLoading, setChecksLoading] = useState(false);
  const [validation, setValidation] = useState<Record<number, { passed: boolean; message?: string | null }>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setChecksLoading(true);
      const { data } = await get<ReusableCheck[]>('/api/authority/criteria/policies');
      if (!cancelled) {
        if (Array.isArray(data)) setChecks(data);
        setChecksLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [get]);

  const patch = (idx: number, p: Partial<CriterionRow>) =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...p } : r)));

  const setPredicate = (idx: number, predicate: Predicate) => {
    const defaults = getPREDICATE_DEFAULTS(t);
    const d = defaults[predicate];
    patch(idx, { predicate, field: d.field, direction: d.direction, name: d.name, failureMessage: d.fail });
  };

  const validate = async (idx: number) => {
    const rule = ruleForRow(rows[idx]);
    const { data } = await post<{ passed: boolean; message?: string | null }>('/api/authority/criteria/validate', {
      rule,
      object: { actor_identity: 'test-signer', value: 0, escalated: false, cosign_present: true, action: 'approve' },
    });
    if (data) setValidation((v) => ({ ...v, [idx]: data }));
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t('criteria.description')}
      </p>

      {rows.map((r, idx) => (
        <div key={idx} className="rounded-md border p-3 space-y-2">
          <div className="flex items-center gap-2">
            <NativeSelect
              className="w-52"
              selectClassName="h-8 text-xs"
              value={r.mode}
              onChange={(e) => patch(idx, { mode: e.target.value as Mode })}
            >
              <option value="builder">{t('criteria.mode.builder')}</option>
              <option value="raw">{t('criteria.mode.raw')}</option>
              <option value="existing">{t('criteria.mode.existing')}</option>
            </NativeSelect>
            <div className="flex-1" />
            <Button variant="ghost" size="icon" onClick={() => onChange(rows.filter((_, i) => i !== idx))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>

          {r.mode === 'existing' ? (
            checksLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <NativeSelect
                value={r.policyId}
                onChange={(e) => patch(idx, { policyId: e.target.value })}
              >
                <option value="">{t('criteria.selections.selectComplianceCheck')}</option>
                {checks.map((c) => <option key={c.id} value={c.id}>{c.name}{c.category ? ` (${c.category})` : ''}</option>)}
              </NativeSelect>
            )
          ) : r.mode === 'raw' ? (
            <div className="space-y-1">
              <Input
                value={r.name}
                onChange={(e) => patch(idx, { name: e.target.value })}
                placeholder={t('criteria.fields.criterionNamePlaceholder')}
              />
              <Textarea
                value={r.rawRule}
                onChange={(e) => patch(idx, { rawRule: e.target.value })}
                rows={2}
                className="font-mono text-xs"
                placeholder={t('criteria.fields.rawRulePlaceholder')}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-[1fr_1fr] gap-2">
                <NativeSelect
                  value={r.predicate}
                  onChange={(e) => setPredicate(idx, e.target.value as Predicate)}
                >
                  <option value="allowlist">{t('criteria.predicate.allowlist')}</option>
                  <option value="ceiling">{t('criteria.predicate.ceiling')}</option>
                  <option value="required_flag">{t('criteria.predicate.requiredFlag')}</option>
                  <option value="action_match">{t('criteria.predicate.actionMatch')}</option>
                </NativeSelect>
                <Input value={r.field} onChange={(e) => patch(idx, { field: e.target.value })} placeholder={t('criteria.fields.fieldPlaceholder')} />
              </div>
              {r.predicate === 'allowlist' && (
                <Input value={r.values} onChange={(e) => patch(idx, { values: e.target.value })} placeholder={t('criteria.fields.allowlistPlaceholder')} />
              )}
              {r.predicate === 'action_match' && (
                <Input value={r.values} onChange={(e) => patch(idx, { values: e.target.value })} placeholder={t('criteria.fields.actionMatchPlaceholder')} />
              )}
              {r.predicate === 'ceiling' && (
                <div className="flex items-center gap-3">
                  <Input value={r.max} onChange={(e) => patch(idx, { max: e.target.value })} placeholder={t('criteria.fields.ceilingPlaceholder')} className="max-w-[140px]" />
                  <label className="flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={r.allowEscalation} onChange={(e) => patch(idx, { allowEscalation: e.target.checked })} />
                    {t('criteria.fields.ceilingAllowEscalation')}
                  </label>
                </div>
              )}
              <div className="text-xs font-mono text-muted-foreground break-all">{t('criteria.assertPrefix')} {builderRule(r)}</div>
              <Input value={r.name} onChange={(e) => patch(idx, { name: e.target.value })} placeholder={t('criteria.fields.criterionNamePlaceholder')} />
              <Input value={r.failureMessage} onChange={(e) => patch(idx, { failureMessage: e.target.value })} placeholder={t('criteria.fields.failureMessagePlaceholder')} />
            </div>
          )}

          {r.mode !== 'existing' && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => validate(idx)}>{t('criteria.validation.validateButton')}</Button>
              {validation[idx] && (
                <span className={`text-xs flex items-center gap-1 ${validation[idx].passed ? 'text-green-600' : 'text-red-600'}`}>
                  {validation[idx].passed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                  {validation[idx].passed ? t('criteria.validation.ruleValid') : (validation[idx].message || t('criteria.validation.ruleInvalid'))}
                </span>
              )}
            </div>
          )}

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.direction')}</Label>
              <NativeSelect
                className="w-56"
                selectClassName="h-8 text-xs"
                value={r.direction}
                onChange={(e) => patch(idx, { direction: e.target.value })}
              >
                {ARF_DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{t(`direction.${d.value}`, { defaultValue: d.label })}</option>)}
              </NativeSelect>
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs">{t('criteria.divergence.weight')}</Label>
              <Input value={r.weight} onChange={(e) => patch(idx, { weight: e.target.value })} className="h-8 w-16 text-xs" />
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.dimension')}</Label>
              <Input value={r.dimension} onChange={(e) => patch(idx, { dimension: e.target.value })}
                     className="h-8 w-24 text-xs" placeholder={t('criteria.divergence.dimensionPlaceholder')} />
            </div>
            {r.mode === 'existing' && <Badge variant="outline" className="text-xs">{t('criteria.divergence.reusedCheckBadge')}</Badge>}
          </div>
        </div>
      ))}

      <Button variant="outline" size="sm" onClick={() => onChange([...rows, emptyCriterionRow(t)])}>
        <Plus className="h-4 w-4 mr-1" /> {t('criteria.buttons.addCriterion')}
      </Button>
    </div>
  );
}
