import { useEffect, useMemo, useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import {
  Search,
  ChevronRight,
  ChevronDown,
  Layers,
  BookOpen,
  Zap,
  User,
  FolderTree,
  Pencil,
  ArrowRight,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  OntologyConcept,
  KnowledgeCollection,
  GroupedConcepts,
} from '@/types/ontology';
import { resolveLabel } from '@/lib/ontology-utils';
import { systemRdfNamespaceDisplayLabel } from '@/lib/system-rdf-namespace-labels';
import { useGlossaryPreferencesStore } from '@/stores/glossary-preferences-store';

interface ConceptsTabProps {
  collections: KnowledgeCollection[];
  groupedConcepts: GroupedConcepts;
  filteredConcepts: OntologyConcept[];
  selectedConcept?: OntologyConcept | null;
  onSelectConcept: (concept: OntologyConcept) => void;
  // Display options (from unified filter panel)
  groupBySource: boolean;
  showProperties: boolean;
  groupByDomain: boolean;
  selectedLanguage: string;
  // Render mode. 'tree' (default) preserves the existing hierarchical engine;
  // 'list' renders a flat, alphabetically-sorted list of concepts with no
  // broader/narrower nesting. Additive — the tree path is unchanged.
  viewMode?: 'list' | 'tree';
  // Callback to open editor for a concept (list view only)
  onEditConcept?: (concept: OntologyConcept) => void;
  // Called after a bulk action mutates concepts, so the parent can refetch.
  onConceptsChanged?: () => void;
}

// Bulk "Set status" targets → the real lifecycle transition endpoints. Only
// the safe, always-available forward transitions are offered here; the backend
// still enforces VALID_TRANSITIONS and returns an error for invalid ones.
const BULK_STATUS_ACTIONS: { action: string; labelKey: string; defaultLabel: string }[] = [
  { action: 'submit-review', labelKey: 'semantic-models:bulk.status.submitReview', defaultLabel: 'Submit for review' },
  { action: 'approve', labelKey: 'semantic-models:bulk.status.approve', defaultLabel: 'Approve' },
  { action: 'publish', labelKey: 'semantic-models:bulk.status.publish', defaultLabel: 'Publish' },
  { action: 'certify', labelKey: 'semantic-models:bulk.status.certify', defaultLabel: 'Certify' },
  { action: 'deprecate', labelKey: 'semantic-models:bulk.status.deprecate', defaultLabel: 'Deprecate' },
  { action: 'archive', labelKey: 'semantic-models:bulk.status.archive', defaultLabel: 'Archive' },
];

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Layers className="h-4 w-4 text-emerald-500 shrink-0" />,
  class: <BookOpen className="h-4 w-4 text-blue-500 shrink-0" />,
  property: <Zap className="h-4 w-4 text-purple-500 shrink-0" />,
  individual: <User className="h-4 w-4 text-violet-500 shrink-0" />,
  term: <Layers className="h-4 w-4 text-emerald-500 shrink-0" />,
};

const typeColors: Record<string, string> = {
  concept: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  class: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  property: 'bg-purple-500/15 text-purple-700 dark:text-purple-400 border-purple-500/30',
  individual: 'bg-violet-500/15 text-violet-700 dark:text-violet-400 border-violet-500/30',
  term: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
};

// Statuses that mean a concept is no longer active clutter — dim them and,
// when they name successors, offer a "Replaced by" link. Kept broad so both
// `deprecated` and any `superseded`/`retired`/`archived` values are covered.
const INACTIVE_STATUSES = new Set(['deprecated', 'superseded', 'retired', 'archived']);
function isInactiveStatus(status?: string | null): boolean {
  return !!status && INACTIVE_STATUSES.has(status);
}

const STATUS_VARIANTS: Record<string, string> = {
  draft: 'bg-muted text-muted-foreground border-muted-foreground/20',
  pending: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
  in_review: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
  under_review: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
  active: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  approved: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  published: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  certified: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  deprecated: 'bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/30',
  archived: 'bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30',
  retired: 'bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30',
};

// Per-concept mapping status, from POST /api/semantic-links/mapping-status.
// Whether a concept links to a physical Asset, a data Product, and/or a data
// Contract. The three are independent (a concept can link to several), so they
// do not partition — they drive the single "Mapping" summary column.
interface MappingStatus {
  asset?: boolean;
  product?: boolean;
  contract?: boolean;
}

// Reduce a MappingStatus to the one label the wireframe shows in the Mapping
// column. `undefined` status => not yet loaded (or endpoint unavailable).
function mappingLabel(
  status: MappingStatus | undefined,
  t: (k: string, d?: any) => string,
): { text: string; none: boolean } | null {
  if (!status) return null; // not loaded — caller renders a muted dash
  const product = !!status.product || !!status.contract;
  if (status.asset && product) {
    return { text: t('semantic-models:mapping.assetAndProduct', 'Asset + product'), none: false };
  }
  if (status.asset) {
    return { text: t('semantic-models:mapping.asset', 'Asset'), none: false };
  }
  if (product) {
    return { text: t('semantic-models:mapping.product', 'Product'), none: false };
  }
  return { text: t('semantic-models:mapping.none', 'Not mapped'), none: true };
}

export const ConceptsTab: React.FC<ConceptsTabProps> = ({
  collections,
  groupedConcepts: _groupedConcepts,
  filteredConcepts,
  selectedConcept,
  onSelectConcept,
  groupBySource,
  showProperties: _showProperties,
  groupByDomain,
  selectedLanguage,
  viewMode = 'tree',
  onEditConcept,
  onConceptsChanged,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();
  const expandedGroups = useGlossaryPreferencesStore((s) => s.expandedConceptGroups);
  const toggleConceptGroup = useGlossaryPreferencesStore((s) => s.toggleConceptGroup);
  const setExpandedConceptGroups = useGlossaryPreferencesStore((s) => s.setExpandedConceptGroups);
  const conceptListScrollTop = useGlossaryPreferencesStore((s) => s.conceptListScrollTop);
  const setConceptListScrollTop = useGlossaryPreferencesStore((s) => s.setConceptListScrollTop);
  const searchQuery = useGlossaryPreferencesStore((s) => s.conceptListSearch);
  const setSearchQuery = useGlossaryPreferencesStore((s) => s.setConceptListSearch);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  // Bulk-select state (list view only). Tracks selected concept IRIs; a light
  // bulk-action bar appears when any are selected. Selection is component-local
  // and resets when the view mode changes.
  const [selectedIris, setSelectedIris] = useState<Set<string>>(new Set());
  useEffect(() => {
    setSelectedIris(new Set());
  }, [viewMode]);

  const toggleRowSelect = useCallback((iri: string) => {
    setSelectedIris((prev) => {
      const next = new Set(prev);
      if (next.has(iri)) next.delete(iri);
      else next.add(iri);
      return next;
    });
  }, []);

  const [bulkBusy, setBulkBusy] = useState(false);

  // Bulk "Set status": POST the chosen lifecycle transition for every selected
  // concept. The backend enforces VALID_TRANSITIONS, so concepts in a state
  // that can't take the transition come back as errors — we count and report
  // successes vs failures rather than assuming all succeed.
  const runBulkStatus = useCallback(
    async (action: string, label: string) => {
      const iris = Array.from(selectedIris);
      if (iris.length === 0) return;
      setBulkBusy(true);
      let ok = 0;
      let failed = 0;
      for (const iri of iris) {
        try {
          const res = await fetch(
            `/api/knowledge/concepts/by-iri/${action}?iri=${encodeURIComponent(iri)}`,
            { method: 'POST' },
          );
          if (res.ok) ok += 1;
          else failed += 1;
        } catch {
          failed += 1;
        }
      }
      setBulkBusy(false);
      toast({
        title:
          failed === 0
            ? t('common:toast.success', 'Success')
            : t('semantic-models:bulk.partial', 'Completed with some errors'),
        description: t(
          'semantic-models:bulk.statusResult',
          '{{label}}: {{ok}} updated, {{failed}} skipped',
          { label, ok, failed },
        ),
        variant: failed > 0 && ok === 0 ? 'destructive' : undefined,
      });
      setSelectedIris(new Set());
      onConceptsChanged?.();
    },
    [selectedIris, toast, t, onConceptsChanged],
  );

  // Per-IRI mapping status, fetched in one batch from the read-model endpoint.
  // Degrades gracefully: if the endpoint is unavailable (e.g. not yet deployed),
  // the map stays empty and the Mapping column shows a muted dash.
  const [mappingStatus, setMappingStatus] = useState<Record<string, MappingStatus>>({});

  // Successor IRIs per concept, from the versioning contract §1
  // (GET .../version → replaced_by_iris). Only fetched for concepts whose
  // status is inactive (deprecated/superseded/retired), so we can render a
  // "Replaced by {successor}" link. Degrades silently if the endpoint is
  // unavailable. Keyed by concept IRI; [] means "checked, no successor".
  const { get } = useApi();
  const [successorsByIri, setSuccessorsByIri] = useState<Record<string, string[]>>({});

  // Restore scroll position once after mount, then again whenever the data
  // size changes substantially. Saving happens on scroll.
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTop = conceptListScrollTop;
    // Only restore on mount; subsequent changes are user-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build tree data structure from concepts
  const treeData = useMemo(() => {
    const conceptMap = new Map<string, OntologyConcept>();
    const hierarchy = new Map<string, string[]>();
    const sourceContexts = new Set<string>();

    const baseConcepts = filteredConcepts.filter(concept => {
      const conceptType = concept.concept_type;
      return conceptType === 'class' || conceptType === 'concept' || conceptType === 'property';
    });

    baseConcepts.forEach(concept => {
      conceptMap.set(concept.iri, concept);

      if (concept.source_context) {
        sourceContexts.add(concept.source_context);
      }

      concept.parent_concepts.forEach(parentIri => {
        if (!hierarchy.has(parentIri)) {
          hierarchy.set(parentIri, []);
        }
        const parentChildren = hierarchy.get(parentIri)!;
        if (!parentChildren.includes(concept.iri)) {
          parentChildren.push(concept.iri);
        }
      });

      if (!hierarchy.has(concept.iri)) {
        hierarchy.set(concept.iri, []);
      }
    });

    return { conceptMap, hierarchy, sourceContexts: Array.from(sourceContexts).sort() };
  }, [filteredConcepts]);

  const rootConcepts = useMemo(() => {
    if (groupBySource) {
      return treeData.sourceContexts;
    }

    return Array.from(treeData.conceptMap.values())
      .filter(concept => {
        if (groupByDomain && concept.concept_type === 'property' && concept.domain) {
          return false;
        }
        return concept.parent_concepts.length === 0 ||
               !concept.parent_concepts.some(parentIri => treeData.conceptMap.has(parentIri));
      })
      .map(concept => concept.iri);
  }, [treeData, groupBySource, groupByDomain]);

  const getChildren = useCallback((itemId: string): string[] => {
    if (groupBySource && treeData.sourceContexts.includes(itemId)) {
      return Array.from(treeData.conceptMap.values())
        .filter(concept => {
          const matchesSource = concept.source_context === itemId;
          if (groupByDomain && concept.concept_type === 'property' && concept.domain) {
            return false;
          }
          const isRootLevel = concept.parent_concepts.length === 0 ||
                 !concept.parent_concepts.some(parentIri => treeData.conceptMap.has(parentIri));
          return matchesSource && isRootLevel;
        })
        .map(concept => concept.iri);
    }

    if (groupByDomain) {
      const regularChildren = treeData.hierarchy.get(itemId) || [];
      const propertiesWithThisDomain = Array.from(treeData.conceptMap.values())
        .filter(concept => concept.concept_type === 'property' && concept.domain === itemId)
        .map(concept => concept.iri);
      return [...new Set([...regularChildren, ...propertiesWithThisDomain])];
    }

    return treeData.hierarchy.get(itemId) || [];
  }, [treeData, groupBySource, groupByDomain]);

  const isFolder = useCallback((itemId: string): boolean => {
    if (groupBySource && treeData.sourceContexts.includes(itemId)) {
      return true;
    }

    const concept = treeData.conceptMap.get(itemId);
    if (!concept) return false;

    if (groupByDomain) {
      const hasPropertiesWithThisDomain = Array.from(treeData.conceptMap.values()).some(
        c => c.concept_type === 'property' && c.domain === concept.iri
      );
      if (hasPropertiesWithThisDomain) return true;
    }

    const children = treeData.hierarchy.get(itemId) || [];
    return children.length > 0 || (concept.child_concepts && concept.child_concepts.length > 0);
  }, [treeData, groupBySource, groupByDomain]);

  // When switching grouping modes, expand the new top-level groups so users
  // see something meaningful instead of a collapsed flat list.
  useEffect(() => {
    if (groupBySource && treeData.sourceContexts.length > 0) {
      const next = new Set(expandedGroups);
      treeData.sourceContexts.forEach((s) => next.add(s));
      if (next.size !== expandedGroups.length) {
        setExpandedConceptGroups(Array.from(next));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupBySource, treeData.sourceContexts.join('|')]);

  const getCollection = useCallback((context?: string) => {
    if (!context) return null;
    return collections.find(c =>
      c.iri === context || c.iri.endsWith(`:${context}`)
    );
  }, [collections]);

  const handleSelect = useCallback((concept: OntologyConcept) => {
    // Save current scroll position so we can restore it on the way back.
    if (scrollContainerRef.current) {
      setConceptListScrollTop(scrollContainerRef.current.scrollTop);
    }
    onSelectConcept(concept);
  }, [onSelectConcept, setConceptListScrollTop]);

  const conceptLabel = useCallback(
    (concept: OntologyConcept) => resolveLabel(concept, selectedLanguage),
    [selectedLanguage],
  );

  // Flat list (list view-mode only): all concepts from the same filtered/typed
  // selection the tree is built from, sorted alphabetically by label. No
  // broader/narrower nesting. groupByDomain still hides domain-owned properties
  // (mirrors the tree's rootConcepts logic) so the two modes cover the same set.
  const flatConcepts = useMemo(() => {
    return Array.from(treeData.conceptMap.values())
      .filter(concept => {
        if (groupByDomain && concept.concept_type === 'property' && concept.domain) {
          return false;
        }
        return true;
      })
      .sort((a, b) =>
        conceptLabel(a).localeCompare(conceptLabel(b), undefined, { sensitivity: 'base' }),
      );
  }, [treeData, groupByDomain, conceptLabel]);

  // Batch-fetch mapping status for the concepts currently on screen (list view).
  // One request for the whole visible set, not per-row. Only IRIs we don't
  // already have are requested, so paging/filtering top-ups stay cheap.
  useEffect(() => {
    if (viewMode !== 'list') return;
    const iris = flatConcepts
      .map((c) => c.iri)
      .filter((iri) => !(iri in mappingStatus));
    if (iris.length === 0) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/semantic-links/mapping-status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ iris }),
        });
        if (!res.ok) return; // endpoint unavailable — leave column as muted dash
        const data = await res.json();
        if (cancelled || !data?.statuses) return;
        setMappingStatus((prev) => ({ ...prev, ...data.statuses }));
      } catch {
        // Network/endpoint error — degrade silently to muted dash.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, flatConcepts]);

  // Fetch successor IRIs for the visible inactive concepts (deprecated /
  // superseded / retired). One §1 read per such concept; results are cached, so
  // scrolling/filtering only queries the newly-seen ones. Runs in both list and
  // tree modes (both surface status badges).
  useEffect(() => {
    const targets = filteredConcepts.filter(
      (c) => isInactiveStatus(c.status) && !(c.iri in successorsByIri),
    );
    if (targets.length === 0) return;

    let cancelled = false;
    (async () => {
      const updates: Record<string, string[]> = {};
      for (const c of targets) {
        try {
          const res = await get<{ replaced_by_iris?: string[] }>(
            `/api/semantic-models/concepts/version?iri=${encodeURIComponent(c.iri)}`,
          );
          if (cancelled) return;
          updates[c.iri] = res.data?.replaced_by_iris ?? [];
        } catch {
          if (cancelled) return;
          updates[c.iri] = [];
        }
      }
      if (!cancelled && Object.keys(updates).length > 0) {
        setSuccessorsByIri((prev) => ({ ...prev, ...updates }));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredConcepts]);

  // Resolve an IRI to a human label from the concepts we already have. Simple
  // view must never show a raw IRI, so fall back to the last path segment (a
  // readable-ish token) rather than the full IRI when the concept isn't loaded.
  const labelForIri = useCallback(
    (iri: string): string => {
      const match = treeData.conceptMap.get(iri) || filteredConcepts.find((c) => c.iri === iri);
      if (match) return conceptLabel(match);
      return iri.split(/[/#]/).pop() || iri;
    },
    [treeData, filteredConcepts, conceptLabel],
  );

  // The "Replaced by {successor}" link shown on inactive concepts that name a
  // successor. Navigates to the successor's detail page. Rendered in both the
  // tree row and the list row.
  const renderReplacedBy = (concept: OntologyConcept): React.ReactNode => {
    if (!isInactiveStatus(concept.status)) return null;
    const successors = successorsByIri[concept.iri];
    if (!successors || successors.length === 0) return null;
    const primary = successors[0];
    return (
      <button
        type="button"
        className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline shrink-0"
        title={t('semantic-models:versionHistory.replacedBy', 'Replaced by {{label}}', {
          label: labelForIri(primary),
        })}
        onClick={(e) => {
          e.stopPropagation();
          const target = treeData.conceptMap.get(primary) || filteredConcepts.find((c) => c.iri === primary);
          if (target) onSelectConcept(target);
        }}
      >
        <ArrowRight className="h-3 w-3" />
        {t('semantic-models:versionHistory.replacedBy', 'Replaced by {{label}}', {
          label: labelForIri(primary),
        })}
      </button>
    );
  };

  // Render a single tree row with rich content (icon + label + type + collection
  // + status pill + property hints).
  //
  // `flat` (default false) is used ONLY by the list view-mode: it forces the row
  // to render as a leaf (no expand chevron, no child recursion) so the SAME row
  // markup can be reused for a flat list without a divergent copy. The tree path
  // never passes `flat`, so its rendering output is unchanged.
  const renderTreeItem = (itemId: string, level: number = 0, flat: boolean = false): React.ReactNode => {
    const isSourceGroup = groupBySource && treeData.sourceContexts.includes(itemId);
    const concept = treeData.conceptMap.get(itemId);
    const isExpanded = !flat && (expandedGroups.includes(itemId) || (searchQuery.length > 0));
    const hasChildren = !flat && isFolder(itemId);
    const children = flat ? [] : getChildren(itemId);
    const isSelected = selectedConcept?.iri === itemId;

    if (isSourceGroup && searchQuery) {
      const hasMatchingChildren = children.some(childId => {
        const child = treeData.conceptMap.get(childId);
        if (!child) return false;
        const query = searchQuery.toLowerCase();
        return child.label?.toLowerCase().includes(query) ||
               child.comment?.toLowerCase().includes(query) ||
               child.iri.toLowerCase().includes(query);
      });
      if (!hasMatchingChildren) return null;
    }

    if (!isSourceGroup && searchQuery && concept) {
      const query = searchQuery.toLowerCase();
      const matchesSelf = concept.label?.toLowerCase().includes(query) ||
                          concept.comment?.toLowerCase().includes(query) ||
                          concept.iri.toLowerCase().includes(query);

      const hasMatchingDescendants = (): boolean => {
        const stack = [...children];
        while (stack.length > 0) {
          const childId = stack.pop()!;
          const child = treeData.conceptMap.get(childId);
          if (child) {
            if (child.label?.toLowerCase().includes(query) ||
                child.comment?.toLowerCase().includes(query) ||
                child.iri.toLowerCase().includes(query)) {
              return true;
            }
            stack.push(...getChildren(childId));
          }
        }
        return false;
      };

      if (!matchesSelf && !hasMatchingDescendants()) {
        return null;
      }
    }

    const getConceptIcon = () => {
      if (isSourceGroup) {
        return <FolderTree className="h-4 w-4 shrink-0 text-orange-500" />;
      }
      return typeIcons[concept?.concept_type || 'concept'] || <Layers className="h-4 w-4 shrink-0" />;
    };

    const displayName = isSourceGroup
      ? systemRdfNamespaceDisplayLabel(itemId, t)
      : (concept ? conceptLabel(concept) : itemId);

    const collection = concept?.source_context ? getCollection(concept.source_context) : null;
    const collectionLabel = collection?.label
      || (concept?.source_context ? systemRdfNamespaceDisplayLabel(concept.source_context, t) : null);

    return (
      <div key={itemId}>
        <div
          role={isSourceGroup ? 'button' : 'link'}
          tabIndex={0}
          data-testid={isSourceGroup ? `concept-group-${itemId}` : `concept-row-${itemId}`}
          className={cn(
            "flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer w-full text-left",
            "hover:bg-accent hover:text-accent-foreground transition-colors",
            isSelected && !isSourceGroup && "bg-primary/10 text-primary",
            isSourceGroup && "font-semibold bg-muted/40",
            // Dim inactive concepts (deprecated/superseded/retired) so they
            // don't read as active clutter. Hover restores full opacity.
            !isSourceGroup && isInactiveStatus(concept?.status) && "opacity-60 hover:opacity-100",
          )}
          style={{ paddingLeft: `${level * 12 + 8}px` }}
          onClick={() => {
            if (!isSourceGroup && concept) {
              handleSelect(concept);
            } else if (hasChildren) {
              toggleConceptGroup(itemId);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              if (!isSourceGroup && concept) {
                handleSelect(concept);
              } else if (hasChildren) {
                toggleConceptGroup(itemId);
              }
            }
          }}
        >
          <div className="flex items-center w-5 justify-center shrink-0">
            {hasChildren && (
              <button
                type="button"
                aria-label={isExpanded ? 'Collapse' : 'Expand'}
                className="p-0.5 hover:bg-muted rounded"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleConceptGroup(itemId);
                }}
              >
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                )}
              </button>
            )}
          </div>

          {getConceptIcon()}

          <span className="truncate text-sm font-medium" title={displayName}>
            {displayName}
          </span>

          {/* Right-side metadata: type, collection, status, property hints */}
          {!isSourceGroup && concept && (
            <div className="ml-auto flex items-center gap-2 shrink-0 pl-2">
              {concept.concept_type === 'property' && (concept.domain || concept.range) && (
                <span
                  className="hidden md:inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground font-mono truncate max-w-[260px]"
                  title={`${concept.domain || '?'} → ${concept.range || '?'}`}
                >
                  {(concept.domain ? concept.domain.split(/[/#]/).pop() : '?')}
                  <span className="opacity-60">→</span>
                  {(concept.range ? concept.range.split(/[/#]/).pop() : '?')}
                </span>
              )}
              {collectionLabel && (
                <Badge
                  variant="outline"
                  className="hidden lg:inline-flex text-[10px] font-normal max-w-[200px] truncate border-muted-foreground/20"
                  title={collectionLabel}
                >
                  {collectionLabel}
                </Badge>
              )}
              <Badge
                variant="outline"
                className={cn('text-[10px] font-medium', typeColors[concept.concept_type] || '')}
              >
                {t(`semantic-models:types.${concept.concept_type}`)}
              </Badge>
              {concept.status && (
                <Badge
                  variant="outline"
                  className={cn(
                    'hidden sm:inline-flex text-[10px] font-medium',
                    STATUS_VARIANTS[concept.status] || '',
                  )}
                >
                  {t(`semantic-models:status.${concept.status}`, concept.status)}
                </Badge>
              )}
              {renderReplacedBy(concept)}
              {onEditConcept && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-foreground"
                  aria-label={t('common:actions.edit')}
                  title={t('common:actions.edit')}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEditConcept(concept);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          )}

          {isSourceGroup && (
            <Badge variant="secondary" className="text-xs ml-auto">
              {children.length}
            </Badge>
          )}
        </div>

        {hasChildren && isExpanded && (
          <div className="ml-2">
            {children.map(childId => renderTreeItem(childId, level + 1))}
          </div>
        )}
      </div>
    );
  };

  // Grid column template shared by the list header and list rows so cells align.
  // checkbox | name+definition | Kind | Scheme | Mapping | Status | edit
  // Name is capped (minmax with a max) and Scheme/Mapping get flexible shares so
  // on wide screens the columns spread out instead of clustering on the right.
  const LIST_GRID =
    'grid grid-cols-[28px_minmax(220px,1.6fr)_110px_minmax(120px,1fr)_minmax(120px,0.8fr)_110px_40px] gap-4 items-center';

  // Render one flat LIST row: a real table row with columns, a bulk-select
  // checkbox, and an inline edit pencil. Distinct from renderTreeItem so the
  // tree engine stays untouched; only the list gets the columnar layout.
  const renderListRow = (concept: OntologyConcept): React.ReactNode => {
    const label = conceptLabel(concept);
    const definition = concept.comment || '';
    const collection = concept.source_context ? getCollection(concept.source_context) : null;
    const collectionLabel = collection?.label
      || (concept.source_context ? systemRdfNamespaceDisplayLabel(concept.source_context, t) : '');
    const map = mappingLabel(mappingStatus[concept.iri], t);
    const checked = selectedIris.has(concept.iri);

    return (
      <div
        key={concept.iri}
        data-testid={`concept-row-${concept.iri}`}
        className={cn(
          LIST_GRID,
          'px-3 py-2 border-b last:border-b-0 cursor-pointer transition-colors',
          checked ? 'bg-sky-500/[0.08]' : 'hover:bg-accent',
          // Dim inactive concepts (deprecated/superseded/retired); hover restores.
          isInactiveStatus(concept.status) && !checked && 'opacity-60 hover:opacity-100',
        )}
        onClick={() => handleSelect(concept)}
      >
        <div onClick={(e) => e.stopPropagation()} className="flex items-center justify-center">
          <Checkbox
            checked={checked}
            onCheckedChange={() => toggleRowSelect(concept.iri)}
            aria-label={t('common:actions.select', 'Select')}
          />
        </div>

        <div className="flex items-center gap-2 min-w-0">
          {typeIcons[concept.concept_type] || typeIcons.concept}
          <div className="min-w-0">
            <div className="truncate text-sm font-medium" title={label}>{label}</div>
            {definition && (
              <div className="truncate text-xs text-muted-foreground" title={definition}>
                {definition}
              </div>
            )}
            {/* Raw IRI is the ontology layer — shown only in Advanced view. */}
            <div className="adv-only truncate text-[10px] font-mono text-muted-foreground/80" title={concept.iri}>
              {concept.iri}
            </div>
          </div>
        </div>

        <span className="text-xs text-muted-foreground truncate">
          {t(`semantic-models:types.${concept.concept_type}`)}
        </span>

        <span className="text-sm truncate" title={collectionLabel}>{collectionLabel}</span>

        <span
          className={cn(
            'text-sm truncate',
            map?.none && 'text-amber-700 dark:text-amber-400',
          )}
        >
          {map ? map.text : <span className="text-muted-foreground">—</span>}
        </span>

        <span className="min-w-0 flex flex-col items-start gap-0.5">
          {concept.status && (
            <Badge
              variant="outline"
              className={cn('text-[10px] font-medium', STATUS_VARIANTS[concept.status] || '')}
            >
              {t(`semantic-models:status.${concept.status}`, concept.status)}
            </Badge>
          )}
          {renderReplacedBy(concept)}
        </span>

        <div className="flex items-center justify-center" onClick={(e) => e.stopPropagation()}>
          {onEditConcept && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground"
              aria-label={t('common:actions.edit')}
              title={t('common:actions.edit')}
              onClick={() => onEditConcept(concept)}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>
    );
  };

  // Column header row for the list. Labels live here so cells stay quiet text.
  const listHeader = (
    <div
      className={cn(
        LIST_GRID,
        'px-3 py-2 border-b bg-muted/40 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sticky top-0 z-10',
      )}
    >
      <span />
      <span>{t('semantic-models:columns.name', 'Name')}</span>
      <span>{t('semantic-models:columns.kind', 'Kind')}</span>
      <span>{t('semantic-models:columns.scheme', 'Scheme')}</span>
      <span>{t('semantic-models:columns.mapping', 'Mapping')}</span>
      <span>{t('semantic-models:columns.status', 'Status')}</span>
      <span />
    </div>
  );

  // Light bulk-action bar, shown when any rows are selected (list view only).
  const bulkBar = selectedIris.size > 0 && (
    <div className="flex items-center gap-3 px-3 py-2 mb-2 rounded-md border border-sky-500/30 bg-sky-500/[0.08] text-sm">
      <b className="font-semibold">
        {t('semantic-models:bulk.selected', '{{count}} selected', { count: selectedIris.size })}
      </b>
      <div className="ml-auto flex items-center gap-2">
        {/* Set status: real lifecycle transitions across the selection. The
            backend enforces which transitions are valid per concept. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-7" disabled={bulkBusy}>
              {t('semantic-models:bulk.setStatus', 'Set status')}
              <ChevronDown className="h-3.5 w-3.5 ml-1" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {BULK_STATUS_ACTIONS.map((a) => {
              const label = t(a.labelKey, a.defaultLabel);
              return (
                <DropdownMenuItem key={a.action} onClick={() => runBulkStatus(a.action, label)}>
                  {label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={t('common:actions.clear', 'Clear')}
          onClick={() => setSelectedIris(new Set())}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );

  return (
    <div className="border rounded-lg flex flex-col bg-card overflow-hidden max-h-[calc(100vh-260px)]">
      <div className="p-2 border-b flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t('common:placeholders.searchConceptsAndTerms')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        className="flex-1 min-h-0 overflow-auto"
        onScroll={(e) => {
          const target = e.currentTarget;
          // Throttle via rAF; this is simple and good enough for a tree.
          if (target) {
            window.requestAnimationFrame(() => {
              setConceptListScrollTop(target.scrollTop);
            });
          }
        }}
      >
        <div className={cn('p-2', viewMode === 'list' ? 'min-w-[760px]' : 'min-w-max')}>
          {viewMode === 'list' ? (
            <>
              {bulkBar}
              {flatConcepts.length > 0 && listHeader}
              {groupBySource
                ? treeData.sourceContexts.map(source => {
                    const rows = flatConcepts.filter(c => c.source_context === source);
                    if (rows.length === 0) return null;
                    return (
                      <div key={`flat-group-${source}`}>
                        <div className="flex items-center gap-2 px-3 py-1.5 font-semibold bg-muted/40 border-b">
                          <FolderTree className="h-4 w-4 shrink-0 text-orange-500" />
                          <span className="truncate text-sm">
                            {systemRdfNamespaceDisplayLabel(source, t)}
                          </span>
                          <Badge variant="secondary" className="text-xs ml-auto">
                            {rows.length}
                          </Badge>
                        </div>
                        {rows.map(c => renderListRow(c))}
                      </div>
                    );
                  })
                : flatConcepts.map(c => renderListRow(c))}

              {flatConcepts.length === 0 && (
                <div className="text-center text-muted-foreground py-12">
                  <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p>{t('semantic-models:messages.noConceptsFound')}</p>
                </div>
              )}
            </>
          ) : (
            <>
              {rootConcepts.map(id => renderTreeItem(id, 0))}

              {rootConcepts.length === 0 && (
                <div className="text-center text-muted-foreground py-12">
                  <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p>{t('semantic-models:messages.noConceptsFound')}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
