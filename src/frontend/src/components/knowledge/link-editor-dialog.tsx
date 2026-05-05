import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  ArrowRight,
  ArrowLeft,
  Link2,
  Search,
  Layers,
  Check,
} from 'lucide-react';
import type { OntologyConcept } from '@/types/ontology';

interface LinkEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceConcept: OntologyConcept | null;
  targetConcept: OntologyConcept | null;
  allConcepts?: OntologyConcept[];
  direction?: 'outgoing' | 'incoming';
  onCreateLink: (relationshipType: string, targetIri?: string) => void;
}

const relationshipTypes = [
  { value: 'broader', label: 'Broader (skos:broader)', description: 'This concept is more specific than target' },
  { value: 'narrower', label: 'Narrower (skos:narrower)', description: 'This concept is more general than target' },
  { value: 'related', label: 'Related (skos:related)', description: 'Associated but not hierarchically' },
  { value: 'sameAs', label: 'Same As (owl:sameAs)', description: 'Equivalent to target' },
  { value: 'domain', label: 'Domain (rdfs:domain)', description: 'Property applies to this class' },
  { value: 'range', label: 'Range (rdfs:range)', description: 'Property has this class as value type' },
];

export const LinkEditorDialog: React.FC<LinkEditorDialogProps> = ({
  open,
  onOpenChange,
  sourceConcept,
  targetConcept: initialTarget,
  allConcepts = [],
  direction = 'outgoing',
  onCreateLink,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [relationshipType, setRelationshipType] = useState('broader');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTarget, setSelectedTarget] = useState<OntologyConcept | null>(initialTarget);
  
  // Filter concepts for search
  const filteredConcepts = useMemo(() => {
    if (!searchQuery && !allConcepts.length) return [];
    
    const query = searchQuery.toLowerCase();
    return allConcepts
      .filter(c => {
        // Exclude self
        if (c.iri === sourceConcept?.iri) return false;
        // Match search
        if (!searchQuery) return true;
        return (
          c.label?.toLowerCase().includes(query) ||
          c.iri.toLowerCase().includes(query)
        );
      })
      .slice(0, 50); // Limit results
  }, [allConcepts, searchQuery, sourceConcept]);
  
  // Handle submit
  const handleSubmit = () => {
    if (initialTarget) {
      // Graph drag-and-drop case: target already selected
      onCreateLink(relationshipType);
    } else if (selectedTarget) {
      // Dialog case: target selected from search
      onCreateLink(relationshipType, selectedTarget.iri);
    }
  };
  
  // Reset on close
  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setSearchQuery('');
      setSelectedTarget(null);
      setRelationshipType('broader');
    }
    onOpenChange(newOpen);
  };
  
  // Get display info for source/target
  const sourceLabel = sourceConcept?.label || sourceConcept?.iri || 'Unknown';
  const targetLabel = (initialTarget || selectedTarget)?.label || 
    (initialTarget || selectedTarget)?.iri || 
    t('semantic-models:links.selectTarget');
  
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {/* z-[60] elevates above the fullscreen knowledge-graph Dialog (z-50). */}
      <DialogContent className="max-w-lg z-[60]" overlayClassName="z-[60]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-5 w-5" />
            {t('semantic-models:dialogs.linkEditor.title')}
          </DialogTitle>
          <DialogDescription>
            {t('semantic-models:dialogs.linkEditor.description')}
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-4 py-4">
          {/* Visual representation */}
          <div className="flex items-center justify-center gap-4 p-4 bg-muted/30 rounded-lg">
            <div className="text-center">
              <Badge variant="outline" className="mb-1">
                {direction === 'outgoing' ? t('semantic-models:links.source') : t('semantic-models:links.target')}
              </Badge>
              <div className="font-medium text-sm truncate max-w-[120px]">
                {sourceLabel}
              </div>
            </div>
            
            <div className="flex flex-col items-center gap-1">
              {direction === 'outgoing' ? (
                <ArrowRight className="h-6 w-6 text-primary" />
              ) : (
                <ArrowLeft className="h-6 w-6 text-primary" />
              )}
              <Badge className="text-xs">{relationshipType}</Badge>
            </div>
            
            <div className="text-center">
              <Badge variant="outline" className="mb-1">
                {direction === 'outgoing' ? t('semantic-models:links.target') : t('semantic-models:links.source')}
              </Badge>
              <div className="font-medium text-sm truncate max-w-[120px]">
                {targetLabel}
              </div>
            </div>
          </div>
          
          {/* Relationship type selector */}
          <div className="space-y-2">
            <Label>{t('semantic-models:links.relationshipType')}</Label>
            <Select value={relationshipType} onValueChange={setRelationshipType}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {relationshipTypes.map(type => (
                  <SelectItem key={type.value} value={type.value}>
                    <div className="flex flex-col">
                      <span>{type.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {type.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          
          {/* Target selector (only if not pre-selected from graph) */}
          {!initialTarget && allConcepts.length > 0 && (
            <div className="space-y-2">
              <Label>{t('semantic-models:links.selectTarget')}</Label>
              
              <div className="border rounded-lg">
                <div className="p-2 border-b">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder={t('common:placeholders.searchConcepts')}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="pl-8"
                    />
                  </div>
                </div>
                
                <ScrollArea className="h-48">
                  <div className="p-1">
                    {filteredConcepts.length === 0 ? (
                      <div className="text-center text-muted-foreground py-4 text-sm">
                        {searchQuery 
                          ? t('semantic-models:messages.noConceptsFound')
                          : t('semantic-models:links.typeToSearch')
                        }
                      </div>
                    ) : (
                      filteredConcepts.map(concept => (
                        <button
                          key={concept.iri}
                          className={`flex items-center gap-2 w-full px-3 py-2 rounded text-sm text-left transition-colors ${
                            selectedTarget?.iri === concept.iri
                              ? 'bg-primary/10 text-primary'
                              : 'hover:bg-muted'
                          }`}
                          onClick={() => setSelectedTarget(concept)}
                        >
                          <Layers className="h-4 w-4 shrink-0" />
                          <span className="truncate flex-1">
                            {concept.label || concept.iri}
                          </span>
                          <Badge variant="outline" className="text-xs shrink-0">
                            {concept.concept_type}
                          </Badge>
                          {selectedTarget?.iri === concept.iri && (
                            <Check className="h-4 w-4 text-primary shrink-0" />
                          )}
                        </button>
                      ))
                    )}
                  </div>
                </ScrollArea>
              </div>
            </div>
          )}
        </div>
        
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            {t('common:actions.cancel')}
          </Button>
          <Button 
            onClick={handleSubmit}
            disabled={!initialTarget && !selectedTarget}
          >
            <Link2 className="h-4 w-4 mr-2" />
            {t('semantic-models:links.createLink')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

