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
  Save,
  Code2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { PrincipalPicker } from '@/components/common/principal-picker';
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
import { PublishVersionDialog } from '@/components/semantic/publish-version-dialog';
import { VersionHistoryPanel } from '@/components/semantic/version-history-panel';
import { DeprecateConceptDialog } from '@/components/semantic/deprecate-concept-dialog';
import { TurtleSerializationPanel } from '@/components/semantic/turtle-serialization-panel';
import { StatusProgressBar } from '@/components/semantic/status-progress-bar';
import KGSearch from '@/components/search/kg-search';

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

// Lifecycle transitions valid from each status, mirroring the backend
// VALID_TRANSITIONS (semantic_models_manager). Each maps to a by-iri action
// endpoint. draft->under_review is "submit-review"; the rest match their verb.
const STATUS_TRANSITIONS: Record<string, { action: string; to: string; labelKey: string; defaultLabel: string }[]> = {
  draft: [{ action: 'submit-review', to: 'under_review', labelKey: 'semantic-models:lifecycle.submitReview', defaultLabel: 'Submit for review' }],
  under_review: [
    { action: 'approve', to: 'approved', labelKey: 'semantic-models:lifecycle.approve', defaultLabel: 'Approve' },
  ],
  approved: [{ action: 'publish', to: 'published', labelKey: 'semantic-models:lifecycle.publish', defaultLabel: 'Publish' }],
  published: [
    { action: 'certify', to: 'certified', labelKey: 'semantic-models:lifecycle.certify', defaultLabel: 'Certify' },
    { action: 'deprecate', to: 'deprecated', labelKey: 'semantic-models:lifecycle.deprecate', defaultLabel: 'Deprecate' },
  ],
  certified: [
    { action: 'deprecate', to: 'deprecated', labelKey: 'semantic-models:lifecycle.deprecate', defaultLabel: 'Deprecate' },
    { action: 'archive', to: 'archived', labelKey: 'semantic-models:lifecycle.archive', defaultLabel: 'Archive' },
  ],
  deprecated: [{ action: 'archive', to: 'archived', labelKey: 'semantic-models:lifecycle.archive', defaultLabel: 'Archive' }],
  archived: [],
};

// Ordered lifecycle chain (forward direction only)
const LIFECYCLE_CHAIN = ['draft', 'under_review', 'approved', 'published', 'certified', 'deprecated', 'archived'];

/**
 * Compute all forward-reachable statuses from a given current status.
 * Returns them as an ordered list with metadata about the next step vs downstream.
 */
function reachableStatuses(currentStatus: string): Array<{
  status: string;
  action: string;
  labelKey: string;
  defaultLabel: string;
  isNextStep: boolean;
}> {
  const chain = LIFECYCLE_CHAIN;
  const idx = chain.indexOf(currentStatus);
  if (idx < 0 || idx === chain.length - 1) return []; // no transitions from archived or unknown status

  const result: Array<{
    status: string;
    action: string;
    labelKey: string;
    defaultLabel: string;
    isNextStep: boolean;
  }> = [];
  const directTransitions = STATUS_TRANSITIONS[currentStatus] ?? [];

  // Iterate from the next status onwards; for each, check if it's reachable
  for (let i = idx + 1; i < chain.length; i++) {
    const targetStatus = chain[i];
    // A status is reachable if there's a path to it via the forward chain
    // (all intermediate steps exist in STATUS_TRANSITIONS)
    let isReachable = true;
    for (let j = idx; j < i; j++) {
      const transitions = STATUS_TRANSITIONS[chain[j]] ?? [];
      if (!transitions.some((tr) => tr.to === chain[j + 1])) {
        isReachable = false;
        break;
      }
    }
    if (isReachable) {
      // Find the transition data from directTransitions if it's the immediate next
      const directTr = directTransitions.find((tr) => tr.to === targetStatus);
      result.push({
        status: targetStatus,
        action: directTr?.action ?? '', // will be computed on walk if empty
        labelKey: directTr?.labelKey ?? `semantic-models:status.${targetStatus}`,
        defaultLabel: directTr?.defaultLabel ?? targetStatus,
        isNextStep: i === idx + 1,
      });
    }
  }
  return result;
}

export default function ConceptDetailView() {
  const params = useParams();
  const rawIri = params['*'] ?? '';
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
  // "Save new version" dialog (versioning contract §4) + a nonce that forces the
  // version-history panel to refetch after a successful publish.
  const [publishOpen, setPublishOpen] = useState(false);
  const [versionRefreshNonce, setVersionRefreshNonce] = useState(0);
  // Real current version from the engine (contract §1). Single integer (v2),
  // NOT semver — replaces the old hardcoded "v1.0.0" badge. Null while loading
  // or if the concept has no version rows yet.
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [neighbourhoodOpen, setNeighbourhoodOpen] = useState(true);
  // Relations and the neighbourhood graph are the same /neighbors data rendered
  // two ways, so they share ONE block with a List (relations) / Graph switch.
  // Defaults to the relations list (per wireframe); graph is opt-in.
  const [relationsView, setRelationsView] = useState<'list' | 'graph'>('list');
  const [deprecateOpen, setDeprecateOpen] = useState(false);
  const [sparqlDialogOpen, setSparqlDialogOpen] = useState(false);
  const [submitReviewOpen, setSubmitReviewOpen] = useState(false);
  const [reviewerEmail, setReviewerEmail] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState('');
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

  // Fetch the real current version from the engine (contract §1) so the badge
  // shows the actual integer, not a hardcoded string. Refetches after a publish
  // (versionRefreshNonce bumps). Degrades silently: if the endpoint is absent or
  // the concept has no version rows, the badge falls back to hiding itself.
  useEffect(() => {
    if (!conceptIri) return;
    let cancelled = false;
    (async () => {
      const res = await get<{ current_version?: number | null }>(
        `/api/semantic-models/concepts/version?iri=${encodeURIComponent(conceptIri)}`,
      );
      if (cancelled) return;
      const cv = res.data?.current_version;
      setCurrentVersion(typeof cv === 'number' ? cv : null);
    })();
    return () => { cancelled = true; };
  }, [conceptIri, versionRefreshNonce, get]);

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

  // Publishing a NEW version is NOT restricted to draft: it is precisely what
  // you do to an already-published/certified concept when its definition needs
  // to change (mint v2, keep the IRI, keep history). It only requires write
  // permission on an editable collection. Retired concepts are the exception
  // (a tombstone should not sprout new versions).
  const canPublishVersion = useMemo(() => {
    if (!concept) return false;
    const isRetired = concept.status === 'retired';
    return !!(canWrite && collection?.is_editable && !isRetired);
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

  // Run a lifecycle status transition via its by-iri action endpoint, then
  // refresh so the status badge + available transitions update.
  const [statusBusy, setStatusBusy] = useState(false);

  // Walk the status chain one step at a time from current to target.
  // If 'deprecate' is encountered along the way, stop and open the deprecate dialog.
  // If 'submit-review' is target, open the reviewer dialog instead.
  const handleStatusTransition = async (targetStatus: string) => {
    if (!concept) return;

    // Special case: if target is 'under_review', open the submit-review dialog
    if (targetStatus === 'under_review') {
      setReviewerEmail(null);
      setReviewNotes('');
      setSubmitReviewOpen(true);
      return;
    }

    // Special case: if target is 'deprecated', open the dialog instead of walking blindly
    if (targetStatus === 'deprecated') {
      setDeprecateOpen(true);
      return;
    }

    setStatusBusy(true);
    try {
      const chain = LIFECYCLE_CHAIN;
      const currentIdx = chain.indexOf(concept.status || 'draft');
      const targetIdx = chain.indexOf(targetStatus);

      if (currentIdx < 0 || targetIdx < 0 || targetIdx <= currentIdx) {
        throw new Error('Invalid target status');
      }

      // Walk from current to target, one step at a time
      let currentStatus: string = concept.status || 'draft';
      for (let i = currentIdx; i < targetIdx; i++) {
        const nextStatus = chain[i + 1];
        const transitions = STATUS_TRANSITIONS[currentStatus] ?? [];
        const transition = transitions.find((tr) => tr.to === nextStatus);

        if (!transition) {
          throw new Error(`No transition available from ${currentStatus} to ${nextStatus}`);
        }

        // If we encounter deprecate along the way, stop and open the dialog
        if (transition.action === 'deprecate' && targetStatus !== 'deprecated') {
          setDeprecateOpen(true);
          setStatusBusy(false);
          return;
        }

        // Execute the transition
        const response = await fetch(
          `/api/knowledge/concepts/by-iri/${transition.action}?iri=${encodeURIComponent(concept.iri)}`,
          { method: 'POST' },
        );
        if (!response.ok) {
          const err = await response.json().catch(() => ({} as any));
          throw new Error(err?.detail || `Failed to transition to ${nextStatus}`);
        }
        currentStatus = nextStatus;
      }

      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.statusChanged', 'Status updated'),
      });
      bumpKnowledgeGraphRefresh('concept-status');
      await fetchConcept();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
      // Re-sync to the TRUE backend status even on failure
      await fetchConcept();
    } finally {
      setStatusBusy(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!concept) return;
    setStatusBusy(true);
    try {
      const body: any = {};
      if (reviewerEmail) body.reviewer_email = reviewerEmail;
      if (reviewNotes.trim()) body.notes = reviewNotes;

      const response = await fetch(
        `/api/knowledge/concepts/by-iri/submit-review?iri=${encodeURIComponent(concept.iri)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      );
      if (!response.ok) {
        const err = await response.json().catch(() => ({} as any));
        throw new Error(err?.detail || 'Failed to submit for review');
      }
      const result = await response.json();
      const governed = result?.governed;
      toast({
        title: t('common:toast.success'),
        description: governed
          ? t('semantic-models:messages.submitReviewGoverned', 'Submitted for review — awaiting approval.')
          : t('semantic-models:messages.submitReview', 'Submitted for review'),
      });
      setSubmitReviewOpen(false);
      bumpKnowledgeGraphRefresh('concept-status');
      await fetchConcept();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
    } finally {
      setStatusBusy(false);
    }
  };

  const handleWithdrawReview = async () => {
    if (!concept) return;
    setStatusBusy(true);
    try {
      const response = await fetch(
        `/api/knowledge/concepts/by-iri/withdraw-review?iri=${encodeURIComponent(concept.iri)}`,
        { method: 'POST' },
      );
      if (!response.ok) {
        const err = await response.json().catch(() => ({} as any));
        throw new Error(err?.detail || 'Failed to withdraw review');
      }
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.withdrawReview', 'Review withdrawn'),
      });
      bumpKnowledgeGraphRefresh('concept-status');
      await fetchConcept();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
    } finally {
      setStatusBusy(false);
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

  // All forward-reachable statuses from the current status. Offered to writers
  // on concepts whose collection is editable (imported/read-only ontologies have
  // no lifecycle). Certify is admin-gated server-side; a non-admin gets a clear
  // 403 toast rather than the option being hidden.
  const currentStatus = concept.status || 'draft';
  // Only offer the DIRECT next-step transitions (single hop). Multi-hop
  // shortcuts were removed: they let users skip the review decision (and now
  // hit the approval-bypass gate anyway). Full lifecycle visibility is provided
  // by the StatusProgressBar below instead.
  const nextStepStatuses =
    canWrite && collection?.is_editable
      ? reachableStatuses(currentStatus).filter((s) => s.isNextStep)
      : [];

  return (
    <div className="py-4 space-y-3">
      {/* Top action row: back + status/edit/delete + mode switch. */}
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate('/concepts/browser')}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t('semantic-models:details.backToList', 'Back to Concepts')}
        </Button>
        <div className="flex items-center gap-2">
          {nextStepStatuses.length > 0 && !isProperty && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" disabled={statusBusy}>
                  {t('semantic-models:lifecycle.changeStatus', 'Change status')}
                  <ChevronDown className="ml-2 h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {nextStepStatuses.map((item) => (
                  <DropdownMenuItem
                    key={item.status}
                    onClick={() => handleStatusTransition(item.status)}
                    className="font-medium"
                  >
                    {t(item.labelKey, item.defaultLabel)}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {currentStatus === 'under_review' && canWrite && (
            <Button
              variant="outline"
              size="sm"
              disabled={statusBusy}
              onClick={handleWithdrawReview}
            >
              {t('semantic-models:lifecycle.withdrawReview', 'Withdraw Review')}
            </Button>
          )}
          {/* "Save new version" is available for any non-retired editable concept,
              NOT just drafts — publishing v2 is exactly how a certified concept's
              definition changes. Edit/Delete stay draft-only (isEditable).
              Properties do not support versioning. */}
          {canPublishVersion && !isProperty && (
            <Button variant="outline" size="sm" onClick={() => setPublishOpen(true)}>
              <Save className="mr-2 h-4 w-4" />
              {t('semantic-models:versionHistory.saveNewVersion', 'Save new version')}
            </Button>
          )}
          {isEditable && (
            <>
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
            </>
          )}
          {/* Power-user SPARQL — Advanced view only. Opens the query surface in
              a modal on this page instead of navigating to the legacy Search
              Concepts page. Seeded with a query scoped to this concept. */}
          <Button
            variant="outline"
            size="sm"
            className="adv-only"
            onClick={() => setSparqlDialogOpen(true)}
          >
            <Code2 className="mr-2 h-4 w-4" />
            {t('semantic-models:concept.sparql', 'SPARQL')}
          </Button>
        </div>
      </div>

      {/* Title + meta block. Name row carries the icon + title; a single badge
          row underneath holds type / status / version / source so nothing is
          orphaned under the icon. The raw IRI is a separate advanced-only row. */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 min-w-0">
          {typeIcons[concept.concept_type] || typeIcons.concept}
          <h1 className="text-2xl font-bold truncate" title={conceptTitle}>
            {conceptTitle}
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Version badge first (leftmost). Wired to the engine's real current
              version (single integer, e.g. v2). Hidden until a version row
              exists (freshly-created concepts before their first version load). */}
          {currentVersion != null && !isProperty && (
            <Badge variant="secondary" className="font-mono text-xs">v{currentVersion}</Badge>
          )}
          {/* "Compare" removed: today only the definition changes across
              versions, and that diff is already shown in the version-history
              panel below. A dedicated compare view adds nothing until we version
              more fields, so it was just a scroll-to-history shortcut that
              confused users. Re-add when there's a real side-by-side diff. */}
          <Badge
            variant="outline"
            className={typeColors[concept.concept_type] || ''}
          >
            {t(`semantic-models:types.${concept.concept_type}`)}
          </Badge>
          {concept.status && !isProperty && (
            <Badge variant="outline">
              {t(`semantic-models:status.${concept.status}`, concept.status)}
            </Badge>
          )}
          {concept.source_context && (
            <span className="text-xs text-muted-foreground">
              · {systemRdfNamespaceDisplayLabel(concept.source_context, t)}
            </span>
          )}
        </div>
        {/* Full-lifecycle visibility: the compact stepper shows the whole chain
            and where this concept sits, complementing the single-hop
            "Change status" dropdown. */}
        {concept.status && !isProperty && (
          <StatusProgressBar status={concept.status} className="mt-0.5" />
        )}
        {/* Reviewer-comment callout — only when a reviewer actually left a
            comment (changes requested). The status chip already says "Under
            Review", so we no longer show a redundant bar for the plain
            under_review state. */}
        {concept.status === 'under_review' && (concept as any)?.review_comment && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950 p-2.5 space-y-1.5">
            <div className="flex items-center gap-2 text-sm font-medium text-blue-900 dark:text-blue-100">
              {t('semantic-models:concept.reviewerComment', 'Reviewer comment')}
            </div>
            <div className="text-xs text-blue-800 dark:text-blue-200 whitespace-pre-wrap">
              {(concept as any).review_comment}
            </div>
          </div>
        )}
        {/* Raw IRI + external link — ontology layer, advanced only, own row. */}
        <div className="adv-only flex items-center gap-2 text-xs text-muted-foreground min-w-0">
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

      {/* Synonyms and examples — each on its own row (a shared card), so they
          are not cramped together. Aligned label column keeps them scannable. */}
      {hasSynonymsOrExamples && (
        <section className="rounded-lg border bg-card p-3 text-xs space-y-2">
          {concept.synonyms?.length > 0 && (
            <div className="flex items-baseline gap-2">
              <span className="w-20 shrink-0 font-semibold uppercase tracking-wide text-muted-foreground">
                {t('semantic-models:fields.synonyms')}
              </span>
              <div className="flex flex-wrap gap-1">
                {concept.synonyms.map((s) => (
                  <Badge key={s} variant="outline" className="text-[10px]">
                    {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {concept.examples?.length > 0 && (
            <div className="flex items-baseline gap-2">
              <span className="w-20 shrink-0 font-semibold uppercase tracking-wide text-muted-foreground">
                {t('semantic-models:fields.examples')}
              </span>
              <div className="flex flex-wrap gap-1">
                {concept.examples.map((e) => (
                  <Badge key={e} variant="outline" className="text-[10px]">
                    {e}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Two-column panel grid (item 7 of CB v2 changes).
          Layout (md breakpoint):
          - Row 1: Owners + Details
          - Row 2: Related concepts + Hierarchy
          - Row 3: Linked assets (full width)
          - Row 4: Metadata + Change history
          - Row 5: Neighbourhood graph (full width) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Row 1: Owners panel */}
        <OwnershipPanel
          objectType="business_term"
          objectId={concept.iri}
          canAssign={canLinkEntities}
        />

        {/* Row 1: Details — scheme/source/created, plus IRI + type in advanced. */}
        <div className="rounded-lg border bg-card p-3">
          <h3 className="text-sm font-medium mb-2">
            {t('semantic-models:details.title', 'Details')}
          </h3>
          <dl className="text-sm divide-y">
            {collection?.label && (
              <div className="flex justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">
                  {t('semantic-models:fields.scheme', 'Concept scheme')}
                </dt>
                <dd className="font-medium text-right truncate">{collection.label}</dd>
              </div>
            )}
            {concept.source_context && (
              <div className="flex justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">
                  {t('semantic-models:fields.source', 'Source')}
                </dt>
                <dd className="font-medium text-right truncate">
                  {systemRdfNamespaceDisplayLabel(concept.source_context, t)}
                </dd>
              </div>
            )}
            {concept.source_file && (
              <div className="flex justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">
                  {t('semantic-models:fields.sourceFile', 'Imported from')}
                </dt>
                <dd className="font-medium text-right truncate">
                  {concept.source_file}
                </dd>
              </div>
            )}
            {concept.created_at && (
              <div className="flex justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">
                  {t('semantic-models:fields.created', 'Created')}
                </dt>
                <dd className="font-medium text-right">
                  {new Date(concept.created_at).toLocaleDateString()}
                </dd>
              </div>
            )}
            {/* Advanced-only: the ontology layer (type + raw IRI). */}
            <div className="adv-only flex justify-between gap-3 py-1.5">
              <dt className="text-muted-foreground">
                {t('semantic-models:fields.type', 'Type')}
              </dt>
              <dd className="font-mono text-xs text-right truncate">
                {concept.concept_type}
              </dd>
            </div>
            <div className="adv-only flex justify-between gap-3 py-1.5">
              <dt className="text-muted-foreground">IRI</dt>
              <dd className="font-mono text-xs text-right truncate" title={concept.iri}>
                {concept.iri}
              </dd>
            </div>
          </dl>
        </div>

        {/* Row 2: Hierarchy — broader (parents) / narrower (children) concepts.
            Relations moved into the shared "Relations / Graph" block below
            (they were the same /neighbors data rendered twice). */}
        <div className="rounded-lg border bg-card p-3 md:col-span-2">
          <h3 className="text-sm font-medium mb-2">
            {t('semantic-models:hierarchy.title', 'Hierarchy')}
          </h3>
          {(concept.parent_concepts?.length ?? 0) === 0
            && (concept.child_concepts?.length ?? 0) === 0 ? (
            <p className="text-xs text-muted-foreground">
              {t('semantic-models:hierarchy.none', 'No broader or narrower concepts.')}
            </p>
          ) : (
            <div className="space-y-2 text-sm">
              {(concept.parent_concepts?.length ?? 0) > 0 && (
                <div className="flex gap-2">
                  <span className="w-16 shrink-0 text-xs text-muted-foreground pt-0.5">
                    {t('semantic-models:hierarchy.parent', 'Parent')}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {concept.parent_concepts.map((iri) => (
                      <Badge
                        key={iri}
                        variant="secondary"
                        className="cursor-pointer"
                        onClick={() => handleNavigateToConcept(iri)}
                      >
                        {iri.split(/[/#]/).pop() || iri}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {(concept.child_concepts?.length ?? 0) > 0 && (
                <div className="flex gap-2">
                  <span className="w-16 shrink-0 text-xs text-muted-foreground pt-0.5">
                    {t('semantic-models:hierarchy.children', 'Children')}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {concept.child_concepts.map((iri) => (
                      <Badge
                        key={iri}
                        variant="secondary"
                        className="cursor-pointer"
                        onClick={() => handleNavigateToConcept(iri)}
                      >
                        {iri.split(/[/#]/).pop() || iri}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Row 3: Linked assets (full width) */}
        <div className="md:col-span-2">
          <LinkedObjectsPanel
            conceptIri={concept.iri}
            conceptLabel={conceptTitle}
            canAssign={canLinkEntities}
            onChanged={fetchConcept}
            maxVisibleRows={MAX_VISIBLE_ROWS}
          />
        </div>

        {/* Row 4: Metadata */}
        <EntityMetadataPanel entityType="concept" entityId={concept.iri} />

        {/* Row 4: Version history — live, drives versioning contract §1 + §2. */}
        {!isProperty && (
          <div id="concept-version-history">
            <VersionHistoryPanel
              conceptIri={concept.iri}
              refreshNonce={versionRefreshNonce}
            />
          </div>
        )}

        {/* Row 5: Relations + neighbourhood graph — ONE block, two views over
            the same /neighbors data. List = relations; Graph = node-link. */}
        <Collapsible open={neighbourhoodOpen} onOpenChange={setNeighbourhoodOpen} className="md:col-span-2">
          <div className="border rounded-lg">
            <div className="flex items-center justify-between p-3 hover:bg-muted/50">
              <CollapsibleTrigger className="flex items-center gap-2 flex-1 text-left">
                {neighbourhoodOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                <Network className="h-4 w-4 text-muted-foreground" />
                <span className="font-medium text-sm">
                  {t('semantic-models:relations.title', { defaultValue: 'Relations' })}
                </span>
              </CollapsibleTrigger>
              {neighbourhoodOpen && (
                <div
                  role="tablist"
                  aria-label={t('semantic-models:relations.viewLabel', 'Relations view')}
                  className="inline-flex items-center gap-1 rounded-md border bg-card p-0.5"
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={relationsView === 'list'}
                    onClick={() => setRelationsView('list')}
                    className={
                      relationsView === 'list'
                        ? 'rounded px-2 py-0.5 text-xs bg-accent text-accent-foreground font-medium'
                        : 'rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground'
                    }
                  >
                    {t('semantic-models:neighborhood.list', 'List')}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={relationsView === 'graph'}
                    onClick={() => setRelationsView('graph')}
                    className={
                      relationsView === 'graph'
                        ? 'rounded px-2 py-0.5 text-xs bg-accent text-accent-foreground font-medium'
                        : 'rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground'
                    }
                  >
                    {t('semantic-models:neighborhood.graph', 'Graph')}
                  </button>
                </div>
              )}
            </div>
            <CollapsibleContent>
              <div className="border-t">
                {relationsView === 'list' ? (
                  <ConceptRelationsPanel
                    conceptIri={concept.iri}
                    onNavigate={handleNavigateToConcept}
                    maxVisibleRows={MAX_VISIBLE_ROWS}
                    embedded
                  />
                ) : (
                  <ConceptNeighborhoodGraph
                    concept={concept}
                    onNavigate={handleNavigateToConcept}
                    view="graph"
                  />
                )}
              </div>
            </CollapsibleContent>
          </div>
        </Collapsible>

        {/* Advanced-only: RDF (Turtle) serialization — kept as the LAST grid
            block so toggling Advanced only APPENDS it at the bottom and never
            reshuffles Version history / Relations above it. */}
        <div className="adv-only md:col-span-2">
          <TurtleSerializationPanel conceptIri={concept.iri} />
        </div>
      </div>

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

      <PublishVersionDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        iri={concept.iri}
        currentDefinition={conceptDefinition || ''}
        onPublished={async () => {
          bumpKnowledgeGraphRefresh('concept-version');
          setVersionRefreshNonce((n) => n + 1);
          await fetchConcept();
        }}
      />

      <DeprecateConceptDialog
        isOpen={deprecateOpen}
        onOpenChange={setDeprecateOpen}
        conceptIri={concept.iri}
        onSuccess={async () => {
          toast({
            title: t('common:toast.success'),
            description: t('semantic-models:messages.statusChanged', 'Status updated'),
          });
          bumpKnowledgeGraphRefresh('concept-status');
          await fetchConcept();
        }}
      />

      <Dialog open={sparqlDialogOpen} onOpenChange={setSparqlDialogOpen}>
        <DialogContent className="sm:max-w-[900px] max-h-[85vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>
              {t('semantic-models:concept.sparqlTitle', 'SPARQL query')}
            </DialogTitle>
            <DialogDescription>
              {t(
                'semantic-models:concept.sparqlDescription',
                'Query the knowledge graph. Pre-seeded with this concept.',
              )}
            </DialogDescription>
          </DialogHeader>
          <KGSearch
            initialSparql={`SELECT ?p ?o WHERE { <${concept.iri}> ?p ?o } LIMIT 100`}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={submitReviewOpen} onOpenChange={setSubmitReviewOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t('semantic-models:submitReview.title', 'Submit for Review')}
            </DialogTitle>
            <DialogDescription>
              {t('semantic-models:submitReview.description', 'Assign an optional reviewer and add notes.')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="reviewer-email">
                {t('semantic-models:submitReview.reviewer', 'Reviewer (optional)')}
              </Label>
              <PrincipalPicker
                id="reviewer-email"
                accepts={['user', 'group']}
                value={reviewerEmail}
                onChange={(next) => setReviewerEmail(next ?? null)}
                placeholder={t('semantic-models:submitReview.reviewerPlaceholder', 'Select a reviewer...')}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="review-notes">
                {t('semantic-models:submitReview.notes', 'Notes (optional)')}
              </Label>
              <Textarea
                id="review-notes"
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder={t('semantic-models:submitReview.notesPlaceholder', 'Add context or instructions...')}
                className="min-h-24 resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setSubmitReviewOpen(false)}
              disabled={statusBusy}
            >
              {t('common:actions.cancel', 'Cancel')}
            </Button>
            <Button
              type="button"
              onClick={handleSubmitReview}
              disabled={statusBusy}
            >
              {statusBusy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('semantic-models:submitReview.submit', 'Submit')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
