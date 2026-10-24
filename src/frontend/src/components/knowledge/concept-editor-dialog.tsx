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
import { ConceptModeSwitch, useConceptMode } from '@/components/concepts/mode-switch';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import {
  OntologyConcept,
  ConceptCreate,
  ConceptUpdate,
  ConceptStatus,
  CollectionType,
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
  /** Create mode only: preset concept type (e.g. from the Explore Create menu).
   *  Still validated against the target scheme via allowedConceptTypes. */
  initialConceptType?: EditorConceptType;
}

export type EditorConceptType = 'class' | 'concept' | 'property' | 'individual' | 'term';

// Concept types a collection of each kind may hold. Glossaries carry terms and
// SKOS concepts, taxonomies only SKOS concepts, ontologies the OWL-ish kinds.
const ALLOWED_TYPES_BY_COLLECTION: Record<CollectionType, EditorConceptType[]> = {
  glossary: ['concept', 'term'],
  taxonomy: ['concept'],
  ontology: ['concept', 'class', 'property', 'individual'],
};

const ALL_CONCEPT_TYPES: EditorConceptType[] = ['concept', 'class', 'property', 'individual', 'term'];

// Types offered for a target collection type. Unknown / missing type -> all.
export function allowedConceptTypes(collectionType?: string | null): EditorConceptType[] {
  return (collectionType && ALLOWED_TYPES_BY_COLLECTION[collectionType as CollectionType]) || ALL_CONCEPT_TYPES;
}

// Label for the Parent (broader) field, by concept type.
export function parentFieldLabelKey(conceptType: EditorConceptType): { key: string; defaultLabel: string } {
  if (conceptType === 'class') return { key: 'semantic-models:conceptEditor.parentClass', defaultLabel: 'Parent Class' };
  if (conceptType === 'property') return { key: 'semantic-models:conceptEditor.parentProperty', defaultLabel: 'Parent Property' };
  return { key: 'semantic-models:conceptEditor.parentConcept', defaultLabel: 'Parent Concept' };
}

// Short display name for an IRI (local name after # or the last /).
function iriLocalName(iri: string): string {
  const hash = iri.lastIndexOf('#');
  const tail = hash >= 0 ? iri.slice(hash + 1) : iri.slice(iri.lastIndexOf('/') + 1);
  return tail || iri;
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
  initialConceptType,
}) => {
  const { t } = useTranslation();
  const [mode] = useConceptMode();
  const advanced = mode === 'advanced';
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
    { value: 'concept', label: t('semantic-models:types.concept'), description: t('semantic-models:conceptEditor.typeDescriptions.concept') },
    { value: 'class', label: t('semantic-models:types.class'), description: t('semantic-models:conceptEditor.typeDescriptions.class') },
    { value: 'property', label: t('semantic-models:types.property'), description: t('semantic-models:conceptEditor.typeDescriptions.property') },
    { value: 'individual', label: t('semantic-models:types.individual'), description: t('semantic-models:conceptEditor.typeDescriptions.individual') },
    { value: 'term', label: t('semantic-models:types.term'), description: t('semantic-models:conceptEditor.typeDescriptions.term') },
  ];

  const propertyTypes = [
    { value: 'object', label: t('semantic-models:propertyTypes.object'), description: t('semantic-models:conceptEditor.propertyTypeDescriptions.object') },
    { value: 'datatype', label: t('semantic-models:propertyTypes.datatype'), description: t('semantic-models:conceptEditor.propertyTypeDescriptions.datatype') },
    { value: 'annotation', label: t('semantic-models:propertyTypes.annotation'), description: t('semantic-models:conceptEditor.propertyTypeDescriptions.annotation') },
  ];
  const [newSynonym, setNewSynonym] = useState('');
  const [newExample, setNewExample] = useState('');
  const [parentPickerOpen, setParentPickerOpen] = useState(false);

  const isNew = !concept;
  const canEdit = !readOnly && (!concept?.status || concept.status === 'draft');
  const editableCollections = collections.filter((c) => c.is_editable);

  // The collection the concept will live in: the picked collection_iri (create)
  // or the concept's source_context (edit). source_context may be a short
  // `prefix:name` form, so also accept a suffix match like the concepts list.
  const targetCollection = (() => {
    const iri = formData.collection_iri;
    if (!iri) return collection;
    const pool = collection ? [collection, ...collections] : collections;
    return pool.find((c) => c.iri === iri || c.iri.endsWith(`:${iri}`));
  })();
  const allowedTypes = allowedConceptTypes(targetCollection?.collection_type);
  // Never hide an existing concept's own type (the selector is read-only then).
  const visibleConceptTypes = conceptTypes.filter(
    (type) =>
      allowedTypes.includes(type.value as EditorConceptType) ||
      (!isNew && type.value === formData.concept_type),
  );

  // Changing the target collection (create mode) can invalidate the chosen
  // type — fall back to a plain concept, which every collection kind allows.
  useEffect(() => {
    if (isNew && !allowedTypes.includes(formData.concept_type)) {
      setFormData((prev) => ({ ...prev, concept_type: 'concept' }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew, allowedTypes.join('|'), formData.concept_type]);

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
        // Preset from the caller; the allowed-type effect above resets it to
        // 'concept' if the target scheme does not accept it.
        concept_type: initialConceptType || 'concept',
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
  }, [concept, collection, open, initialConceptType]);

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
          <div className="flex items-start justify-between gap-4">
            <div>
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
            </div>
            <ConceptModeSwitch tipLeft />
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] px-1">
          <form onSubmit={handleSubmit}>
            <div className="grid gap-4 py-4 px-1">
              {/* Collection (for new concepts) */}
              {isNew && editableCollections.length > 0 && (
                <div className="grid gap-2">
                  <Label htmlFor="collection">{t('semantic-models:conceptEditor.collectionLabel')}</Label>
                  <Select
                    value={formData.collection_iri}
                    onValueChange={(value) =>
                      setFormData((prev) => ({ ...prev, collection_iri: value }))
                    }
                    disabled={editableCollections.length <= 1}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('semantic-models:conceptEditor.selectCollectionPlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      {editableCollections.map((c) => (
                        <SelectItem key={c.iri} value={c.iri}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Type Selector — ontology layer, Advanced view only. In Simple
                  mode a new concept defaults to skos:Concept; the raw type is
                  hidden. Existing concepts still show their type in Advanced. */}
              {advanced && (
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
                      {visibleConceptTypes.map((type) => (
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
              )}

              {/* Simple mode: the Type selector is hidden, so name a non-default
                  (preset) type and point properties at the Advanced fields. */}
              {!advanced && formData.concept_type !== 'concept' && (
                <div className="grid gap-1" data-testid="simple-type-hint">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">{t('Type')}:</span>
                    <Badge variant="outline">
                      {conceptTypes.find((ct) => ct.value === formData.concept_type)?.label ?? formData.concept_type}
                    </Badge>
                  </div>
                  {formData.concept_type === 'property' && (
                    <p className="text-xs text-muted-foreground">
                      {t('semantic-models:conceptEditor.domainRangeInAdvanced', 'Domain and range are set in Advanced view.')}
                    </p>
                  )}
                </div>
              )}

              {/* Label */}
              <div className="grid gap-2">
                <Label htmlFor="label">{t('semantic-models:conceptEditor.label')}</Label>
                <Input
                  id="label"
                  value={formData.label}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, label: e.target.value }))
                  }
                  placeholder={t('semantic-models:conceptEditor.labelPlaceholder')}
                  required
                  disabled={!canEdit}
                />
              </div>

              {/* Definition */}
              <div className="grid gap-2">
                <Label htmlFor="definition">{t('semantic-models:fields.definition')}</Label>
                <Textarea
                  id="definition"
                  value={formData.definition}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, definition: e.target.value }))
                  }
                  placeholder={t('semantic-models:conceptEditor.definitionPlaceholder')}
                  rows={3}
                  disabled={!canEdit}
                />
              </div>

              {/* Parent (broader): shown in Simple and Advanced. Saved as
                  broader_iris; the backend picks the predicate by type
                  (skos:broader / rdfs:subClassOf / rdfs:subPropertyOf). */}
              <div className="grid gap-2" data-testid="parent-field">
                <Label>
                  {t(parentFieldLabelKey(formData.concept_type).key, parentFieldLabelKey(formData.concept_type).defaultLabel)}
                </Label>
                <div className="flex flex-wrap gap-2">
                  {formData.broader_iris.map((iri) => (
                    <Badge key={iri} variant="secondary" className="flex items-center gap-1" title={iri}>
                      {iriLocalName(iri)}
                      {canEdit && (
                        <button
                          type="button"
                          aria-label={t('semantic-models:conceptEditor.removeParent', { defaultValue: 'Remove {{name}}', name: iriLocalName(iri) })}
                          onClick={() =>
                            setFormData((prev) => ({
                              ...prev,
                              broader_iris: prev.broader_iris.filter((p) => p !== iri),
                            }))
                          }
                          className="ml-1 hover:text-destructive"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </Badge>
                  ))}
                  {formData.broader_iris.length === 0 && !canEdit && (
                    <span className="text-sm text-muted-foreground">-</span>
                  )}
                </div>
                {canEdit && (
                  <div>
                    <Button type="button" variant="outline" size="sm" onClick={() => setParentPickerOpen(true)}>
                      <Plus className="h-4 w-4 mr-1" />
                      {t('semantic-models:conceptEditor.addParent', 'Add Parent')}
                    </Button>
                  </div>
                )}
              </div>

              {/* Property-specific fields — ontology layer, Advanced only. */}
              {advanced && formData.concept_type === 'property' && (
                <>
                  <Separator />
                  <div className="space-y-4 bg-muted/30 rounded-lg p-4">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <Link2 className="h-4 w-4" />
                      {t('semantic-models:conceptEditor.propertyConfiguration')}
                    </h4>
                    
                    {/* Property Type */}
                    <div className="grid gap-2">
                      <Label>{t('semantic-models:conceptEditor.propertyType')}</Label>
                      <Select
                        value={formData.property_type}
                        onValueChange={(value) =>
                          setFormData((prev) => ({ ...prev, property_type: value as any }))
                        }
                        disabled={!canEdit}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('semantic-models:conceptEditor.selectPropertyTypePlaceholder')} />
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
                      <Label htmlFor="domain">{t('semantic-models:fields.domain')}</Label>
                      <Input
                        id="domain"
                        value={formData.domain}
                        onChange={(e) =>
                          setFormData((prev) => ({ ...prev, domain: e.target.value }))
                        }
                        placeholder={t('semantic-models:conceptEditor.domainPlaceholder')}
                        disabled={!canEdit}
                      />
                      <p className="text-xs text-muted-foreground">
                        {t('semantic-models:conceptEditor.domainHelp')}
                      </p>
                    </div>
                    
                    {/* Range */}
                    <div className="grid gap-2">
                      <Label htmlFor="range">{t('semantic-models:fields.range')}</Label>
                      <Input
                        id="range"
                        value={formData.range}
                        onChange={(e) =>
                          setFormData((prev) => ({ ...prev, range: e.target.value }))
                        }
                        placeholder={
                          formData.property_type === 'datatype'
                            ? t('semantic-models:conceptEditor.rangeDatatypePlaceholder')
                            : t('semantic-models:conceptEditor.rangeObjectPlaceholder')
                        }
                        disabled={!canEdit}
                      />
                      <p className="text-xs text-muted-foreground">
                        {formData.property_type === 'datatype'
                          ? t('semantic-models:conceptEditor.rangeDatatypeHelp')
                          : t('semantic-models:conceptEditor.rangeObjectHelp')}
                      </p>
                    </div>
                  </div>
                  <Separator />
                </>
              )}

              {/* Synonyms */}
              <div className="grid gap-2">
                <Label>{t('semantic-models:fields.synonyms')}</Label>
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
                      placeholder={t('semantic-models:conceptEditor.addSynonymPlaceholder')}
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
                <Label>{t('semantic-models:fields.examples')}</Label>
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
                      placeholder={t('semantic-models:conceptEditor.addExamplePlaceholder')}
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
                        <span>{t('semantic-models:conceptEditor.certified')}: {new Date(concept.certified_at).toLocaleDateString()}</span>
                      </div>
                      {concept.certification_expires_at && (
                        <div className="flex items-center gap-1">
                          <Calendar className="h-4 w-4" />
                          <span>{t('semantic-models:conceptEditor.expires')}: {new Date(concept.certification_expires_at).toLocaleDateString()}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Provenance info */}
                  {concept.promotion_type && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <ArrowUp className="h-4 w-4" />
                      <span>
                        {concept.promotion_type === 'promoted' ? t('semantic-models:conceptEditor.promotedFrom') : t('semantic-models:conceptEditor.migratedFrom')}:{' '}
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
                  {t('semantic-models:conceptEditor.history')}
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
                  {t('semantic-models:conceptEditor.submitForReview')}
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
                  {t('semantic-models:promotion.promote')}
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
            {t('common:actions.cancel')}
          </Button>
          {canEdit && (
            <Button onClick={handleSubmit} disabled={isLoading || !formData.label}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('common:actions.create') : t('common:actions.save')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
      {/* Mounted only while open: the picker fetches on mount. */}
      {parentPickerOpen && (
        <ConceptSelectDialog
          isOpen={parentPickerOpen}
          onOpenChange={setParentPickerOpen}
          entityType={formData.concept_type === 'property' ? 'property' : 'class'}
          onSelect={(iri) => {
            setFormData((prev) =>
              prev.broader_iris.includes(iri) || iri === concept?.iri
                ? prev
                : { ...prev, broader_iris: [...prev.broader_iris, iri] },
            );
            setParentPickerOpen(false);
          }}
        />
      )}
    </Dialog>
  );
};

export default ConceptEditorDialog;

