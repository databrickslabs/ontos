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

// Params holding an enum value that has its own translation (status names, rule kinds).
const RELEASE_STATUS_CODES = new Set(['release_transition', 'deliver_status']);

function translatedParams(t: TFunction, code: string, params: Record<string, unknown>): Record<string, unknown> {
  const statusNs = RELEASE_STATUS_CODES.has(code) ? 'releases.status' : 'status';
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    const text = String(value);
    if (key === 'status' || key === 'from' || key === 'to') {
      out[key] = t(`access-policies:${statusNs}.${text}`, { defaultValue: text });
    } else if (key === 'kind' && ['permission', 'prohibition', 'obligation'].includes(text)) {
      out[key] = t(`access-policies:ruleKinds.${text}`, { defaultValue: text });
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
