/**
 * Concept Detail Side Panel
 * Slides in from the right when a concept node is clicked in knowledge/domain graphs.
 * Fetches SKOS properties and shows hierarchy (broader, narrower, related, seeAlso).
 * Navigating between concepts is supported via clickable relationship pills.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { ExternalLink, Loader2, AlertCircle, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import type { OntologyConcept } from '@/types/ontology';

// Predicate → accent color for relationship section left borders
const PREDICATE_ACCENT: Record<string, string> = {
  'skos:broader': '#3b82f6', 'skos:narrower': '#3b82f6', 'Broader': '#3b82f6',
  'rdfs:subClassOf': '#10b981', 'rdfs:subPropertyOf': '#f59e0b',
  'owl:equivalentClass': '#8b5cf6', 'rdf:type': '#64748b',
  'skos:related': '#ec4899', 'Narrower': '#3b82f6', 'Related': '#ec4899',
};

// W3C concept type → colored badge style
// W3C concept-type → Tailwind utility classes for the type badge (background +
// border + text). Using palette tokens (instead of raw rgba/hex) so dark-mode
// theme switching and color-token edits flow through automatically.
const W3C_TYPE_BADGE_CLASS: Record<string, string> = {
  scheme:   'bg-violet-500/10 border-violet-500/30 text-violet-500',
  concept:  'bg-blue-500/10 border-blue-500/30 text-blue-500',
  class:    'bg-emerald-500/10 border-emerald-500/30 text-emerald-500',
  property: 'bg-amber-500/10 border-amber-500/30 text-amber-500',
  term:     'bg-blue-500/10 border-blue-500/30 text-blue-500',
};

// Matching solid colors for the 3px stripe at the panel top.
const W3C_TYPE_STRIPE_CLASS: Record<string, string> = {
  scheme:   'bg-violet-500',
  concept:  'bg-blue-500',
  class:    'bg-emerald-500',
  property: 'bg-amber-500',
  term:     'bg-blue-500',
};

const W3C_TYPE_LABEL: Record<string, string> = {
  scheme: 'skos:ConceptScheme', concept: 'skos:Concept', class: 'owl:Class',
  property: 'owl:Property', term: 'skos:Concept', individual: 'owl:NamedIndividual',
};

interface ConceptDetailPanelProps {
  /** IRI of the concept to display, or null to hide the panel */
  conceptIri: string | null;
  /** Pre-loaded concept data from the graph (avoids redundant fetch) */
  conceptData?: OntologyConcept | null;
  /** Called when the panel close button is clicked or overlay is dismissed */
  onClose: () => void;
  /** Called when a related concept is clicked — navigates the panel to that concept */
  onNavigate?: (iri: string) => void;
  /** Called when the edit button is clicked — opens concept editor */
  onEdit?: (concept: OntologyConcept) => void;
  /** Called when the delete button is clicked — triggers concept deletion */
  onDelete?: (concept: OntologyConcept) => void;
}

/** Shorthand for a concept reference (IRI + display label) */
interface ConceptRef {
  iri: string;
  label: string;
}

export const ConceptDetailPanel: React.FC<ConceptDetailPanelProps> = ({
  conceptIri,
  conceptData,
  onClose,
  onNavigate,
  onEdit,
  onDelete,
}) => {
  const [concept, setConcept] = useState<OntologyConcept | null>(null);
  const [parentRefs, setParentRefs] = useState<ConceptRef[]>([]);
  const [childRefs, setChildRefs] = useState<ConceptRef[]>([]);
  const [relatedRefs, setRelatedRefs] = useState<ConceptRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!conceptIri) return;

    // If we already have the concept data from the graph, use it directly
    if (conceptData && conceptData.iri === conceptIri) {
      setConcept(conceptData);
      resolveRefs(conceptData);
      return;
    }

    // Otherwise fetch from API
    setLoading(true);
    setError(null);
    setConcept(null);

    const encoded = encodeURIComponent(conceptIri);
    fetch(`/api/semantic-models/concepts/${encoded}`)
      .then(r => {
        if (!r.ok) throw new Error(`Concept not found (${r.status})`);
        return r.json();
      })
      .then(data => {
        // API may wrap in { concept: ... } or return directly
        const c = data.concept ?? data;
        setConcept(c);
        resolveRefs(c);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [conceptIri, conceptData]);

  /** Resolve parent/child/related IRIs to display labels */
  const resolveRefs = async (c: OntologyConcept) => {
    const toRef = (iri: string): ConceptRef => ({
      iri,
      label: iri.split(/[/#]/).pop() || iri,
    });

    // Set immediate refs from IRIs (labels will just be local names)
    setParentRefs((c.parent_concepts ?? []).map(toRef));
    setChildRefs((c.child_concepts ?? []).map(toRef));
    setRelatedRefs((c.related_concepts ?? []).map(toRef));

    // Try to fetch labels for each ref in parallel
    const allIris = [
      ...(c.parent_concepts ?? []),
      ...(c.child_concepts ?? []),
      ...(c.related_concepts ?? []),
    ];
    if (!allIris.length) return;

    const labelMap = new Map<string, string>();
    await Promise.all(
      allIris.slice(0, 30).map(async (iri) => {
        try {
          const r = await fetch(`/api/semantic-models/concepts/${encodeURIComponent(iri)}`);
          if (!r.ok) return;
          const data = await r.json();
          const detail = data.concept ?? data;
          if (detail?.label) labelMap.set(iri, detail.label);
        } catch { /* ignore */ }
      })
    );

    if (labelMap.size === 0) return;

    const enrich = (iris: string[]): ConceptRef[] =>
      iris.map(iri => ({ iri, label: labelMap.get(iri) || iri.split(/[/#]/).pop() || iri }));

    setParentRefs(enrich(c.parent_concepts ?? []));
    setChildRefs(enrich(c.child_concepts ?? []));
    setRelatedRefs(enrich(c.related_concepts ?? []));
  };

  const handleNavigate = useCallback((iri: string) => {
    if (onNavigate) {
      onNavigate(iri);
    }
  }, [onNavigate]);

  return (
    <Sheet open={!!conceptIri} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent
        side="right"
        className="w-[380px] sm:max-w-[420px] p-0 flex flex-col gap-0"
        data-testid="concept-detail-panel"
        // No single description fits a panel that scrolls through many SKOS
        // sections; opt out of Radix's auto-aria-describedby check explicitly.
        aria-describedby={undefined}
      >
        {/* Colored type stripe */}
        {concept && (
          <div
            className={`h-[3px] flex-shrink-0 ${W3C_TYPE_STRIPE_CLASS[concept.concept_type] || W3C_TYPE_STRIPE_CLASS.concept}`}
          />
        )}

        {/* Header. Edit/Delete sit at right-12 to leave the standard right-4
            slot free for Sheet's built-in close (X) button — keeps interaction
            patterns consistent with the rest of the app's slide-in panels. */}
        <div className="px-6 pt-5 pb-4 border-b sticky top-0 bg-background z-10">
          {(onEdit || onDelete) && concept && (
            <div className="absolute top-4 right-12 flex items-center gap-1">
              {onEdit && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => onEdit(concept)}
                  aria-label="Edit concept"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
              {onDelete && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-destructive hover:text-destructive"
                  onClick={() => onDelete(concept)}
                  aria-label="Delete concept"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}

          {concept ? (() => {
            const badgeClasses = W3C_TYPE_BADGE_CLASS[concept.concept_type] || W3C_TYPE_BADGE_CLASS.concept;
            return (
              <>
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium border ${badgeClasses}`}
                  >
                    {W3C_TYPE_LABEL[concept.concept_type] || concept.concept_type}
                  </span>
                  {concept.is_top_concept && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-300 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-600">
                      <svg className="w-2.5 h-2.5" viewBox="0 0 12 12" fill="currentColor"><polygon points="6,0.5 7.8,4.2 12,4.7 8.8,7.5 9.6,11.5 6,9.5 2.4,11.5 3.2,7.5 0,4.7 4.2,4.2"/></svg>
                      Top Concept
                    </span>
                  )}
                </div>
                <SheetTitle className="text-xl font-bold pr-8 leading-tight">
                  {concept.label || concept.iri.split(/[/#]/).pop()}
                </SheetTitle>
                <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                  {concept.notation && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded bg-muted font-mono text-xs font-semibold text-foreground/80 border border-border tracking-wide">
                      {concept.notation}
                    </span>
                  )}
                  <span className="font-mono text-[11px] text-muted-foreground truncate max-w-[200px]" title={concept.iri}>
                    {concept.iri.split(/[/#]/).pop()}
                  </span>
                </div>
              </>
            );
          })() : (
            <>
              <SheetTitle className="sr-only">Concept Details</SheetTitle>
              <div className="text-muted-foreground">Loading...</div>
            </>
          )}
        </div>

        {/* Body */}
        <ScrollArea className="flex-1">
          <div className="p-6 space-y-5">
            {loading && (
              <div className="flex items-center gap-2 text-muted-foreground" data-testid="concept-panel-loading">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading concept...
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-destructive text-sm" data-testid="concept-panel-error">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}

            {concept && (
              <>
                {/* Synonyms / Alt Labels */}
                {concept.synonyms?.length > 0 && (
                  <Section label="Also known as">
                    <div className="flex flex-wrap gap-1.5" data-testid="concept-alt-labels">
                      {concept.synonyms.map(alt => (
                        <Badge key={alt} variant="outline" className="text-xs font-normal">
                          {alt}
                        </Badge>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Definition */}
                {concept.comment && (
                  <Section label="Definition">
                    <p className="text-sm leading-relaxed" data-testid="concept-definition">
                      {concept.comment}
                    </p>
                  </Section>
                )}

                <Separator />

                {/* Parents grouped by predicate type */}
                {parentRefs.length > 0 && (() => {
                  // Group parents by predicate label when typed data is available
                  const typedMap = new Map<string, string>();
                  concept.typed_parents?.forEach(tp => typedMap.set(tp.iri, tp.predicate_label));
                  const groups: Record<string, ConceptRef[]> = {};
                  parentRefs.forEach(ref => {
                    const pred = typedMap.get(ref.iri) || 'Broader';
                    (groups[pred] ??= []).push(ref);
                  });
                  return Object.entries(groups).map(([pred, refs]) => (
                    <Section key={`parent-${pred}`} label={pred} accentColor={PREDICATE_ACCENT[pred]}>
                      <div className="flex flex-wrap gap-1.5" data-testid="concept-broader">
                        {refs.map(c => (
                          <ConceptPill
                            key={c.iri}
                            label={c.label}
                            onClick={() => handleNavigate(c.iri)}
                          />
                        ))}
                      </div>
                    </Section>
                  ));
                })()}

                {/* Children grouped by predicate type */}
                {childRefs.length > 0 && (() => {
                  const typedMap = new Map<string, string>();
                  concept.typed_children?.forEach(tc => typedMap.set(tc.iri, tc.predicate_label));
                  const groups: Record<string, ConceptRef[]> = {};
                  childRefs.forEach(ref => {
                    const pred = typedMap.get(ref.iri) || 'Narrower';
                    (groups[pred] ??= []).push(ref);
                  });
                  return Object.entries(groups).map(([pred, refs]) => (
                    <Section key={`child-${pred}`} label={pred} accentColor={PREDICATE_ACCENT[pred]}>
                      <div className="flex flex-wrap gap-1.5" data-testid="concept-narrower">
                        {refs.map(c => (
                          <ConceptPill
                            key={c.iri}
                            label={c.label}
                            onClick={() => handleNavigate(c.iri)}
                          />
                        ))}
                      </div>
                    </Section>
                  ));
                })()}

                {/* Related grouped by predicate type */}
                {relatedRefs.length > 0 && (() => {
                  const typedMap = new Map<string, string>();
                  concept.typed_related?.forEach(tr => typedMap.set(tr.iri, tr.predicate_label));
                  const groups: Record<string, ConceptRef[]> = {};
                  relatedRefs.forEach(ref => {
                    const pred = typedMap.get(ref.iri) || 'Related';
                    (groups[pred] ??= []).push(ref);
                  });
                  return Object.entries(groups).map(([pred, refs]) => (
                    <Section key={`related-${pred}`} label={pred} accentColor={PREDICATE_ACCENT[pred]}>
                      <div className="flex flex-wrap gap-1.5" data-testid="concept-related">
                        {refs.map(c => (
                          <ConceptPill
                            key={c.iri}
                            label={c.label}
                            onClick={() => handleNavigate(c.iri)}
                          />
                        ))}
                      </div>
                    </Section>
                  ));
                })()}

                {/* Scheme membership */}
                {concept.in_scheme && (
                  <Section label="skos:inScheme" accentColor="#8b5cf6">
                    <ConceptPill
                      label={concept.in_scheme.split(/[/#]/).pop() || concept.in_scheme}
                      onClick={() => handleNavigate(concept.in_scheme!)}
                    />
                  </Section>
                )}

                {/* Tagged Assets */}
                {concept.tagged_assets?.length > 0 && (
                  <>
                    <Separator />
                    <Section label="Tagged Assets">
                      <div className="space-y-1">
                        {concept.tagged_assets.map(asset => (
                          <div key={asset.id} className="flex items-center gap-2 text-sm">
                            <ExternalLink className="h-3 w-3 text-muted-foreground" />
                            <span>{asset.name}</span>
                            {asset.type && (
                              <Badge variant="outline" className="text-[10px]">{asset.type}</Badge>
                            )}
                          </div>
                        ))}
                      </div>
                    </Section>
                  </>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
};

// ---- Helper Components ----

const Section: React.FC<{ label: string; children: React.ReactNode; accentColor?: string }> = ({ label, children, accentColor }) => (
  <div
    className={accentColor ? 'pl-3 border-l-[3px]' : ''}
    style={accentColor ? { borderLeftColor: accentColor } : undefined}
  >
    <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 font-mono">
      {label}
    </div>
    {children}
  </div>
);

const ConceptPill: React.FC<{ label: string; onClick: () => void }> = ({ label, onClick }) => (
  <button
    onClick={onClick}
    className="inline-flex items-center px-3 py-1 rounded-full bg-muted text-primary text-xs font-medium hover:bg-primary/10 hover:shadow-sm active:scale-[0.97] transition-all cursor-pointer border border-transparent hover:border-primary/20"
  >
    {label}
  </button>
);

export default ConceptDetailPanel;
