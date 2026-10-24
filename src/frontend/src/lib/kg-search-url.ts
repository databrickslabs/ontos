export type KgDirectionFilter = 'all' | 'incoming' | 'outgoing' | string;

export interface KgSearchUrlState {
  prefix: string;
  path: string[];
  sparql: string;
  directionFilter: KgDirectionFilter;
  showConceptsOnly: boolean;
}

export const DEFAULT_KG_SPARQL = 'SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10';

// Query-string keys owned by the knowledge-graph search. Every other key
// (e.g. ?view=, ?source=, ?concept= on the Explore page) belongs to the host
// page and must survive a search.
const KG_KEYS = ['prefix', 'path', 'sparql', 'direction', 'concepts_only'] as const;

/** Merge the search state into the current query string, keeping foreign keys. */
export function buildKgSearchParams(currentSearch: string, state: KgSearchUrlState): URLSearchParams {
  const params = new URLSearchParams(currentSearch);
  for (const key of KG_KEYS) params.delete(key);

  if (state.prefix) params.set('prefix', state.prefix);
  if (state.path.length > 0) params.set('path', state.path.join('|'));
  if (state.sparql && state.sparql !== DEFAULT_KG_SPARQL) params.set('sparql', state.sparql);
  if (state.directionFilter && state.directionFilter !== 'all') params.set('direction', state.directionFilter);
  if (state.showConceptsOnly) params.set('concepts_only', 'true');
  params.set('tab', 'kg');
  return params;
}
