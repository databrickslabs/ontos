import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import i18n from 'i18next';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { useConceptMode } from '@/components/concepts/mode-switch';
import KGSearch from '@/components/search/kg-search';

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
  Code2,
  X,
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
import { useExploreConcepts, useExploreSessionStore } from '@/hooks/use-explore-concepts';
import {
  ConceptsTab,
  GraphTab,
  CollectionEditorDialog,
  ConceptEditorDialog,
  GlossaryFilterPanel,
  ImportConceptsDialog,
} from '@/components/knowledge';
import { allowedConceptTypes } from '@/components/knowledge/concept-editor-dialog';

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

// Concept types the Create menu can preset, in menu order per scheme type.
type CreatableConceptType = 'term' | 'concept' | 'class' | 'property';

const CREATE_ITEMS: Record<CreatableConceptType, { labelKey: string; defaultLabel: string }> = {
  term: { labelKey: 'concepts:explore.createTerm', defaultLabel: 'New Term' },
  concept: { labelKey: 'concepts:explore.createConcept', defaultLabel: 'New Concept' },
  class: { labelKey: 'concepts:explore.createClass', defaultLabel: 'New Class' },
  property: { labelKey: 'concepts:explore.createProperty', defaultLabel: 'New Property' },
};

const CREATE_TYPES_BY_SCHEME: Record<string, CreatableConceptType[]> = {
  glossary: ['term'],
  taxonomy: ['concept'],
  ontology: ['class', 'property', 'concept'],
};

// Generic set (no single scheme in focus), in display order.
const GENERIC_CREATE_TYPES: CreatableConceptType[] = ['concept', 'term', 'class', 'property'];

/**
 * Create-menu concept types for the scheme in focus. A known scheme type gets
 * its own set; otherwise the generic set, limited to types at least one
 * editable scheme accepts (all of them when no scheme is known).
 */
export function createMenuTypes(
  focused: KnowledgeCollection | undefined,
  editable: KnowledgeCollection[],
): CreatableConceptType[] {
  const byScheme = focused?.collection_type ? CREATE_TYPES_BY_SCHEME[focused.collection_type] : undefined;
  if (byScheme) return byScheme;
  if (editable.length === 0) return GENERIC_CREATE_TYPES;
  return GENERIC_CREATE_TYPES.filter((ct) =>
    editable.some((c) => allowedConceptTypes(c.collection_type).includes(ct)),
  );
}

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

  // SPARQL / knowledge-graph search panel: Advanced view only, session-only
  // open state (not persisted, not in the URL).
  const [conceptMode] = useConceptMode();
  const advanced = conceptMode === 'advanced';
  const [sparqlOpen, setSparqlOpen] = useState(false);

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

  // Session-only "Show system ontologies" toggle (default OFF). The hook reads
  // the same store and refetches with include_system=true when it is on.
  const showSystemSources = useExploreSessionStore((s) => s.showSystemSources);
  const setShowSystemSources = useExploreSessionStore((s) => s.setShowSystemSources);

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
  // Create-menu preset: the concept type and target scheme for a new concept.
  const [createConceptType, setCreateConceptType] = useState<CreatableConceptType | undefined>(undefined);
  const [createCollection, setCreateCollection] = useState<KnowledgeCollection | undefined>(undefined);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  // Language selection - defaults to UI language
  const [selectedLanguage, setSelectedLanguage] = useState<string>(i18n.language?.split('-')[0] || 'en');

  const {
    hiddenSources,
    groupByDimension,
    groupBySource,
    groupByFile,
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
      { label: t('semantic-models:title', 'Concepts'), path: '/concepts' },
      { label: t('semantic-models:tabs.explore', 'Explore'), path: '/concepts/browser' },
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
  const handleCreateConcept = (conceptType: CreatableConceptType) => {
    setEditingConcept(null);
    setCreateConceptType(conceptType);
    // Target the focused scheme; otherwise the first editable scheme that
    // accepts this type (the dialog re-validates if the user switches scheme).
    setCreateCollection(
      focusedCollection ??
        editableCollections.find((c) => allowedConceptTypes(c.collection_type).includes(conceptType)) ??
        defaultCollection,
    );
    setConceptEditorOpen(true);
  };

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
      // Bump the shared nonce ONLY (useExploreConcepts does a single quiet
      // reload) — AND defer it a tick past the dialog close. Firing the list
      // re-render in the same tick as the Radix dialog close raced its
      // focus-restore + aria-hidden/scroll-lock cleanup, which could leave
      // <#root aria-hidden> / body pointer-events:none stuck = "can't click
      // anything" until the next render. Deferring lets the dialog fully settle.
      setTimeout(() => bumpKnowledgeGraphRefresh(isNew ? 'concept-create' : 'concept-update'), 0);
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
      // Bump the shared nonce ONLY (single quiet reload), deferred a tick past
      // the dialog close so the list re-render doesn't race the Radix dialog's
      // focus-restore + aria-hidden/scroll-lock cleanup (see handleSaveConcept).
      setTimeout(() => bumpKnowledgeGraphRefresh(isNew ? 'collection-create' : 'collection-update'), 0);
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
      // Bump the shared nonce ONLY (single quiet reload via the hook's subscriber).
      bumpKnowledgeGraphRefresh('collection-delete');
    } catch (error: any) {
      toast({ title: t('common:toast.error'), description: error.message, variant: 'destructive' });
    }
  }, [t, toast, bumpKnowledgeGraphRefresh]);

  const editableCollections = useMemo(() => collections.filter((c) => c.is_editable), [collections]);
  const defaultCollection = editableCollections[0];

  // The scheme the user is working in: the only editable scheme, or the only
  // editable scheme left visible by the source filter. Otherwise none (the
  // Create menu then offers the generic set).
  const focusedCollection = useMemo(() => {
    if (editableCollections.length === 1) return editableCollections[0];
    const visible = editableCollections.filter(
      (c) => !hiddenSources.includes(stripSourcePrefix(c.iri)),
    );
    return visible.length === 1 ? visible[0] : undefined;
  }, [editableCollections, hiddenSources]);
  const createTypes = createMenuTypes(focusedCollection, editableCollections);

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
          {advanced && (
            <Button
              variant={sparqlOpen ? 'secondary' : 'outline'}
              className="adv-only"
              aria-pressed={sparqlOpen}
              aria-controls="explore-sparql-panel"
              onClick={() => setSparqlOpen((open) => !open)}
            >
              <Code2 className="h-4 w-4 mr-2" />
              {t('concepts:explore.sparql', 'SPARQL')}
            </Button>
          )}
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
                  {createTypes.map((ct) => (
                    <DropdownMenuItem key={ct} onClick={() => handleCreateConcept(ct)}>
                      <Plus className="h-4 w-4 mr-2" />
                      {t(CREATE_ITEMS[ct].labelKey, CREATE_ITEMS[ct].defaultLabel)}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={handleCreateCollection}>
                    <FolderTree className="h-4 w-4 mr-2" />
                    {t('concepts:explore.createScheme', 'New Concept Scheme')}
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

      {/* SPARQL / knowledge-graph search: full-width inline panel above the
          results (Advanced view only). Not bound to any one concept. */}
      {advanced && sparqlOpen && (
        <section
          id="explore-sparql-panel"
          data-testid="explore-sparql-panel"
          aria-label={t('concepts:explore.sparqlPanel', 'SPARQL and knowledge graph search')}
          className="adv-only mb-4 rounded-lg border bg-card p-4 min-h-[420px]"
        >
          <div className="flex items-center justify-between gap-2 mb-3">
            <h2 className="text-sm font-medium">
              {t('concepts:explore.sparqlPanel', 'SPARQL and knowledge graph search')}
            </h2>
            <Button
              variant="ghost"
              size="icon"
              title={t('common:actions.close', 'Close')}
              aria-label={t('common:actions.close', 'Close')}
              onClick={() => setSparqlOpen(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <KGSearch />
        </section>
      )}

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
            showSystemSources={showSystemSources}
            onSetShowSystemSources={setShowSystemSources}
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
              showRootBadges={!groupBySource && !groupByFile}
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
              groupByFile={groupByFile}
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
        collection={editingConcept ? undefined : (createCollection ?? defaultCollection)}
        collections={editableCollections}
        initialConceptType={editingConcept ? undefined : createConceptType}
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
