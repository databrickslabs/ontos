import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import i18n from 'i18next';
import { useTranslation } from 'react-i18next';
import {
  Network,
} from 'lucide-react';
import { GraphCanvasSkeleton } from '@/components/common/list-view-skeleton';
import type {
  OntologyConcept,
  GroupedConcepts,
} from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import {
  GraphTab,
  GlossaryFilterPanel,
} from '@/components/knowledge';

export default function OntologyHomeView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const navigate = useNavigate();

  // Data state
  const [isLoading, setIsLoading] = useState(true);
  const [groupedConcepts, setGroupedConcepts] = useState<GroupedConcepts>({});
  const [groupedProperties, setGroupedProperties] = useState<Record<string, OntologyConcept[]>>({});
  const [hiddenRoots, setHiddenRoots] = useState<Set<string>>(new Set());

  // Language selection - defaults to UI language
  const [selectedLanguage, setSelectedLanguage] = useState<string>(i18n.language?.split('-')[0] || 'en');

  // Glossary preferences from persistent store
  const {
    hiddenSources,
    groupBySource,
    showProperties,
    groupByDomain,
    isFilterExpanded,
    toggleSource,
    selectAllSources,
    selectNoneSources,
    setGroupBySource,
    setShowProperties,
    setGroupByDomain,
    setFilterExpanded,
  } = useGlossaryPreferencesStore();

  // Extract unique source contexts
  const availableSources = useMemo(() => {
    const allConcepts = Object.values(groupedConcepts).flat();
    const allProperties = Object.values(groupedProperties).flat();
    const sources = new Set<string>();
    allConcepts.forEach((c) => { if (c.source_context) sources.add(c.source_context); });
    allProperties.forEach((p) => { if (p.source_context) sources.add(p.source_context); });
    return Array.from(sources).sort();
  }, [groupedConcepts, groupedProperties]);

  // Per-source concept counts (unaffected by filter/dedup — shows what each source contains)
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

  // Breadcrumbs
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('common:terms.viewGraph', { defaultValue: 'View Graph' }));
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [setStaticSegments, setDynamicTitle, t]);

  // Fetch data
  const fetchData = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/semantic-models/concepts-grouped');
      if (res.ok) {
        const data = await res.json();
        setGroupedConcepts(data.grouped_concepts || {});
      }
    } catch (error) {
      console.error('Failed to fetch concepts:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch properties when toggle is enabled
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

  // Refetch when other views (Settings rebuild, ontology generator save,
  // collection/concept edits) bump the global knowledge-graph nonce.
  const knowledgeGraphRefreshNonce = useKnowledgeGraphStore((s) => s.refreshNonce);
  useEffect(() => {
    if (knowledgeGraphRefreshNonce > 0) {
      fetchData();
    }
  }, [knowledgeGraphRefreshNonce, fetchData]);

  // Navigate to concept in Business Terms view on node click
  const handleNodeClick = useCallback((concept: OntologyConcept) => {
    navigate(`/semantic-models?concept=${encodeURIComponent(concept.iri)}`);
  }, [navigate]);

  // Toggle root visibility in the graph
  const handleToggleRoot = useCallback((rootIri: string) => {
    setHiddenRoots((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(rootIri)) {
        newSet.delete(rootIri);
      } else {
        newSet.add(rootIri);
      }
      return newSet;
    });
  }, []);

  return (
    <div className="flex flex-col py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Network className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">{t('common:terms.viewGraph', { defaultValue: 'View Graph' })}</h1>
            <p className="text-sm text-muted-foreground">
              {filteredConcepts.length} {t('common:terms.concepts')}
            </p>
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading ? (
        <div className="flex-1">
          <GraphCanvasSkeleton showFilterPanel showToolbar={false} height="h-[600px]" />
        </div>
      ) : (
        <div className="flex-1 flex flex-col">
          {/* Filter Panel */}
          <GlossaryFilterPanel
            filteredConcepts={filteredConcepts}
            sourceConceptCounts={sourceConceptCounts}
            availableSources={availableSources}
            hiddenSources={hiddenSources}
            onToggleSource={toggleSource}
            onSelectAllSources={selectAllSources}
            onSelectNoneSources={selectNoneSources}
            groupBySource={groupBySource}
            showProperties={showProperties}
            groupByDomain={groupByDomain}
            onSetGroupBySource={setGroupBySource}
            onSetShowProperties={setShowProperties}
            onSetGroupByDomain={setGroupByDomain}
            selectedLanguage={selectedLanguage}
            onSetSelectedLanguage={setSelectedLanguage}
            isFilterExpanded={isFilterExpanded}
            onSetFilterExpanded={setFilterExpanded}
          />

          {/* View Graph */}
          <GraphTab
            concepts={filteredConcepts}
            hiddenRoots={hiddenRoots}
            onToggleRoot={handleToggleRoot}
            onNodeClick={handleNodeClick}
            showRootBadges={!groupBySource}
            selectedLanguage={selectedLanguage}
          />
        </div>
      )}
    </div>
  );
}
