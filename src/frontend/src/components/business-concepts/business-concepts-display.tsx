import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X, Shapes, Columns2 } from 'lucide-react'
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog'
import type { TermMappingTargetEntityType } from '@/types/term-mapping'

// Entity types we know map cleanly to a term-mapping adapter. Strings outside
// this list silently disable the inline-suggester tier.
const MAPPING_ENTITY_TYPES: TermMappingTargetEntityType[] = [
  'asset',
  'data_contract',
  'data_contract_schema',
  'data_contract_property',
  'data_product',
  'dataset',
]

interface BusinessConcept {
  iri: string
  label?: string
}

interface BusinessConceptsDisplayProps {
  concepts: BusinessConcept[]
  onConceptsChange: (concepts: BusinessConcept[]) => void
  parentConceptIris?: string[]
  entityType?: string
  entityId?: string
  conceptType?: 'class' | 'property'
}

export default function BusinessConceptsDisplay({
  concepts = [],
  onConceptsChange,
  parentConceptIris,
  entityType,
  entityId,
  conceptType = 'class'
}: BusinessConceptsDisplayProps) {
  const [showDialog, setShowDialog] = useState(false)

  // Derive a human-readable label from an IRI. This splits on both
  // '/' and '#' so IRIs like ".../concepts#BusinessConcept" become
  // just "BusinessConcept". Underscores are converted to spaces.
  const getLabelFromIri = (iri: string) => {
    const last = iri.split(/[\/#]/).pop() || iri
    return last.replace(/_/g, ' ')
  }

  const getDisplayLabel = (iri: string, label?: string) => {
    // If provided label looks like a URL/URN, prefer IRI-derived fallback
    const looksLikeUrl = label && /^(https?:\/\/|urn:)/i.test(label)
    if (!label || looksLikeUrl) return getLabelFromIri(iri)
    return label
  }

  const handleAddConcept = (iri: string) => {
    // Extract clean label from IRI for display (name only)
    const label = getLabelFromIri(iri)

    const newConcept: BusinessConcept = { iri, label }
    onConceptsChange([...concepts, newConcept])
    setShowDialog(false)
  }

  const handleRemoveConcept = (iri: string) => {
    onConceptsChange(concepts.filter(c => c.iri !== iri))
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">Linked Business {conceptType === 'property' ? 'Properties' : 'Concepts'}:</div>

      {concepts.length === 0 ? (
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">No business {conceptType === 'property' ? 'properties' : 'concepts'} linked</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowDialog(true)}
            className="h-6 px-2 text-xs"
          >
            Add {conceptType === 'property' ? 'Property' : 'Concept'}
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">
            {concepts.map((concept) => (
              <Badge key={concept.iri} variant="secondary" className="flex items-center gap-1">
                {conceptType === 'property' ? (
                  <Columns2 className="h-3 w-3" />
                ) : (
                  <Shapes className="h-3 w-3" />
                )}
                <span>{getDisplayLabel(concept.iri, concept.label)}</span>
                <X
                  className="h-3 w-3 cursor-pointer hover:text-destructive"
                  onClick={() => handleRemoveConcept(concept.iri)}
                />
              </Badge>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowDialog(true)}
            className="h-6 px-2 text-xs"
          >
            Add {conceptType === 'property' ? 'Property' : 'Concept'}
          </Button>
        </div>
      )}

      <ConceptSelectDialog
        isOpen={showDialog}
        onOpenChange={setShowDialog}
        onSelect={handleAddConcept}
        parentConceptIris={parentConceptIris}
        entityType={conceptType}
        mappingSource={
          entityType && entityId && (MAPPING_ENTITY_TYPES as string[]).includes(entityType)
            ? { entity_type: entityType as TermMappingTargetEntityType, entity_id: entityId }
            : undefined
        }
      />
    </div>
  )
}