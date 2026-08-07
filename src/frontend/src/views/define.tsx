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
import { ImportConceptsDialog } from '@/components/knowledge';
import type { KnowledgeCollection } from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';

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

  const [importOpen, setImportOpen] = useState(false);
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
    <div className="flex flex-col py-6 max-w-[1180px]">
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
            <Button className="w-full" onClick={() => navigate('/concepts/collections')}>
              {t('semantic-models:define.author.cta', 'New concept scheme')}
            </Button>
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
            <Button className="w-full" onClick={() => navigate('/concepts/generator')}>
              {t('semantic-models:define.generate.cta', 'Start guided build')}
            </Button>
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
          </CardContent>
        </Card>
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
