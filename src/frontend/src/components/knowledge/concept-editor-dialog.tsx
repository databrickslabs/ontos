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
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import { collectionSourceKey } from '@/lib/collection-source-key';
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
  collection?: KnowledgeCollection; // Preferred scheme in create mode
  collections?: KnowledgeCollection[]; // Schemes offered in create mode (may be nested)
  onSave: (data: ConceptCreate | ConceptUpdate, isNew: boolean) => Promise<void>;
  onSubmitForReview?: (concept: OntologyConcept) => Promise<void>;
  onPromote?: (concept: OntologyConcept) => void;
  onViewHistory?: (concept: OntologyConcept) => void;
  readOnly?: boolean;
  /** Create mode only: the fixed type of the new entry (e.g. from the Explore
   *  Create menu). Defaults to 'concept'; the dialog never changes it. */
  initialConceptType?: EditorConceptType;
  /** Called from the "no fitting scheme" notice so the caller can open the
   *  scheme editor preset to that kind. The button is hidden without it. */
  onCreateScheme?: (kind: CollectionType) => void;
}

export type EditorConceptType = 'class' | 'concept' | 'property' | 'individual' | 'term';

// Scheme kinds an entry of each type may live in. The type is fixed, so it
// decides which schemes the dialog offers (not the other way round).
const SCHEME_KINDS_BY_TYPE: Record<EditorConceptType, CollectionType[]> = {
  term: ['glossary'],
  concept: ['taxonomy'],
  class: ['ontology'],
  individual: ['ontology'],
  property: ['ontology'],
};

export function schemeKindsForType(type: EditorConceptType): CollectionType[] {
  return SCHEME_KINDS_BY_TYPE[type] ?? ['taxonomy'];
}

// Flatten the (possibly nested) scheme tree into the editable schemes of the
// given kinds. Non-editable schemes are skipped but their children still count.
function fittingSchemes(colls: KnowledgeCollection[], kinds: CollectionType[]): KnowledgeCollection[] {
  const result: KnowledgeCollection[] = [];
  const seen = new Set<string>();
  const visit = (c: KnowledgeCollection) => {
    if (c.is_editable && kinds.includes(c.collection_type) && !seen.has(c.iri)) {
      seen.add(c.iri);
      result.push(c);
    }
    c.child_collections?.forEach(visit);
  };
  colls.forEach(visit);
  return result;
}

// Every scheme in the (possibly nested) tree, once each, editable or not.
function allSchemes(colls: KnowledgeCollection[]): KnowledgeCollection[] {
  const result: KnowledgeCollection[] = [];
  const seen = new Set<string>();
  const visit = (c: KnowledgeCollection) => {
    if (!seen.has(c.iri)) {
      seen.add(c.iri);
      result.push(c);
    }
    c.child_collections?.forEach(visit);
  };
  colls.forEach(visit);
  return result;
}

// Parent field per type. Only listed types show one; the payload field is
// always `broader_iris` and the backend picks the predicate by type
// (class -> rdfs:subClassOf, concept -> skos:broader). Glossary terms stay a
// flat list of agreed terms (hierarchy lives in taxonomies); add a 'term'
// entry here to bring their Parent field back.
const PARENT_FIELD_BY_TYPE: Partial<Record<EditorConceptType, {
  labelKey: string;
  defaultLabel: string;
  addKey: string;
  defaultAdd: string;
}>> = {
  concept: {
    labelKey: 'semantic-models:conceptEditor.parentConcept',
    defaultLabel: 'Parent Concept',
    addKey: 'semantic-models:conceptEditor.addParent',
    defaultAdd: 'Add Parent',
  },
  class: {
    labelKey: 'semantic-models:conceptEditor.subclassOf',
    defaultLabel: 'Subclass of',
    addKey: 'semantic-models:conceptEditor.selectClass',
    defaultAdd: 'Select Class',
  },
};

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
  onCreateScheme,
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
  // Create mode: only editable schemes of the kinds the (fixed) type allows.
  // The `collection` prop joins the pool so a preset scheme is always found.
  const schemeKinds = schemeKindsForType(formData.concept_type);
  const schemeOptions = isNew
    ? fittingSchemes(collection ? [collection, ...collections] : collections, schemeKinds)
    : [];
  const schemeOptionKey = schemeOptions.map((c) => c.iri).join('|');
  const noFittingScheme = isNew && schemeOptions.length === 0;
  const typeLabel =
    conceptTypes.find((ct) => ct.value === formData.concept_type)?.label ?? formData.concept_type;
  const parentField = PARENT_FIELD_BY_TYPE[formData.concept_type];
  const showParent = !!parentField;
  // An entry is never its own parent; a class also may not subclass one of
  // its current subclasses (edit mode), which would create a cycle.
  const excludedParentIris = new Set<string>(
    concept
      ? [concept.iri, ...(formData.concept_type === 'class' ? concept.child_concepts || [] : [])]
      : [],
  );
  // The parent picker lists the TARGET scheme only (a hierarchy lives inside
  // its scheme): the picked scheme in create mode, the entry's own scheme
  // when editing. No resolvable key falls back to the unscoped list.
  const schemePool = allSchemes(collection ? [collection, ...collections] : collections);
  const schemeLabels: Record<string, string> = {};
  schemePool.forEach((c) => {
    const key = collectionSourceKey(c);
    if (!(key in schemeLabels)) schemeLabels[key] = c.label;
  });
  const targetScheme = isNew ? schemePool.find((c) => c.iri === formData.collection_iri) : undefined;
  const parentScopeKey = (isNew ? (targetScheme ? collectionSourceKey(targetScheme) : '') : concept?.source_context) || undefined;
  const parentScopeLabel = parentScopeKey ? targetScheme?.label || schemeLabels[parentScopeKey] : undefined;
  // Never offered: self, direct children (deeper descendants are not known
  // here) and parents already chosen.
  const pickerExcludeIris = Array.from(
    new Set([
      ...(concept ? [concept.iri, ...(concept.child_concepts || [])] : []),
      ...formData.broader_iris,
    ]),
  );
  const isClassParent = formData.concept_type === 'class';

  // Keep the picked scheme valid: the preset `collection` when it fits,
  // otherwise the first fitting scheme (or none).
  useEffect(() => {
    if (!isNew) return;
    const iris = schemeOptionKey ? schemeOptionKey.split('|') : [];
    setFormData((prev) => {
      if (iris.includes(prev.collection_iri)) return prev;
      const preferred = collection && iris.includes(collection.iri) ? collection.iri : iris[0] || '';
      return prev.collection_iri === preferred ? prev : { ...prev, collection_iri: preferred };
    });
  }, [isNew, schemeOptionKey, collection, formData.collection_iri]);

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
        // Fixed for the dialog's lifetime; it decides which schemes are offered.
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
    if (!canEdit || noFittingScheme) return;
    
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
                {isNew
                  ? t('semantic-models:conceptEditor.createTitle', 'Create Entry')
                  : t('semantic-models:conceptEditor.editTitle', 'Edit Entry')}
                {concept?.status && (
                  <Badge className={statusColors[concept.status as ConceptStatus]}>
                    {concept.status}
                  </Badge>
                )}
              </DialogTitle>
              <DialogDescription>
                {isNew
                  ? t('semantic-models:conceptEditor.createDescription', 'Add a new entry to a scheme.')
                  : concept?.iri}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] px-1">
          <form onSubmit={handleSubmit}>
            <div className="grid gap-4 py-4 px-1">
              {/* Type: fixed (preset on create, the entry's own on edit). */}
              <div className="flex items-center gap-2 text-sm" data-testid="concept-type-row">
                <span className="text-muted-foreground">{t('Type')}:</span>
                <Badge variant="outline">{typeLabel}</Badge>
              </div>

              {/* Scheme (for new entries): only schemes that fit the type. */}
              {isNew && !noFittingScheme && (
                <div className="grid gap-2">
                  <Label htmlFor="collection">{t('semantic-models:conceptEditor.collectionLabel', 'Scheme')}</Label>
                  <Select
                    value={formData.collection_iri}
                    onValueChange={(value) =>
                      setFormData((prev) => ({ ...prev, collection_iri: value }))
                    }
                    disabled={schemeOptions.length <= 1}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('semantic-models:conceptEditor.selectCollectionPlaceholder', 'Select scheme...')} />
                    </SelectTrigger>
                    <SelectContent>
                      {schemeOptions.map((c) => (
                        <SelectItem key={c.iri} value={c.iri}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* No editable scheme of the right kind: say so instead of an
                  empty dropdown, and offer to create one. */}
              {noFittingScheme && (
                <div className="grid gap-2 rounded-md border border-dashed p-3" data-testid="no-scheme-notice">
                  <p className="text-sm text-muted-foreground">
                    {t('semantic-models:conceptEditor.noFittingScheme', {
                      defaultValue: 'No editable scheme for this entry type yet ({{kind}}). Create one first.',
                      // Localized kind label (Glossary / Taxonomy / Ontology), not the raw id.
                      kind: t(`semantic-models:collections.${schemeKinds[0]}`),
                    })}
                  </p>
                  {onCreateScheme && (
                    <div>
                      <Button type="button" variant="outline" size="sm" onClick={() => onCreateScheme(schemeKinds[0])}>
                        <Plus className="h-4 w-4 mr-1" />
                        {t('concepts:explore.createScheme', 'New Concept Scheme')}
                      </Button>
                    </div>
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

              {/* Parent: see PARENT_FIELD_BY_TYPE. Hidden for other types, but
                  broader_iris stays in state and in the save payload so existing
                  parents of a term, property or individual are kept. */}
              {parentField && (
              <div className="grid gap-2" data-testid="parent-field">
                <Label>
                  {t(parentField.labelKey, parentField.defaultLabel)}
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
                      {t(parentField.addKey, parentField.defaultAdd)}
                    </Button>
                  </div>
                )}
              </div>
              )}

              {/* Property-specific fields: shown for every property. */}
              {formData.concept_type === 'property' && (
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
            <Button onClick={handleSubmit} disabled={isLoading || !formData.label || noFittingScheme}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('common:actions.create') : t('common:actions.save')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
      {/* Mounted only while open: the picker fetches on mount. */}
      {showParent && parentPickerOpen && (
        <ConceptSelectDialog
          isOpen={parentPickerOpen}
          onOpenChange={setParentPickerOpen}
          entityType="class"
          // Class parents: classes. Taxonomy parents: SKOS concepts (no terms).
          conceptTypes={isClassParent ? ['class'] : ['concept']}
          scopeSourceKey={parentScopeKey}
          scopeLabel={parentScopeLabel}
          schemeLabels={schemeLabels}
          // Classes may subclass one from another ontology (opt-in).
          allowOtherSchemes={isClassParent}
          excludeIris={pickerExcludeIris}
          title={
            isClassParent
              ? t('semantic-models:conceptEditor.selectSuperclass', 'Select Superclass')
              : t('semantic-models:conceptEditor.selectParentConcept', 'Select Parent Concept')
          }
          searchPlaceholder={
            isClassParent
              ? t('semantic-models:conceptEditor.searchClasses', 'Search classes...')
              : t('semantic-models:conceptEditor.searchConceptsInScheme', 'Search concepts in this scheme...')
          }
          onSelect={(iri) => {
            setFormData((prev) =>
              prev.broader_iris.includes(iri) || excludedParentIris.has(iri)
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

