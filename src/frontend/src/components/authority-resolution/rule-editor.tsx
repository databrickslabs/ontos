import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import NativeSelect from '@/components/ui/native-select';
import { useApi } from '@/hooks/use-api';
import { CheckCircle2, Loader2, Plus, Trash2, XCircle } from 'lucide-react';
import { InfoHint } from '@/components/authority-resolution/info-hint';
import {
  ARF_DIRECTIONS, ODRL_OPERATORS, RULE_REQUEST_OPERANDS, operandForKey, operandKey,
  type ArfRule, type DivergenceFacets, type DomainContext, type OdrlConstraint,
  type OdrlOperator, type PolicyClause, type RuleConstraint,
} from '@/types/authority-resolution';

/**
 * The AR's ODRL-shaped rule (#1294): permission constraints (a failure denies),
 * duties (unfulfilled = the decision is conditional, e.g. a pending
 * co-approval) and prohibitions (matched = denied). Each condition compares a
 * request field or context key with a value or a variable (`ctx.<param>`,
 * `req.<key>`); alternatives combine as any-of / all-of. Derived and aggregate
 * logic stays in the Compliance Checks below.
 */

export type ItemKind = 'constraint' | 'duty' | 'prohibition';
const CUSTOM = '__custom__';
const LITERAL = '';

export interface PartDraft {
  operand: string;      // a RULE_REQUEST_OPERANDS operand, or CUSTOM
  customKey: string;    // request-context key when operand = CUSTOM
  operator: OdrlOperator;
  ref: string;          // variable (ctx.x / req.y), or LITERAL
  value: string;        // literal; comma list for isAnyOf / isNoneOf
}

export interface ItemDraft extends Required<Pick<DivergenceFacets, 'name' | 'message' | 'direction' | 'dimension' | 'clause'>> {
  kind: ItemKind;
  action: string;       // duty action
  join: 'or' | 'and';
  parts: PartDraft[];
  weight: string;
  rawJson?: string;     // shapes the editor can't show (nested logic) round-trip as JSON
}

const emptyPart = (): PartDraft => ({ operand: 'payAmount', customKey: '', operator: 'lteq', ref: LITERAL, value: '' });

export const emptyItem = (kind: ItemKind): ItemDraft => ({
  kind,
  action: kind === 'duty' ? 'arf:obtainCoApproval' : '',
  join: 'or',
  parts: [kind === 'constraint' ? emptyPart() : { ...emptyPart(), operand: 'arf:cosignPresent', operator: 'eq', value: 'true' }],
  name: '', message: '', clause: '',
  direction: kind === 'duty' ? 'documented-exceeds-actual' : 'actual-exceeds-documented',
  weight: '1.0', dimension: 'policy',
});

// ------------------------------------------------------------ load / save

const isLogical = (c: RuleConstraint): c is { or?: OdrlConstraint[]; and?: OdrlConstraint[] } & DivergenceFacets =>
  'or' in c || 'and' in c;

function partFrom(c: OdrlConstraint): PartDraft {
  const known = RULE_REQUEST_OPERANDS.some((o) => o.operand === c.leftOperand);
  const v = c.rightOperand;
  return {
    operand: known ? c.leftOperand : CUSTOM,
    customKey: known ? '' : operandKey(c.leftOperand),
    operator: c.operator,
    ref: c.rightOperandReference || LITERAL,
    value: Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v),
  };
}

function facetsFrom(f: DivergenceFacets, kind: ItemKind) {
  const base = emptyItem(kind);
  return {
    name: f.name || '', message: f.message || '', clause: f.clause || '',
    direction: f.direction || base.direction,
    weight: f.weight != null ? String(f.weight) : '1.0',
    dimension: f.dimension || 'policy',
  };
}

/** Editor items from a stored rule. A constraint list (duty / prohibition)
 * reads as all-of; a logical constraint as its any-of / all-of parts. */
function itemFrom(kind: ItemKind, constraints: RuleConstraint[], facets: DivergenceFacets, action = ''): ItemDraft {
  const base: ItemDraft = { ...emptyItem(kind), ...facetsFrom(facets, kind), action };
  const flat = constraints.length === 1 && isLogical(constraints[0])
    ? { join: ('or' in constraints[0] ? 'or' : 'and') as 'or' | 'and', parts: (constraints[0].or || constraints[0].and || []) as RuleConstraint[] }
    : { join: 'and' as const, parts: constraints };
  if (flat.parts.some(isLogical)) {
    return { ...base, rawJson: JSON.stringify(constraints, null, 2) };
  }
  return { ...base, join: flat.join, parts: (flat.parts as OdrlConstraint[]).map(partFrom) };
}

export function itemsFromRule(rule?: ArfRule | null): ItemDraft[] {
  if (!rule) return [];
  const out: ItemDraft[] = [];
  for (const c of rule.permission?.constraint || []) {
    out.push(itemFrom('constraint', isLogical(c) ? [c] : [c], c));
  }
  for (const d of rule.permission?.duty || []) out.push(itemFrom('duty', d.constraint || [], d, d.action));
  for (const p of rule.prohibition || []) out.push(itemFrom('prohibition', p.constraint || [], p));
  return out;
}

const kindOf = (operand: string) => RULE_REQUEST_OPERANDS.find((o) => o.operand === operand)?.kind;

function literal(raw: string, kind?: 'number' | 'string' | 'boolean'): string | number | boolean {
  const s = raw.trim();
  if (kind === 'number' || (!kind && s !== '' && Number.isFinite(Number(s)))) {
    const n = Number(s);
    return Number.isFinite(n) ? n : s;
  }
  if (kind === 'boolean' || (!kind && (s === 'true' || s === 'false'))) return s === 'true';
  return s;
}

function constraintFrom(p: PartDraft): OdrlConstraint {
  const leftOperand = p.operand === CUSTOM ? operandForKey(p.customKey) : p.operand;
  const out: OdrlConstraint = { leftOperand, operator: p.operator };
  if (p.ref) {
    out.rightOperandReference = p.ref;
  } else {
    const kind = p.operand === CUSTOM ? undefined : kindOf(p.operand);
    out.rightOperand = p.operator === 'isAnyOf' || p.operator === 'isNoneOf'
      ? p.value.split(',').map((v) => v.trim()).filter(Boolean).map((v) => literal(v, kind))
      : literal(p.value, kind);
  }
  return out;
}

function facetsOut(it: ItemDraft): DivergenceFacets {
  const f: DivergenceFacets = { direction: it.direction, dimension: it.dimension || 'policy' };
  const w = parseFloat(it.weight);
  f.weight = Number.isFinite(w) ? w : 1.0;
  if (it.name.trim()) f.name = it.name.trim();
  if (it.message.trim()) f.message = it.message.trim();
  if (it.clause.trim()) f.clause = it.clause.trim();
  return f;
}

/** The rule payload, or `null` when there's nothing to enforce. Throws on bad JSON. */
export function ruleFromItems(items: ItemDraft[]): ArfRule | null {
  const constraint: RuleConstraint[] = [];
  const duty: NonNullable<NonNullable<ArfRule['permission']>['duty']> = [];
  const prohibition: NonNullable<ArfRule['prohibition']> = [];
  for (const it of items) {
    let list: RuleConstraint[];
    if (it.rawJson != null) {
      list = JSON.parse(it.rawJson);
    } else {
      const parts = it.parts.map(constraintFrom);
      if (!parts.length) continue;
      list = parts.length === 1 ? parts
        : it.kind === 'constraint' || it.join === 'or' ? [{ [it.join]: parts } as RuleConstraint]
          : parts;  // duty / prohibition: a list is all-of
    }
    const f = facetsOut(it);
    if (it.kind === 'constraint') {
      list.forEach((c) => constraint.push({ ...c, ...f }));
    } else if (it.kind === 'duty') {
      duty.push({ action: it.action.trim() || 'arf:obtainCoApproval', constraint: list, ...f });
    } else {
      prohibition.push({ constraint: list, ...f });
    }
  }
  if (!constraint.length && !duty.length && !prohibition.length) return null;
  const rule: ArfRule = { permission: { constraint, duty } };
  if (prohibition.length) rule.prohibition = prohibition;
  return rule;
}

// ------------------------------------------------------------ component

/** "Implements clause" picker; keeps a cited ref that is no longer on the policy. */
export function ClauseSelect({ value, clauses, onChange }: { value: string; clauses: PolicyClause[]; onChange: (ref: string) => void }) {
  const { t } = useTranslation(['authority-resolution']);
  return (
    <div className="flex items-center gap-1">
      <Label className="text-xs whitespace-nowrap">{t('policy.citation.clause')}</Label>
      <NativeSelect className="w-40" selectClassName="h-8 text-xs" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {clauses.map((c) => <option key={c.ref} value={c.ref}>{c.ref}{c.title ? ` ${c.title}` : ''}</option>)}
        {value && !clauses.some((c) => c.ref === value) && <option value={value}>{value}</option>}
      </NativeSelect>
    </div>
  );
}

interface Props {
  items: ItemDraft[];
  onChange: (items: ItemDraft[]) => void;
  /** Parameter keys (ctx.<key>) and scope keys (req.<key>) offered as variables. */
  paramKeys: string[];
  scopeKeys: string[];
  /** Current domain context, for server-side validation. */
  domainContext?: DomainContext;
  /** Clauses of the cited Authority Policy; each item may cite the one it implements. */
  clauses?: PolicyClause[];
}

export default function RuleEditor({ items, onChange, paramKeys, scopeKeys, domainContext, clauses = [] }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const { post } = useApi();
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<{ valid: boolean; error?: string; compiled?: { kind: string; name: string; rule: string }[] } | null>(null);

  const variables = [
    ...paramKeys.filter(Boolean).map((k) => `ctx.${k}`),
    ...Array.from(new Set([...scopeKeys.filter(Boolean), ...RULE_REQUEST_OPERANDS.map((o) => o.field)])).map((k) => `req.${k}`),
  ];

  const patch = (i: number, p: Partial<ItemDraft>) => onChange(items.map((it, j) => (j === i ? { ...it, ...p } : it)));
  const patchPart = (i: number, k: number, p: Partial<PartDraft>) =>
    patch(i, { parts: items[i].parts.map((part, j) => (j === k ? { ...part, ...p } : part)) });

  const validate = async () => {
    let rule: ArfRule | null;
    try {
      rule = ruleFromItems(items);
    } catch {
      setValidation({ valid: false, error: t('rule.validation.badJson') });
      return;
    }
    setValidating(true);
    const { data, error } = await post<{ valid: boolean; error?: string; compiled: { kind: string; name: string; rule: string }[] }>(
      '/api/authority/rule/validate', { rule, domain_context: domainContext },
    );
    setValidating(false);
    setValidation(error ? { valid: false, error } : data);
  };

  return (
    <div className="space-y-3">
      {items.map((it, i) => (
        <div key={i} className="rounded-md border p-3 space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant={it.kind === 'prohibition' ? 'destructive' : it.kind === 'duty' ? 'secondary' : 'default'}>
              {t(`rule.kind.${it.kind}`)}
            </Badge>
            {it.kind === 'duty' && (
              <Input value={it.action} onChange={(e) => patch(i, { action: e.target.value })}
                     className="h-7 w-56 text-xs font-mono" placeholder="arf:obtainCoApproval" />
            )}
            <span className="text-xs text-muted-foreground">{t(`rule.kindHint.${it.kind}`)}</span>
            <div className="flex-1" />
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onChange(items.filter((_, j) => j !== i))}
                    aria-label={t('rule.buttons.remove')}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>

          {it.rawJson != null ? (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">{t('rule.rawJsonHint')}</p>
              <Textarea value={it.rawJson} onChange={(e) => patch(i, { rawJson: e.target.value })} rows={4} className="font-mono text-xs" />
            </div>
          ) : (
            <div className="space-y-1.5">
              {it.parts.map((p, k) => (
                <div key={k} className="flex flex-wrap items-center gap-1.5">
                  {k > 0 && <span className="text-xs text-muted-foreground w-10">{t(`rule.join.${it.join}Word`)}</span>}
                  <NativeSelect className="w-40" selectClassName="h-8 text-xs" value={p.operand}
                                onChange={(e) => patchPart(i, k, { operand: e.target.value })}>
                    {RULE_REQUEST_OPERANDS.map((o) => (
                      <option key={o.operand} value={o.operand}>{t(`rule.operand.${o.field}`, { defaultValue: o.operand })}</option>
                    ))}
                    <option value={CUSTOM}>{t('rule.operand.custom')}</option>
                  </NativeSelect>
                  {p.operand === CUSTOM && (
                    <Input value={p.customKey} onChange={(e) => patchPart(i, k, { customKey: e.target.value })}
                           list={`rule-scope-keys-${i}-${k}`} placeholder={t('rule.customKeyPlaceholder')}
                           className="h-8 w-36 text-xs font-mono" />
                  )}
                  {p.operand === CUSTOM && (
                    <datalist id={`rule-scope-keys-${i}-${k}`}>
                      {scopeKeys.filter(Boolean).map((key) => <option key={key} value={key} />)}
                    </datalist>
                  )}
                  <NativeSelect className="w-28" selectClassName="h-8 text-xs" value={p.operator}
                                onChange={(e) => patchPart(i, k, { operator: e.target.value as OdrlOperator })}>
                    {ODRL_OPERATORS.map((op) => <option key={op} value={op}>{t(`rule.operator.${op}`)}</option>)}
                  </NativeSelect>
                  <NativeSelect className="w-36" selectClassName="h-8 text-xs" value={p.ref}
                                onChange={(e) => patchPart(i, k, { ref: e.target.value })}>
                    <option value={LITERAL}>{t('rule.rightValue')}</option>
                    {variables.map((v) => <option key={v} value={v}>{v}</option>)}
                    {p.ref && !variables.includes(p.ref) && <option value={p.ref}>{p.ref}</option>}
                  </NativeSelect>
                  {!p.ref && (kindOf(p.operand) === 'boolean' && p.operator !== 'isAnyOf' && p.operator !== 'isNoneOf' ? (
                    <NativeSelect className="w-24" selectClassName="h-8 text-xs" value={p.value || 'true'}
                                  onChange={(e) => patchPart(i, k, { value: e.target.value })}>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </NativeSelect>
                  ) : (
                    <Input value={p.value} onChange={(e) => patchPart(i, k, { value: e.target.value })}
                           placeholder={t(p.operator === 'isAnyOf' || p.operator === 'isNoneOf' ? 'rule.valueListPlaceholder' : 'rule.valuePlaceholder')}
                           className="h-8 w-32 text-xs" />
                  ))}
                  {it.parts.length > 1 && (
                    <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={t('rule.buttons.removeAlternative')}
                            onClick={() => patch(i, { parts: it.parts.filter((_, j) => j !== k) })}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => patch(i, { parts: [...it.parts, emptyPart()] })}>
                  <Plus className="h-3.5 w-3.5 mr-1" /> {t('rule.buttons.addCondition')}
                </Button>
                {it.parts.length > 1 && (
                  <NativeSelect className="w-36" selectClassName="h-7 text-xs" value={it.join}
                                onChange={(e) => patch(i, { join: e.target.value as 'or' | 'and' })}>
                    <option value="or">{t('rule.join.or')}</option>
                    <option value="and">{t('rule.join.and')}</option>
                  </NativeSelect>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <Input value={it.name} onChange={(e) => patch(i, { name: e.target.value })}
                   placeholder={t('rule.namePlaceholder')} className="h-8 text-xs" />
            <Input value={it.message} onChange={(e) => patch(i, { message: e.target.value })}
                   placeholder={t(`rule.messagePlaceholder.${it.kind}`)} className="h-8 text-xs" />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.direction')}</Label>
              <NativeSelect className="w-56" selectClassName="h-8 text-xs" value={it.direction}
                            onChange={(e) => patch(i, { direction: e.target.value })}>
                {ARF_DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{t(`direction.${d.value}`, { defaultValue: d.label })}</option>)}
              </NativeSelect>
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs">{t('criteria.divergence.weight')}</Label>
              <Input value={it.weight} onChange={(e) => patch(i, { weight: e.target.value })} className="h-8 w-16 text-xs" />
            </div>
            <div className="flex items-center gap-1">
              <Label className="text-xs whitespace-nowrap">{t('criteria.divergence.dimension')}</Label>
              <Input value={it.dimension} onChange={(e) => patch(i, { dimension: e.target.value })}
                     className="h-8 w-24 text-xs" placeholder="policy" />
            </div>
            {(clauses.length > 0 || it.clause) && (
              <ClauseSelect value={it.clause} clauses={clauses} onChange={(clause) => patch(i, { clause })} />
            )}
          </div>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        {(['constraint', 'duty', 'prohibition'] as ItemKind[]).map((k) => (
          <Button key={k} variant="outline" size="sm" onClick={() => onChange([...items, emptyItem(k)])}>
            <Plus className="h-4 w-4 mr-1" /> {t(`rule.buttons.add.${k}`)}
          </Button>
        ))}
        {items.length > 0 && (
          <Button variant="outline" size="sm" onClick={validate} disabled={validating}>
            {validating && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            {t('criteria.validation.validateButton')}
          </Button>
        )}
        <InfoHint>{t('rule.variablesHint')}</InfoHint>
      </div>

      {validation && (
        <div className="rounded-md border p-2 space-y-1">
          <div className={`text-xs flex items-center gap-1 ${validation.valid ? 'text-green-600' : 'text-red-600'}`}>
            {validation.valid ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
            {validation.valid ? t('rule.validation.valid') : validation.error}
          </div>
          {(validation.compiled || []).map((c, i) => (
            <div key={i} className="text-xs font-mono break-all">
              <span className="text-muted-foreground">[{t(`rule.kind.${c.kind}`, { defaultValue: c.kind })}]</span> {c.rule}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
