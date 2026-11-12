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
 * The AR's Compliance Checks: derived and aggregate predicates the ODRL rule
 * doesn't express (the rule editor carries scope-like bounds, duties and
 * prohibitions). Each row is a raw `ASSERT` rule authored here or a reused
 * check; rules read the request as `obj.<field>` / `req.<key>` and the AR's
 * parameters as `ctx.<param>`. `direction`/`weight` are the ARF divergence
 * facets carried on the link. The gate needs only pass/fail, so one row can be
 * a whole compound rule; split rows only when you want per-reason divergence
 * attribution with distinct direction/weight.
 */

type Mode = 'raw' | 'existing';

export interface CriterionRow {
  mode: Mode;
  rawRule: string;
  policyId: string;
  name: string;
  failureMessage: string;
  direction: string;
  weight: string;
  dimension: string;   // DNAco dimension (people|policy|…)
}

export const emptyCriterionRow = (): CriterionRow => ({
  mode: 'raw', rawRule: '', policyId: '', name: '', failureMessage: '',
  direction: 'actual-exceeds-documented', weight: '1.0', dimension: 'people',
});

/** Existing criteria round-trip into raw rows (no rule parsing). */
export const rowsFromCriteria = (criteria?: AuthorityCriterion[] | null): CriterionRow[] =>
  (criteria || []).map((c) => ({
    mode: 'raw' as Mode,
    rawRule: c.rule || '', policyId: '',
    name: c.name || '', failureMessage: c.failure_message || '',
    direction: c.direction || 'neutral', weight: String(c.weight ?? 1.0),
    dimension: c.dimension || 'people',
  }));

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
    const rule = r.rawRule.trim();
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

const SAMPLE_REQUEST = { actor_identity: 'test-signer', value: 0, escalated: false, cosign_present: true, action: 'approve' };

interface Props {
  rows: CriterionRow[];
  onChange: (rows: CriterionRow[]) => void;
  /** The AR's parameters (ctx.<key>) and scope keys (req.<key>): offered as
   * variables and used as the validation sample. */
  params?: Record<string, any>;
  scopeKeys?: string[];
}

export default function CriteriaBuilder({ rows, onChange, params = {}, scopeKeys = [] }: Props) {
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

  const variables = [
    ...Object.keys(params).map((k) => `ctx.${k}`),
    ...Array.from(new Set([...scopeKeys.filter(Boolean), ...Object.keys(SAMPLE_REQUEST)])).map((k) => `req.${k}`),
  ];

  const patch = (idx: number, p: Partial<CriterionRow>) =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...p } : r)));

  const insertVariable = (idx: number, v: string) => {
    const rule = rows[idx].rawRule;
    patch(idx, { rawRule: rule ? `${rule.replace(/\s+$/, '')} ${v}` : v });
  };

  const validate = async (idx: number) => {
    const { data } = await post<{ passed: boolean; message?: string | null }>('/api/authority/criteria/validate', {
      rule: rows[idx].rawRule.trim(),
      object: SAMPLE_REQUEST,
      context: Object.fromEntries(scopeKeys.filter(Boolean).map((k) => [k, ''])),
      params,
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
          ) : (
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
              {variables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-xs text-muted-foreground">{t('criteria.variables')}</span>
                  {variables.map((v) => (
                    <button key={v} type="button" onClick={() => insertVariable(idx, v)}
                            className="rounded border px-1.5 py-0.5 font-mono text-[11px] hover:bg-muted">
                      {v}
                    </button>
                  ))}
                </div>
              )}
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

      <Button variant="outline" size="sm" onClick={() => onChange([...rows, emptyCriterionRow()])}>
        <Plus className="h-4 w-4 mr-1" /> {t('criteria.buttons.addCriterion')}
      </Button>
    </div>
  );
}
