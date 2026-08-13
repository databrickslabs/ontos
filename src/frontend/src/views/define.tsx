import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  PencilLine,
  Sparkles,
  Upload,
  Zap,
  ArrowUpFromLine,
  Loader2,
  List,
  ListTree,
  Share2,
  Layers,
} from 'lucide-react';
import { usePagination, PaginationControls } from '@/components/common/paginated-list';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ImportConceptsDialog, CollectionEditorDialog } from '@/components/knowledge';
import type {
  KnowledgeCollection,
  KnowledgeCollectionCreate,
  KnowledgeCollectionUpdate,
} from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useToast } from '@/hooks/use-toast';
import { GuidedGenerateDialog } from '@/components/concepts/guided-generate-dialog';

// A recent creation-work item shown in the "In progress" list. Sourced from the
// ontology generator runs endpoint (real data). Imports do not yet have a
// dedicated feed, so this list is generator-runs only for now.
interface GenerationRunSummary {
  run_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress_message?: string | null;
  created_at?: string | null;
  step_count?: number;
}

function formatDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Compact relative time ("just now", "3 min ago", "2 h ago", "5 d ago"),
// falling back to an absolute date for anything older than a week. Small local
// helper — the shared RelativeDate component is date-only and localized
// differently; these in-progress rows want minute/hour granularity.
function relativeTime(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 45) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} d ago`;
  return formatDate(iso);
}

// The three output "rungs" — a glossary -> taxonomy -> ontology maturity ladder.
// Defined once, rendered both in the top legend and (via BuildsRow) inside every
// path card, so the same icon vocabulary is taught once and reused everywhere.
const RUNGS = [
  { key: 'glossary', label: 'Glossary', Icon: List,     blurb: 'agreed terms + definitions' },
  { key: 'taxonomy', label: 'Taxonomy', Icon: ListTree, blurb: 'terms in a broader/narrower hierarchy' },
  { key: 'ontology', label: 'Ontology', Icon: Share2,   blurb: 'typed relationships a machine can reason over' },
] as const;

type RungKey = (typeof RUNGS)[number]['key'];
// Per-path production: 'yes' = this path builds that rung, 'file' = depends on the
// uploaded file (Import), undefined = not produced by this path.
type BuildsMap = Partial<Record<RungKey, 'yes' | 'file'>>;

// The reused "Builds:" row inside each path card. Lights the rungs this path
// produces; dims the rest. Same three icons, same order, in every card — so the
// user reads them as the shared vocabulary from the legend above.
function BuildsRow({ builds, note }: { builds: BuildsMap; note?: string }) {
  return (
    <div className="mt-3 pt-2.5 border-t">
      <div className="text-[11px] font-medium text-muted-foreground mb-1.5">Builds</div>
      <div className="flex items-center gap-2.5">
        {RUNGS.map((r) => {
          const state = builds[r.key];
          const active = state === 'yes';
          const fileDep = state === 'file';
          return (
            <Tooltip key={r.key}>
              <TooltipTrigger asChild>
                <span
                  className={
                    'flex items-center gap-1 text-xs whitespace-nowrap ' +
                    (active
                      ? 'text-foreground'
                      : fileDep
                      ? 'text-muted-foreground'
                      : 'text-muted-foreground/30')
                  }
                >
                  <r.Icon className="h-4 w-4" />
                  <span>{r.label}</span>
                  {fileDep && <span className="text-[10px]">*</span>}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-[220px] text-xs">
                <span className="font-medium">{r.label}</span> — {r.blurb}.{' '}
                {active
                  ? 'This path builds it.'
                  : fileDep
                  ? 'Produced if the uploaded file contains it.'
                  : 'Not produced by this path.'}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
      {note && <p className="text-[11px] text-muted-foreground/80 mt-1.5">{note}</p>}
    </div>
  );
}

export default function DefineView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const navigate = useNavigate();

  const { toast } = useToast();
  const [importOpen, setImportOpen] = useState(false);
  const [authorOpen, setAuthorOpen] = useState(false);
  const [guidedOpen, setGuidedOpen] = useState(false);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [runs, setRuns] = useState<GenerationRunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);

  useEffect(() => {
    setStaticSegments([
      { label: t('semantic-models:title', 'Concepts'), path: '/concepts' },
      { label: t('semantic-models:tabs.define', 'Define'), path: '/concepts/define' },
    ]);
  }, [setStaticSegments, t]);

  // Collections feed the Import dialog's target-scheme selector.
  const fetchCollections = useCallback(async () => {
    try {
      const res = await fetch('/api/knowledge/collections?hierarchical=true');
      if (res.ok) {
        const data = await res.json();
        setCollections(data.collections || []);
      }
    } catch (err) {
      console.error('Failed to fetch collections:', err);
    }
  }, []);

  // In-progress list: recent generator runs (real endpoint).
  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res = await fetch('/api/ontology/runs?limit=10');
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
      }
    } catch (err) {
      console.error('Failed to fetch generation runs:', err);
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCollections();
    fetchRuns();
  }, [fetchCollections, fetchRuns]);

  // Author flow: create a new concept scheme (collection) in place, then land
  // the user in Explore scoped to it so they can add concepts within it.
  const handleCreateScheme = useCallback(
    async (data: KnowledgeCollectionCreate | KnowledgeCollectionUpdate, _isNew: boolean) => {
      const res = await fetch('/api/knowledge/collections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail || 'Failed to create concept scheme');
      }
      const created = await res.json();
      toast({
        title: t('common:toast.success', 'Success'),
        description: t('semantic-models:messages.collectionCreated', 'Concept scheme created'),
      });
      setAuthorOpen(false);
      await fetchCollections();
      // Scope Explore to the new scheme (source filter) so the user starts
      // adding concepts within it.
      const iri = created?.iri;
      navigate(iri ? `/concepts/browser?source=${encodeURIComponent(iri)}` : '/concepts/browser');
    },
    [fetchCollections, navigate, t, toast],
  );

  // Creation work still open: not-yet-kept generator runs.
  const inProgress = runs.filter(
    (r) => r.status === 'pending' || r.status === 'running' || r.status === 'completed'
  );

  // Paginate the in-progress list (5 per page) so a long run history doesn't
  // push the whole landing page down.
  const {
    pageItems: inProgressPage,
    page: inProgressPageNum,
    setPage: setInProgressPage,
    pageCount: inProgressPageCount,
  } = usePagination(inProgress, 5);

  const statusBadge = (status: GenerationRunSummary['status']) => {
    switch (status) {
      case 'completed':
        return <Badge variant="secondary">{t('semantic-models:define.needsReview', 'Needs review')}</Badge>;
      case 'running':
      case 'pending':
        return <Badge variant="outline">{t('semantic-models:define.running', 'Running')}</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <TooltipProvider>
    <div className="flex flex-col pt-3 pb-6 max-w-[1180px]">
      {/* Header — description only (Simple/Advanced switch lives in the tab row). */}
      <div className="mb-4">
        <p className="text-sm text-muted-foreground">
          {t('concepts:define.description', 'Author, generate, or import your business concept schemes.')}
        </p>
      </div>

      {/* Slim education legend: the three output rungs, each with a reused icon +
          one-line "what it is". The SAME three icons reappear inside every path
          card below (the "Builds" row), lit for what that path produces. Teach the
          vocabulary once here, then show it per card. Glossary -> taxonomy ->
          ontology is a maturity progression: start simple, harden where needed. */}
      <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border bg-muted/30 px-3.5 py-2.5 text-xs">
        <span className="font-medium text-foreground">What you can build:</span>
        {RUNGS.map((r, i) => (
          <div key={r.key} className="flex items-center gap-2">
            {i > 0 && <span className="text-muted-foreground/40 -ml-3 mr-1">→</span>}
            <r.Icon className="h-4 w-4 text-foreground shrink-0" />
            <span>
              <span className="font-medium text-foreground">{r.label}</span>
              <span className="text-muted-foreground"> — {r.blurb}</span>
            </span>
          </div>
        ))}
      </div>

      {/* Path cards */}
      <h2 className="text-base font-semibold mb-3">
        {t('semantic-models:define.startWith', 'Start with…')}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-9">
        {/* Author */}
        <Card className="flex flex-col">
          <CardHeader className="pb-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary mb-2">
              <PencilLine className="h-4 w-4" />
            </div>
            <CardTitle className="flex items-center gap-1.5 text-base">
              {t('semantic-models:define.author.title', 'Author')}
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help text-xs text-muted-foreground border rounded-full h-4 w-4 inline-flex items-center justify-center">i</span>
                </TooltipTrigger>
                <TooltipContent className="max-w-[240px]">
                  {t(
                    'semantic-models:define.author.tip',
                    'Creates skos:Concept entries inside a concept scheme. Terms can later be promoted to owl:Class or rdf:Property as the scheme matures.'
                  )}
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <CardDescription>
              {t('semantic-models:define.author.desc', 'Write terms yourself. Best when you own the definitions.')}
            </CardDescription>
          </CardHeader>
          <CardContent className="mt-auto">
            <Button className="w-full" onClick={() => setAuthorOpen(true)}>
              {t('semantic-models:define.author.cta', 'New concept scheme')}
            </Button>
            <BuildsRow
              builds={{ glossary: 'yes', taxonomy: 'yes', ontology: 'yes' }}
              note="You choose the depth — start as a glossary, harden into an ontology over time."
            />
            <p className="adv-only mt-3 pt-2 border-t border-dashed text-xs text-muted-foreground leading-relaxed">
              {t(
                'semantic-models:define.author.adv',
                'Creates skos:Concept entries in a skos:ConceptScheme. Terms can harden into owl:Class or rdf:Property as the scheme matures.',
              )}
            </p>
          </CardContent>
        </Card>

        {/* Generate */}
        <Card className="flex flex-col">
          <CardHeader className="pb-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary mb-2">
              <Sparkles className="h-4 w-4" />
            </div>
            <CardTitle className="flex items-center gap-1.5 text-base">
              {t('semantic-models:define.generate.title', 'Generate')}
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help text-xs text-muted-foreground border rounded-full h-4 w-4 inline-flex items-center justify-center">i</span>
                </TooltipTrigger>
                <TooltipContent className="max-w-[240px]">
                  {t(
                    'semantic-models:define.generate.tip',
                    'A guided interview constrained to a fixed predicate palette (skos:Concept, rdfs:Class, rdf:Property) so the draft stays valid SKOS/OWL. Every candidate carries its source.'
                  )}
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <CardDescription>
              {t('semantic-models:define.generate.desc', 'Answer a few questions. Ontos drafts the scheme as you talk.')}
            </CardDescription>
          </CardHeader>
          <CardContent className="mt-auto">
            <Button className="w-full" onClick={() => setGuidedOpen(true)}>
              {t('semantic-models:define.generate.cta', 'Start guided build')}
            </Button>
            <BuildsRow
              builds={{ ontology: 'yes' }}
              note="Drafts a formal ontology (classes + properties) from your tables. Saved as Draft for review."
            />
            <p className="adv-only mt-3 pt-2 border-t border-dashed text-xs text-muted-foreground leading-relaxed">
              {t(
                'semantic-models:define.generate.adv',
                'The interview keeps the model on a fixed predicate palette (skos:Concept, rdfs:Class, rdf:Property) so the draft stays valid SKOS/OWL.',
              )}
            </p>
          </CardContent>
        </Card>

        {/* Import */}
        <Card className="flex flex-col">
          <CardHeader className="pb-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary mb-2">
              <ArrowUpFromLine className="h-4 w-4" />
            </div>
            <CardTitle className="flex items-center gap-1.5 text-base">
              {t('semantic-models:define.import.title', 'Import')}
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help text-xs text-muted-foreground border rounded-full h-4 w-4 inline-flex items-center justify-center">i</span>
                </TooltipTrigger>
                <TooltipContent className="max-w-[240px]">
                  {t(
                    'semantic-models:define.import.tip',
                    'Parses .ttl / .rdf / .owl / .n3 / .jsonld via RDF. Several files can merge into one scheme, or land one scheme per file.'
                  )}
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <CardDescription>
              {t('semantic-models:define.import.desc', 'Drop several files, land them in one scheme. Imported terms stay read-only.')}
            </CardDescription>
          </CardHeader>
          <CardContent className="mt-auto">
            <Button className="w-full" variant="outline" onClick={() => setImportOpen(true)}>
              <Upload className="h-4 w-4 mr-2" />
              {t('semantic-models:define.import.cta', 'Upload files')}
            </Button>
            <BuildsRow
              builds={{ glossary: 'file', taxonomy: 'file', ontology: 'file' }}
              note="* Whatever the uploaded file contains. Imported terms stay read-only."
            />
            <p className="adv-only mt-3 pt-2 border-t border-dashed text-xs text-muted-foreground leading-relaxed">
              {t(
                'semantic-models:define.import.adv',
                'owl:Class / skos:Concept from each file map into a skos:ConceptScheme per your choice. The source graph is preserved for round-trip export.',
              )}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Advanced-only: what a "concept scheme" maps to under the hood. */}
      <div className="adv-only -mt-5 mb-9 rounded-lg border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground leading-relaxed">
        <span className="font-semibold text-foreground">Under the hood: </span>
        {t(
          'semantic-models:define.underTheHood',
          'a concept scheme is a skos:ConceptScheme. Maturity runs glossary → taxonomy → ontology (flat terms → broader/narrower hierarchy → formal owl:Class / rdf:Property a reasoner can use). Start light, harden where you need it.',
        )}
      </div>

      {/* In progress */}
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
        {t('semantic-models:define.inProgress', 'In progress')}
      </h3>
      {runsLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('common:status.loading', 'Loading…')}
        </div>
      ) : inProgress.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4">
          {t('semantic-models:define.noInProgress', 'No creation work in progress. Start with one of the paths above.')}
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {inProgressPage.map((run) => (
            <Card key={run.run_id}>
              <CardContent className="flex items-center gap-3.5 p-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-secondary shrink-0">
                  <Zap className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <span className="truncate">
                      {t('semantic-models:define.generatorRun', 'Generator run')}
                    </span>
                    {statusBadge(run.status)}
                  </div>
                  <div className="text-sm text-muted-foreground mt-0.5 truncate">
                    {run.progress_message ||
                      t('semantic-models:define.draftPending', 'Draft not yet assigned to a concept scheme.')}
                  </div>
                  {/* Distinguishing metadata sourced from the run summary
                      (relative time + step count) — no backend change. */}
                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground mt-1">
                    {run.created_at && (
                      <span title={new Date(run.created_at).toLocaleString()}>
                        {relativeTime(run.created_at)}
                      </span>
                    )}
                    {typeof run.step_count === 'number' && run.step_count > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <Layers className="h-3 w-3" />
                        {t('semantic-models:define.stepCount', '{{count}} steps', {
                          count: run.step_count,
                        })}
                      </span>
                    )}
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate(`/concepts/generator?run=${encodeURIComponent(run.run_id)}`)}
                >
                  {t('semantic-models:define.review', 'Review')}
                </Button>
              </CardContent>
            </Card>
          ))}
          <PaginationControls
            page={inProgressPageNum}
            pageCount={inProgressPageCount}
            onPageChange={setInProgressPage}
          />
        </div>
      )}

      {/* Author: create a new concept scheme in place (reuses the collection
          editor; a collection IS a concept scheme in the domain model). */}
      <CollectionEditorDialog
        open={authorOpen}
        onOpenChange={setAuthorOpen}
        collection={null}
        collections={collections}
        onSave={handleCreateScheme}
      />

      {/* Generate: guided prompt-builder that feeds the existing generator. */}
      <GuidedGenerateDialog open={guidedOpen} onOpenChange={setGuidedOpen} />

      {/* Import dialog */}
      <ImportConceptsDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        collections={collections}
        onImported={() => {
          fetchCollections();
        }}
      />
    </div>
    </TooltipProvider>
  );
}
