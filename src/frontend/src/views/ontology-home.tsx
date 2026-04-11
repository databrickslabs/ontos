import { useState, useEffect, useCallback, useMemo } from 'react';
import i18n from 'i18next';
import { useTranslation } from 'react-i18next';
import {
  Network,
  Loader2,
  Plus,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type {
  OntologyConcept,
  KnowledgeCollection,
  GroupedConcepts,
} from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useToast } from '@/hooks/use-toast';
import {
  GraphTab,
  GlossaryFilterPanel,
  ConceptEditorDialog,
  LinkEditorDialog,
} from '@/components/knowledge';
import { ConceptDetailPanel } from '@/components/semantic-models/concept-detail-panel';
import { GraphContextMenu } from '@/components/semantic-models/graph-context-menu';

export default function OntologyHomeView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  // Data state
  const [isLoading, setIsLoading] = useState(true);
  const [groupedConcepts, setGroupedConcepts] = useState<GroupedConcepts>({});
  const [groupedProperties, setGroupedProperties] = useState<Record<string, OntologyConcept[]>>({});
  const [hiddenRoots, setHiddenRoots] = useState<Set<string>>(new Set());
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);

  // Concept detail panel state
  const [selectedConceptIri, setSelectedConceptIri] = useState<string | null>(null);
  const [selectedConceptData, setSelectedConceptData] = useState<OntologyConcept | null>(null);

  // Concept editor state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorConcept, setEditorConcept] = useState<OntologyConcept | null>(null);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; concept?: OntologyConcept;
  } | null>(null);

  // Link draw state (click-to-connect mode)
  const [linkDrawSource, setLinkDrawSource] = useState<OntologyConcept | null>(null);
  const [linkTarget, setLinkTarget] = useState<OntologyConcept | null>(null);
  const [linkEditorOpen, setLinkEditorOpen] = useState(false);

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
      const [conceptsRes, collectionsRes] = await Promise.all([
        fetch('/api/semantic-models/concepts-grouped'),
        fetch('/api/knowledge/collections?hierarchical=true'),
      ]);
      if (conceptsRes.ok) {
        const data = await conceptsRes.json();
        setGroupedConcepts(data.grouped_concepts || {});
      }
      if (collectionsRes.ok) {
        const data = await collectionsRes.json();
        setCollections(data.collections || []);
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

  // Open detail panel on node click (instead of navigating away)
  const handleNodeClick = useCallback((concept: OntologyConcept) => {
    setSelectedConceptIri(concept.iri);
    setSelectedConceptData(concept);
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedConceptIri(null);
    setSelectedConceptData(null);
  }, []);

  const handleEditConcept = useCallback((concept: OntologyConcept) => {
    setEditorConcept(concept);
    setEditorOpen(true);
  }, []);

  const handleSaveConcept = useCallback(async (data: any, isNew: boolean) => {
    try {
      if (!isNew && !editorConcept) return;
      const url = isNew
        ? '/api/knowledge/concepts'
        : `/api/knowledge/concepts/${encodeURIComponent(editorConcept!.iri)}`;
      const method = isNew ? 'POST' : 'PATCH';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save concept');
      }

      toast({
        title: t('common:toast.success'),
        description: isNew
          ? t('semantic-models:messages.conceptCreated')
          : t('semantic-models:messages.conceptUpdated'),
      });

      setEditorOpen(false);
      await fetchData();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
      throw error;
    }
  }, [editorConcept, fetchData, toast, t]);

  const handleDeleteConcept = useCallback(async (concept: OntologyConcept) => {
    if (!confirm(`Delete "${concept.label || concept.iri}"? This cannot be undone.`)) return;

    try {
      const response = await fetch(
        `/api/knowledge/concepts/${encodeURIComponent(concept.iri)}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete concept');
      }

      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.conceptDeleted'),
      });

      if (selectedConceptIri === concept.iri) {
        setSelectedConceptIri(null);
        setSelectedConceptData(null);
      }
      await fetchData();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  }, [selectedConceptIri, fetchData, toast, t]);

  // Right-click handlers for context menu
  const handleNodeRightClick = useCallback((concept: OntologyConcept, event: MouseEvent) => {
    setContextMenu({ x: event.clientX, y: event.clientY, concept });
  }, []);

  const handleBackgroundRightClick = useCallback((event: MouseEvent) => {
    setContextMenu({ x: event.clientX, y: event.clientY });
  }, []);

  // Link draw handlers (click-to-connect mode)
  const handleStartLinkDraw = useCallback((concept: OntologyConcept) => {
    setLinkDrawSource(concept);
  }, []);

  const handleLinkDraw = useCallback((source: OntologyConcept, target: OntologyConcept) => {
    setLinkDrawSource(source);
    setLinkTarget(target);
    setLinkEditorOpen(true);
  }, []);

  const handleLinkDrawCancel = useCallback(() => {
    setLinkDrawSource(null);
  }, []);

  const handleCreateLink = useCallback(async (relationshipType: string, targetIri?: string) => {
    if (!linkDrawSource || !targetIri) return;

    try {
      // Determine which relationship array to update based on type
      const conceptIri = linkDrawSource.iri;
      const update: Record<string, string[]> = {};

      if (relationshipType === 'broader') {
        update.broader_iris = [...(linkDrawSource.parent_concepts || []), targetIri];
      } else if (relationshipType === 'narrower') {
        update.narrower_iris = [...(linkDrawSource.child_concepts || []), targetIri];
      } else if (relationshipType === 'related') {
        update.related_iris = [...(linkDrawSource.related_concepts || []), targetIri];
      }

      const response = await fetch(
        `/api/knowledge/concepts/${encodeURIComponent(conceptIri)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(update),
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to create link');
      }

      toast({
        title: t('common:toast.success'),
        description: 'Relationship created successfully',
      });

      setLinkEditorOpen(false);
      setLinkDrawSource(null);
      setLinkTarget(null);
      await fetchData();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  }, [linkDrawSource, fetchData, toast, t]);

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
        {canWrite && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setEditorConcept(null); setEditorOpen(true); }}
          >
            <Plus className="h-4 w-4 mr-1" />
            {t('semantic-models:actions.newConcept', { defaultValue: 'New Concept' })}
          </Button>
        )}
      </div>

      {/* Loading state */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
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
            onNodeRightClick={canWrite ? handleNodeRightClick : undefined}
            onBackgroundRightClick={canWrite ? handleBackgroundRightClick : undefined}
            linkDrawSource={linkDrawSource?.iri ?? null}
            onLinkDraw={handleLinkDraw}
            onLinkDrawCancel={handleLinkDrawCancel}
            showRootBadges={!groupBySource}
          />
        </div>
      )}

      {/* Graph context menu (right-click on node or background) */}
      <GraphContextMenu
        position={contextMenu ? { x: contextMenu.x, y: contextMenu.y } : null}
        concept={contextMenu?.concept}
        onClose={() => setContextMenu(null)}
        onViewDetails={(concept) => {
          setSelectedConceptIri(concept.iri);
          setSelectedConceptData(concept);
        }}
        onEdit={canWrite ? handleEditConcept : undefined}
        onDelete={canWrite ? handleDeleteConcept : undefined}
        onCreateLink={canWrite ? handleStartLinkDraw : undefined}
        onCreateConcept={canWrite ? () => { setEditorConcept(null); setEditorOpen(true); } : undefined}
      />

      {/* Concept detail side panel (slides in from right on node click) */}
      <ConceptDetailPanel
        conceptIri={selectedConceptIri}
        conceptData={selectedConceptData}
        onClose={handleClosePanel}
        onNavigate={(iri) => { setSelectedConceptIri(iri); setSelectedConceptData(null); }}
        onEdit={canWrite ? handleEditConcept : undefined}
        onDelete={canWrite ? handleDeleteConcept : undefined}
      />

      {/* Concept editor dialog (create/edit) */}
      <ConceptEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        concept={editorConcept}
        collections={collections}
        onSave={handleSaveConcept}
      />

      {/* Link editor dialog (create relationship between concepts) */}
      <LinkEditorDialog
        open={linkEditorOpen}
        onOpenChange={(open) => {
          setLinkEditorOpen(open);
          if (!open) { setLinkDrawSource(null); setLinkTarget(null); }
        }}
        sourceConcept={linkDrawSource}
        targetConcept={linkTarget}
        allConcepts={filteredConcepts}
        onCreateLink={handleCreateLink}
      />
    </div>
  );
}
