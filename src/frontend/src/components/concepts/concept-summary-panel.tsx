import { useTranslation } from 'react-i18next';
import { BookOpen, Copy, ExternalLink, Layers, User, Zap } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { StatusProgressBar } from '@/components/semantic/status-progress-bar';
import { useToast } from '@/hooks/use-toast';
import { systemRdfNamespaceDisplayLabel } from '@/lib/system-rdf-namespace-labels';
import type { OntologyConcept } from '@/types/ontology';

// ---------------------------------------------------------------------------
// ConceptSummaryPanel: the first panel on the concept detail page. Mirrors the
// Data Contracts "core metadata" header card: icon + title, status on the
// right, the full lifecycle chain, a key-facts grid (type / version / status /
// source), the copyable IRI chip (Advanced view only, it is the ontology
// layer), and the business-facing synonyms / examples captured in the Edit
// Concept dialog. Purely presentational: the page owns data and actions.
// ---------------------------------------------------------------------------

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Layers className="h-6 w-6 text-emerald-500 shrink-0" />,
  class: <BookOpen className="h-6 w-6 text-blue-500 shrink-0" />,
  property: <Zap className="h-6 w-6 text-purple-500 shrink-0" />,
  individual: <User className="h-6 w-6 text-violet-500 shrink-0" />,
  term: <Layers className="h-6 w-6 text-emerald-500 shrink-0" />,
};

const typeColors: Record<string, string> = {
  concept: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  class: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  property: 'bg-purple-500/15 text-purple-700 dark:text-purple-400 border-purple-500/30',
  individual: 'bg-violet-500/15 text-violet-700 dark:text-violet-400 border-violet-500/30',
  term: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
};

export interface ConceptSummaryPanelProps {
  concept: OntologyConcept;
  /** Resolved (language-aware) label. */
  title: string;
  /** Engine's current version number; hidden while unknown. */
  currentVersion?: number | null;
}

export function ConceptSummaryPanel({
  concept,
  title,
  currentVersion,
}: ConceptSummaryPanelProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();

  // Properties have no lifecycle and no versions.
  const isProperty = concept.concept_type === 'property';
  const showStatus = Boolean(concept.status) && !isProperty;
  const synonyms = concept.synonyms ?? [];
  const examples = concept.examples ?? [];

  const handleCopyIri = async () => {
    try {
      await navigator.clipboard.writeText(concept.iri);
      toast({
        title: t('common:toast.success'),
        description: t('common:messages.copiedToClipboard', { defaultValue: 'Copied to clipboard' }),
      });
    } catch {
      toast({
        variant: 'destructive',
        title: t('common:toast.error'),
        description: t('semantic-models:summary.copyFailed', 'Could not copy the IRI.'),
      });
    }
  };

  const factLabel = 'text-xs text-muted-foreground min-w-[4rem]';

  return (
    <Card data-testid="concept-summary-panel">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-2xl font-bold flex items-center gap-3">
              {typeIcons[concept.concept_type] || typeIcons.concept}
              <span className="truncate" title={title}>
                {title}
              </span>
            </CardTitle>
            {concept.source_context && (
              <CardDescription className="pt-1">
                {systemRdfNamespaceDisplayLabel(concept.source_context, t)}
              </CardDescription>
            )}
          </div>
          {showStatus && (
            <div className="flex flex-col items-center gap-1 shrink-0">
              <Badge variant="outline">
                {t(`semantic-models:status.${concept.status}`, concept.status as string)}
              </Badge>
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {t('semantic-models:summary.status', 'Status')}
              </span>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Full-lifecycle visibility: where this concept sits in the chain. */}
        {showStatus && <StatusProgressBar status={concept.status as string} />}

        {/* Key facts grid (mirrors the contract header card). */}
        <div className="grid md:grid-cols-3 gap-x-6 gap-y-2">
          <div className="flex items-center gap-2">
            <span className={factLabel}>{t('semantic-models:summary.type', 'Type')}:</span>
            <Badge variant="outline" className={typeColors[concept.concept_type] || ''}>
              {t(`semantic-models:types.${concept.concept_type}`)}
            </Badge>
          </div>
          {!isProperty && (
            <div className="flex items-center gap-2">
              <span className={factLabel}>{t('semantic-models:summary.version', 'Version')}:</span>
              {currentVersion != null ? (
                <Badge variant="secondary" className="font-mono text-xs">
                  v{currentVersion}
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">-</span>
              )}
            </div>
          )}
          {showStatus && (
            <div className="flex items-center gap-2">
              <span className={factLabel}>{t('semantic-models:summary.status', 'Status')}:</span>
              <span className="text-xs">
                {t(`semantic-models:status.${concept.status}`, concept.status as string)}
              </span>
            </div>
          )}
        </div>

        {/* Raw IRI chip: ontology layer, Advanced view only. Copyable. */}
        <div
          className="adv-only flex items-center gap-2 text-xs text-muted-foreground min-w-0"
          data-testid="concept-summary-iri"
        >
          <span className={factLabel}>IRI:</span>
          <code
            className="px-1.5 py-0.5 bg-muted rounded font-mono truncate"
            title={concept.iri}
          >
            {concept.iri}
          </code>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            onClick={() => {
              void handleCopyIri();
            }}
            aria-label={t('semantic-models:summary.copyIri', 'Copy IRI')}
            title={t('semantic-models:summary.copyIri', 'Copy IRI')}
          >
            <Copy className="h-3 w-3" />
          </Button>
          <a
            href={concept.iri}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center text-muted-foreground hover:text-foreground shrink-0"
            aria-label={t('semantic-models:details.openIriAria')}
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        {/* Synonyms and examples from the Edit Concept dialog, only when set. */}
        {synonyms.length > 0 && (
          <div className="flex items-baseline gap-2" data-testid="concept-summary-synonyms">
            <span className={factLabel}>{t('semantic-models:fields.synonyms', 'Synonyms')}:</span>
            <div className="flex flex-wrap gap-1">
              {synonyms.map((s) => (
                <Badge key={s} variant="outline" className="text-xs">
                  {s}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {examples.length > 0 && (
          <div className="flex items-baseline gap-2" data-testid="concept-summary-examples">
            <span className={factLabel}>{t('semantic-models:fields.examples', 'Examples')}:</span>
            <ul className="list-disc pl-4 text-sm space-y-0.5">
              {examples.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ConceptSummaryPanel;
