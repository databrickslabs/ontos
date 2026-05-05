import React, { useState, useEffect } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  OntologyConcept,
  ConceptCreate,
  ConceptUpdate,
  ConceptStatus,
  KnowledgeCollection,
} from '@/types/ontology';
import {
  Loader2,
  Plus,
  X,
  Link2,
  Calendar,
  Shield,
  ArrowUp,
  History,
  Send,
} from 'lucide-react';

interface ConceptEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  concept?: OntologyConcept | null; // null = create mode
  collection?: KnowledgeCollection; // Required for create mode
  collections?: KnowledgeCollection[]; // For changing collection
  onSave: (data: ConceptCreate | ConceptUpdate, isNew: boolean) => Promise<void>;
  onSubmitForReview?: (concept: OntologyConcept) => Promise<void>;
  onPromote?: (concept: OntologyConcept) => void;
  onViewHistory?: (concept: OntologyConcept) => void;
  readOnly?: boolean;
}

const statusColors: Record<ConceptStatus, string> = {
  draft: 'bg-gray-100 text-gray-700',
  under_review: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-blue-100 text-blue-700',
  active: 'bg-green-100 text-green-700',
  deprecated: 'bg-orange-100 text-orange-700',
  retired: 'bg-red-100 text-red-700',
};

export const ConceptEditorDialog: React.FC<ConceptEditorDialogProps> = ({
  open,
  onOpenChange,
  concept,
  collection,
  collections = [],
  onSave,
  onSubmitForReview,
  onPromote,
  onViewHistory,
  readOnly = false,
}) => {
  const { t } = useTranslation();
  const [isLoading, setIsLoading] = useState(false);
  const [formData, setFormData] = useState({
    collection_iri: '',
    label: '',
    definition: '',
    concept_type: 'concept' as 'class' | 'concept' | 'property' | 'individual' | 'term',
    property_type: 'object' as 'datatype' | 'object' | 'annotation',
    domain: '',
    range: '',
    synonyms: [] as string[],
    examples: [] as string[],
    broader_iris: [] as string[],
    narrower_iris: [] as string[],
    related_iris: [] as string[],
  });
  
  const conceptTypes = [
    { value: 'concept', label: t('Concept'), description: 'A general term or notion (SKOS Concept)' },
    { value: 'class', label: t('Class'), description: 'A category or type (RDFS/OWL Class)' },
    { value: 'property', label: t('Property'), description: 'A relationship or attribute (RDF Property)' },
    { value: 'individual', label: t('Individual'), description: 'A specific instance (OWL Individual)' },
    { value: 'term', label: t('Term'), description: 'A business glossary term' },
  ];
  
  const propertyTypes = [
    { value: 'object', label: t('Object Property'), description: 'Relates to other concepts' },
    { value: 'datatype', label: t('Datatype Property'), description: 'Relates to literal values' },
    { value: 'annotation', label: t('Annotation Property'), description: 'Metadata annotation' },
  ];
  const [newSynonym, setNewSynonym] = useState('');
  const [newExample, setNewExample] = useState('');

  const isNew = !concept;
  const canEdit = !readOnly && (!concept?.status || concept.status === 'draft');

  useEffect(() => {
    if (concept) {
      setFormData({
        collection_iri: concept.source_context || '',
        label: concept.label || '',
        definition: concept.comment || '',
        concept_type: (concept.concept_type as any) || 'concept',
        property_type: (concept.property_type as any) || 'object',
        domain: concept.domain || '',
        range: concept.range || '',
        synonyms: concept.synonyms || [],
        examples: concept.examples || [],
        broader_iris: concept.parent_concepts || [],
        narrower_iris: concept.child_concepts || [],
        related_iris: concept.related_concepts || [],
      });
    } else {
      setFormData({
        collection_iri: collection?.iri || '',
        label: '',
        definition: '',
        concept_type: 'concept',
        property_type: 'object',
        domain: '',
        range: '',
        synonyms: [],
        examples: [],
        broader_iris: [],
        narrower_iris: [],
        related_iris: [],
      });
    }
  }, [concept, collection, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canEdit) return;
    
    setIsLoading(true);
    try {
      const baseData = {
        label: formData.label,
        definition: formData.definition || undefined,
        concept_type: formData.concept_type,
        synonyms: formData.synonyms,
        examples: formData.examples,
        broader_iris: formData.broader_iris,
        narrower_iris: formData.narrower_iris,
        related_iris: formData.related_iris,
      };
      
      // Add property-specific fields
      const propertyData = formData.concept_type === 'property' ? {
        property_type: formData.property_type,
        domain: formData.domain || undefined,
        range: formData.range || undefined,
      } : {};
      
      if (isNew) {
        await onSave(
          {
            collection_iri: formData.collection_iri,
            ...baseData,
            ...propertyData,
          } as ConceptCreate,
          true
        );
      } else {
        await onSave(
          {
            ...baseData,
            ...propertyData,
          } as ConceptUpdate,
          false
        );
      }
      onOpenChange(false);
    } finally {
      setIsLoading(false);
    }
  };

  const addSynonym = () => {
    if (newSynonym.trim() && !formData.synonyms.includes(newSynonym.trim())) {
      setFormData((prev) => ({
        ...prev,
        synonyms: [...prev.synonyms, newSynonym.trim()],
      }));
      setNewSynonym('');
    }
  };

  const removeSynonym = (syn: string) => {
    setFormData((prev) => ({
      ...prev,
      synonyms: prev.synonyms.filter((s) => s !== syn),
    }));
  };

  const addExample = () => {
    if (newExample.trim() && !formData.examples.includes(newExample.trim())) {
      setFormData((prev) => ({
        ...prev,
        examples: [...prev.examples, newExample.trim()],
      }));
      setNewExample('');
    }
  };

  const removeExample = (ex: string) => {
    setFormData((prev) => ({
      ...prev,
      examples: prev.examples.filter((e) => e !== ex),
    }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {isNew ? t('Create Concept') : t('Edit Concept')}
            {concept?.status && (
              <Badge className={statusColors[concept.status as ConceptStatus]}>
                {concept.status}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {isNew
              ? t('Create a new term or concept in the collection.')
              : concept?.iri}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] px-1">
          <form onSubmit={handleSubmit}>
            <div className="grid gap-4 py-4 px-1">
              {/* Collection (for new concepts) */}
              {isNew && collections.length > 0 && (
                <div className="grid gap-2">
                  <Label htmlFor="collection">{t('Collection')}</Label>
                  <Select
                    value={formData.collection_iri}
                    onValueChange={(value) =>
                      setFormData((prev) => ({ ...prev, collection_iri: value }))
                    }
                    disabled={!!collection}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('Select collection...')} />
                    </SelectTrigger>
                    <SelectContent>
                      {collections
                        .filter((c) => c.is_editable)
                        .map((c) => (
                          <SelectItem key={c.iri} value={c.iri}>
                            {c.label}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Type Selector */}
              <div className="grid gap-2">
                <Label>{t('Type')}</Label>
                <Select
                  value={formData.concept_type}
                  onValueChange={(value) =>
                    setFormData((prev) => ({ ...prev, concept_type: value as any }))
                  }
                  disabled={!canEdit || !isNew} // Can only set type on creation
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('Select type...')} />
                  </SelectTrigger>
                  <SelectContent>
                    {conceptTypes.map((type) => (
                      <SelectItem
                        key={type.value}
                        value={type.value}
                        displayValue={type.label}
                        description={type.description}
                      >
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Label */}
              <div className="grid gap-2">
                <Label htmlFor="label">{t('Label')}</Label>
                <Input
                  id="label"
                  value={formData.label}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, label: e.target.value }))
                  }
                  placeholder={t('e.g., Revenue')}
                  required
                  disabled={!canEdit}
                />
              </div>

              {/* Definition */}
              <div className="grid gap-2">
                <Label htmlFor="definition">{t('Definition')}</Label>
                <Textarea
                  id="definition"
                  value={formData.definition}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, definition: e.target.value }))
                  }
                  placeholder={t('A clear, concise definition...')}
                  rows={3}
                  disabled={!canEdit}
                />
              </div>

              {/* Property-specific fields */}
              {formData.concept_type === 'property' && (
                <>
                  <Separator />
                  <div className="space-y-4 bg-muted/30 rounded-lg p-4">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <Link2 className="h-4 w-4" />
                      {t('Property Configuration')}
                    </h4>
                    
                    {/* Property Type */}
                    <div className="grid gap-2">
                      <Label>{t('Property Type')}</Label>
                      <Select
                        value={formData.property_type}
                        onValueChange={(value) =>
                          setFormData((prev) => ({ ...prev, property_type: value as any }))
                        }
                        disabled={!canEdit}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('Select property type...')} />
                        </SelectTrigger>
                        <SelectContent>
                          {propertyTypes.map((type) => (
                            <SelectItem
                              key={type.value}
                              value={type.value}
                              displayValue={type.label}
                              description={type.description}
                            >
                              {type.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    
                    {/* Domain */}
                    <div className="grid gap-2">
                      <Label htmlFor="domain">{t('Domain')}</Label>
                      <Input
                        id="domain"
                        value={formData.domain}
                        onChange={(e) =>
                          setFormData((prev) => ({ ...prev, domain: e.target.value }))
                        }
                        placeholder={t('e.g., schema:Person or IRI...')}
                        disabled={!canEdit}
                      />
                      <p className="text-xs text-muted-foreground">
                        {t('The class or type this property applies to (subject)')}
                      </p>
                    </div>
                    
                    {/* Range */}
                    <div className="grid gap-2">
                      <Label htmlFor="range">{t('Range')}</Label>
                      <Input
                        id="range"
                        value={formData.range}
                        onChange={(e) =>
                          setFormData((prev) => ({ ...prev, range: e.target.value }))
                        }
                        placeholder={
                          formData.property_type === 'datatype'
                            ? t('e.g., xsd:string, xsd:integer...')
                            : t('e.g., schema:Organization or IRI...')
                        }
                        disabled={!canEdit}
                      />
                      <p className="text-xs text-muted-foreground">
                        {formData.property_type === 'datatype'
                          ? t('The datatype of the property value')
                          : t('The class or type of the property value (object)')}
                      </p>
                    </div>
                  </div>
                  <Separator />
                </>
              )}

              {/* Synonyms */}
              <div className="grid gap-2">
                <Label>{t('Synonyms')}</Label>
                <div className="flex flex-wrap gap-2">
                  {formData.synonyms.map((syn) => (
                    <Badge key={syn} variant="secondary" className="flex items-center gap-1">
                      {syn}
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => removeSynonym(syn)}
                          className="ml-1 hover:text-destructive"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </Badge>
                  ))}
                </div>
                {canEdit && (
                  <div className="flex gap-2">
                    <Input
                      value={newSynonym}
                      onChange={(e) => setNewSynonym(e.target.value)}
                      placeholder={t('Add synonym...')}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addSynonym();
                        }
                      }}
                    />
                    <Button type="button" variant="outline" size="icon" onClick={addSynonym}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>

              {/* Examples */}
              <div className="grid gap-2">
                <Label>{t('Examples')}</Label>
                <div className="flex flex-col gap-1">
                  {formData.examples.map((ex) => (
                    <div
                      key={ex}
                      className="flex items-center justify-between bg-muted px-3 py-1.5 rounded text-sm"
                    >
                      <span className="truncate">{ex}</span>
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => removeExample(ex)}
                          className="ml-2 hover:text-destructive"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {canEdit && (
                  <div className="flex gap-2">
                    <Input
                      value={newExample}
                      onChange={(e) => setNewExample(e.target.value)}
                      placeholder={t('Add example...')}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addExample();
                        }
                      }}
                    />
                    <Button type="button" variant="outline" size="icon" onClick={addExample}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>

              <Separator />

              {/* Governance info (for existing concepts) */}
              {!isNew && concept && (
                <>
                  {/* Certification info */}
                  {concept.certified_at && (
                    <div className="flex items-center gap-4 text-sm text-muted-foreground">
                      <div className="flex items-center gap-1">
                        <Shield className="h-4 w-4 text-purple-500" />
                        <span>{t('Certified')}: {new Date(concept.certified_at).toLocaleDateString()}</span>
                      </div>
                      {concept.certification_expires_at && (
                        <div className="flex items-center gap-1">
                          <Calendar className="h-4 w-4" />
                          <span>{t('Expires')}: {new Date(concept.certification_expires_at).toLocaleDateString()}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Provenance info */}
                  {concept.promotion_type && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <ArrowUp className="h-4 w-4" />
                      <span>
                        {concept.promotion_type === 'promoted' ? t('Promoted from') : t('Migrated from')}:{' '}
                        {concept.source_collection_iri}
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>
          </form>
        </ScrollArea>

        <DialogFooter className="flex-wrap gap-2">
          {/* Action buttons for existing concepts */}
          {!isNew && concept && (
            <div className="flex gap-2 mr-auto">
              {onViewHistory && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onViewHistory(concept)}
                >
                  <History className="h-4 w-4 mr-1" />
                  {t('History')}
                </Button>
              )}
              {onSubmitForReview && concept.status === 'draft' && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onSubmitForReview(concept)}
                >
                  <Send className="h-4 w-4 mr-1" />
                  {t('Submit for Review')}
                </Button>
              )}
              {onPromote && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onPromote(concept)}
                >
                  <ArrowUp className="h-4 w-4 mr-1" />
                  {t('Promote')}
                </Button>
              )}
            </div>
          )}

          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            {t('Cancel')}
          </Button>
          {canEdit && (
            <Button onClick={handleSubmit} disabled={isLoading || !formData.label}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('Create') : t('Save')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ConceptEditorDialog;

