import type { TFunction } from 'i18next';

/**
 * Known internal graph names / API pseudo-row `name` values (not user taxonomies).
 * Keys use the semantic-models namespace as default when calling `t`.
 */
const SYSTEM_RDF_NAMESPACE_KEYS: Record<string, { i18nKey: string; defaultLabel: string }> = {
  'urn:meta:sources': {
    i18nKey: 'rdfSources.systemNamespaces.metaSources',
    defaultLabel: 'Source registry metadata',
  },
  'urn:semantic-links': {
    i18nKey: 'rdfSources.systemNamespaces.semanticLinks',
    defaultLabel: 'Semantic links',
  },
  'urn:x-rdflib:default': {
    i18nKey: 'rdfSources.systemNamespaces.rdflibDefault',
    defaultLabel: 'Default graph',
  },
  /** Same human-facing intent as bundled collection metadata (Collections tab labels). */
  'urn:app-entities': {
    i18nKey: 'rdfSources.systemNamespaces.appEntities',
    defaultLabel: 'App Entities',
  },
  'urn:demo': {
    i18nKey: 'rdfSources.systemNamespaces.demoGraph',
    defaultLabel: 'Demo business concepts',
  },
};

/**
 * Human-readable label for internal RDF graph keys, or the original key if unknown.
 * Pass `t` from `useTranslation('semantic-models')` (or ['semantic-models', …] with semantic-models first).
 */
export function systemRdfNamespaceDisplayLabel(
  graphKey: string,
  t: TFunction<'semantic-models', undefined> | TFunction,
): string {
  const entry = SYSTEM_RDF_NAMESPACE_KEYS[graphKey];
  if (!entry) return graphKey;
  return t(entry.i18nKey, { defaultValue: entry.defaultLabel });
}
