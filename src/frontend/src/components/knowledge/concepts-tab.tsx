import { useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Search,
  Plus,
  ChevronRight,
  ChevronDown,
  Layers,
  BookOpen,
  Zap,
  User,
  FolderTree,
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
  onCreateConcept: () => void;
  // Display options (from unified filter panel)
  groupBySource: boolean;
  showProperties: boolean;
  groupByDomain: boolean;
  selectedLanguage: string;
  canEdit: boolean;
}

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

export const ConceptsTab: React.FC<ConceptsTabProps> = ({
  collections,
  groupedConcepts: _groupedConcepts,
  filteredConcepts,
  selectedConcept,
  onSelectConcept,
  onCreateConcept,
  groupBySource,
  showProperties: _showProperties,
  groupByDomain,
  selectedLanguage,
  canEdit,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const expandedGroups = useGlossaryPreferencesStore((s) => s.expandedConceptGroups);
  const toggleConceptGroup = useGlossaryPreferencesStore((s) => s.toggleConceptGroup);
  const setExpandedConceptGroups = useGlossaryPreferencesStore((s) => s.setExpandedConceptGroups);
  const conceptListScrollTop = useGlossaryPreferencesStore((s) => s.conceptListScrollTop);
  const setConceptListScrollTop = useGlossaryPreferencesStore((s) => s.setConceptListScrollTop);
  const searchQuery = useGlossaryPreferencesStore((s) => s.conceptListSearch);
  const setSearchQuery = useGlossaryPreferencesStore((s) => s.setConceptListSearch);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

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

  // Render a single tree row with rich content (icon + label + type + collection
  // + status pill + property hints).
  const renderTreeItem = (itemId: string, level: number = 0): React.ReactNode => {
    const isSourceGroup = groupBySource && treeData.sourceContexts.includes(itemId);
    const concept = treeData.conceptMap.get(itemId);
    const isExpanded = expandedGroups.includes(itemId) || (searchQuery.length > 0);
    const hasChildren = isFolder(itemId);
    const children = getChildren(itemId);
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
        {canEdit && (
          <Button
            variant="outline"
            size="sm"
            onClick={onCreateConcept}
          >
            <Plus className="h-4 w-4 mr-2" />
            {t('semantic-models:actions.createConcept')}
          </Button>
        )}
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
        <div className="p-2 min-w-max">
          {rootConcepts.map(id => renderTreeItem(id, 0))}

          {rootConcepts.length === 0 && (
            <div className="text-center text-muted-foreground py-12">
              <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>{t('semantic-models:messages.noConceptsFound')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
