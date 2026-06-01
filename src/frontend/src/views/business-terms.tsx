import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import i18n from 'i18next';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  FolderTree,
  Layers,
  Plus,
  ChevronDown,
  Upload,
} from 'lucide-react';
import {
  FilterBarSkeleton,
  HierarchyTreeSkeleton,
} from '@/components/common/list-view-skeleton';
import type {
  OntologyConcept,
  KnowledgeCollection,
  GroupedConcepts,
  TaxonomyStats,
} from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useToast } from '@/hooks/use-toast';
import {
  ConceptsTab,
  CollectionEditorDialog,
  ConceptEditorDialog,
  GlossaryFilterPanel,
  ImportConceptsDialog,
} from '@/components/knowledge';

export default function BusinessTermsView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);

  const canWrite = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  // Data state
  const [isLoading, setIsLoading] = useState(true);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [groupedConcepts, setGroupedConcepts] = useState<GroupedConcepts>({});
  const [groupedProperties, setGroupedProperties] = useState<Record<string, OntologyConcept[]>>({});
  const [stats, setStats] = useState<TaxonomyStats | null>(null);

  // Dialog state
  const [collectionEditorOpen, setCollectionEditorOpen] = useState(false);
  const [editingCollection, setEditingCollection] = useState<KnowledgeCollection | null>(null);
  const [conceptEditorOpen, setConceptEditorOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

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

  // Backwards-compat: the old single-page view tracked the selected concept
  // via ?concept=IRI. New layout uses /concepts/browser/:iri, so any old
  // deep link gets redirected once at mount.
  useEffect(() => {
    const conceptIri = searchParams.get('concept');
    if (!conceptIri) return;
    const decoded = (() => {
      try { return decodeURIComponent(conceptIri); } catch { return conceptIri; }
    })();
    navigate(`/concepts/browser/${encodeURIComponent(decoded)}`, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  useEffect(() => {
    setStaticSegments([
      { label: t('semantic-models:title'), path: '/concepts/browser' },
    ]);
    return () => { setStaticSegments([]); };
  }, [setStaticSegments, t]);

  // Fetch data
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
      console.error('Failed to fetch data:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Handle source URL parameter for filtering
  useEffect(() => {
    const sourceParam = searchParams.get('source');
    if (sourceParam && availableSources.length > 0) {
      const sourcesToHide = availableSources.filter(s => s !== sourceParam);
      sourcesToHide.forEach(source => {
        if (!hiddenSources.includes(source)) {
          toggleSource(source);
        }
      });
      if (hiddenSources.includes(sourceParam)) {
        toggleSource(sourceParam);
      }
    }
  }, [searchParams, availableSources, hiddenSources, toggleSource]);

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

  // Refetch when any other view (Settings/RDF Sources rebuild, ontology
  // generator save, etc.) bumps the global knowledge-graph nonce.
  const knowledgeGraphRefreshNonce = useKnowledgeGraphStore((s) => s.refreshNonce);
  useEffect(() => {
    if (knowledgeGraphRefreshNonce > 0) {
      fetchData();
    }
  }, [knowledgeGraphRefreshNonce, fetchData]);

  // Concept selection handler — navigates to dedicated detail page.
  const handleSelectConcept = useCallback((concept: OntologyConcept) => {
    navigate(`/concepts/browser/${encodeURIComponent(concept.iri)}`);
  }, [navigate]);

  // Concept CRUD handlers (creation flow only; edit/delete now live on the
  // detail page itself).
  const handleCreateConcept = () => {
    setConceptEditorOpen(true);
  };

  const handleSaveConcept = async (data: any, isNew: boolean) => {
    try {
      const url = '/api/knowledge/concepts';
      const method = 'POST';
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

      setConceptEditorOpen(false);
      await fetchData();
      bumpKnowledgeGraphRefresh(isNew ? 'concept-create' : 'concept-update');
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
      throw error;
    }
  };

  // Collection handlers (needed for create dropdown and collection editor)
  const handleCreateCollection = () => {
    setEditingCollection(null);
    setCollectionEditorOpen(true);
  };

  const handleSaveCollection = async (data: any, isNew: boolean) => {
    try {
      const url = isNew
        ? '/api/knowledge/collections'
        : `/api/knowledge/collections/${encodeURIComponent(editingCollection!.iri)}`;
      const method = isNew ? 'POST' : 'PATCH';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save collection');
      }

      toast({
        title: t('common:toast.success'),
        description: isNew
          ? t('semantic-models:messages.collectionCreated')
          : t('semantic-models:messages.collectionUpdated'),
      });

      setCollectionEditorOpen(false);
      await fetchData();
      bumpKnowledgeGraphRefresh(isNew ? 'collection-create' : 'collection-update');
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
      throw error;
    }
  };

  const editableCollections = collections.filter((c) => c.is_editable);
  const totalConcepts = stats?.total_concepts ?? Object.values(groupedConcepts).flat().length;
  const totalProperties = stats?.total_properties ?? Object.values(groupedProperties).flat().length;
  const selectedCollection = editableCollections[0] || null;

  return (
    <div className="flex flex-col py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Layers className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">{t('semantic-models:tabs.concepts')}</h1>
            <p className="text-sm text-muted-foreground">
              {totalConcepts} {t('common:terms.concepts')}
              {showProperties && ` / ${totalProperties} ${t('common:terms.properties')}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {canWrite && (
            <>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button>
                    <Plus className="h-4 w-4 mr-2" />
                    {t('common:actions.create')}
                    <ChevronDown className="h-4 w-4 ml-2" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={handleCreateConcept}>
                    <Layers className="h-4 w-4 mr-2" />
                    {t('semantic-models:actions.createConcept')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleCreateCollection}>
                    <FolderTree className="h-4 w-4 mr-2" />
                    {t('semantic-models:actions.createCollection')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <Button
                variant="outline"
                size="icon"
                title={t('common:actions.import')}
                onClick={() => setImportDialogOpen(true)}
              >
                <Upload className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Loading state */}
      {isLoading ? (
        <div className="flex-1 flex flex-col gap-4">
          <FilterBarSkeleton filterCount={3} />
          <HierarchyTreeSkeleton groups={4} itemsPerGroup={4} />
        </div>
      ) : (
        <div className="flex-1 flex flex-col gap-4">
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

          {/* Concepts list — full-width tree, navigates to detail page on row click */}
          <ConceptsTab
            collections={collections}
            groupedConcepts={groupedConcepts}
            filteredConcepts={filteredConcepts}
            selectedConcept={null}
            onSelectConcept={handleSelectConcept}
            onCreateConcept={handleCreateConcept}
            canEdit={canWrite}
            groupBySource={groupBySource}
            showProperties={showProperties}
            groupByDomain={groupByDomain}
            selectedLanguage={selectedLanguage}
          />
        </div>
      )}

      {/* Collection Editor Dialog */}
      <CollectionEditorDialog
        open={collectionEditorOpen}
        onOpenChange={setCollectionEditorOpen}
        collection={editingCollection}
        collections={collections}
        onSave={handleSaveCollection}
      />

      {/* Concept Editor Dialog (create-only from this view) */}
      <ConceptEditorDialog
        open={conceptEditorOpen}
        onOpenChange={setConceptEditorOpen}
        concept={null}
        collection={selectedCollection || editableCollections[0]}
        collections={editableCollections}
        onSave={handleSaveConcept}
      />

      {/* Import Dialog */}
      <ImportConceptsDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        collections={collections}
        onImported={fetchData}
      />
    </div>
  );
}
