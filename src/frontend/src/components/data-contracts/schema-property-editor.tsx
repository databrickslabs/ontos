import { useState, forwardRef, useImperativeHandle } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Plus, Trash2, Edit, Info } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from 'react-i18next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { ColumnProperty, QualityRule, SchemaRelationship } from '@/types/data-contract'
import BusinessConceptsDisplay from '@/components/business-concepts/business-concepts-display'
import QualityRuleFormDialog from './quality-rule-form-dialog'

const LOGICAL_TYPES = ['string', 'date', 'number', 'integer', 'object', 'array', 'boolean']
const CLASSIFICATION_LEVELS = ['public', 'internal', 'confidential', 'restricted', 'pii', '1', '2', '3', '4', '5']

// Helper function to detect which tabs have values for a column property
const getTabsWithValues = (prop: ColumnProperty) => ({
  constraints: !!(prop.required || prop.unique || prop.primaryKey || prop.partitioned ||
                  prop.minLength || prop.maxLength || prop.pattern ||
                  prop.minimum || prop.maximum || prop.multipleOf || prop.precision ||
                  prop.format || prop.timezone || prop.customFormat ||
                  prop.itemType || prop.minItems || prop.maxItems),
  quality: !!((prop as any).quality?.length),
  governance: !!(prop.classification || prop.examples || (prop as any).tags?.length),
  business: !!(prop.businessName || prop.encryptedName || prop.criticalDataElement),
  transform: !!(prop.transformLogic || prop.transformSourceObjects || prop.transformDescription),
  semantics: !!(prop.authoritativeDefinitions?.length || (prop as any).semanticConcepts?.length),
  relationships: !!(prop.relationships?.length)
})

// Compact 6-square indicator showing which tabs have values configured
const TabIndicator = ({ prop }: { prop: ColumnProperty }) => {
  const tabs = getTabsWithValues(prop)
  const indicators = [
    { key: 'constraints', label: 'Constraints', active: tabs.constraints },
    { key: 'quality', label: 'Quality', active: tabs.quality },
    { key: 'governance', label: 'Governance', active: tabs.governance },
    { key: 'business', label: 'Business', active: tabs.business },
    { key: 'transform', label: 'Transform', active: tabs.transform },
    { key: 'semantics', label: 'Semantics', active: tabs.semantics },
    { key: 'relationships', label: 'Relationships', active: tabs.relationships },
  ]
  
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex gap-[2px] mr-1.5">
            {indicators.map(i => (
              <span
                key={i.key}
                className={`w-[4px] h-[4px] ${
                  i.active ? 'bg-primary' : 'bg-muted-foreground/25'
                }`}
              />
            ))}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <div className="text-xs">
            {indicators.map(i => (
              <div key={i.key} className="flex items-center gap-1.5">
                <span className={`w-[4px] h-2 ${i.active ? 'bg-primary' : 'bg-muted'}`} />
                <span className={i.active ? '' : 'text-muted-foreground'}>{i.label}</span>
              </div>
            ))}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

// Normalize a column property for stable comparison (dirty check).
// Compare semantics by URL set only (authoritativeDefinitions vs semanticConcepts are equivalent).
// Normalize optional fields so empty string and undefined are treated the same.
function normalizePropertyForCompare(prop: ColumnProperty): string {
  const semanticsUrls = [
    ...(prop.authoritativeDefinitions || []).map(d => d.url || ''),
    ...((prop as any).semanticConcepts || []).map((c: { iri: string }) => c.iri || ''),
  ].filter(Boolean).sort()
  const tags = ((prop as any).tags || []).slice().sort()
  const o: Record<string, unknown> = {
    name: (prop.name || '').trim(),
    logicalType: prop.logicalType || (prop as any).logical_type || 'string',
    description: (prop.description || '').trim() || undefined,
    physicalType: (prop.physicalType || (prop as any).physical_type || '').trim() || undefined,
    physicalName: (prop.physicalName || '').trim() || undefined,
    required: !!prop.required,
    unique: !!prop.unique,
    primaryKey: !!prop.primaryKey,
    primaryKeyPosition: prop.primaryKeyPosition !== undefined && prop.primaryKeyPosition !== -1 ? prop.primaryKeyPosition : undefined,
    partitioned: !!prop.partitioned,
    partitionKeyPosition: prop.partitionKeyPosition !== undefined && prop.partitionKeyPosition !== -1 ? prop.partitionKeyPosition : undefined,
    minLength: prop.minLength,
    maxLength: prop.maxLength,
    pattern: (prop.pattern || '').trim() || undefined,
    minimum: prop.minimum,
    maximum: prop.maximum,
    multipleOf: prop.multipleOf,
    precision: prop.precision,
    format: (prop.format || '').trim() || undefined,
    timezone: (prop.timezone || '').trim() || undefined,
    customFormat: (prop.customFormat || '').trim() || undefined,
    itemType: (prop.itemType || '').trim() || undefined,
    minItems: prop.minItems,
    maxItems: prop.maxItems,
    classification: (prop.classification || '').trim() || undefined,
    examples: (prop.examples || '').trim() || undefined,
    businessName: (prop.businessName || '').trim() || undefined,
    encryptedName: (prop.encryptedName || '').trim() || undefined,
    criticalDataElement: !!prop.criticalDataElement,
    transformLogic: (prop.transformLogic || '').trim() || undefined,
    transformSourceObjects: (prop.transformSourceObjects || '').trim() || undefined,
    transformDescription: (prop.transformDescription || '').trim() || undefined,
    semanticsUrls,
    tags,
    qualityCount: ((prop as any).quality || []).length,
    customPropsKeys: Object.keys((prop as any).customProperties || {}).sort(),
  }
  return JSON.stringify(o)
}

interface SchemaPropertyEditorProps {
  properties: ColumnProperty[]
  onChange: (properties: ColumnProperty[]) => void
  readOnly?: boolean
}

export interface SchemaPropertyEditorHandle {
  getPropertiesForSubmit: () => ColumnProperty[]
  isColumnEditDirty: () => boolean
}

function SchemaPropertyEditorInner(
  { properties, onChange, readOnly = false }: SchemaPropertyEditorProps,
  ref: React.Ref<SchemaPropertyEditorHandle>
) {
  const { toast } = useToast()
  const { t } = useTranslation('data-contracts')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)

  // Core fields
  const [name, setName] = useState('')
  const [logicalType, setLogicalType] = useState('string')
  const [description, setDescription] = useState('')

  // Physical fields
  const [physicalType, setPhysicalType] = useState('')
  const [physicalName, setPhysicalName] = useState('')

  // Constraints
  const [required, setRequired] = useState(false)
  const [unique, setUnique] = useState(false)
  const [primaryKey, setPrimaryKey] = useState(false)
  const [primaryKeyPosition, setPrimaryKeyPosition] = useState('')

  // Partitioning
  const [partitioned, setPartitioned] = useState(false)
  const [partitionKeyPosition, setPartitionKeyPosition] = useState('')

  // Type-specific constraints
  const [minLength, setMinLength] = useState('')
  const [maxLength, setMaxLength] = useState('')
  const [pattern, setPattern] = useState('')
  const [minimum, setMinimum] = useState('')
  const [maximum, setMaximum] = useState('')
  const [multipleOf, setMultipleOf] = useState('')
  const [precision, setPrecision] = useState('')
  const [dateFormat, setDateFormat] = useState('')
  const [timezone, setTimezone] = useState('')
  const [customFormat, setCustomFormat] = useState('')
  const [itemType, setItemType] = useState('')
  const [minItems, setMinItems] = useState('')
  const [maxItems, setMaxItems] = useState('')

  // Governance
  const [classification, setClassification] = useState('')
  const [examples, setExamples] = useState('')

  // Business
  const [businessName, setBusinessName] = useState('')
  const [encryptedName, setEncryptedName] = useState('')
  const [criticalDataElement, setCriticalDataElement] = useState(false)

  // Transformation
  const [transformLogic, setTransformLogic] = useState('')
  const [transformSourceObjects, setTransformSourceObjects] = useState('')
  const [transformDescription, setTransformDescription] = useState('')

  // Semantics (business properties)
  const SEMANTIC_ASSIGNMENT_TYPE = 'http://databricks.com/ontology/uc/semanticAssignment'
  const [authoritativeDefinitions, setAuthoritativeDefinitions] = useState<{ url: string; type: string }[]>([])
  const [semanticConcepts, setSemanticConcepts] = useState<{ iri: string; label?: string }[]>([])
  
  // Quality checks, tags, and custom properties
  const [qualityChecks, setQualityChecks] = useState<any[]>([])
  const [tags, setTags] = useState('')
  const [customProps, setCustomProps] = useState<Record<string, any>>({})

  // Property-level relationships (ODCS v3.1.0)
  const [propRelationships, setPropRelationships] = useState<SchemaRelationship[]>([])
  const [newRelTo, setNewRelTo] = useState('')
  const [newRelType, setNewRelType] = useState('foreignKey')

  // Quality rule dialog state
  const [isQualityRuleDialogOpen, setIsQualityRuleDialogOpen] = useState(false)
  const [editingQualityCheckIndex, setEditingQualityCheckIndex] = useState<number | null>(null)

  const resetForm = () => {
    setName('')
    setLogicalType('string')
    setDescription('')
    setPhysicalType('')
    setPhysicalName('')
    setRequired(false)
    setUnique(false)
    setPrimaryKey(false)
    setPrimaryKeyPosition('')
    setPartitioned(false)
    setPartitionKeyPosition('')
    setMinLength('')
    setMaxLength('')
    setPattern('')
    setMinimum('')
    setMaximum('')
    setMultipleOf('')
    setPrecision('')
    setDateFormat('')
    setTimezone('')
    setCustomFormat('')
    setItemType('')
    setMinItems('')
    setMaxItems('')
    setClassification('')
    setExamples('')
    setBusinessName('')
    setEncryptedName('')
    setCriticalDataElement(false)
    setTransformLogic('')
    setTransformSourceObjects('')
    setTransformDescription('')
    setAuthoritativeDefinitions([])
    setSemanticConcepts([])
    setQualityChecks([])
    setTags('')
    setCustomProps({})
    setPropRelationships([])
    setNewRelTo('')
    setNewRelType('foreignKey')
    setEditingIndex(null)
  }

  const loadProperty = (prop: ColumnProperty) => {
    setName(prop.name)
    setLogicalType(prop.logicalType)
    setDescription(prop.description || '')
    setPhysicalType(prop.physicalType || '')
    setPhysicalName(prop.physicalName || '')
    setRequired(prop.required || false)
    setUnique(prop.unique || false)
    setPrimaryKey(prop.primaryKey || false)
    setPrimaryKeyPosition(prop.primaryKeyPosition !== undefined && prop.primaryKeyPosition !== -1 ? String(prop.primaryKeyPosition) : '')
    setPartitioned(prop.partitioned || false)
    setPartitionKeyPosition(prop.partitionKeyPosition !== undefined && prop.partitionKeyPosition !== -1 ? String(prop.partitionKeyPosition) : '')
    setMinLength(prop.minLength !== undefined ? String(prop.minLength) : '')
    setMaxLength(prop.maxLength !== undefined ? String(prop.maxLength) : '')
    setPattern(prop.pattern || '')
    setMinimum(prop.minimum !== undefined ? String(prop.minimum) : '')
    setMaximum(prop.maximum !== undefined ? String(prop.maximum) : '')
    setMultipleOf(prop.multipleOf !== undefined ? String(prop.multipleOf) : '')
    setPrecision(prop.precision !== undefined ? String(prop.precision) : '')
    setDateFormat(prop.format || '')
    setTimezone(prop.timezone || '')
    setCustomFormat(prop.customFormat || '')
    setItemType(prop.itemType || '')
    setMinItems(prop.minItems !== undefined ? String(prop.minItems) : '')
    setMaxItems(prop.maxItems !== undefined ? String(prop.maxItems) : '')
    setClassification(prop.classification || '')
    setExamples(prop.examples || '')
    setBusinessName(prop.businessName || '')
    setEncryptedName(prop.encryptedName || '')
    setCriticalDataElement(prop.criticalDataElement || false)
    setTransformLogic(prop.transformLogic || '')
    setTransformSourceObjects(prop.transformSourceObjects || '')
    setTransformDescription(prop.transformDescription || '')
    setAuthoritativeDefinitions(prop.authoritativeDefinitions || [])
    // When loading, derive semanticConcepts from authoritativeDefinitions for display if needed
    const concepts = (prop as any).semanticConcepts as { iri: string; label?: string }[] | undefined
    if (concepts && Array.isArray(concepts) && concepts.length > 0) {
      // Use explicitly set semanticConcepts if available
      setSemanticConcepts(concepts)
    } else if (prop.authoritativeDefinitions && prop.authoritativeDefinitions.length > 0) {
      // Derive from authoritativeDefinitions
      setSemanticConcepts(prop.authoritativeDefinitions.map(def => ({ iri: def.url })))
    } else {
      setSemanticConcepts([])
    }
    // Load quality checks, tags, custom properties, and relationships
    setQualityChecks((prop as any).quality || [])
    setTags((prop as any).tags ? (prop as any).tags.join(', ') : '')
    setCustomProps((prop as any).customProperties || {})
    setPropRelationships(prop.relationships || [])
  }

  // Build a ColumnProperty from current form state (shared by handleAddOrUpdate and getPropertiesForSubmit)
  const buildPropertyFromFormState = (): ColumnProperty => ({
    name: name.trim(),
    logicalType,
    description: description.trim() || undefined,
    physicalType: physicalType.trim() || undefined,
    physicalName: physicalName.trim() || undefined,
    required: required || undefined,
    unique: unique || undefined,
    primaryKey: primaryKey || undefined,
    primaryKeyPosition: primaryKey && primaryKeyPosition ? parseInt(primaryKeyPosition) : undefined,
    partitioned: partitioned || undefined,
    partitionKeyPosition: partitioned && partitionKeyPosition ? parseInt(partitionKeyPosition) : undefined,
    minLength: minLength ? parseInt(minLength) : undefined,
    maxLength: maxLength ? parseInt(maxLength) : undefined,
    pattern: pattern.trim() || undefined,
    minimum: minimum ? Number(minimum) : undefined,
    maximum: maximum ? Number(maximum) : undefined,
    multipleOf: multipleOf ? Number(multipleOf) : undefined,
    precision: precision ? parseInt(precision) : undefined,
    format: dateFormat.trim() || undefined,
    timezone: timezone.trim() || undefined,
    customFormat: customFormat.trim() || undefined,
    itemType: itemType.trim() || undefined,
    minItems: minItems ? parseInt(minItems) : undefined,
    maxItems: maxItems ? parseInt(maxItems) : undefined,
    classification: classification || undefined,
    examples: examples.trim() || undefined,
    businessName: businessName.trim() || undefined,
    encryptedName: encryptedName.trim() || undefined,
    criticalDataElement: criticalDataElement || undefined,
    transformLogic: transformLogic.trim() || undefined,
    transformSourceObjects: transformSourceObjects.trim() || undefined,
    transformDescription: transformDescription.trim() || undefined,
    authoritativeDefinitions: authoritativeDefinitions.length > 0 ? authoritativeDefinitions : undefined,
    // @ts-ignore
    semanticConcepts: semanticConcepts && semanticConcepts.length > 0 ? semanticConcepts : undefined,
    // @ts-ignore
    quality: qualityChecks.length > 0 ? qualityChecks : undefined,
    // @ts-ignore
    tags: tags ? tags.split(',').map(t => t.trim()).filter(Boolean) : undefined,
    // @ts-ignore
    customProperties: Object.keys(customProps).length > 0 ? customProps : undefined,
    relationships: propRelationships.length > 0 ? propRelationships : undefined,
  })

  useImperativeHandle(ref, () => ({
    getPropertiesForSubmit(): ColumnProperty[] {
      if (editingIndex === null) return properties
      const merged = buildPropertyFromFormState()
      const updated = [...properties]
      updated[editingIndex] = merged
      return updated
    },
    isColumnEditDirty(): boolean {
      if (editingIndex === null) return false
      const current = buildPropertyFromFormState()
      const existing = properties[editingIndex]
      return normalizePropertyForCompare(current) !== normalizePropertyForCompare(existing)
    },
  }), [editingIndex, properties, name, logicalType, description, physicalType, physicalName, required, unique, primaryKey, primaryKeyPosition, partitioned, partitionKeyPosition, minLength, maxLength, pattern, minimum, maximum, multipleOf, precision, dateFormat, timezone, customFormat, itemType, minItems, maxItems, classification, examples, businessName, encryptedName, criticalDataElement, transformLogic, transformSourceObjects, transformDescription, authoritativeDefinitions, semanticConcepts, qualityChecks, tags, customProps, propRelationships])

  const isDirty = editingIndex !== null && (() => {
    const current = buildPropertyFromFormState()
    const existing = properties[editingIndex]
    return normalizePropertyForCompare(current) !== normalizePropertyForCompare(existing)
  })()

  const handleAddOrUpdate = () => {
    if (!name.trim()) {
      toast({ title: 'Validation Error', description: 'Column name is required', variant: 'destructive' })
      return
    }

    const newProperty = buildPropertyFromFormState()

    if (editingIndex !== null) {
      const updated = [...properties]
      updated[editingIndex] = newProperty
      onChange(updated)
    } else {
      onChange([...properties, newProperty])
    }

    resetForm()
  }

  const handleEdit = (index: number) => {
    loadProperty(properties[index])
    setEditingIndex(index)
  }

  const handleDelete = (index: number) => {
    onChange(properties.filter((_, i) => i !== index))
    if (editingIndex === index) {
      resetForm()
    }
  }

  const handleAddQualityCheck = async (rule: QualityRule) => {
    setQualityChecks([...qualityChecks, rule])
    setIsQualityRuleDialogOpen(false)
  }

  const handleUpdateQualityCheck = async (rule: QualityRule) => {
    if (editingQualityCheckIndex === null) return
    const updated = [...qualityChecks]
    updated[editingQualityCheckIndex] = rule
    setQualityChecks(updated)
    setEditingQualityCheckIndex(null)
    setIsQualityRuleDialogOpen(false)
  }

  const FieldTooltip = ({ content }: { content: string }) => (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Info className="h-3 w-3 text-muted-foreground cursor-help inline-block ml-1" />
        </TooltipTrigger>
        <TooltipContent>
          <p className="text-xs max-w-xs">{content}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )

  return (
    <div className="space-y-4">
      {/* Property Form */}
      {!readOnly && (
        <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
          {/* Title showing which column is being edited */}
          {editingIndex !== null ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 pb-2 border-b mb-2">
                <Edit className="h-5 w-5 text-primary" />
                <h3 className="text-lg font-semibold">{t('schemaEditor.editingColumn')}: <span className="font-mono text-primary">{name || properties[editingIndex]?.name}</span></h3>
                {isDirty && (
                  <Badge variant="secondary" className="text-xs font-normal">{t('schemaEditor.unsavedChanges')}</Badge>
                )}
              </div>
              {isDirty && (
                <p className="text-xs text-muted-foreground">{t('schemaEditor.applyWithUpdateOrSave')}</p>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 pb-2 border-b mb-2">
              <Plus className="h-5 w-5 text-primary" />
              <h3 className="text-lg font-semibold">{t('schemaEditor.addingNewColumn')}</h3>
            </div>
          )}
          
          <Tabs defaultValue="core" className="w-full">
            <TabsList className="grid w-full grid-cols-8">
              <TabsTrigger value="core">Core</TabsTrigger>
              <TabsTrigger value="constraints">Constraints</TabsTrigger>
              <TabsTrigger value="quality">Quality</TabsTrigger>
              <TabsTrigger value="governance">Governance</TabsTrigger>
              <TabsTrigger value="business">Business</TabsTrigger>
              <TabsTrigger value="transform">Transform</TabsTrigger>
              <TabsTrigger value="semantics">Semantics</TabsTrigger>
              <TabsTrigger value="relationships">
                Relationships
                {propRelationships.length > 0 && (
                  <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1">{propRelationships.length}</Badge>
                )}
              </TabsTrigger>
            </TabsList>

            {/* Core Tab */}
            <TabsContent value="core" className="space-y-3 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="prop-name" className="text-xs">
                    Column Name <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="prop-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g., customer_id"
                    className="h-9"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="prop-logical-type" className="text-xs">
                    Logical Type <span className="text-destructive">*</span>
                  </Label>
                  <Select value={logicalType} onValueChange={setLogicalType}>
                    <SelectTrigger id="prop-logical-type" className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LOGICAL_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {type}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="prop-physical-type" className="text-xs flex items-center">
                    Physical Type
                    <FieldTooltip content="Physical data type like VARCHAR(50), INT, DECIMAL(10,2)" />
                  </Label>
                  <Input
                    id="prop-physical-type"
                    value={physicalType}
                    onChange={(e) => setPhysicalType(e.target.value)}
                    placeholder="e.g., VARCHAR(50)"
                    className="h-9"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="prop-physical-name" className="text-xs flex items-center">
                    Physical Name
                    <FieldTooltip content="Physical column name in the database" />
                  </Label>
                  <Input
                    id="prop-physical-name"
                    value={physicalName}
                    onChange={(e) => setPhysicalName(e.target.value)}
                    placeholder="e.g., cust_id"
                    className="h-9"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-description" className="text-xs">
                  Description
                </Label>
                <Input
                  id="prop-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe this column"
                  className="h-9"
                />
              </div>
            </TabsContent>

            {/* Constraints Tab */}
            <TabsContent value="constraints" className="space-y-3 mt-4">
              <div className="space-y-3">
                <div className="flex items-center gap-6">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="prop-required"
                      checked={required}
                      onCheckedChange={(checked) => setRequired(checked as boolean)}
                    />
                    <Label htmlFor="prop-required" className="text-sm font-normal cursor-pointer">
                      Required (NOT NULL)
                    </Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="prop-unique"
                      checked={unique}
                      onCheckedChange={(checked) => setUnique(checked as boolean)}
                    />
                    <Label htmlFor="prop-unique" className="text-sm font-normal cursor-pointer">
                      Unique
                    </Label>
                  </div>
                </div>

                <div className="border-t pt-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Checkbox
                      id="prop-primary-key"
                      checked={primaryKey}
                      onCheckedChange={(checked) => setPrimaryKey(checked as boolean)}
                    />
                    <Label htmlFor="prop-primary-key" className="text-sm font-normal cursor-pointer flex items-center">
                      Primary Key
                      <FieldTooltip content="Mark this column as part of the primary key" />
                    </Label>
                  </div>
                  {primaryKey && (
                    <div className="ml-6 space-y-1.5">
                      <Label htmlFor="prop-pk-position" className="text-xs flex items-center">
                        Primary Key Position
                        <FieldTooltip content="Position in composite primary key (starting from 1)" />
                      </Label>
                      <Input
                        id="prop-pk-position"
                        type="number"
                        min="1"
                        value={primaryKeyPosition}
                        onChange={(e) => setPrimaryKeyPosition(e.target.value)}
                        placeholder="e.g., 1"
                        className="h-9 w-32"
                      />
                    </div>
                  )}
                </div>

                <div className="border-t pt-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Checkbox
                      id="prop-partitioned"
                      checked={partitioned}
                      onCheckedChange={(checked) => setPartitioned(checked as boolean)}
                    />
                    <Label htmlFor="prop-partitioned" className="text-sm font-normal cursor-pointer flex items-center">
                      Partition Column
                      <FieldTooltip content="This column is used for table partitioning" />
                    </Label>
                  </div>
                  {partitioned && (
                    <div className="ml-6 space-y-1.5">
                      <Label htmlFor="prop-partition-position" className="text-xs flex items-center">
                        Partition Position
                        <FieldTooltip content="Position in partition key (starting from 1)" />
                      </Label>
                      <Input
                        id="prop-partition-position"
                        type="number"
                        min="1"
                        value={partitionKeyPosition}
                        onChange={(e) => setPartitionKeyPosition(e.target.value)}
                        placeholder="e.g., 1"
                        className="h-9 w-32"
                      />
                    </div>
                  )}
                </div>

                <div className="border-t pt-3 space-y-3">
                  {logicalType === 'string' && (
                    <div className="grid grid-cols-3 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-min-length" className="text-xs">Min Length</Label>
                        <Input id="prop-min-length" type="number" min="0" value={minLength} onChange={(e) => setMinLength(e.target.value)} className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-max-length" className="text-xs">Max Length</Label>
                        <Input id="prop-max-length" type="number" min="0" value={maxLength} onChange={(e) => setMaxLength(e.target.value)} className="h-9" />
                      </div>
                      <div className="space-y-1.5 col-span-3">
                        <Label htmlFor="prop-pattern" className="text-xs">Pattern (ECMA-262 regex)</Label>
                        <Input id="prop-pattern" value={pattern} onChange={(e) => setPattern(e.target.value)} className="h-9" />
                      </div>
                    </div>
                  )}

                  {(logicalType === 'number' || logicalType === 'integer') && (
                    <div className="grid grid-cols-4 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-minimum" className="text-xs">Minimum</Label>
                        <Input id="prop-minimum" type="number" value={minimum} onChange={(e) => setMinimum(e.target.value)} className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-maximum" className="text-xs">Maximum</Label>
                        <Input id="prop-maximum" type="number" value={maximum} onChange={(e) => setMaximum(e.target.value)} className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-multiple-of" className="text-xs">Multiple Of</Label>
                        <Input id="prop-multiple-of" type="number" value={multipleOf} onChange={(e) => setMultipleOf(e.target.value)} className="h-9" />
                      </div>
                      {logicalType === 'number' && (
                        <div className="space-y-1.5">
                          <Label htmlFor="prop-precision" className="text-xs">Precision</Label>
                          <Input id="prop-precision" type="number" min="0" value={precision} onChange={(e) => setPrecision(e.target.value)} className="h-9" />
                        </div>
                      )}
                    </div>
                  )}

                  {logicalType === 'date' && (
                    <div className="grid grid-cols-3 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-date-format" className="text-xs">Format</Label>
                        <Input id="prop-date-format" value={dateFormat} onChange={(e) => setDateFormat(e.target.value)} placeholder="e.g., yyyy-MM-dd" className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-timezone" className="text-xs">Timezone</Label>
                        <Input id="prop-timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="e.g., UTC" className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-custom-format" className="text-xs">Custom Format</Label>
                        <Input id="prop-custom-format" value={customFormat} onChange={(e) => setCustomFormat(e.target.value)} className="h-9" />
                      </div>
                    </div>
                  )}

                  {logicalType === 'array' && (
                    <div className="grid grid-cols-4 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-item-type" className="text-xs">Item Type</Label>
                        <Input id="prop-item-type" value={itemType} onChange={(e) => setItemType(e.target.value)} placeholder="string | number | object..." className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-min-items" className="text-xs">Min Items</Label>
                        <Input id="prop-min-items" type="number" min="0" value={minItems} onChange={(e) => setMinItems(e.target.value)} className="h-9" />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="prop-max-items" className="text-xs">Max Items</Label>
                        <Input id="prop-max-items" type="number" min="0" value={maxItems} onChange={(e) => setMaxItems(e.target.value)} className="h-9" />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>

            {/* Quality Tab */}
            <TabsContent value="quality" className="space-y-3 mt-4">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-semibold flex items-center">
                    Property-Level Quality Checks
                    <FieldTooltip content="ODCS quality checks that apply specifically to this column" />
                  </Label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditingQualityCheckIndex(null)
                      setIsQualityRuleDialogOpen(true)
                    }}
                    className="h-7"
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    Add Check
                  </Button>
                </div>
                
                {qualityChecks.length > 0 ? (
                  <div className="space-y-2">
                    {qualityChecks.map((check, idx) => (
                      <div key={idx} className="flex items-start justify-between p-3 border rounded-lg bg-background">
                        <div className="flex-1 space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-medium">{check.name || check.rule}</span>
                            {check.dimension && (
                              <Badge variant="outline" className="text-xs">{check.dimension}</Badge>
                            )}
                            {check.severity && (
                              <Badge variant={check.severity === 'error' ? 'destructive' : 'default'} className="text-xs">
                                {check.severity}
                              </Badge>
                            )}
                          </div>
                          {check.description && (
                            <p className="text-xs text-muted-foreground">{check.description}</p>
                          )}
                          {check.rule && (
                            <p className="text-xs font-mono text-muted-foreground">{check.rule}</p>
                          )}
                        </div>
                        <div className="flex gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditingQualityCheckIndex(idx)
                              setIsQualityRuleDialogOpen(true)
                            }}
                            className="h-7 w-7 p-0"
                          >
                            <Edit className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              const updated = qualityChecks.filter((_, i) => i !== idx)
                              setQualityChecks(updated)
                            }}
                            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-6 border-2 border-dashed rounded-lg">
                    <p className="text-sm text-muted-foreground">No quality checks defined for this column</p>
                    <p className="text-xs text-muted-foreground mt-1">Click "Add Check" to define quality rules</p>
                  </div>
                )}
              </div>
            </TabsContent>

            {/* Governance Tab */}
            <TabsContent value="governance" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="prop-classification" className="text-xs flex items-center">
                  Classification
                  <FieldTooltip content="Data sensitivity: public, internal, confidential, restricted, pii, or 1-5" />
                </Label>
                <Select value={classification || undefined} onValueChange={setClassification}>
                  <SelectTrigger id="prop-classification" className="h-9">
                    <SelectValue placeholder="Select classification" />
                  </SelectTrigger>
                  <SelectContent>
                    {CLASSIFICATION_LEVELS.map((level) => (
                      <SelectItem key={level} value={level}>
                        {level}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-examples" className="text-xs flex items-center">
                  Examples
                  <FieldTooltip content="Sample values, comma-separated or as JSON array" />
                </Label>
                <Input
                  id="prop-examples"
                  value={examples}
                  onChange={(e) => setExamples(e.target.value)}
                  placeholder='e.g., "John", "Jane" or ["value1", "value2"]'
                  className="h-9"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-tags" className="text-xs flex items-center">
                  Tags
                  <FieldTooltip content="ODCS tags for categorization (comma-separated)" />
                </Label>
                <Input
                  id="prop-tags"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder='e.g., "finance", "sensitive", "employee_record"'
                  className="h-9"
                />
              </div>
            </TabsContent>

            {/* Business Tab */}
            <TabsContent value="business" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="prop-business-name" className="text-xs flex items-center">
                  Business Name
                  <FieldTooltip content="Human-readable business name for this column" />
                </Label>
                <Input
                  id="prop-business-name"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                  placeholder="e.g., Customer Identifier"
                  className="h-9"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-encrypted-name" className="text-xs flex items-center">
                  Encrypted Name
                  <FieldTooltip content="Column name containing encrypted version of this data" />
                </Label>
                <Input
                  id="prop-encrypted-name"
                  value={encryptedName}
                  onChange={(e) => setEncryptedName(e.target.value)}
                  placeholder="e.g., customer_id_encrypted"
                  className="h-9"
                />
              </div>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="prop-cde"
                  checked={criticalDataElement}
                  onCheckedChange={(checked) => setCriticalDataElement(checked as boolean)}
                />
                <Label htmlFor="prop-cde" className="text-sm font-normal cursor-pointer flex items-center">
                  Critical Data Element (CDE)
                  <FieldTooltip content="Mark as critical data element requiring special governance" />
                </Label>
              </div>
            </TabsContent>

            {/* Transform Tab */}
            <TabsContent value="transform" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="prop-transform-logic" className="text-xs flex items-center">
                  Transform Logic
                  <FieldTooltip content="The transformation logic/formula applied to generate this column" />
                </Label>
                <Input
                  id="prop-transform-logic"
                  value={transformLogic}
                  onChange={(e) => setTransformLogic(e.target.value)}
                  placeholder="e.g., UPPER(source_column)"
                  className="h-9"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-transform-sources" className="text-xs flex items-center">
                  Transform Source Objects
                  <FieldTooltip content="Source tables/columns used in transformation (comma-separated)" />
                </Label>
                <Input
                  id="prop-transform-sources"
                  value={transformSourceObjects}
                  onChange={(e) => setTransformSourceObjects(e.target.value)}
                  placeholder="e.g., source_table.column1, other_table.column2"
                  className="h-9"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prop-transform-desc" className="text-xs flex items-center">
                  Transform Description
                  <FieldTooltip content="Simple description of what the transformation does" />
                </Label>
                <Input
                  id="prop-transform-desc"
                  value={transformDescription}
                  onChange={(e) => setTransformDescription(e.target.value)}
                  placeholder="e.g., Converts name to uppercase"
                  className="h-9"
                />
              </div>
            </TabsContent>

            {/* Semantics Tab */}
            <TabsContent value="semantics" className="space-y-3 mt-4">
              <div className="space-y-2">
                <Label className="text-sm font-semibold flex items-center">
                  Linked Business Concepts
                  <FieldTooltip content="Link this property to business concepts from your semantic model (ontology)" />
                </Label>
                <BusinessConceptsDisplay
                  concepts={semanticConcepts}
                  onConceptsChange={(concepts) => {
                    setSemanticConcepts(concepts)
                    // Keep authoritativeDefinitions in sync
                    setAuthoritativeDefinitions(concepts.map(c => ({ url: c.iri, type: SEMANTIC_ASSIGNMENT_TYPE })))
                  }}
                  entityType="data_contract_property"
                  entityId={name || 'property'}
                  conceptType="property"
                />
              </div>
            </TabsContent>

            {/* Relationships Tab (ODCS v3.1.0) */}
            <TabsContent value="relationships" className="space-y-3 mt-4">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-semibold flex items-center">
                    Foreign Key Relationships
                    <FieldTooltip content="ODCS v3.1.0 property-level relationships (e.g., foreign keys to other schema/table columns)" />
                  </Label>
                </div>

                {propRelationships.length > 0 && (
                  <div className="space-y-2">
                    {propRelationships.map((rel, idx) => (
                      <div key={idx} className="flex items-center justify-between p-3 border rounded-lg bg-background">
                        <div className="flex items-center gap-2 flex-1">
                          <Badge variant="outline" className="text-xs">{rel.type}</Badge>
                          <span className="text-sm font-mono">→ {typeof rel.to === 'string' ? rel.to : JSON.stringify(rel.to)}</span>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => setPropRelationships(propRelationships.filter((_, i) => i !== idx))}
                          className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="border rounded-lg p-3 bg-background space-y-2">
                  <div className="grid grid-cols-3 gap-2">
                    <div className="col-span-2 space-y-1">
                      <Label className="text-xs">Target Reference (to)</Label>
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
                    disabled={!newRelTo.trim()}
                    onClick={() => {
                      setPropRelationships([...propRelationships, { type: newRelType, to: newRelTo.trim() }])
                      setNewRelTo('')
                      setNewRelType('foreignKey')
                    }}
                    className="h-7"
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    Add Relationship
                  </Button>
                </div>

                {propRelationships.length === 0 && (
                  <div className="text-center py-4 border-2 border-dashed rounded-lg">
                    <p className="text-sm text-muted-foreground">No relationships defined</p>
                    <p className="text-xs text-muted-foreground mt-1">Add a foreign key reference to link this property to another entity</p>
                  </div>
                )}
              </div>
            </TabsContent>
          </Tabs>

          <div className="flex gap-2 pt-2">
            <Button
              type="button"
              size="sm"
              variant={editingIndex !== null && isDirty ? 'default' : 'outline'}
              onClick={handleAddOrUpdate}
              className="h-8"
            >
              {editingIndex !== null ? (
                <>
                  <Edit className="h-3.5 w-3.5 mr-1.5" />
                  {t('schemaEditor.updateColumn')}
                </>
              ) : (
                <>
                  <Plus className="h-3.5 w-3.5 mr-1.5" />
                  {t('schemaEditor.addColumn')}
                </>
              )}
            </Button>
            {editingIndex !== null && (
              <Button type="button" size="sm" variant="outline" onClick={resetForm} className="h-8">
                {t('schemaEditor.cancel')}
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Properties List */}
      {properties.length > 0 ? (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="text-left p-2 font-medium">Name</th>
                <th className="text-left p-2 font-medium">Type</th>
                <th className="text-left p-2 font-medium">Constraints</th>
                <th className="text-left p-2 font-medium">Governance</th>
                <th className="text-left p-2 font-medium">Description</th>
                {!readOnly && <th className="text-right p-2 font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {properties.map((prop, idx) => {
                const constraints: string[] = []
                if (prop.required) constraints.push('Required')
                if (prop.unique) constraints.push('Unique')
                if (prop.primaryKey) constraints.push(`PK${prop.primaryKeyPosition ? `(${prop.primaryKeyPosition})` : ''}`)
                if (prop.partitioned) constraints.push(`Part${prop.partitionKeyPosition ? `(${prop.partitionKeyPosition})` : ''}`)

                const governance: string[] = []
                if (prop.classification) governance.push(prop.classification)
                if (prop.criticalDataElement) governance.push('CDE')

                return (
                  <tr
                    key={idx}
                    className={`border-t hover:bg-muted/50 cursor-pointer ${
                      editingIndex === idx 
                        ? 'bg-primary/10 border-l-4 border-l-primary' 
                        : ''
                    }`}
                    onClick={() => handleEdit(idx)}
                  >
                    <td className="p-2">
                      <div className="flex items-center">
                        <TabIndicator prop={prop} />
                        <span className="font-mono text-xs font-medium">{prop.name}</span>
                      </div>
                      {prop.physicalName && (
                        <div className="text-xs text-muted-foreground mt-0.5 ml-[21px]">→ {prop.physicalName}</div>
                      )}
                    </td>
                    <td className="p-2">
                      <div className="text-xs bg-secondary px-2 py-0.5 rounded inline-block">
                        {prop.logicalType || (prop as any).logical_type || '-'}
                      </div>
                      {prop.physicalType && (
                        <div className="text-xs text-muted-foreground mt-0.5">{prop.physicalType}</div>
                      )}
                    </td>
                    <td className="p-2">
                      {constraints.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {constraints.map((c, i) => (
                            <span key={i} className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded">
                              {c}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="p-2">
                      {governance.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {governance.map((g, i) => (
                            <span key={i} className="text-xs bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded">
                              {g}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="p-2 text-xs text-muted-foreground max-w-xs">
                      <div className="truncate">{prop.description || '-'}</div>
                      {prop.businessName && (
                        <div className="text-xs text-muted-foreground italic mt-0.5">
                          {prop.businessName}
                        </div>
                      )}
                    </td>
                    {!readOnly && (
                      <td className="p-2">
                        <div className="flex justify-end gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={(e) => { e.stopPropagation(); handleEdit(idx) }}
                            className="h-7 w-7 p-0"
                          >
                            <Edit className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={(e) => { e.stopPropagation(); handleDelete(idx) }}
                            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground text-center py-8 border rounded-lg bg-muted/30">
          {readOnly ? 'No columns defined.' : 'No columns added yet. Add at least one column above.'}
        </p>
      )}

      {/* Quality Rule Dialog */}
      <QualityRuleFormDialog
        isOpen={isQualityRuleDialogOpen}
        onOpenChange={(open) => {
          setIsQualityRuleDialogOpen(open)
          if (!open) {
            setEditingQualityCheckIndex(null)
          }
        }}
        initial={editingQualityCheckIndex !== null ? qualityChecks[editingQualityCheckIndex] : undefined}
        onSubmit={editingQualityCheckIndex !== null ? handleUpdateQualityCheck : handleAddQualityCheck}
      />
    </div>
  )
}

export default forwardRef(SchemaPropertyEditorInner)
