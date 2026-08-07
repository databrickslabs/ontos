import { useState, useEffect, useCallback, useMemo } from 'react';
import type {
  OntologyConcept,
  KnowledgeCollection,
  GroupedConcepts,
  TaxonomyStats,
} from '@/types/ontology';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';

// ---------------------------------------------------------------------------
// use-explore-concepts — the SINGLE source of concept data for the unified
// Explore surface. Previously the fetch + filter/dedup memo was duplicated,
// byte-for-byte, in business-terms.tsx (List) and ontology-home.tsx (Graph).
// This hook lifts that logic up so List / Tree / Graph all read from ONE
// fetch and ONE `filteredConcepts` selection.
//
// Filtering is driven by the persistent `useGlossaryPreferencesStore`
// (hiddenSources / showProperties). Grouping is a display LENS handled inside
// the render engines; it does not change this set.
// ---------------------------------------------------------------------------

export interface UseExploreConceptsResult {
  isLoading: boolean;
  collections: KnowledgeCollection[];
  groupedConcepts: GroupedConcepts;
  groupedProperties: Record<string, OntologyConcept[]>;
  stats: TaxonomyStats | null;
  availableSources: string[];
  sourceConceptCounts: Record<string, number>;
  filteredConcepts: OntologyConcept[];
  totalConcepts: number;
  totalProperties: number;
  refetch: () => Promise<void>;
}

export function useExploreConcepts(): UseExploreConceptsResult {
  const [isLoading, setIsLoading] = useState(true);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [groupedConcepts, setGroupedConcepts] = useState<GroupedConcepts>({});
  const [groupedProperties, setGroupedProperties] = useState<Record<string, OntologyConcept[]>>({});
  const [stats, setStats] = useState<TaxonomyStats | null>(null);

  const showProperties = useGlossaryPreferencesStore((s) => s.showProperties);
  const hiddenSources = useGlossaryPreferencesStore((s) => s.hiddenSources);

  // Extract unique source contexts (unaffected by filter — for the panel).
  const availableSources = useMemo(() => {
    const allConcepts = Object.values(groupedConcepts).flat();
    const allProperties = Object.values(groupedProperties).flat();
    const sources = new Set<string>();
    allConcepts.forEach((c) => { if (c.source_context) sources.add(c.source_context); });
    allProperties.forEach((p) => { if (p.source_context) sources.add(p.source_context); });
    return Array.from(sources).sort();
  }, [groupedConcepts, groupedProperties]);

  // Per-source concept counts (unaffected by filter/dedup — shows what each
  // source contains).
  const sourceConceptCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const [source, concepts] of Object.entries(groupedConcepts)) {
      counts[source] = (counts[source] || 0) + concepts.length;
    }
    for (const [source, props] of Object.entries(groupedProperties)) {
      counts[source] = (counts[source] || 0) + props.length;
    }
    return counts;
  }, [groupedConcepts, groupedProperties]);

  // Filter concepts: apply source filter FIRST, then deduplicate by IRI.
  // This prevents cross-source deduplication from hiding concepts when the
  // user selects only one of several sources that share the same IRIs.
  const filteredConcepts = useMemo(() => {
    const allConcepts = Object.values(groupedConcepts).flat();
    const allProperties = showProperties ? Object.values(groupedProperties).flat() : [];
    const all = [...allConcepts, ...allProperties];

    const sourceFiltered = hiddenSources.length === 0
      ? all
      : all.filter(item => !item.source_context || !hiddenSources.includes(item.source_context));

    const seenIris = new Set<string>();
    const combined: OntologyConcept[] = [];
    for (const item of sourceFiltered) {
      if (!showProperties && item.concept_type === 'property') continue;
      if (!seenIris.has(item.iri)) {
        seenIris.add(item.iri);
        combined.push(item);
      }
    }
    return combined;
  }, [groupedConcepts, groupedProperties, hiddenSources, showProperties]);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [collectionsRes, conceptsRes, statsRes] = await Promise.all([
        fetch('/api/knowledge/collections?hierarchical=true'),
        fetch('/api/semantic-models/concepts-grouped'),
        fetch('/api/semantic-models/stats'),
      ]);

      if (collectionsRes.ok) {
        const data = await collectionsRes.json();
        setCollections(data.collections || []);
      }
      if (conceptsRes.ok) {
        const data = await conceptsRes.json();
        setGroupedConcepts(data.grouped_concepts || {});
      }
      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data.stats);
      }
    } catch (error) {
      console.error('Failed to fetch explore concepts:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchProperties = useCallback(async () => {
    try {
      const response = await fetch('/api/semantic-models/properties-grouped');
      if (!response.ok) throw new Error('Failed to fetch properties');
      const data = await response.json();

      const propsGrouped: Record<string, OntologyConcept[]> = {};
      for (const [source, props] of Object.entries(data.grouped_properties || {})) {
        propsGrouped[source] = (props as any[]).map((p: any) => ({
          ...p,
          properties: [],
          synonyms: [],
          examples: [],
        } as OntologyConcept));
      }
      setGroupedProperties(propsGrouped);
    } catch (err) {
      console.error('Failed to fetch properties:', err);
    }
  }, []);

  useEffect(() => {
    if (showProperties) {
      fetchProperties();
    } else {
      setGroupedProperties({});
    }
  }, [showProperties, fetchProperties]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Refetch when any other view (Settings/RDF Sources rebuild, ontology
  // generator save, concept/collection edits) bumps the global nonce.
  const knowledgeGraphRefreshNonce = useKnowledgeGraphStore((s) => s.refreshNonce);
  useEffect(() => {
    if (knowledgeGraphRefreshNonce > 0) {
      fetchData();
    }
  }, [knowledgeGraphRefreshNonce, fetchData]);

  const totalConcepts = stats?.total_concepts ?? Object.values(groupedConcepts).flat().length;
  const totalProperties = stats?.total_properties ?? Object.values(groupedProperties).flat().length;

  return {
    isLoading,
    collections,
    groupedConcepts,
    groupedProperties,
    stats,
    availableSources,
    sourceConceptCounts,
    filteredConcepts,
    totalConcepts,
    totalProperties,
    refetch: fetchData,
  };
}
