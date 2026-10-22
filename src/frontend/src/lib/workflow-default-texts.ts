import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import type { i18n as I18n, TFunction } from 'i18next';

/**
 * Translation of the texts the shipped default workflows show to users
 * (wizard step titles, descriptions and field labels, from
 * `src/backend/src/data/default_workflows.yaml`).
 *
 * The workflows store these texts in English. A text is translated only while
 * it is exactly the shipped English one, found in the `workflowDefaults`
 * namespace of the English bundle; a text an admin changed in the Workflow
 * Designer has no entry and is shown as written. Nothing is stored with the
 * workflow, so Load Defaults and edits need no extra handling.
 */
export const WORKFLOW_DEFAULTS_NS = 'workflowDefaults';

let index: Map<string, string> | null = null;
let indexedBundle: unknown = null;

function collect(node: unknown, path: string[], out: Map<string, string>): void {
  if (typeof node === 'string') {
    if (!out.has(node)) out.set(node, path.join('.'));
  } else if (node && typeof node === 'object') {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      collect(value, [...path, key], out);
    }
  }
}

/** Key of a shipped English text in the `workflowDefaults` namespace, if any. */
export function defaultTextKey(i18n: I18n, text: string): string | undefined {
  const bundle = i18n.getResourceBundle?.('en', WORKFLOW_DEFAULTS_NS);
  if (!bundle) return undefined;
  if (index === null || indexedBundle !== bundle) {
    index = new Map();
    indexedBundle = bundle;
    collect(bundle, [], index);
  }
  // Surrounding whitespace is ignored on purpose: it doesn't change what the
  // user reads, so a shipped text with spaces added around it still counts as
  // the shipped one and is translated.
  return index.get(text.trim());
}

/** The text in the user's language when it is a shipped default, else as configured. */
export function translateDefaultText(
  t: TFunction,
  i18n: I18n,
  text: string | undefined | null,
): string | undefined {
  if (!text) return text ?? undefined;
  const key = defaultTextKey(i18n, text);
  return key ? t(`${WORKFLOW_DEFAULTS_NS}:${key}`, { defaultValue: text }) : text;
}

/** Hook form of {@link translateDefaultText} for components. */
export function useDefaultWorkflowText(): (text: string | undefined | null) => string | undefined {
  const { t, i18n } = useTranslation(WORKFLOW_DEFAULTS_NS);
  return useCallback((text) => translateDefaultText(t, i18n, text), [t, i18n]);
}
