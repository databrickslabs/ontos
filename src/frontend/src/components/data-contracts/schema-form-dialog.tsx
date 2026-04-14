import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Plus, Trash2 } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from 'react-i18next'
import SchemaPropertyEditor, { type SchemaPropertyEditorHandle } from './schema-property-editor'
import BusinessConceptsDisplay from '@/components/business-concepts/business-concepts-display'
import type { SchemaObject, ColumnProperty, SchemaRelationship } from '@/types/data-contract'

type SchemaFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (schema: SchemaObject) => Promise<void>
  initial?: SchemaObject
}

const PHYSICAL_TYPES = ['table', 'view', 'materialized_view', 'external_table', 'managed_table', 'streaming_table']

export default function SchemaFormDialog({ isOpen, onOpenChange, onSubmit, initial }: SchemaFormProps) {
  const { toast } = useToast()
  const { t } = useTranslation(['data-contracts', 'common'])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const propertyEditorRef = useRef<SchemaPropertyEditorHandle | null>(null)

  // Schema-level fields
  const [name, setName] = useState('')
  const [physicalName, setPhysicalName] = useState('')
  const [description, setDescription] = useState('')
  const [businessName, setBusinessName] = useState('')
  const [physicalType, setPhysicalType] = useState('table')
  const [dataGranularityDescription, setDataGranularityDescription] = useState('')

  // Properties (columns)
  const [properties, setProperties] = useState<ColumnProperty[]>([])
  const [schemaSemanticConcepts, setSchemaSemanticConcepts] = useState<{ iri: string; label?: string }[]>([])

  // Schema-level relationships (ODCS v3.1.0)
  const [schemaRelationships, setSchemaRelationships] = useState<SchemaRelationship[]>([])
  const [newRelFrom, setNewRelFrom] = useState('')
  const [newRelTo, setNewRelTo] = useState('')
  const [newRelType, setNewRelType] = useState('foreignKey')

  // Initialize form when dialog opens
  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '')
      setPhysicalName(initial.physicalName || '')
      setDescription(initial.description || '')
      setBusinessName(initial.businessName || '')
      setPhysicalType(initial.physicalType || 'table')
      setDataGranularityDescription(initial.dataGranularityDescription || '')
      // Normalize legacy snake_case fields coming from backend or older drafts
      const normalizedProps = (initial.properties || []).map((p: any) => ({
        ...p,
        logicalType: p.logicalType || p.logical_type || 'string',
        physicalType: p.physicalType || p.physical_type,
        primaryKey: p.primaryKey ?? p.primary_key,
        primaryKeyPosition: p.primaryKeyPosition ?? p.primary_key_position,
        partitionKeyPosition: p.partitionKeyPosition ?? p.partition_key_position,
      }))
      setProperties(normalizedProps)
      // Load semantics
      const concepts = (initial as any).semanticConcepts as { iri: string; label?: string }[] | undefined
      if (concepts && Array.isArray(concepts)) {
        setSchemaSemanticConcepts(concepts)
      } else if (initial.authoritativeDefinitions && initial.authoritativeDefinitions.length > 0) {
        setSchemaSemanticConcepts(initial.authoritativeDefinitions.map(def => ({ iri: (def as any).url })))
      } else {
        setSchemaSemanticConcepts([])
      }
      setSchemaRelationships(initial.relationships || [])
    } else if (isOpen && !initial) {
      // Reset for new schema
      setName('')
      setPhysicalName('')
      setDescription('')
      setBusinessName('')
      setPhysicalType('table')
      setDataGranularityDescription('')
      setProperties([])
      setSchemaSemanticConcepts([])
      setSchemaRelationships([])
      setNewRelFrom('')
      setNewRelTo('')
      setNewRelType('foreignKey')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    // Validate
    if (!name.trim()) {
      toast({ title: 'Validation Error', description: 'Schema name is required', variant: 'destructive' })
      return
    }

    const propsToUse = propertyEditorRef.current?.getPropertiesForSubmit?.() ?? properties
    if (propsToUse.length === 0) {
      toast({ title: 'Validation Error', description: 'At least one column is required', variant: 'destructive' })
      return
    }

    setIsSubmitting(true)
    try {
      const schema: SchemaObject = {
        name: name.trim(),
        physicalName: physicalName.trim() || undefined,
        description: description.trim() || undefined,
        businessName: businessName.trim() || undefined,
        physicalType: physicalType || undefined,
        dataGranularityDescription: dataGranularityDescription.trim() || undefined,
        properties: propsToUse,
        authoritativeDefinitions: schemaSemanticConcepts.length > 0 ? schemaSemanticConcepts.map(c => ({ url: c.iri, type: 'http://databricks.com/ontology/uc/semanticAssignment' })) : undefined,
        // @ts-ignore retain local concepts for further editing flows
        semanticConcepts: schemaSemanticConcepts.length > 0 ? schemaSemanticConcepts : undefined,
        relationships: schemaRelationships.length > 0 ? schemaRelationships : undefined,
      }

      await onSubmit(schema)
      onOpenChange(false)
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save schema',
        variant: 'destructive',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Edit Schema' : 'Add New Schema'}</DialogTitle>
          <DialogDescription>
            Define a schema object (table/view) and its properties (columns).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Schema-level fields */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold">Schema Information</h3>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">
                  Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., customers"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="physicalName">Physical Name</Label>
                <Input
                  id="physicalName"
                  value={physicalName}
                  onChange={(e) => setPhysicalName(e.target.value)}
                  placeholder="e.g., catalog.schema.customers"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="businessName">Business Name</Label>
                <Input
                  id="businessName"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                  placeholder="Human-readable name"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="physicalType">Physical Type</Label>
                <Select value={physicalType} onValueChange={setPhysicalType}>
                  <SelectTrigger id="physicalType">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PHYSICAL_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe this schema"
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="dataGranularityDescription">Data Granularity</Label>
              <Input
                id="dataGranularityDescription"
                value={dataGranularityDescription}
                onChange={(e) => setDataGranularityDescription(e.target.value)}
                placeholder="e.g., One row per customer"
              />
            </div>
          </div>

          {/* Schema-level Business Concepts */}
          <div className="space-y-2">
            <Label className="text-sm font-semibold">Business Concepts</Label>
            <BusinessConceptsDisplay
              concepts={schemaSemanticConcepts}
              onConceptsChange={setSchemaSemanticConcepts}
              entityType="data_contract_schema"
              entityId={name || 'schema'}
              conceptType="class"
            />
          </div>

          {/* Unity Catalog Metadata (read-only, shown when present) */}
          {initial && (initial.tableType || initial.owner || initial.createdAt || initial.updatedAt || initial.tableProperties) && (
            <div className="space-y-4 border-t pt-4">
              <h3 className="text-sm font-semibold text-muted-foreground">Unity Catalog Metadata (Read-Only)</h3>

              <div className="grid grid-cols-2 gap-4">
                {initial.tableType && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Table Type</Label>
                    <Input value={initial.tableType} disabled className="bg-muted" />
                  </div>
                )}
                {initial.owner && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Owner</Label>
                    <Input value={initial.owner} disabled className="bg-muted" />
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4">
                {initial.createdAt && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Created At</Label>
                    <Input value={initial.createdAt} disabled className="bg-muted" />
                  </div>
                )}
                {initial.updatedAt && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Updated At</Label>
                    <Input value={initial.updatedAt} disabled className="bg-muted" />
                  </div>
                )}
              </div>

              {initial.tableProperties && Object.keys(initial.tableProperties).length > 0 && (
                <div className="space-y-2">
                  <Label className="text-muted-foreground">Table Properties</Label>
                  <div className="rounded-md border bg-muted p-3 text-sm">
                    {Object.entries(initial.tableProperties).map(([key, value]) => (
                      <div key={key} className="flex justify-between py-1">
                        <span className="font-medium">{key}:</span>
                        <span className="text-muted-foreground">{String(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Properties section */}
          <div className="space-y-4 border-t pt-4">
            <h3 className="text-sm font-semibold">
              Properties (Columns) <span className="text-destructive">*</span>
            </h3>

            <SchemaPropertyEditor
              ref={propertyEditorRef}
              properties={properties}
              onChange={setProperties}
            />
          </div>

          {/* Schema-level Relationships (ODCS v3.1.0) */}
          <div className="space-y-4 border-t pt-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                Relationships (Foreign Keys)
                {schemaRelationships.length > 0 && (
                  <Badge variant="secondary" className="text-xs">{schemaRelationships.length}</Badge>
                )}
              </h3>
            </div>

            {schemaRelationships.length > 0 && (
              <div className="space-y-2">
                {schemaRelationships.map((rel, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 border rounded-lg bg-muted/30">
                    <div className="flex items-center gap-2 flex-1 text-sm">
                      <Badge variant="outline" className="text-xs">{rel.type}</Badge>
                      <span className="font-mono">{typeof rel.from === 'string' ? rel.from : JSON.stringify(rel.from)}</span>
                      <span className="text-muted-foreground">→</span>
                      <span className="font-mono">{typeof rel.to === 'string' ? rel.to : JSON.stringify(rel.to)}</span>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setSchemaRelationships(schemaRelationships.filter((_, i) => i !== idx))}
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            <div className="border rounded-lg p-3 bg-background space-y-2">
              <div className="grid grid-cols-7 gap-2">
                <div className="col-span-3 space-y-1">
                  <Label className="text-xs">From (local column)</Label>
                  <Input
                    value={newRelFrom}
                    onChange={(e) => setNewRelFrom(e.target.value)}
                    placeholder="e.g., customer_id"
                    className="h-9 font-mono text-xs"
                  />
                </div>
                <div className="col-span-3 space-y-1">
                  <Label className="text-xs">To (target reference)</Label>
                  <Input
                    value={newRelTo}
                    onChange={(e) => setNewRelTo(e.target.value)}
                    placeholder="e.g., schema.table.column"
                    className="h-9 font-mono text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Type</Label>
                  <Select value={newRelType} onValueChange={setNewRelType}>
                    <SelectTrigger className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="foreignKey">foreignKey</SelectItem>
                      <SelectItem value="reference">reference</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!newRelFrom.trim() || !newRelTo.trim()}
                onClick={() => {
                  setSchemaRelationships([...schemaRelationships, { type: newRelType, from: newRelFrom.trim(), to: newRelTo.trim() }])
                  setNewRelFrom('')
                  setNewRelTo('')
                  setNewRelType('foreignKey')
                }}
                className="h-7"
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Relationship
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('data-contracts:schemaEditor.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.saveChanges') : t('data-contracts:schemaEditor.addSchema')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
