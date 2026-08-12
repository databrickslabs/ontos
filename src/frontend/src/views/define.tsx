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
  Check,
  Minus,
  CircleDashed,
} from 'lucide-react';
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

      {/* What you can build — output/capability clarity (not persona). Two output
          kinds, and which of them each path below produces. Keeps the choice
          honest at the fork: Concepts are lighter; Classes & properties are more
          powerful but carry more to understand and manage. */}
      <div className="mb-6 rounded-lg border bg-muted/30 p-3.5">
        <div className="grid gap-3 sm:grid-cols-2 mb-3">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 shrink-0 rounded-md bg-secondary p-1"><PencilLine className="h-3.5 w-3.5" /></span>
            <div>
              <div className="text-sm font-medium">Concepts</div>
              <div className="text-xs text-muted-foreground">Agreed business terms with definitions and synonyms. Simple to manage; the shared vocabulary.</div>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <span className="mt-0.5 shrink-0 rounded-md bg-secondary p-1"><Zap className="h-3.5 w-3.5" /></span>
            <div>
              <div className="text-sm font-medium">Classes &amp; properties</div>
              <div className="text-xs text-muted-foreground">Formal types a machine can reason over, with typed relationships. More capable, more depth to manage.</div>
            </div>
          </div>
        </div>
        {/* What each path produces */}
        <div className="border-t pt-2.5 space-y-1.5">
          {[
            { label: 'Author', concepts: 'yes', classes: 'opt' },
            { label: 'Generate', concepts: 'no', classes: 'yes' },
            { label: 'Import', concepts: 'file', classes: 'file' },
          ].map((row) => {
            const cell = (v: string) =>
              v === 'yes' ? <Check className="h-3.5 w-3.5 text-emerald-600" />
              : v === 'opt' ? <CircleDashed className="h-3.5 w-3.5 text-muted-foreground" />
              : v === 'file' ? <Check className="h-3.5 w-3.5 text-muted-foreground/70" />
              : <Minus className="h-3.5 w-3.5 text-muted-foreground/40" />;
            return (
              <div key={row.label} className="grid grid-cols-[110px_1fr_1fr] items-center gap-2 text-xs">
                <span className="font-medium">{row.label}</span>
                <span className="flex items-center gap-1.5 text-muted-foreground">{cell(row.concepts)} Concepts</span>
                <span className="flex items-center gap-1.5 text-muted-foreground">{cell(row.classes)} Classes &amp; properties</span>
              </div>
            );
          })}
          <p className="text-[11px] text-muted-foreground/80 pt-1">
            <Check className="h-3 w-3 inline text-emerald-600" /> produces &nbsp;·&nbsp;
            <CircleDashed className="h-3 w-3 inline" /> optional &nbsp;·&nbsp;
            <Minus className="h-3 w-3 inline" /> no &nbsp;·&nbsp; Import brings in whatever the file contains (read-only).
          </p>
        </div>
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
          {inProgress.map((run) => (
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
                </div>
                <span className="text-xs text-muted-foreground font-mono shrink-0">
                  {formatDate(run.created_at)}
                </span>
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
