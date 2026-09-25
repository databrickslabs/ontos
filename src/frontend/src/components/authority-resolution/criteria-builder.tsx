import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
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

const PREDICATE_DEFAULTS: Record<Predicate, { field: string; direction: string; name: string; fail: string }> = {
  allowlist: { field: 'actor_identity', direction: 'actual-exceeds-documented', name: 'Authorized signer', fail: 'Signer is not authorized.' },
  ceiling: { field: 'value', direction: 'actual-exceeds-documented', name: 'Within threshold', fail: 'Value exceeds the threshold without escalation.' },
  required_flag: { field: 'cosign_present', direction: 'documented-exceeds-actual', name: 'Required flag present', fail: 'A required condition is missing.' },
  action_match: { field: 'action', direction: 'neutral', name: 'Action match', fail: 'Action is not permitted.' },
};

export const emptyCriterionRow = (): CriterionRow => ({
  mode: 'builder', predicate: 'allowlist', field: 'actor_identity', values: '', max: '0.15',
  allowEscalation: true, rawRule: '', policyId: '',
  name: PREDICATE_DEFAULTS.allowlist.name, failureMessage: PREDICATE_DEFAULTS.allowlist.fail,
  direction: PREDICATE_DEFAULTS.allowlist.direction, weight: '1.0', dimension: 'people',
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
  const { get, post } = useApi();
  const [checks, setChecks] = useState<ReusableCheck[]>([]);
  const [validation, setValidation] = useState<Record<number, { passed: boolean; message?: string | null }>>({});

  useEffect(() => {
    (async () => {
      const { data } = await get<ReusableCheck[]>('/api/authority/criteria/policies');
      if (Array.isArray(data)) setChecks(data);
    })();
  }, [get]);

  const patch = (idx: number, p: Partial<CriterionRow>) =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...p } : r)));

  const setPredicate = (idx: number, predicate: Predicate) => {
    const d = PREDICATE_DEFAULTS[predicate];
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
        The gate approves only when every enabled criterion passes. A criterion that fails for a past
        decision counts as a divergence in the DNA-Coefficient — weighted and signed by its direction.
        One compound rule is fine; split into separate criteria only when you want per-reason divergence.
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
              <option value="builder">Structured</option>
              <option value="raw">Raw ASSERT</option>
              <option value="existing">Reuse existing check</option>
            </NativeSelect>
            <div className="flex-1" />
            <Button variant="ghost" size="icon" onClick={() => onChange(rows.filter((_, i) => i !== idx))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>

          {r.mode === 'existing' ? (
            <NativeSelect
              value={r.policyId}
              onChange={(e) => patch(idx, { policyId: e.target.value })}
            >
              <option value="">Select a Compliance Check…</option>
              {checks.map((c) => <option key={c.id} value={c.id}>{c.name}{c.category ? ` (${c.category})` : ''}</option>)}
            </NativeSelect>
          ) : r.mode === 'raw' ? (
            <div className="space-y-1">
              <Input
                value={r.name}
                onChange={(e) => patch(idx, { name: e.target.value })}
                placeholder="Criterion name"
              />
              <Textarea
                value={r.rawRule}
                onChange={(e) => patch(idx, { rawRule: e.target.value })}
                rows={2}
                className="font-mono text-xs"
                placeholder="obj.actor_identity IN ['rsm-east'] AND (obj.value <= 0.15 OR obj.escalated = True)"
              />
            </div>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-[1fr_1fr] gap-2">
                <NativeSelect
                  value={r.predicate}
                  onChange={(e) => setPredicate(idx, e.target.value as Predicate)}
                >
                  <option value="allowlist">Signer allowlist</option>
                  <option value="ceiling">Numeric ceiling</option>
                  <option value="required_flag">Required flag</option>
                  <option value="action_match">Action match</option>
                </NativeSelect>
                <Input value={r.field} onChange={(e) => patch(idx, { field: e.target.value })} placeholder="field (e.g. actor_identity)" />
              </div>
              {r.predicate === 'allowlist' && (
                <Input value={r.values} onChange={(e) => patch(idx, { values: e.target.value })} placeholder="rsm-east, rsm-west" />
              )}
              {r.predicate === 'action_match' && (
                <Input value={r.values} onChange={(e) => patch(idx, { values: e.target.value })} placeholder="approve" />
              )}
              {r.predicate === 'ceiling' && (
                <div className="flex items-center gap-3">
                  <Input value={r.max} onChange={(e) => patch(idx, { max: e.target.value })} placeholder="0.15" className="max-w-[140px]" />
                  <label className="flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={r.allowEscalation} onChange={(e) => patch(idx, { allowEscalation: e.target.checked })} />
                    allow if escalated
                  </label>
                </div>
              )}
              <div className="text-xs font-mono text-muted-foreground break-all">ASSERT {builderRule(r)}</div>
              <Input value={r.name} onChange={(e) => patch(idx, { name: e.target.value })} placeholder="Criterion name" />
              <Input value={r.failureMessage} onChange={(e) => patch(idx, { failureMessage: e.target.value })} placeholder="Denial message shown when this fails" />
            </div>
          )}

          {r.mode !== 'existing' && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => validate(idx)}>Validate</Button>
              {validation[idx] && (
                <span className={`text-xs flex items-center gap-1 ${validation[idx].passed ? 'text-green-600' : 'text-red-600'}`}>
                  {validation[idx].passed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                  {validation[idx].passed ? 'Rule is valid' : (validation[idx].message || 'Invalid')}
                </span>
              )}
            </div>
          )}

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">Direction</Label>
              <NativeSelect
                className="w-56"
                selectClassName="h-8 text-xs"
                value={r.direction}
                onChange={(e) => patch(idx, { direction: e.target.value })}
              >
                {ARF_DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </NativeSelect>
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs">Weight</Label>
              <Input value={r.weight} onChange={(e) => patch(idx, { weight: e.target.value })} className="h-8 w-16 text-xs" />
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">Dimension</Label>
              <Input value={r.dimension} onChange={(e) => patch(idx, { dimension: e.target.value })}
                     className="h-8 w-24 text-xs" placeholder="people" />
            </div>
            {r.mode === 'existing' && <Badge variant="outline" className="text-xs">reused check</Badge>}
          </div>
        </div>
      ))}

      <Button variant="outline" size="sm" onClick={() => onChange([...rows, emptyCriterionRow()])}>
        <Plus className="h-4 w-4 mr-1" /> Add criterion
      </Button>
    </div>
  );
}
