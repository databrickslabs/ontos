import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BookOpen, ExternalLink, Loader2 } from 'lucide-react';

/** Shape returned by GET /api/semantic-models/search */
export interface ConceptMatch {
  concept: {
    iri: string;
    label?: string;
    comment?: string;
    concept_type: string;
    source_context?: string;
  };
  relevance_score: number;
  match_type: string; // 'label' | 'comment' | 'iri'
}

export interface ConceptTooltipProps {
  /** The node type to look up in the glossary (null = nothing selected). */
  nodeType: string | null;
}

/**
 * Surfaces glossary definitions for a node type by calling the existing
 * Semantic Models search endpoint.  Renders in the right sidebar of
 * Graph Explorer when a node is selected.
 *
 * - Calls GET /api/semantic-models/search?q={nodeType}&limit=3
 * - Caches results per node type for the session
 * - Shows nothing when there is no match or no selection
 */
export function ConceptTooltip({ nodeType }: ConceptTooltipProps) {
  const { t } = useTranslation('graph-explorer');
  const cacheRef = useRef<Map<string, ConceptMatch[] | null>>(new Map());
  const [matches, setMatches] = useState<ConceptMatch[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchConcepts = useCallback(async (type: string) => {
    // Check cache first
    if (cacheRef.current.has(type)) {
      setMatches(cacheRef.current.get(type) ?? null);
      return;
    }

    setIsLoading(true);
    try {
      const params = new URLSearchParams({ q: type, limit: '3' });
      const response = await fetch(`/api/semantic-models/search?${params}`);
      if (!response.ok) {
        cacheRef.current.set(type, null);
        setMatches(null);
        return;
      }
      const data = await response.json();
      const results: ConceptMatch[] = data.results || [];
      const value = results.length > 0 ? results : null;
      cacheRef.current.set(type, value);
      setMatches(value);
    } catch {
      cacheRef.current.set(type, null);
      setMatches(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!nodeType) {
      setMatches(null);
      return;
    }
    fetchConcepts(nodeType);
  }, [nodeType, fetchConcepts]);

  // Nothing selected
  if (!nodeType) return null;

  // Loading spinner (compact)
  if (isLoading) {
    return (
      <Card className="w-full" data-testid="concept-tooltip-loading">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            {t('conceptTooltip.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  // No matches — show nothing (plan says "if no match: show nothing")
  if (!matches || matches.length === 0) return null;

  return (
    <Card className="w-full" data-testid="concept-tooltip">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <BookOpen className="h-4 w-4" />
          {t('conceptTooltip.title')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {matches.map((match) => (
          <div key={match.concept.iri} className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {match.concept.label || match.concept.iri}
              </span>
              <Badge variant="outline" className="text-[0.6rem] px-1 py-0">
                {match.concept.concept_type}
              </Badge>
            </div>
            {match.concept.comment && (
              <p className="text-xs text-muted-foreground line-clamp-2">
                {match.concept.comment}
              </p>
            )}
            <Link
              to="/semantic-models"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {t('conceptTooltip.viewInGlossary')}
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
