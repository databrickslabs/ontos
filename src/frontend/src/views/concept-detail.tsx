import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import i18n from 'i18next';
import {
  ArrowLeft,
  AlertCircle,
  ExternalLink,
  Loader2,
  Pencil,
  Trash2,
  Layers,
  BookOpen,
  Zap,
  User,
  Network,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  SkeletonLine,
  PanelSkeleton,
} from '@/components/common/list-view-skeleton';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type {
  KnowledgeCollection,
  OntologyConcept,
} from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import { resolveLabel, resolveComment } from '@/lib/ontology-utils';
import { systemRdfNamespaceDisplayLabel } from '@/lib/system-rdf-namespace-labels';
import ConceptRelationsPanel from '@/components/semantic/concept-relations-panel';
import LinkedObjectsPanel from '@/components/semantic/linked-objects-panel';
import ConceptNeighborhoodGraph from '@/components/semantic/concept-neighborhood-graph';
import { ConceptEditorDialog } from '@/components/knowledge/concept-editor-dialog';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Layers className="h-5 w-5 text-emerald-500 shrink-0" />,
  class: <BookOpen className="h-5 w-5 text-blue-500 shrink-0" />,
  property: <Zap className="h-5 w-5 text-purple-500 shrink-0" />,
  individual: <User className="h-5 w-5 text-violet-500 shrink-0" />,
  term: <Layers className="h-5 w-5 text-emerald-500 shrink-0" />,
};

const typeColors: Record<string, string> = {
  concept: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  class: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  property: 'bg-purple-500/15 text-purple-700 dark:text-purple-400 border-purple-500/30',
  individual: 'bg-violet-500/15 text-violet-700 dark:text-violet-400 border-violet-500/30',
  term: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
};

// Bound list-like sections to ~10 rows of vertical real-estate via internal
// scrolling, so the page stays compact regardless of how many relations or
// linked objects a concept has.
const MAX_VISIBLE_ROWS = 10;

export default function ConceptDetailView() {
  const { iri: rawIri } = useParams<{ iri: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation(['semantic-models', 'common']);
  const { get } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);

  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  // The :iri segment is URL-encoded; double-decoding is harmless because
  // valid IRIs do not contain literal '%' characters in their canonical form.
  const conceptIri = useMemo(() => {
    if (!rawIri) return '';
    try {
      return decodeURIComponent(rawIri);
    } catch {
      return rawIri;
    }
  }, [rawIri]);

  const canWrite = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  const [concept, setConcept] = useState<OntologyConcept | null>(null);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [neighbourhoodOpen, setNeighbourhoodOpen] = useState(true);
  const selectedLanguage = i18n.language?.split('-')[0] || 'en';

  // Fetch the focused concept by IRI. This is intentionally separated from
  // the (lazier) neighbourhood load so the header renders ASAP.
  const fetchConcept = useCallback(async () => {
    if (!conceptIri) return;
    setIsLoading(true);
    setError(null);
    try {
      // Query-param form (``?iri=``) is required because some HTTP proxies
      // collapse ``%2F%2F`` in path segments, mangling IRIs like
      // ``http://ontos.example.org/...`` before they reach the backend.
      const res = await get<{ concept?: OntologyConcept }>(
        `/api/semantic-models/concepts/by-iri?iri=${encodeURIComponent(conceptIri)}`,
      );
      if (res.error || !res.data?.concept) {
        setError(res.error || 'Concept not found');
        setConcept(null);
        return;
      }
      setConcept(res.data.concept);
    } catch (err: any) {
      setError(err?.message || 'Failed to load concept');
      setConcept(null);
    } finally {
      setIsLoading(false);
    }
  }, [conceptIri, get]);

  // Collections are needed for source-context lookup (editability check) and
  // for the create/edit concept dialog. The relations panel itself loads
  // its data straight from the neighbours API and does not need a global
  // concept list.
  const fetchSupporting = useCallback(async () => {
    try {
      const res = await get<{ collections?: KnowledgeCollection[] }>(
        '/api/knowledge/collections?hierarchical=true',
      );
      if (res.data?.collections) {
        setCollections(res.data.collections);
      }
    } catch (err) {
      console.error('ConceptDetailView: failed to load collections', err);
    }
  }, [get]);

  useEffect(() => {
    fetchConcept();
  }, [fetchConcept]);

  useEffect(() => {
    fetchSupporting();
  }, [fetchSupporting]);

  // Keep breadcrumbs in sync with the concept the URL is pointing at.
  useEffect(() => {
    setStaticSegments([
      { label: t('semantic-models:title', 'Concepts'), path: '/concepts/browser' },
    ]);
    if (concept) {
      setDynamicTitle(resolveLabel(concept, selectedLanguage));
    } else {
      setDynamicTitle(null);
    }
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [concept, setStaticSegments, setDynamicTitle, selectedLanguage, t]);

  const collection = useMemo(() => {
    if (!concept?.source_context) return null;
    return (
      collections.find(
        (c) => c.iri === concept.source_context || c.iri.endsWith(`:${concept.source_context}`),
      ) || null
    );
  }, [collections, concept]);

  // Whether the concept *itself* can be modified (label, definition, status,
  // relations within the concept document). Restricted to draft concepts in
  // an editable collection, since imported ontologies (databricks-ontology,
  // SKOS, etc.) are read-only by design.
  const isEditable = useMemo(() => {
    if (!concept) return false;
    const isDraftStatus = !concept.status || concept.status === 'draft';
    return !!(canWrite && collection?.is_editable && isDraftStatus);
  }, [canWrite, collection, concept]);

  // Linking Ontos entities to a concept and assigning ownership are stored
  // *on our side* (semantic_links / ownership tables), not in the source
  // ontology. So they only require write permission on semantic-models --
  // they should work even for concepts that come from a read-only ontology.
  const canLinkEntities = canWrite;

  // Navigation between concepts (from in-graph clicks, link clicks, etc.)
  // updates the URL in place, which re-mounts the data effects via the new
  // :iri param. We use replace=false so browser-back works as expected.
  const handleNavigateToConcept = useCallback(
    (iri: string) => {
      if (!iri) return;
      navigate(`/concepts/browser/${encodeURIComponent(iri)}`);
    },
    [navigate],
  );

  const handleSaveConcept = async (data: any, isNew: boolean) => {
    if (!concept) return;
    try {
      const url = isNew
        ? '/api/knowledge/concepts'
        : `/api/knowledge/concepts/by-iri?iri=${encodeURIComponent(concept.iri)}`;
      const method = isNew ? 'POST' : 'PATCH';
      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({} as any));
        throw new Error(err?.detail || 'Failed to save concept');
      }
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.conceptUpdated'),
      });
      setEditorOpen(false);
      bumpKnowledgeGraphRefresh('concept-update');
      await fetchConcept();
      await fetchSupporting();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
      throw err;
    }
  };

  const handleDelete = async () => {
    if (!concept) return;
    try {
      const response = await fetch(
        `/api/knowledge/concepts/by-iri?iri=${encodeURIComponent(concept.iri)}`,
        { method: 'DELETE' },
      );
      if (!response.ok) {
        const err = await response.json().catch(() => ({} as any));
        throw new Error(err?.detail || 'Failed to delete concept');
      }
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.conceptDeleted'),
      });
      bumpKnowledgeGraphRefresh('concept-delete');
      navigate('/concepts/browser', { replace: true });
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
    }
  };

  // Mirrors the rendered concept detail: real back button, title block,
  // compact definition card, and two side panels (ownership/metadata + links).
  if (isLoading && !concept) {
    return (
      <div className="py-6 space-y-4">
        <div className="flex items-center justify-between">
          <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t('semantic-models:details.backToList', 'Back to Concepts')}
          </Button>
          <div className="flex items-center gap-2">
            <SkeletonLine height="h-9" width="w-24" />
            <SkeletonLine height="h-9" width="w-24" />
          </div>
        </div>
        <SkeletonLine height="h-9" width="w-2/3" />
        <SkeletonLine height="h-3" width="w-1/2" />
        <PanelSkeleton rows={2} rowHeight="h-10" />
        <PanelSkeleton rows={3} rowHeight="h-9" />
      </div>
    );
  }

  if (error || !concept) {
    return (
      <div className="py-6 space-y-4">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate('/concepts/browser')}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t('semantic-models:details.backToList', 'Back to Concepts')}
        </Button>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common:toast.error')}</AlertTitle>
          <AlertDescription>
            {error || t('semantic-models:details.notFound', 'Concept not found')}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const conceptTitle = resolveLabel(concept, selectedLanguage);
  const conceptDefinition = resolveComment(concept, selectedLanguage);
  const hasSynonymsOrExamples =
    (concept.synonyms?.length ?? 0) > 0 || (concept.examples?.length ?? 0) > 0;
  const isProperty = concept.concept_type === 'property';
  const hasDomainRange = isProperty && (concept.domain || concept.range);

  return (
    <div className="py-4 space-y-3">
      {/* Top action row: back + edit/delete (matches asset-detail). */}
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate('/concepts/browser')}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t('semantic-models:details.backToList', 'Back to Concepts')}
        </Button>
        {isEditable && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditorOpen(true)}>
              <Pencil className="mr-2 h-4 w-4" />
              {t('common:actions.edit')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={handleDelete}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('common:actions.delete')}
            </Button>
          </div>
        )}
      </div>

      {/* Title + meta block (no extra card; mirrors asset-detail). */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          {typeIcons[concept.concept_type] || typeIcons.concept}
          <h1 className="text-2xl font-bold truncate" title={conceptTitle}>
            {conceptTitle}
          </h1>
          <Badge
            variant="outline"
            className={typeColors[concept.concept_type] || ''}
          >
            {t(`semantic-models:types.${concept.concept_type}`)}
          </Badge>
          {concept.status && (
            <Badge variant="outline">
              {t(`semantic-models:status.${concept.status}`, concept.status)}
            </Badge>
          )}
          {concept.source_context && (
            <span className="text-xs text-muted-foreground ml-1">
              · {systemRdfNamespaceDisplayLabel(concept.source_context, t)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
          <code
            className="px-1.5 py-0.5 bg-muted rounded font-mono truncate"
            title={concept.iri}
          >
            {concept.iri}
          </code>
          <a
            href={concept.iri}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center text-muted-foreground hover:text-foreground shrink-0"
            aria-label="Open IRI"
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>

      {/* Definition + property domain/range collapsed into a single compact
          card so short definitions don't get an entire page section to
          themselves. */}
      {(conceptDefinition || hasDomainRange) && (
        <section className="rounded-lg border bg-muted/20 p-3 space-y-2">
          {conceptDefinition && (
            <p className="text-sm whitespace-pre-line">{conceptDefinition}</p>
          )}
          {hasDomainRange && (
            <div className="flex flex-wrap items-center gap-2 text-xs pt-1">
              {concept.domain && (
                <span className="inline-flex items-center gap-1">
                  <span className="text-muted-foreground uppercase tracking-wide">
                    {t('semantic-models:fields.domain')}:
                  </span>
                  <Badge
                    variant="secondary"
                    className="cursor-pointer"
                    onClick={() => handleNavigateToConcept(concept.domain!)}
                  >
                    {concept.domain.split(/[/#]/).pop() || concept.domain}
                  </Badge>
                </span>
              )}
              {concept.range && (
                <span className="inline-flex items-center gap-1">
                  <span className="text-muted-foreground uppercase tracking-wide">
                    {t('semantic-models:fields.range')}:
                  </span>
                  <Badge
                    variant="secondary"
                    className="cursor-pointer"
                    onClick={() => handleNavigateToConcept(concept.range!)}
                  >
                    {concept.range.split(/[/#]/).pop() || concept.range}
                  </Badge>
                </span>
              )}
            </div>
          )}
        </section>
      )}

      {/* Synonyms + examples on a single dense row. */}
      {hasSynonymsOrExamples && (
        <section className="flex flex-wrap items-start gap-x-6 gap-y-2 rounded-lg border bg-card p-3 text-xs">
          {concept.synonyms?.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-semibold uppercase tracking-wide text-muted-foreground mr-1">
                {t('semantic-models:fields.synonyms')}:
              </span>
              {concept.synonyms.map((s) => (
                <Badge key={s} variant="outline" className="text-[10px]">
                  {s}
                </Badge>
              ))}
            </div>
          )}
          {concept.examples?.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-semibold uppercase tracking-wide text-muted-foreground mr-1">
                {t('semantic-models:fields.examples')}:
              </span>
              {concept.examples.map((e) => (
                <Badge key={e} variant="outline" className="text-[10px]">
                  {e}
                </Badge>
              ))}
            </div>
          )}
        </section>
      )}

      <ConceptRelationsPanel
        conceptIri={concept.iri}
        onNavigate={handleNavigateToConcept}
        maxVisibleRows={MAX_VISIBLE_ROWS}
      />

      <LinkedObjectsPanel
        conceptIri={concept.iri}
        conceptLabel={conceptTitle}
        canAssign={canLinkEntities}
        onChanged={fetchConcept}
        maxVisibleRows={MAX_VISIBLE_ROWS}
      />

      {/* Inline neighbourhood graph at full width. Clicking any node updates
          the :iri route in place so the user can keep walking the graph. */}
      <Collapsible open={neighbourhoodOpen} onOpenChange={setNeighbourhoodOpen}>
        <div className="border rounded-lg">
          <CollapsibleTrigger className="flex items-center justify-between w-full p-3 hover:bg-muted/50">
            <div className="flex items-center gap-2">
              {neighbourhoodOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              <Network className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">
                {t('semantic-models:neighborhood.title', {
                  defaultValue: 'Concept Neighbourhood',
                })}
              </span>
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="border-t">
              <ConceptNeighborhoodGraph
                concept={concept}
                onNavigate={handleNavigateToConcept}
              />
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>

      <OwnershipPanel
        objectType="business_term"
        objectId={concept.iri}
        canAssign={canLinkEntities}
      />

      <EntityMetadataPanel entityType="concept" entityId={concept.iri} />

      {concept.created_at && (
        <p className="text-xs text-muted-foreground">
          Created: {new Date(concept.created_at).toLocaleDateString()}
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Refreshing...
        </div>
      )}

      <ConceptEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        concept={concept}
        collection={collection ?? undefined}
        collections={collections.filter((c) => c.is_editable)}
        onSave={handleSaveConcept}
      />
    </div>
  );
}
