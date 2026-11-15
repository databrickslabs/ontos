/**
 * Translated text for what the Access Policies backend reports: validation issues, compile issues,
 * activation problems, route errors, SHACL results and ODRL profile labels.
 *
 * The backend sends a stable `code` and `params` next to its English `message`; the text is looked up
 * as `access-policies:issues.<code>` and falls back to the message when a key is missing.
 */
import type { TFunction } from 'i18next';

export interface Coded {
  code?: string | null;
  params?: Record<string, unknown> | null;
  message?: string | null;
}

/** A rule's label in the user's language: `Sales analytics read · Erlaubnis #1`. */
export function ruleLabel(t: TFunction, s: { policy_name: string; rule_kind: string; rule_index: number }): string {
  const kind = t(`access-policies:ruleKinds.${s.rule_kind}`, { defaultValue: s.rule_kind });
  return `${s.policy_name} · ${kind} #${s.rule_index + 1}`;
}

// Params holding an enum value that has its own translation (status names, rule and entity kinds).
const RELEASE_STATUS_CODES = new Set(['release_transition', 'deliver_status']);
const RULE_KINDS = ['permission', 'prohibition', 'obligation'];
const ENTITY_KINDS = ['policy', 'audience', 'asset_collection', 'target'];
const ABAC_KINDS = ['row_filter', 'column_mask'];
// The backend's English rule label (RuleSource.label): `<policy> <kind> #<n>`.
const RULE_LABEL = /^(.*) (permission|prohibition|obligation) #(\d+)$/;

function translatedParams(t: TFunction, code: string, params: Record<string, unknown>): Record<string, unknown> {
  const statusNs = RELEASE_STATUS_CODES.has(code) ? 'releases.status' : 'status';
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      // A list of coded problems (e.g. what blocks an activation): each translated.
      out[key] = value.map((v) => (v && typeof v === 'object' ? issueText(t, v as Coded) : String(v))).join('; ');
      continue;
    }
    const text = String(value);
    const label = key === 'rule' ? RULE_LABEL.exec(text) : null;
    if (key === 'status' || key === 'from' || key === 'to') {
      out[key] = t(`access-policies:${statusNs}.${text}`, { defaultValue: text });
    } else if (key === 'kind' && RULE_KINDS.includes(text)) {
      out[key] = t(`access-policies:ruleKinds.${text}`, { defaultValue: text });
    } else if (key === 'kind' && ENTITY_KINDS.includes(text)) {
      out[key] = t(`access-policies:kinds.${text}`, { defaultValue: text });
    } else if (key === 'kind' && ABAC_KINDS.includes(text)) {
      out[key] = t(`access-policies:abacKinds.${text}`, { defaultValue: text });
    } else if (label) {
      out[key] = ruleLabel(t, { policy_name: label[1], rule_kind: label[2], rule_index: Number(label[3]) - 1 });
    } else {
      out[key] = value;
    }
  }
  return out;
}

/** The translated text of one coded item, or its English message. */
export function issueText(t: TFunction, item: Coded | string | null | undefined): string {
  if (item == null) return '';
  if (typeof item === 'string') return item;
  const message = item.message ?? '';
  if (!item.code || item.code === 'message') return message;
  return t(`access-policies:issues.${item.code}`, {
    ...translatedParams(t, item.code, item.params ?? {}),
    defaultValue: message,
  });
}

/** The translated error of an API response (`useApi`), or `fallback` when it has none. */
export function errorText(
  t: TFunction,
  res: { error?: string | null; errorCode?: string | null; errorParams?: Record<string, unknown> | null },
  fallback = '',
): string {
  if (!res.error) return fallback;
  if (!res.errorCode) return res.error;
  return issueText(t, { code: res.errorCode, params: res.errorParams, message: res.error });
}

/** A profile key as a translation key segment (`ontos:browse` → `ontos_browse`). */
export const profileKey = (key: string): string => key.replace(/[:.]/g, '_');

export const actionLabel = (t: TFunction, key: string, label?: string | null): string =>
  t(`access-policies:profile.actions.${profileKey(key)}.label`, { defaultValue: label || key });

export const actionDescription = (t: TFunction, key: string, description?: string | null): string =>
  t(`access-policies:profile.actions.${profileKey(key)}.description`, { defaultValue: description || '' });

export const operandLabel = (t: TFunction, key: string, label?: string | null): string =>
  t(`access-policies:profile.operands.${profileKey(key)}.label`, { defaultValue: label || key });

export const operandDescription = (t: TFunction, key: string, description?: string | null): string =>
  t(`access-policies:profile.operands.${profileKey(key)}.description`, { defaultValue: description || '' });

export const operatorLabel = (t: TFunction, key: string, label?: string | null): string =>
  t(`access-policies:profile.operators.${profileKey(key)}`, { defaultValue: label || key });

/** `http://www.w3.org/ns/odrl/2/target` → `target`. */
export const localName = (iri?: string | null): string => (iri ? iri.split(/[#/]/).pop() || iri : '');

/** A SHACL result, translated per constraint component (falls back to the shape's message). */
export function shaclText(
  t: TFunction,
  r: { constraint?: string | null; message?: string | null; path?: string | null; focus?: string | null },
): string {
  const message = r.message ?? '';
  if (!r.constraint) return message;
  return t(`access-policies:shacl.constraint.${r.constraint}`, {
    path: localName(r.path) || t('access-policies:shacl.thePolicy'),
    defaultValue: message,
  });
}
