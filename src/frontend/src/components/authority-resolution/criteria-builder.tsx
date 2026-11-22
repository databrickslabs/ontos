import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import NativeSelect from '@/components/ui/native-select';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useApi } from '@/hooks/use-api';
import { Plus, Trash2, CheckCircle2, XCircle } from 'lucide-react';
import {
  ARF_DIRECTIONS,
  type AuthorityCriterion,
  type AuthorityCriterionTemplate,
  type CriterionInput,
  type CriterionProvenance,
  type PolicyClause,
  type ReusableCheck,
} from '@/types/authority-resolution';
import { ClauseSelect } from '@/components/authority-resolution/rule-editor';

/**
 * Author-configurable decision criteria. Each row is owned by the AR version —
 * authored with a structured builder (the ASSERT rule is generated) or a raw
 * ASSERT escape-hatch. Rows can also start from an ARF template or be copied
 * from a Compliance check; the copy is a label only, with no live link.
 * `direction`/`weight` are the ARF divergence facets carried on the row. The gate
 * needs only pass/fail, so one row can be a whole compound rule; split rows only
 * when you want per-reason divergence attribution with distinct direction/weight.
 */

type Mode = 'builder' | 'raw';
type Predicate = 'allowlist' | 'ceiling' | 'required_flag' | 'action_match';

export interface CriterionRow {
  mode: Mode;
  // builder fields
  predicate: Predicate;
  field: string;
  values: string;        // comma list (allowlist) / single value (action_match)
  max: string;           // ceiling
  allowEscalation: boolean;
  // raw rule (also holds the rule of a copied or template row, for display)
  rawRule: string;
  // provenance: where the row came from (null for a new check)
  copiedFrom: CriterionProvenance | null;
  // set on ARF template rows: the server fills the rule from the registry
  templateKey: string | null;
  // the Authority Policy clause this check enforces ('' when none)
  clauseRef: string;
  // shared
  name: string;
  failureMessage: string;
  direction: string;
  weight: string;
  dimension: string;   // DNAco dimension (people|policy|…)
  enabled: boolean;
}

const getPREDICATE_DEFAULTS = (t: (key: string, options?: any) => string): Record<Predicate, { field: string; direction: string; name: string; fail: string }> => ({
  allowlist: { field: 'actor_identity', direction: 'actual-exceeds-documented', name: t('criteria.predicateDefaults.allowlistName'), fail: t('criteria.predicateDefaults.allowlistFailure') },
  ceiling: { field: 'value', direction: 'actual-exceeds-documented', name: t('criteria.predicateDefaults.ceilingName'), fail: t('criteria.predicateDefaults.ceilingFailure') },
  required_flag: { field: 'cosign_present', direction: 'documented-exceeds-actual', name: t('criteria.predicateDefaults.requiredFlagName'), fail: t('criteria.predicateDefaults.requiredFlagFailure') },
  action_match: { field: 'action', direction: 'neutral', name: t('criteria.predicateDefaults.actionMatchName'), fail: t('criteria.predicateDefaults.actionMatchFailure') },
});

export const emptyCriterionRow = (t: (key: string, options?: any) => string): CriterionRow => ({
  mode: 'builder', predicate: 'allowlist', field: 'actor_identity', values: '', max: '0.15',
  allowEscalation: true, rawRule: '', copiedFrom: null, templateKey: null, clauseRef: '',
  name: getPREDICATE_DEFAULTS(t).allowlist.name, failureMessage: getPREDICATE_DEFAULTS(t).allowlist.fail,
  direction: 'actual-exceeds-documented', weight: '1.0', dimension: 'people', enabled: true,
});

/** Existing criteria round-trip into raw rows (no rule parsing). */
export const rowsFromCriteria = (criteria?: AuthorityCriterion[] | null): CriterionRow[] =>
  (criteria || []).map((c) => {
    const copiedFrom = c.copied_from ?? null;
    return {
      mode: 'raw' as Mode,
      predicate: 'allowlist' as Predicate, field: '', values: '', max: '', allowEscalation: false,
      rawRule: c.rule || '', copiedFrom,
      templateKey: copiedFrom?.kind === 'template' ? (copiedFrom.key ?? null) : null,
      clauseRef: c.policy_clause_ref || '',
      name: c.name || '', failureMessage: c.failure_message || '',
      direction: c.direction || 'neutral', weight: String(c.weight ?? 1.0),
      dimension: c.dimension || 'people',
      enabled: c.enabled ?? true,
    };
  });

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

/**
 * Parse a weight. Valid only when it is a finite number >= 0; 0 stays 0.
 * An empty field is invalid (Number('') would read as 0).
 */
export function parseWeight(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  const n = Number(text);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** True when any row has a weight that is not a finite number >= 0. Blocks save. */
export const hasInvalidWeight = (rows: CriterionRow[]): boolean =>
  rows.some((r) => parseWeight(r.weight) === null);

/** Convert editor rows into the API payload (skips empty rows). Call hasInvalidWeight first. */
export function rowsToPayload(rows: CriterionRow[]): CriterionInput[] {
  const out: CriterionInput[] = [];
  rows.forEach((r, idx) => {
    // Validated by the caller (hasInvalidWeight); an invalid weight never reaches here.
    const weight = parseWeight(r.weight) as number;
    const policy_clause_ref = r.clauseRef.trim() || undefined;
    if (r.templateKey) {
      // The server fills name, rule, failure_message, dimension and direction.
      out.push({ template_key: r.templateKey, weight, order: idx, enabled: r.enabled, policy_clause_ref });
      return;
    }
    const dimension = (r.dimension || 'people').trim() || 'people';
    const rule = ruleForRow(r);
    if (!rule) return;
    out.push({
      name: r.name.trim() || `Criterion ${idx + 1}`,
      rule,
      failure_message: r.failureMessage.trim() || undefined,
      direction: r.direction, weight, dimension, order: idx, enabled: r.enabled,
      copied_from: r.copiedFrom ?? undefined, policy_clause_ref,
    });
  });
  return out;
}

interface Props {
  rows: CriterionRow[];
  /** Clauses of the cited Authority Policy; each check may cite the one it enforces. */
  clauses?: PolicyClause[];
  onChange: (rows: CriterionRow[]) => void;
  /** Hides the Add check menu and the row remove buttons (AR is not editable). */
  readOnly?: boolean;
  /** The AR's scoped parameters (ODRL slice 1): accepted from the dialog; ctx./req. completion is not wired here yet. */
  params?: Record<string, any>;
  scopeKeys?: string[];
}

type ChecksState = 'loading' | 'ready' | 'failed';

export default function CriteriaBuilder({ rows, onChange, readOnly = false, clauses = [] }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const { get, post } = useApi();
  const [checks, setChecks] = useState<ReusableCheck[]>([]);
  const [checksState, setChecksState] = useState<ChecksState>('loading');
  const [templates, setTemplates] = useState<AuthorityCriterionTemplate[]>([]);
  const [validation, setValidation] = useState<Record<number, { passed: boolean; message?: string | null }>>({});

  // The Add check menu is the only consumer of these lists, so load them for editable ARs only.
  useEffect(() => {
    if (readOnly) return;
    let cancelled = false;
    (async () => {
      const [policies, tpls] = await Promise.all([
        get<ReusableCheck[]>('/api/authority/criteria/policies'),
        get<AuthorityCriterionTemplate[]>('/api/authority/criteria/templates'),
      ]);
      if (cancelled) return;
      if (Array.isArray(policies.data) && !policies.error) {
        setChecks(policies.data);
        setChecksState('ready');
      } else {
        setChecksState('failed');
      }
      if (Array.isArray(tpls.data)) setTemplates(tpls.data);
    })();
    return () => { cancelled = true; };
  }, [get, readOnly]);

  const patch = (idx: number, p: Partial<CriterionRow>) =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...p } : r)));

  const addRow = (row: CriterionRow) => onChange([...rows, row]);

  const addFromTemplate = (tpl: AuthorityCriterionTemplate) =>
    addRow({
      ...emptyCriterionRow(t),
      mode: 'raw',
      rawRule: tpl.rule,
      name: tpl.name,
      failureMessage: tpl.failure_message || '',
      direction: tpl.direction || 'neutral',
      dimension: tpl.dimension || 'people',
      templateKey: tpl.key,
      copiedFrom: { kind: 'template', label: tpl.name, key: tpl.key },
    });

  // Copies the rule text and the check name; the row does not follow the Compliance check afterwards.
  const addFromCompliance = (c: ReusableCheck) =>
    addRow({
      ...emptyCriterionRow(t),
      mode: 'raw',
      rawRule: c.rule,
      name: c.name,
      failureMessage: c.failure_message || '',
      copiedFrom: { kind: 'compliance', label: c.name, id: c.id },
    });

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

  const provenanceText = (p: CriterionProvenance): string => {
    if (p.kind === 'template') return t('criteria.provenance.fromTemplate', { name: p.label });
    if (p.kind === 'migrated') return t('criteria.provenance.migratedFromCompliance', { label: p.label });
    return t('criteria.provenance.copiedFromCompliance', { label: p.label });
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t('criteria.description')}
      </p>

      {rows.map((r, idx) => {
        const weight = parseWeight(r.weight);
        const weightInvalid = weight === null;
        const fromTemplate = !!r.templateKey;
        return (
        <div key={idx} className="rounded-md border p-3 space-y-2">
          <div className="flex items-center gap-2">
            {!fromTemplate && (
              <NativeSelect
                className="w-52"
                selectClassName="h-8 text-xs"
                value={r.mode}
                onChange={(e) => patch(idx, { mode: e.target.value as Mode })}
              >
                <option value="builder">{t('criteria.mode.builder')}</option>
                <option value="raw">{t('criteria.mode.raw')}</option>
              </NativeSelect>
            )}
            <div className="flex-1" />
            {!readOnly && (
              <Button variant="ghost" size="icon" onClick={() => onChange(rows.filter((_, i) => i !== idx))}>
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>

          {r.copiedFrom && (
            <div className="text-xs text-muted-foreground">{provenanceText(r.copiedFrom)}</div>
          )}

          {fromTemplate ? (
            <div className="space-y-1">
              <div className="text-sm font-medium">{r.name}</div>
              <div className="font-mono text-xs break-all">{r.rawRule}</div>
              {r.failureMessage && <div className="text-xs text-muted-foreground">↳ {r.failureMessage}</div>}
            </div>
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

          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => validate(idx)}>{t('criteria.validation.validateButton')}</Button>
            {validation[idx] && (
              <span className={`text-xs flex items-center gap-1 ${validation[idx].passed ? 'text-green-600' : 'text-red-600'}`}>
                {validation[idx].passed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {validation[idx].passed ? t('criteria.validation.ruleValid') : (validation[idx].message || t('criteria.validation.ruleInvalid'))}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.direction')}</Label>
              <NativeSelect
                className="w-56"
                selectClassName="h-8 text-xs"
                value={r.direction}
                disabled={fromTemplate}
                onChange={(e) => patch(idx, { direction: e.target.value })}
              >
                {ARF_DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{t(`direction.${d.value}`, { defaultValue: d.label })}</option>)}
              </NativeSelect>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1">
                <Label className="text-xs">{t('criteria.divergence.weight')}</Label>
                <Input
                  value={r.weight}
                  aria-invalid={weightInvalid || undefined}
                  onChange={(e) => patch(idx, { weight: e.target.value })}
                  className={`h-8 w-16 text-xs ${weightInvalid ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                />
              </div>
              {weightInvalid && <span className="text-xs text-destructive">{t('criteria.errors.weightInvalid')}</span>}
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.dimension')}</Label>
              <Input value={r.dimension} onChange={(e) => patch(idx, { dimension: e.target.value })}
                     disabled={fromTemplate}
                     className="h-8 w-24 text-xs" placeholder={t('criteria.divergence.dimensionPlaceholder')} />
            </div>
            {(clauses.length > 0 || r.clauseRef) && (
              <ClauseSelect value={r.clauseRef} clauses={clauses} onChange={(clauseRef) => patch(idx, { clauseRef })} />
            )}
            <label className="flex items-center gap-1 text-xs whitespace-nowrap">
              <input type="checkbox" checked={r.enabled} onChange={(e) => patch(idx, { enabled: e.target.checked })} />
              {t('criteria.divergence.enabled')}
            </label>
          </div>
        </div>
        );
      })}

      {!readOnly && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              <Plus className="h-4 w-4 mr-1" /> {t('criteria.buttons.addCheck')}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-w-sm">
            <DropdownMenuItem onSelect={() => addRow(emptyCriterionRow(t))}>
              {t('criteria.addMenu.newCheck')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>{t('criteria.addMenu.fromTemplate')}</DropdownMenuLabel>
            {templates.map((tpl) => (
              <DropdownMenuItem key={tpl.key} onSelect={() => addFromTemplate(tpl)} className="flex-col items-start">
                <span>{tpl.name}</span>
                {tpl.description && <span className="text-xs text-muted-foreground">{tpl.description}</span>}
              </DropdownMenuItem>
            ))}
            {checksState === 'ready' && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{t('criteria.addMenu.copyFromCompliance')}</DropdownMenuLabel>
                {checks.length === 0 ? (
                  <DropdownMenuItem disabled>{t('criteria.addMenu.noComplianceChecks')}</DropdownMenuItem>
                ) : checks.map((c) => (
                  <DropdownMenuItem key={c.id} onSelect={() => addFromCompliance(c)}>
                    {c.name}{c.category ? ` (${c.category})` : ''}
                  </DropdownMenuItem>
                ))}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
