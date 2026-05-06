import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  ChevronDown,
  ChevronRight,
  ArrowRight,
  ArrowLeft,
  Plus,
  X,
} from 'lucide-react';
import type { OntologyConcept, KnowledgeCollection } from '@/types/ontology';
import { LinkEditorDialog } from './link-editor-dialog';
import { useToast } from '@/hooks/use-toast';
import { resolveLabel } from '@/lib/ontology-utils';

interface NodeLinksPanelProps {
  concept: OntologyConcept;
  allConcepts: OntologyConcept[];
  collections: KnowledgeCollection[];
  onSelectConcept: (concept: OntologyConcept) => void;
  onRefresh: () => Promise<void>;
  canEdit: boolean;
  selectedLanguage?: string;
  // When set, the outgoing/incoming lists scroll internally past this row
  // count instead of growing the page. ~36px per row, so 10 ≈ 360px.
  maxVisibleRows?: number;
}

interface LinkInfo {
  iri: string;
  label: string;
  relationshipType: string;
  direction: 'outgoing' | 'incoming';
  concept?: OntologyConcept;
  // For property domain/range links, show the other end
  otherEndIri?: string;
  otherEndLabel?: string;
  otherEndConcept?: OntologyConcept;
}

const relationshipColors: Record<string, string> = {
  broader: 'bg-indigo-500/10 text-indigo-600 border-indigo-500/30',
  narrower: 'bg-green-500/10 text-green-600 border-green-500/30',
  related: 'bg-orange-500/10 text-orange-600 border-orange-500/30',
  domain: 'bg-violet-500/10 text-violet-600 border-violet-500/30',
  range: 'bg-pink-500/10 text-pink-600 border-pink-500/30',
  sameAs: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/30',
};

export const NodeLinksPanel: React.FC<NodeLinksPanelProps> = ({
  concept,
  allConcepts,
  collections: _collections,
  onSelectConcept,
  onRefresh,
  canEdit,
  selectedLanguage = 'en',
  maxVisibleRows,
}) => {
  // Approx row height for the list rows below (py-1.5 + gap + text-sm ≈ 36px).
  const ROW_HEIGHT_PX = 36;
  const listMaxHeight = maxVisibleRows
    ? { maxHeight: ROW_HEIGHT_PX * maxVisibleRows }
    : undefined;
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();
  const [outgoingOpen, setOutgoingOpen] = useState(true);
  const [incomingOpen, setIncomingOpen] = useState(true);
  const [linkEditorOpen, setLinkEditorOpen] = useState(false);
  const [linkDirection, setLinkDirection] = useState<'outgoing' | 'incoming'>('outgoing');
  
  // Build concept map for quick lookups
  const conceptMap = useMemo(() => {
    return new Map(allConcepts.map(c => [c.iri, c]));
  }, [allConcepts]);
  
  // Helper to get label with language resolution
  const getLabel = (c: OntologyConcept | undefined, iri: string): string => {
    if (c) return resolveLabel(c, selectedLanguage);
    return iri.split(/[/#]/).pop() || iri;
  };
  
  // Calculate outgoing links: triples where this concept is the SUBJECT
  // (i.e. what this concept explicitly asserts in the ontology)
  const outgoingLinks = useMemo((): LinkInfo[] => {
    const links: LinkInfo[] = [];
    
    // rdfs:subClassOf / skos:broader — this concept asserts it is narrower than parent
    concept.parent_concepts?.forEach(iri => {
      const c = conceptMap.get(iri);
      links.push({
        iri,
        label: getLabel(c, iri),
        relationshipType: 'broader',
        direction: 'outgoing',
        concept: c,
      });
    });
    
    // child_concepts are NOT shown here — they are the materialized inverse
    // of other concepts' parent_concepts and appear in "incoming" instead.
    
    // Related
    concept.related_concepts?.forEach(iri => {
      const c = conceptMap.get(iri);
      links.push({
        iri,
        label: getLabel(c, iri),
        relationshipType: 'related',
        direction: 'outgoing',
        concept: c,
      });
    });
    
    // Domain (for properties)
    if (concept.concept_type === 'property' && concept.domain) {
      const c = conceptMap.get(concept.domain);
      links.push({
        iri: concept.domain,
        label: getLabel(c, concept.domain),
        relationshipType: 'domain',
        direction: 'outgoing',
        concept: c,
      });
    }
    
    // Range (for properties)
    if (concept.concept_type === 'property' && concept.range) {
      const c = conceptMap.get(concept.range);
      links.push({
        iri: concept.range,
        label: getLabel(c, concept.range),
        relationshipType: 'range',
        direction: 'outgoing',
        concept: c,
      });
    }
    
    return links;
  }, [concept, conceptMap]);
  
  // Calculate incoming links: triples where this concept is the OBJECT
  // (i.e. what other concepts assert about this one)
  const incomingLinks = useMemo((): LinkInfo[] => {
    const links: LinkInfo[] = [];
    
    allConcepts.forEach(other => {
      if (other.iri === concept.iri) return;
      
      // Other asserts rdfs:subClassOf / skos:broader pointing to this concept
      // → the other concept is narrower than this one
      if (other.parent_concepts?.includes(concept.iri)) {
        links.push({
          iri: other.iri,
          label: getLabel(other, other.iri),
          relationshipType: 'narrower',
          direction: 'incoming',
          concept: other,
        });
      }
      
      // child_concepts check removed — it is the materialized inverse of
      // parent_concepts and would duplicate the outgoing "broader" links.
      
      // Other relates to this
      if (other.related_concepts?.includes(concept.iri)) {
        links.push({
          iri: other.iri,
          label: getLabel(other, other.iri),
          relationshipType: 'related',
          direction: 'incoming',
          concept: other,
        });
      }
      
      // Other property has this as domain → show range as "other end"
      if (other.concept_type === 'property' && other.domain === concept.iri) {
        const rangeConcept = other.range ? conceptMap.get(other.range) : undefined;
        links.push({
          iri: other.iri,
          label: getLabel(other, other.iri),
          relationshipType: 'domain',
          direction: 'incoming',
          concept: other,
          otherEndIri: other.range,
          otherEndLabel: other.range ? getLabel(rangeConcept, other.range) : undefined,
          otherEndConcept: rangeConcept,
        });
      }
      
      // Other property has this as range → show domain as "other end"
      if (other.concept_type === 'property' && other.range === concept.iri) {
        const domainConcept = other.domain ? conceptMap.get(other.domain) : undefined;
        links.push({
          iri: other.iri,
          label: getLabel(other, other.iri),
          relationshipType: 'range',
          direction: 'incoming',
          concept: other,
          otherEndIri: other.domain,
          otherEndLabel: other.domain ? getLabel(domainConcept, other.domain) : undefined,
          otherEndConcept: domainConcept,
        });
      }
    });
    
    return links;
  }, [concept, allConcepts]);
  
  // Handle add link
  const handleAddLink = (direction: 'outgoing' | 'incoming') => {
    setLinkDirection(direction);
    setLinkEditorOpen(true);
  };
  
  // Handle create link
  const handleCreateLink = async (relationshipType: string, targetIri?: string) => {
    if (!targetIri) return;
    
    try {
      // Build the update based on relationship type
      const update: Record<string, any> = {};
      
      if (relationshipType === 'broader') {
        update.broader_iris = [...(concept.parent_concepts || []), targetIri];
      } else if (relationshipType === 'narrower') {
        update.narrower_iris = [...(concept.child_concepts || []), targetIri];
      } else if (relationshipType === 'related') {
        update.related_iris = [...(concept.related_concepts || []), targetIri];
      }
      // TODO: Handle domain/range for properties
      
      const response = await fetch(
        `/api/knowledge/concepts/${encodeURIComponent(concept.iri)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(update),
        }
      );
      
      if (!response.ok) {
        throw new Error('Failed to add link');
      }
      
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.linkAdded'),
      });
      
      setLinkEditorOpen(false);
      await onRefresh();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  };
  
  // Handle remove link
  const handleRemoveLink = async (link: LinkInfo) => {
    try {
      const update: Record<string, any> = {};
      
      if (link.relationshipType === 'broader') {
        update.broader_iris = concept.parent_concepts?.filter(iri => iri !== link.iri) || [];
      } else if (link.relationshipType === 'narrower') {
        update.narrower_iris = concept.child_concepts?.filter(iri => iri !== link.iri) || [];
      } else if (link.relationshipType === 'related') {
        update.related_iris = concept.related_concepts?.filter(iri => iri !== link.iri) || [];
      }
      
      const response = await fetch(
        `/api/knowledge/concepts/${encodeURIComponent(concept.iri)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(update),
        }
      );
      
      if (!response.ok) {
        throw new Error('Failed to remove link');
      }
      
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.linkRemoved'),
      });
      
      await onRefresh();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  };
  
  // Render link item
  const renderLink = (link: LinkInfo) => (
    <div
      key={`${link.direction}-${link.relationshipType}-${link.iri}`}
      className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-muted/50 group"
    >
      <Badge
        variant="outline"
        className={`text-xs ${relationshipColors[link.relationshipType] || ''}`}
      >
        {link.relationshipType}
      </Badge>
      
      {link.direction === 'outgoing' ? (
        <ArrowRight className="h-3 w-3 text-muted-foreground" />
      ) : (
        <ArrowLeft className="h-3 w-3 text-muted-foreground" />
      )}
      
      <button
        className="text-sm text-primary hover:underline text-left truncate"
        onClick={() => link.concept && onSelectConcept(link.concept)}
      >
        {link.label}
      </button>
      
      {/* Show the other end of property relationships */}
      {link.otherEndLabel && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <span>(</span>
          <span>{link.relationshipType === 'range' ? 'from' : 'to'}</span>
          <button
            className="text-primary hover:underline truncate"
            onClick={() => link.otherEndConcept && onSelectConcept(link.otherEndConcept)}
          >
            {link.otherEndLabel}
          </button>
          <span>)</span>
        </span>
      )}
      
      {canEdit && (
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 opacity-0 group-hover:opacity-100 flex-shrink-0"
          onClick={() => handleRemoveLink(link)}
        >
          <X className="h-3 w-3" />
        </Button>
      )}
    </div>
  );
  
  return (
    <div className="space-y-3">
      {/* Outgoing Links */}
      <Collapsible open={outgoingOpen} onOpenChange={setOutgoingOpen}>
        <div className="border rounded-lg">
          <CollapsibleTrigger className="flex items-center justify-between w-full p-3 hover:bg-muted/50">
            <div className="flex items-center gap-2">
              {outgoingOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">
                {t('semantic-models:links.outgoing')}
              </span>
              <Badge variant="secondary" className="text-xs">
                {outgoingLinks.length}
              </Badge>
            </div>
            
            {canEdit && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                onClick={(e) => {
                  e.stopPropagation();
                  handleAddLink('outgoing');
                }}
              >
                <Plus className="h-3 w-3 mr-1" />
                {t('common:actions.add')}
              </Button>
            )}
          </CollapsibleTrigger>
          
          <CollapsibleContent>
            <div
              className={`border-t px-2 py-1 ${maxVisibleRows ? 'overflow-y-auto' : ''}`}
              style={listMaxHeight}
            >
              {outgoingLinks.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2 px-2">
                  {t('semantic-models:links.noOutgoing')}
                </p>
              ) : (
                outgoingLinks.map(renderLink)
              )}
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
      
      {/* Incoming Links */}
      <Collapsible open={incomingOpen} onOpenChange={setIncomingOpen}>
        <div className="border rounded-lg">
          <CollapsibleTrigger className="flex items-center justify-between w-full p-3 hover:bg-muted/50">
            <div className="flex items-center gap-2">
              {incomingOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              <ArrowLeft className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">
                {t('semantic-models:links.incoming')}
              </span>
              <Badge variant="secondary" className="text-xs">
                {incomingLinks.length}
              </Badge>
            </div>
            
            {canEdit && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                onClick={(e) => {
                  e.stopPropagation();
                  handleAddLink('incoming');
                }}
              >
                <Plus className="h-3 w-3 mr-1" />
                {t('common:actions.add')}
              </Button>
            )}
          </CollapsibleTrigger>
          
          <CollapsibleContent>
            <div
              className={`border-t px-2 py-1 ${maxVisibleRows ? 'overflow-y-auto' : ''}`}
              style={listMaxHeight}
            >
              {incomingLinks.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2 px-2">
                  {t('semantic-models:links.noIncoming')}
                </p>
              ) : (
                incomingLinks.map(renderLink)
              )}
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
      
      {/* Link Editor Dialog */}
      <LinkEditorDialog
        open={linkEditorOpen}
        onOpenChange={setLinkEditorOpen}
        sourceConcept={concept}
        targetConcept={null}
        allConcepts={allConcepts}
        direction={linkDirection}
        onCreateLink={handleCreateLink}
      />
    </div>
  );
};

