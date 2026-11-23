import { useEffect, useRef, useState } from 'react';
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
 * The AR's decision checks. Each row is owned by the AR version and is a raw
 * ASSERT rule (the ODRL rule editor holds constraints, duties and prohibitions).
 * A rule reads the request as obj.<field> / req.<key> and the AR's parameters as
 * ctx.<param>; the variable picker inserts those at the cursor, and Validate runs
 * the rule on a sample built from the AR's parameters. Rows can also start from an
 * ARF template or be copied from a Compliance check; the copy is a label only.
 * `direction`/`weight` are the ARF divergence facets carried on the row. The gate
 * needs only pass/fail, so one row can be a whole compound rule; split rows only
 * when you want per-reason divergence attribution with distinct direction/weight.
 */

/** A sample request for Validate: the standard request fields a rule may read. */
const SAMPLE_REQUEST = { actor_identity: 'test-signer', value: 0, escalated: false, cosign_present: true, action: 'approve' };

export interface CriterionRow {
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

export const emptyCriterionRow = (): CriterionRow => ({
  rawRule: '', copiedFrom: null, templateKey: null, clauseRef: '', name: '', failureMessage: '',
  direction: 'actual-exceeds-documented', weight: '1.0', dimension: 'people', enabled: true,
});

/** Existing criteria round-trip into raw rows (no rule parsing). */
export const rowsFromCriteria = (criteria?: AuthorityCriterion[] | null): CriterionRow[] =>
  (criteria || []).map((c) => {
    const copiedFrom = c.copied_from ?? null;
    return {
      rawRule: c.rule || '', copiedFrom,
      templateKey: copiedFrom?.kind === 'template' ? (copiedFrom.key ?? null) : null,
      clauseRef: c.policy_clause_ref || '',
      name: c.name || '', failureMessage: c.failure_message || '',
      direction: c.direction || 'neutral', weight: String(c.weight ?? 1.0),
      dimension: c.dimension || 'people',
      enabled: c.enabled ?? true,
    };
  });

/** The rule a row will submit (builder-generated or raw). */
export function ruleForRow(r: CriterionRow): string {
  return r.rawRule.trim();
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
  /** Clause labels are offered only when the AR cites a policy reference (ARF 1.2.0). */
  citable?: boolean;
  onChange: (rows: CriterionRow[]) => void;
  /** Hides the Add check menu and the row remove buttons (AR is not editable). */
  readOnly?: boolean;
  /** The AR's scoped parameters (ODRL slice 1): accepted from the dialog; ctx./req. completion is not wired here yet. */
  params?: Record<string, any>;
  scopeKeys?: string[];
}

type ChecksState = 'loading' | 'ready' | 'failed';

export default function CriteriaBuilder({ rows, onChange, readOnly = false, clauses = [], citable = false, params = {}, scopeKeys = [] }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const { get, post } = useApi();
  const [checks, setChecks] = useState<ReusableCheck[]>([]);
  const [checksState, setChecksState] = useState<ChecksState>('loading');
  const [templates, setTemplates] = useState<AuthorityCriterionTemplate[]>([]);
  const [validation, setValidation] = useState<Record<number, { passed: boolean; message?: string | null }>>({});
  // The raw rule editors, by row, so a variable is inserted at the cursor.
  const rawRefs = useRef<Record<number, HTMLTextAreaElement | null>>({});

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
      ...emptyCriterionRow(),
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
      ...emptyCriterionRow(),
      rawRule: c.rule,
      name: c.name,
      failureMessage: c.failure_message || '',
      copiedFrom: { kind: 'compliance', label: c.name, id: c.id },
    });

  // The variables a rule may use: the AR's parameters (ctx.<key>) and the request
  // fields (req.<key>: the scope keys and the standard request fields).
  const variables = [
    ...Object.keys(params).map((k) => `ctx.${k}`),
    ...Array.from(new Set([...scopeKeys.filter(Boolean), ...Object.keys(SAMPLE_REQUEST)])).map((k) => `req.${k}`),
  ];

  const insertVariable = (idx: number, v: string) => {
    const rule = rows[idx].rawRule;
    const el = rawRefs.current[idx];
    const start = el ? el.selectionStart : rule.length;
    const end = el ? el.selectionEnd : rule.length;
    const before = rule.slice(0, start);
    const after = rule.slice(end);
    const pad = before && !/\s$/.test(before) ? ' ' : '';
    const tail = after && !/^\s/.test(after) ? ' ' : '';
    const caret = (before + pad + v).length;
    patch(idx, { rawRule: `${before}${pad}${v}${tail}${after}` });
    if (el) setTimeout(() => { el.focus(); el.setSelectionRange(caret, caret); }, 0);
  };

  // Validates the rule on the sample request, with the AR's parameters as ctx.<key> and
  // its scope keys as req.<key>: the same evaluation a resolve uses.
  const validate = async (idx: number) => {
    const { data } = await post<{ passed: boolean; message?: string | null }>('/api/authority/criteria/validate', {
      rule: rows[idx].rawRule.trim(),
      object: SAMPLE_REQUEST,
      context: Object.fromEntries(scopeKeys.filter(Boolean).map((k) => [k, ''])),
      params,
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
          ) : (
            <div className="space-y-1">
              <Input
                value={r.name}
                onChange={(e) => patch(idx, { name: e.target.value })}
                placeholder={t('criteria.fields.criterionNamePlaceholder')}
              />
              <Textarea
                ref={(el) => { rawRefs.current[idx] = el; }}
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
            {citable && <ClauseSelect value={r.clauseRef} clauses={clauses} onChange={(clauseRef) => patch(idx, { clauseRef })} />}
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
            <DropdownMenuItem onSelect={() => addRow(emptyCriterionRow())}>
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
