/**
 * Conversions between stored (atomic) ODRL rules and the rule-builder form model,
 * plus human-readable rendering of rules and constraints.
 */
import type { OdrlConstraint, OdrlRef, OdrlRule, OdrlRules, RuleKind } from '@/types/access-policy';
import { ASSET_COLLECTION_IRI_PREFIX, AUDIENCE_IRI_PREFIX } from '@/types/access-policy';

export const RULE_KINDS: RuleKind[] = ['permission', 'prohibition', 'obligation'];
export const LIST_OPERATORS = ['isAnyOf', 'isAllOf', 'isNoneOf'];

/** Actions offered for data rules vs. duty/obligation rules. */
export const DUTY_ACTIONS = ['ontos:acknowledgeTerms', 'ontos:obtainApproval', 'ontos:recertify', 'inform', 'delete', 'anonymize'];
export const REMEDY_ACTIONS = ['delete', 'anonymize', 'inform'];

export interface FormConstraint {
  leftOperand: string;
  operator: string;
  value: string;
}

export type TargetMode = 'asset' | 'collection';
export type AssigneeMode = 'everyone' | 'audience' | 'principal';

export interface FormRule {
  key: string;
  kind: RuleKind;
  action: string;
  targetMode: TargetMode;
  target: string;
  assigneeMode: AssigneeMode;
  assignee: string;
  constraints: FormConstraint[];
  /** Duty actions (permission) or remedy actions (prohibition). */
  duties: string[];
  /** ODRL rule uid, preserved so external references keep resolving. */
  uid?: string;
}

let keySeq = 0;
export const newRuleKey = () => `r${++keySeq}`;

export function emptyRule(kind: RuleKind = 'permission'): FormRule {
  return {
    key: newRuleKey(),
    kind,
    action: kind === 'obligation' ? 'ontos:recertify' : 'read',
    targetMode: 'asset',
    target: '',
    assigneeMode: 'audience',
    assignee: '',
    constraints: [],
    duties: [],
  };
}

export function constraintToForm(c: OdrlConstraint): FormConstraint | null {
  if (c.logical || !c.leftOperand) return null;
  const v = c.rightOperand;
  const value = Array.isArray(v) ? v.map(String).join(', ') : v === undefined || v === null ? '' : String(v);
  return { leftOperand: c.leftOperand, operator: c.operator || 'eq', value };
}

export function formToConstraint(c: FormConstraint): OdrlConstraint {
  const raw = c.value.trim();
  let right: unknown = raw;
  if (LIST_OPERATORS.includes(c.operator)) {
    right = raw.split(',').map((s) => s.trim()).filter(Boolean);
  } else if (/^-?\d+(\.\d+)?$/.test(raw) && !/^\d{4}-/.test(raw)) {
    right = Number(raw);
  }
  return { leftOperand: c.leftOperand, operator: c.operator, rightOperand: right };
}

/** Convert stored rules to the form model; returns null when a rule can't be represented (use JSON mode). */
export function rulesToForm(rules: OdrlRules | undefined): FormRule[] | null {
  const out: FormRule[] = [];
  for (const kind of RULE_KINDS) {
    for (const r of rules?.[kind] || []) {
      if ((r.target && typeof r.target !== 'string') || (r.assignee && typeof r.assignee !== 'string')) return null;
      if (r.action_refinement?.length || r.assigner) return null;
      const constraints: FormConstraint[] = [];
      for (const c of r.constraint || []) {
        const fc = constraintToForm(c);
        if (!fc) return null;
        constraints.push(fc);
      }
      // Anything the builder can't round-trip goes to the JSON editor instead of being dropped.
      if (kind === 'obligation' && (r.duty?.length || r.remedy?.length || r.consequence?.length)) return null;
      if (r.consequence?.length) return null;
      const subs = kind === 'prohibition' ? r.remedy : r.duty;
      if (subs?.some((d) => d.constraint?.length || d.target || d.assignee || d.assigner || d.consequence?.length || d.uid)) return null;
      const target = (r.target as string) || '';
      const assignee = (r.assignee as string) || '';
      out.push({
        key: newRuleKey(),
        kind,
        action: r.action || '',
        targetMode: target.startsWith(ASSET_COLLECTION_IRI_PREFIX) ? 'collection' : 'asset',
        target,
        assigneeMode: !assignee ? 'everyone' : assignee.startsWith(AUDIENCE_IRI_PREFIX) ? 'audience' : 'principal',
        assignee,
        constraints,
        duties: (subs || []).map((d) => d.action || '').filter(Boolean),
        uid: r.uid,
      });
    }
  }
  return out;
}

export function formToRules(rules: FormRule[]): OdrlRules {
  const out: OdrlRules = { permission: [], prohibition: [], obligation: [] };
  for (const r of rules) {
    const rule: OdrlRule = { action: r.action };
    if (r.uid) rule.uid = r.uid;
    if (r.target.trim()) rule.target = r.target.trim();
    if (r.assigneeMode !== 'everyone' && r.assignee.trim()) rule.assignee = r.assignee.trim();
    const cons = r.constraints.filter((c) => c.leftOperand && c.value.trim()).map(formToConstraint);
    if (cons.length) rule.constraint = cons;
    if (r.duties.length) {
      const subs = r.duties.map((a) => ({ action: a }));
      if (r.kind === 'prohibition') rule.remedy = subs;
      else if (r.kind === 'permission') rule.duty = subs;
    }
    out[r.kind]!.push(rule);
  }
  return out;
}

/** Builder-level checks the backend can't catch (an empty picker silently means "everyone"). */
export function formRuleProblems(rules: FormRule[]): string[] {
  const problems: string[] = [];
  rules.forEach((r, i) => {
    const n = i + 1;
    if (r.kind !== 'obligation' && !r.target.trim()) problems.push(`Rule ${n}: pick a target`);
    if (r.assigneeMode !== 'everyone' && !r.assignee.trim()) problems.push(`Rule ${n}: pick an assignee or choose "Everyone"`);
  });
  return problems;
}

export function formatValue(v: unknown): string {
  if (Array.isArray(v)) return v.map(formatValue).join(', ');
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('@value' in o) return String(o['@value']);
    if ('@id' in o) return String(o['@id']);
    return JSON.stringify(v);
  }
  return String(v ?? '');
}

export function describeConstraint(c: OdrlConstraint, labelFor: (k: string) => string = (k) => k): string {
  if (c.logical) {
    const parts = (c.constraints || []).map((x) => describeConstraint(x, labelFor));
    return `(${parts.join(` ${c.logical.toUpperCase()} `)})`;
  }
  return `${labelFor(c.leftOperand || '?')} ${c.operator || '?'} ${formatValue(c.rightOperand ?? c.rightOperandReference)}`;
}

export function describeRef(ref: OdrlRef | undefined, nameForIri: (iri: string) => string | null): string {
  if (!ref) return '';
  if (typeof ref === 'string') return nameForIri(ref) || ref;
  const base = ref.source || ref.uid || (ref.members || []).join(', ') || ref['@type'] || 'collection';
  const named = nameForIri(base) || base;
  const refine = (ref.refinement || []).map((c) => describeConstraint(c)).join(' AND ');
  return refine ? `${named} where ${refine}` : named;
}
