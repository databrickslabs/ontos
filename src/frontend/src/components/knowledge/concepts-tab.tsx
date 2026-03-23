import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Search,
  Plus,
  ChevronRight,
  ChevronDown,
  Layers,
  BookOpen,
  Zap,
  Pencil,
  Trash2,
  User,
  ExternalLink,
  FolderTree,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  OntologyConcept,
  KnowledgeCollection,
  GroupedConcepts,
} from '@/types/ontology';
import { NodeLinksPanel } from '@/components/knowledge/node-links-panel';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import { resolveLabel, resolveComment } from '@/lib/ontology-utils';

interface ConceptsTabProps {
  collections: KnowledgeCollection[];
  groupedConcepts: GroupedConcepts;
  filteredConcepts: OntologyConcept[];
  selectedConcept: OntologyConcept | null;
  onSelectConcept: (concept: OntologyConcept) => void;
  onCreateConcept: () => void;
  onEditConcept: (concept: OntologyConcept) => void;
  onDeleteConcept: (concept: OntologyConcept) => void;
  onRefresh: () => Promise<void>;
  canEdit: boolean;
  // Display options (from unified filter panel)
  groupBySource: boolean;
  showProperties: boolean;
  groupByDomain: boolean;
  selectedLanguage: string;
}

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Layers className="h-4 w-4 text-emerald-500" />,
  class: <BookOpen className="h-4 w-4 text-blue-500" />,
  property: <Zap className="h-4 w-4 text-purple-500" />,
  individual: <User className="h-4 w-4 text-violet-500" />,
  term: <Layers className="h-4 w-4 text-emerald-500" />,
};

const typeColors: Record<string, string> = {
  concept: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400',
  class: 'bg-blue-500/20 text-blue-700 dark:text-blue-400',
  property: 'bg-purple-500/20 text-purple-700 dark:text-purple-400',
  individual: 'bg-violet-500/20 text-violet-700 dark:text-violet-400',
  term: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400',
};


export const ConceptsTab: React.FC<ConceptsTabProps> = ({
  collections,
  groupedConcepts: _groupedConcepts,
  filteredConcepts,
  selectedConcept,
  onSelectConcept,
  onCreateConcept,
  onEditConcept,
  onDeleteConcept,
  onRefresh,
  canEdit,
  // Display options (from unified filter panel)
  groupBySource,
  showProperties: _showProperties,
  groupByDomain,
  selectedLanguage,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['root']));
  
  // Build tree data structure from concepts
  const treeData = useMemo(() => {
    const conceptMap = new Map<string, OntologyConcept>();
    const hierarchy = new Map<string, string[]>();
    const sourceContexts = new Set<string>();

    // Filter to classes, concepts, and properties
    const baseConcepts = filteredConcepts.filter(concept => {
      const conceptType = concept.concept_type;
      return conceptType === 'class' || conceptType === 'concept' || conceptType === 'property';
    });
    
    // Build concept map and hierarchy
    baseConcepts.forEach(concept => {
      conceptMap.set(concept.iri, concept);
      
      // Track source contexts
      if (concept.source_context) {
        sourceContexts.add(concept.source_context);
      }

      // Build parent-child relationships
      concept.parent_concepts.forEach(parentIri => {
        if (!hierarchy.has(parentIri)) {
          hierarchy.set(parentIri, []);
        }
        const parentChildren = hierarchy.get(parentIri)!;
        if (!parentChildren.includes(concept.iri)) {
          parentChildren.push(concept.iri);
        }
      });
      
      // Ensure concept is in the map
      if (!hierarchy.has(concept.iri)) {
        hierarchy.set(concept.iri, []);
      }
    });
    
    return { conceptMap, hierarchy, sourceContexts: Array.from(sourceContexts).sort() };
  }, [filteredConcepts]);
  
  // Get root concepts (no parents in our dataset)
  const rootConcepts = useMemo(() => {
    if (groupBySource) {
      return treeData.sourceContexts;
    }
    
    return Array.from(treeData.conceptMap.values())
      .filter(concept => {
        // When groupByDomain is enabled, properties with domains are shown under their domain concept
        if (groupByDomain && concept.concept_type === 'property' && concept.domain) {
          return false;
        }
        return concept.parent_concepts.length === 0 || 
               !concept.parent_concepts.some(parentIri => treeData.conceptMap.has(parentIri));
      })
      .map(concept => concept.iri);
  }, [treeData, groupBySource, groupByDomain]);
  
  // Get children of a node
  const getChildren = useCallback((itemId: string): string[] => {
    if (groupBySource && treeData.sourceContexts.includes(itemId)) {
      // Return root concepts from that source
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
      // Add properties that have this concept as domain
      const propertiesWithThisDomain = Array.from(treeData.conceptMap.values())
        .filter(concept => concept.concept_type === 'property' && concept.domain === itemId)
        .map(concept => concept.iri);
      return [...new Set([...regularChildren, ...propertiesWithThisDomain])];
    }
    
    return treeData.hierarchy.get(itemId) || [];
  }, [treeData, groupBySource, groupByDomain]);
  
  // Check if node is a folder
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
  
  // Toggle group expansion
  const toggleGroup = useCallback((group: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(group)) {
        next.delete(group);
      } else {
        next.add(group);
      }
      return next;
    });
  }, []);
  
  // Get collection by context
  const getCollection = useCallback((context?: string) => {
    if (!context) return null;
    return collections.find(c => 
      c.iri === context || c.iri.endsWith(`:${context}`)
    );
  }, [collections]);
  
  // Check if concept is editable
  const isConceptEditable = useCallback((concept: OntologyConcept): boolean => {
    const collection = getCollection(concept.source_context);
    const isDraftStatus = !concept.status || concept.status === 'draft';
    return !!(canEdit && collection?.is_editable && isDraftStatus);
  }, [canEdit, getCollection]);

  // Render a tree item recursively
  const renderTreeItem = (itemId: string, level: number = 0) => {
    const isSourceGroup = groupBySource && treeData.sourceContexts.includes(itemId);
    const concept = treeData.conceptMap.get(itemId);
    const isExpanded = expandedGroups.has(itemId) || (searchQuery.length > 0);
    const hasChildren = isFolder(itemId);
    const children = getChildren(itemId);
    const isSelected = selectedConcept?.iri === itemId;
    
    // For source groups, check if any child matches search
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
    
    // For concepts, check if matches search
    if (!isSourceGroup && searchQuery && concept) {
      const query = searchQuery.toLowerCase();
      const matchesSelf = concept.label?.toLowerCase().includes(query) ||
                          concept.comment?.toLowerCase().includes(query) ||
                          concept.iri.toLowerCase().includes(query);
      
      // Check if any descendant matches
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
      return typeIcons[concept?.concept_type || 'concept'] || <Layers className="h-4 w-4" />;
    };
    
    const displayName = isSourceGroup 
      ? itemId 
      : (concept ? resolveLabel(concept, selectedLanguage) : itemId);
    
    return (
      <div key={itemId}>
        <div
          className={cn(
            "flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer w-full text-left",
            "hover:bg-accent hover:text-accent-foreground transition-colors",
            isSelected && !isSourceGroup && "bg-primary/10 text-primary",
            isSourceGroup && "font-semibold bg-muted/50"
          )}
          style={{ paddingLeft: `${level * 12 + 8}px` }}
          onClick={() => {
            if (!isSourceGroup && concept) {
              onSelectConcept(concept);
            } else if (hasChildren) {
              toggleGroup(itemId);
            }
          }}
        >
          <div className="flex items-center w-5 justify-center">
            {hasChildren && (
              <button
                className="p-0.5 hover:bg-muted rounded"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleGroup(itemId);
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
          <div className="flex items-center gap-2 min-w-0 flex-1">
            {getConceptIcon()}
            <span className="truncate text-sm font-medium" title={displayName}>
              {displayName}
            </span>
          </div>
          {isSourceGroup && (
            <Badge variant="secondary" className="text-xs">
              {children.length}
            </Badge>
          )}
        </div>
        
        {/* Render children */}
        {hasChildren && isExpanded && (
          <div className="ml-2">
            {children.map(childId => renderTreeItem(childId, level + 1))}
          </div>
        )}
      </div>
    );
  };
  
  // Helper to get concept label by IRI with language resolution
  const getConceptLabel = (iri: string): string => {
    const concept = filteredConcepts.find(c => c.iri === iri);
    if (concept) return resolveLabel(concept, selectedLanguage);
    return iri.split(/[/#]/).pop() || iri;
  };
  
  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Left Panel - Concept Tree */}
      <div className="col-span-4 border rounded-lg flex flex-col bg-card overflow-hidden max-h-[calc(100vh-280px)]">
        {/* Search */}
        <div className="p-4 border-b">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={t('common:placeholders.searchConceptsAndTerms')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>
        
        {/* Concept Tree */}
        <div className="flex-1 min-h-0 overflow-auto">
          <div className="p-2 min-w-max">
            {rootConcepts.map(id => renderTreeItem(id, 0))}
            
            {rootConcepts.length === 0 && (
              <div className="text-center text-muted-foreground py-8">
                <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>{t('semantic-models:messages.noConceptsFound')}</p>
              </div>
            )}
          </div>
        </div>
        
        {/* Create button */}
        {canEdit && (
          <div className="p-3 border-t">
            <Button
              variant="outline"
              className="w-full"
              onClick={onCreateConcept}
            >
              <Plus className="h-4 w-4 mr-2" />
              {t('semantic-models:actions.createConcept')}
            </Button>
          </div>
        )}
      </div>
      
      {/* Right Panel - Concept Detail */}
      <div className="col-span-8 border rounded-lg bg-card">
        {selectedConcept ? (
          <ScrollArea className="h-full">
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    {typeIcons[selectedConcept.concept_type]}
                    <h2 className="text-2xl font-bold">
                      {resolveLabel(selectedConcept, selectedLanguage)}
                    </h2>
                    <Badge className={typeColors[selectedConcept.concept_type]}>
                      {t(`semantic-models:types.${selectedConcept.concept_type}`)}
                    </Badge>
                    {selectedConcept.status && (
                      <Badge variant="outline">{t(`semantic-models:status.${selectedConcept.status}`)}</Badge>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <code className="px-2 py-0.5 bg-muted rounded text-xs">
                      {selectedConcept.iri}
                    </code>
                    <Button variant="ghost" size="icon" className="h-6 w-6">
                      <ExternalLink className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                
                {isConceptEditable(selectedConcept) && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onEditConcept(selectedConcept)}
                    >
                      <Pencil className="h-4 w-4 mr-1" />
                      {t('common:actions.edit')}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => onDeleteConcept(selectedConcept)}
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      {t('common:actions.delete')}
                    </Button>
                  </div>
                )}
              </div>
              
              {/* Definition */}
              {(selectedConcept.comments || selectedConcept.comment) && (
                <div className="bg-muted/30 rounded-lg p-4">
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.definition')}</h3>
                  <p className="text-sm">{resolveComment(selectedConcept, selectedLanguage)}</p>
                </div>
              )}
              
              {/* Property-specific: Domain & Range */}
              {selectedConcept.concept_type === 'property' && (
                <div className="grid grid-cols-2 gap-4">
                  {selectedConcept.domain && (
                    <div className="bg-muted/30 rounded-lg p-4">
                      <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.domain')}</h3>
                      <Badge 
                        variant="secondary" 
                        className="cursor-pointer"
                        onClick={() => {
                          const domain = filteredConcepts.find(c => c.iri === selectedConcept.domain);
                          if (domain) onSelectConcept(domain);
                        }}
                      >
                        {getConceptLabel(selectedConcept.domain)}
                      </Badge>
                    </div>
                  )}
                  {selectedConcept.range && (
                    <div className="bg-muted/30 rounded-lg p-4">
                      <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.range')}</h3>
                      <Badge 
                        variant="secondary"
                        className="cursor-pointer"
                        onClick={() => {
                          const range = filteredConcepts.find(c => c.iri === selectedConcept.range);
                          if (range) onSelectConcept(range);
                        }}
                      >
                        {getConceptLabel(selectedConcept.range)}
                      </Badge>
                    </div>
                  )}
                </div>
              )}
              
              {/* Parent & Child concepts */}
              {selectedConcept.parent_concepts.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.parentConcepts')}</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedConcept.parent_concepts.map(parentIri => (
                      <Badge 
                        key={parentIri} 
                        variant="secondary" 
                        className="cursor-pointer hover:bg-secondary/80"
                        onClick={() => {
                          const parent = filteredConcepts.find(c => c.iri === parentIri);
                          if (parent) onSelectConcept(parent);
                        }}
                      >
                        {getConceptLabel(parentIri)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              
              {selectedConcept.child_concepts.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.childConcepts')}</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedConcept.child_concepts.map(childIri => (
                      <Badge 
                        key={childIri} 
                        variant="outline" 
                        className="cursor-pointer hover:bg-accent/80"
                        onClick={() => {
                          const child = filteredConcepts.find(c => c.iri === childIri);
                          if (child) onSelectConcept(child);
                        }}
                      >
                        {getConceptLabel(childIri)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Synonyms & Examples */}
              {(selectedConcept.synonyms?.length > 0 || selectedConcept.examples?.length > 0) && (
                <div className="grid grid-cols-2 gap-4">
                  {selectedConcept.synonyms?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.synonyms')}</h3>
                      <div className="flex flex-wrap gap-1">
                        {selectedConcept.synonyms.map(syn => (
                          <Badge key={syn} variant="outline" className="text-xs">{syn}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {selectedConcept.examples?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.examples')}</h3>
                      <div className="flex flex-wrap gap-1">
                        {selectedConcept.examples.map(ex => (
                          <Badge key={ex} variant="outline" className="text-xs">{ex}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
              
              {/* Links Panel */}
              <NodeLinksPanel
                concept={selectedConcept}
                allConcepts={filteredConcepts}
                collections={collections}
                onSelectConcept={onSelectConcept}
                onRefresh={onRefresh}
                canEdit={isConceptEditable(selectedConcept)}
                selectedLanguage={selectedLanguage}
              />
              
              {/* Ownership Panel */}
              <OwnershipPanel
                objectType="business_term"
                objectId={selectedConcept.iri}
                canAssign={isConceptEditable(selectedConcept)}
              />

              {/* Source Info */}
              <div className="text-sm text-muted-foreground border-t pt-4">
                <p>Source: {selectedConcept.source_context}</p>
                {selectedConcept.created_at && (
                  <p>Created: {new Date(selectedConcept.created_at).toLocaleDateString()}</p>
                )}
              </div>
              
              {/* Metadata Panel */}
              <EntityMetadataPanel 
                entityType="concept" 
                entityId={selectedConcept.iri} 
              />
            </div>
          </ScrollArea>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
            <Layers className="h-12 w-12 mb-4 opacity-50" />
            <p>{t('semantic-models:messages.selectConcept')}</p>
          </div>
        )}
      </div>
    </div>
  );
};
