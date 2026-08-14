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
import { cn } from '@/lib/utils';

// Strip known URN prefixes so an incoming ?source= (which may be a full IRI
// like urn:glossary:test) matches availableSources (which are already stripped).
function stripSourcePrefix(iri: string): string {
  const prefixes = ['urn:glossary:', 'urn:taxonomy:', 'urn:ontology:', 'urn:semantic-model:', 'urn:schema:'];
  for (const prefix of prefixes) {
    if (iri.startsWith(prefix)) {
      return iri.slice(prefix.length);
    }
  }
  return iri;
}
import {
  FolderTree,
  Plus,
  ChevronDown,
  Upload,
  List,
  Network,
  Globe2,
  type LucideIcon,
} from 'lucide-react';
import {
  FilterBarSkeleton,
  HierarchyTreeSkeleton,
} from '@/components/common/list-view-skeleton';
import type { OntologyConcept, KnowledgeCollection } from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useToast } from '@/hooks/use-toast';
import { useExploreConcepts } from '@/hooks/use-explore-concepts';
import {
  ConceptsTab,
  GraphTab,
  CollectionEditorDialog,
  ConceptEditorDialog,
  GlossaryFilterPanel,
  ImportConceptsDialog,
} from '@/components/knowledge';

// ---------------------------------------------------------------------------
// Explore — the ONE unified browse surface for concepts.
//
// A single fetch (via useExploreConcepts) feeds three render engines as
// interchangeable view-modes over the SAME filtered selection:
//   - List / Tree -> ConceptsTab (unchanged engine)
//   - Graph        -> GraphTab (unchanged cytoscape engine)
//
// Filters + Group-by (GlossaryFilterPanel) drive all modes. SPARQL search and
// the instance/estate hierarchy are intentionally NOT view-modes here; they
// live on their own routes (see app.tsx / concepts-layout.tsx).
// ---------------------------------------------------------------------------

type ViewMode = 'list' | 'tree' | 'graph';

const VIEW_MODES: { id: ViewMode; labelKey: string; defaultLabel: string; icon: LucideIcon }[] = [
  { id: 'list', labelKey: 'concepts:explore.viewList', defaultLabel: 'List', icon: List },
  { id: 'tree', labelKey: 'concepts:explore.viewTree', defaultLabel: 'Tree', icon: Network },
  { id: 'graph', labelKey: 'concepts:explore.viewGraph', defaultLabel: 'Graph', icon: Globe2 },
];

function parseViewMode(value: string | null): ViewMode {
  if (value === 'tree' || value === 'graph') return value;
  return 'list';
}

export default function ExploreView() {
  const { t } = useTranslation(['semantic-models', 'common', 'concepts']);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);

  const canWrite = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  // Single source of concept data — fetch + filteredConcepts live here.
  const {
    isLoading,
    collections,
    groupedConcepts,
    availableSources,
    sourceConceptCounts,
    filteredConcepts,
    refetch,
  } = useExploreConcepts();

  // View-mode: List | Tree | Graph. Kept in the URL (?view=) so links are
  // shareable and refresh-safe; defaults to List.
  const viewMode = parseViewMode(searchParams.get('view'));
  const setViewMode = useCallback(
    (mode: ViewMode) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (mode === 'list') next.delete('view');
          else next.set('view', mode);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // hiddenRoots stays LOCAL to Graph mode (user decision). List/Tree ignore it
  // and it is never lifted into the shared store.
  const [hiddenRoots, setHiddenRoots] = useState<Set<string>>(new Set());

  // Dialog state
  const [collectionEditorOpen, setCollectionEditorOpen] = useState(false);
  const [editingCollection, setEditingCollection] = useState<KnowledgeCollection | null>(null);
  const [conceptEditorOpen, setConceptEditorOpen] = useState(false);
  const [editingConcept, setEditingConcept] = useState<OntologyConcept | null>(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  // Language selection - defaults to UI language
  const [selectedLanguage, setSelectedLanguage] = useState<string>(i18n.language?.split('-')[0] || 'en');

  const {
    hiddenSources,
    groupByDimension,
    groupBySource,
    showProperties,
    groupByDomain,
    isFilterExpanded,
    toggleSource,
    setHiddenSources,
    selectAllSources,
    selectNoneSources,
    setGroupByDimension,
    setShowProperties,
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

  // Breadcrumbs
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  useEffect(() => {
    setStaticSegments([
      { label: t('semantic-models:title'), path: '/concepts/browser' },
    ]);
    return () => { setStaticSegments([]); };
  }, [setStaticSegments, t]);

  // Handle ?source= URL parameter for filtering (from home breakdown / Author).
  // Normalize the incoming param by stripping known URN prefixes (it may be a
  // full IRI) before comparing against availableSources (already stripped).
  //
  // Apply the filter in ONE idempotent set (hide every source except the target)
  // and then consume the ?source= param, so this runs once per deep-link. It must
  // NOT depend on or react to hiddenSources: an earlier version toggled sources
  // one-by-one and depended on hiddenSources, so each toggle re-fired the effect
  // — an infinite loop that froze the page. If the target isn't found, leave the
  // filter as-is (no blank page) but still consume the param.
  useEffect(() => {
    const sourceParam = searchParams.get('source');
    if (!sourceParam || availableSources.length === 0) return;

    const normalizedTarget = stripSourcePrefix(sourceParam);
    if (availableSources.includes(normalizedTarget)) {
      // Show only the target: hide everything else, in a single set.
      setHiddenSources(availableSources.filter((s) => s !== normalizedTarget));
    }
    // Consume the param either way so the effect can't re-fire on it.
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('source');
        return next;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, availableSources]);

  // Concept selection (List/Tree row click) — navigate to dedicated detail page.
  const handleSelectConcept = useCallback((concept: OntologyConcept) => {
    navigate(`/concepts/browser/${encodeURIComponent(concept.iri)}`);
  }, [navigate]);

  // Graph node click — same destination as a list row (unified detail page).
  const handleNodeClick = useCallback((concept: OntologyConcept) => {
    navigate(`/concepts/browser/${encodeURIComponent(concept.iri)}`);
  }, [navigate]);

  // Toggle root visibility in the graph (graph-local state only).
  const handleToggleRoot = useCallback((rootIri: string) => {
    setHiddenRoots((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(rootIri)) newSet.delete(rootIri);
      else newSet.add(rootIri);
      return newSet;
    });
  }, []);

  // Concept CRUD handlers (creation flow only; edit/delete live on detail page).
  const handleCreateConcept = () => setConceptEditorOpen(true);

  const handleSaveConcept = async (data: any, isNew: boolean) => {
    try {
      const response = await fetch('/api/knowledge/concepts', {
        method: 'POST',
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
      await refetch();
      bumpKnowledgeGraphRefresh(isNew ? 'concept-create' : 'concept-update');
    } catch (error: any) {
      toast({ title: t('common:toast.error'), description: error.message, variant: 'destructive' });
      throw error;
    }
  };

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
      await refetch();
      bumpKnowledgeGraphRefresh(isNew ? 'collection-create' : 'collection-update');
    } catch (error: any) {
      toast({ title: t('common:toast.error'), description: error.message, variant: 'destructive' });
      throw error;
    }
  };

  // Handle rename scheme from filter panel — open the collection editor in edit mode
  const handleRenameScheme = useCallback((collection: KnowledgeCollection) => {
    setEditingCollection(collection);
    setCollectionEditorOpen(true);
  }, []);

  // Handle delete scheme from filter panel
  const handleDeleteScheme = useCallback(async (collection: KnowledgeCollection) => {
    try {
      const response = await fetch(`/api/knowledge/collections/${encodeURIComponent(collection.iri)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete collection');
      }
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.collectionDeleted'),
      });
      await refetch();
      bumpKnowledgeGraphRefresh('collection-delete');
    } catch (error: any) {
      toast({ title: t('common:toast.error'), description: error.message, variant: 'destructive' });
    }
  }, [t, toast, refetch, bumpKnowledgeGraphRefresh]);

  const editableCollections = useMemo(() => collections.filter((c) => c.is_editable), [collections]);
  const defaultCollection = editableCollections[0];

  return (
    <div className="flex flex-col pt-3 pb-6">
      {/* Header — page description only (the section tab strip already names
          "Concepts"/"Explore"; the Simple/Advanced switch lives up in the tab
          row). Kept tight to the nav boundary to avoid a blank gap. */}
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {t(
              'concepts:explore.description',
              'Author, browse, and deliver your business concept schemes.'
            )}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
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
                    <Plus className="h-4 w-4 mr-2" />
                    {t('concepts:explore.createConcept', 'New concept')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleCreateCollection}>
                    <FolderTree className="h-4 w-4 mr-2" />
                    {t('concepts:explore.createScheme', 'New concept scheme')}
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

      {isLoading ? (
        <div className="flex-1 flex flex-col gap-4">
          <FilterBarSkeleton filterCount={3} />
          <HierarchyTreeSkeleton groups={4} itemsPerGroup={4} />
        </div>
      ) : (
        <div className="flex-1 flex flex-col gap-4">
          {/* Filter Panel — drives ALL view-modes (unchanged component). */}
          <GlossaryFilterPanel
            filteredConcepts={filteredConcepts}
            sourceConceptCounts={sourceConceptCounts}
            availableSources={availableSources}
            hiddenSources={hiddenSources}
            onToggleSource={toggleSource}
            onSelectAllSources={selectAllSources}
            onSelectNoneSources={selectNoneSources}
            groupByDimension={groupByDimension}
            onSetGroupByDimension={setGroupByDimension}
            showProperties={showProperties}
            onSetShowProperties={setShowProperties}
            selectedLanguage={selectedLanguage}
            onSetSelectedLanguage={setSelectedLanguage}
            isFilterExpanded={isFilterExpanded}
            onSetFilterExpanded={setFilterExpanded}
            collections={collections}
            onRenameScheme={handleRenameScheme}
            onDeleteScheme={handleDeleteScheme}
          />

          {/* View-mode switch: List | Tree | Graph */}
          <div
            role="tablist"
            aria-label={t('concepts:explore.viewLabel', 'Explore views')}
            className="inline-flex items-center gap-1 rounded-lg border bg-card p-1 self-start"
          >
            {VIEW_MODES.map((mode) => {
              const active = mode.id === viewMode;
              return (
                <button
                  key={mode.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setViewMode(mode.id)}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
                    active
                      ? 'bg-accent text-accent-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  )}
                >
                  <mode.icon className="h-4 w-4 shrink-0" />
                  {t(mode.labelKey, mode.defaultLabel)}
                </button>
              );
            })}
          </div>

          {/* Surface — same filteredConcepts feeds every mode.
              List and Tree both render through ConceptsTab, which now honours a
              genuine viewMode: 'list' renders a flat alphabetical list, 'tree'
              renders the broader/narrower hierarchy. Graph uses GraphTab. */}
          {viewMode === 'graph' ? (
            <GraphTab
              concepts={filteredConcepts}
              hiddenRoots={hiddenRoots}
              onToggleRoot={handleToggleRoot}
              onNodeClick={handleNodeClick}
              showRootBadges={!groupBySource}
              selectedLanguage={selectedLanguage}
            />
          ) : (
            <ConceptsTab
              collections={collections}
              groupedConcepts={groupedConcepts}
              filteredConcepts={filteredConcepts}
              selectedConcept={null}
              onSelectConcept={handleSelectConcept}
              groupBySource={groupBySource}
              showProperties={showProperties}
              groupByDomain={groupByDomain}
              selectedLanguage={selectedLanguage}
              viewMode={viewMode === 'tree' ? 'tree' : 'list'}
              onEditConcept={(concept) => {
                setEditingConcept(concept);
                setConceptEditorOpen(true);
              }}
              onConceptsChanged={refetch}
            />
          )}
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

      {/* Concept Editor Dialog (edit from list or create from action bar) */}
      <ConceptEditorDialog
        open={conceptEditorOpen}
        onOpenChange={(open) => {
          setConceptEditorOpen(open);
          if (!open) setEditingConcept(null);
        }}
        concept={editingConcept}
        collection={editingConcept ? undefined : defaultCollection}
        collections={editableCollections}
        onSave={handleSaveConcept}
      />

      {/* Import Dialog */}
      <ImportConceptsDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        collections={collections}
        onImported={refetch}
      />
    </div>
  );
}
