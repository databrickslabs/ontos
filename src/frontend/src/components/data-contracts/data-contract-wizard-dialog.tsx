import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import InferFromAssetDialog from './infer-from-asset-dialog'
import type { InferredSchemaObject } from './infer-from-asset-dialog'
import BusinessConceptsDisplay from '@/components/business-concepts/business-concepts-display'
import { PrincipalPicker } from '@/components/common/principal-picker'
import { useDomains } from '@/hooks/use-domains'
import DomainMultiSelector from '@/components/ui/domain-multi-selector'
import { useToast } from '@/hooks/use-toast'

type WizardProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: any) => Promise<void>
  initial?: any
}

const statuses = ['draft', 'active', 'deprecated', 'archived']

interface SemanticConcept {
  iri: string
  label?: string
  description?: string
  type?: string
}
// ODCS v3.1.0 compliant logical types (exact match with spec)
const LOGICAL_TYPES = [
  'string',
  'date',
  'number',
  'integer',
  'object',
  'array',
  'boolean'
]

// ODCS v3.1.0 quality framework constants
const QUALITY_DIMENSIONS = ['accuracy', 'completeness', 'conformity', 'consistency', 'coverage', 'timeliness', 'uniqueness']
const QUALITY_TYPES = ['text', 'library', 'sql', 'custom']
const QUALITY_SEVERITIES = ['info', 'warning', 'error']
const BUSINESS_IMPACTS = ['operational', 'regulatory']

// ODCS v3.1.0 server types
const ODCS_SERVER_TYPES = [
  'api', 'athena', 'azure', 'bigquery', 'clickhouse', 'databricks', 'denodo', 'dremio',
  'duckdb', 'glue', 'cloudsql', 'db2', 'informix', 'kafka', 'kinesis', 'local',
  'mysql', 'oracle', 'postgresql', 'postgres', 'presto', 'pubsub',
  'redshift', 's3', 'sftp', 'snowflake', 'sqlserver', 'synapse', 'trino', 'vertica', 'custom'
]
const ENVIRONMENTS = ['production', 'staging', 'development', 'test']

// ODCS v3.1.0 physical types for schema objects
const PHYSICAL_TYPES = ['table', 'view', 'materialized_view', 'external_table', 'managed_table', 'streaming_table']

export default function DataContractWizardDialog({ isOpen, onOpenChange, onSubmit, initial }: WizardProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { refetch: refetchDomains } = useDomains()
  const { toast } = useToast()

  // Helper function to handle domain-related errors
  const handleDomainError = async (error: any) => {
    const errorMessage = error?.message || error?.detail || error?.toString() || 'Unknown error'

    if (errorMessage.includes('Domain with ID') && errorMessage.includes('not found')) {
      // This is a domain validation error
      toast({
        title: t('data-contracts:wizard.toast.domainError.title', 'Domain Error'),
        description: t('data-contracts:wizard.toast.domainError.description', 'The selected domain is no longer available. Please select a different domain.'),
        variant: 'destructive' as any
      })

      // Clear the invalid domain selection
      setDomainIds([])
      setPrimaryDomainId(null)

      // Refetch domains to get the latest list
      try {
        await refetchDomains()
        toast({
          title: t('data-contracts:wizard.toast.domainsUpdated.title', 'Domains Updated'),
          description: t('data-contracts:wizard.toast.domainsUpdated.description', 'Available domains have been refreshed. Please select a domain again.'),
          variant: 'default' as any
        })
      } catch (refetchError) {
        console.error('Failed to refetch domains:', refetchError)
      }

      return true // Indicates this was a domain error and was handled
    }

    return false // Not a domain error
  }
  const [step, setStep] = useState(1)
  const totalSteps = 5
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSavingDraft, setIsSavingDraft] = useState(false)

  // Step fields
  const [name, setName] = useState(initial?.name || '')
  const [version, setVersion] = useState(initial?.version || '1.0.0')
  const [status, setStatus] = useState(initial?.status || 'draft')
  const [owner, setOwner] = useState(initial?.owner || '')
  const [domainIds, setDomainIds] = useState<string[]>(
    initial?.domainIds || (initial?.domainId ? [initial.domainId] : (initial?.domain ? [initial.domain] : []))
  )
  const [primaryDomainId, setPrimaryDomainId] = useState<string | null>(
    initial?.primaryDomainId ?? initial?.domainId ?? initial?.domain ?? null
  )
  const [tenant, setTenant] = useState(initial?.tenant || '')
  const [dataProduct, setDataProduct] = useState(initial?.dataProduct || '')
  const [descriptionUsage, setDescriptionUsage] = useState(initial?.descriptionUsage || '')
  const [descriptionPurpose, setDescriptionPurpose] = useState(initial?.descriptionPurpose || '')
  const [descriptionLimitations, setDescriptionLimitations] = useState(initial?.descriptionLimitations || '')

  // ODCS v3.2.0 contract-level context (RFC-0038): AI/semantic guidance.
  // Read from the contract's `context` block (string shorthand or object), which
  // is what the API returns — so editing an existing contract prefills it.
  const initialContext = (() => {
    const c = (initial as { context?: unknown } | undefined)?.context
    if (!c) return { instructions: '', verifiedStatements: [] as { question: string; answer: string }[], constraints: [] as string[] }
    if (typeof c === 'string') return { instructions: c, verifiedStatements: [], constraints: [] }
    const obj = c as {
      instructions?: string
      verifiedStatements?: { question?: string; answer?: string }[]
      constraints?: ({ constraint?: string } | string)[]
    }
    return {
      instructions: obj.instructions ?? '',
      verifiedStatements: (obj.verifiedStatements ?? []).map((s) => ({ question: s.question ?? '', answer: s.answer ?? '' })),
      constraints: (obj.constraints ?? []).map((x) => (typeof x === 'string' ? x : x.constraint ?? '')).filter(Boolean),
    }
  })()
  const [contextInstructions, setContextInstructions] = useState<string>(initialContext.instructions)
  const [contextVerifiedStatements, setContextVerifiedStatements] = useState<{ question: string; answer: string }[]>(
    initialContext.verifiedStatements,
  )
  const [contextConstraints, setContextConstraints] = useState<string[]>(initialContext.constraints)

  // Stakeholders / access groups / support contacts wired up in Phase 4
  // (PRD #335). Previously these step-4 fields rendered but their values
  // were dropped at submit time; they now flow into the wizard payload.
  const [consumers, setConsumers] = useState<string[]>(
    (initial as { consumers?: string[] } | undefined)?.consumers ?? [],
  )
  const [subjectMatterExperts, setSubjectMatterExperts] = useState<string[]>(
    (initial as { subjectMatterExperts?: string[] } | undefined)?.subjectMatterExperts ?? [],
  )
  const [readGroups, setReadGroups] = useState<string[]>(
    (initial as { readGroups?: string[] } | undefined)?.readGroups ?? [],
  )
  const [writeGroups, setWriteGroups] = useState<string[]>(
    (initial as { writeGroups?: string[] } | undefined)?.writeGroups ?? [],
  )
  const [primarySupportEmail, setPrimarySupportEmail] = useState<string>(
    (initial as { primarySupportEmail?: string } | undefined)?.primarySupportEmail ?? '',
  )

  type Column = {
    name: string;
    physicalType?: string;
    logicalType: string;
    required?: boolean;
    unique?: boolean;
    primaryKey?: boolean;
    primaryKeyPosition?: number;
    partitioned?: boolean;
    partitionKeyPosition?: number;
    description?: string;
    classification?: string;
    examples?: string;
    semanticConcepts?: SemanticConcept[];
    // ODCS v3.1.0 additional property fields
    businessName?: string;
    encryptedName?: string;
    criticalDataElement?: boolean;
    transformLogic?: string;
    transformSourceObjects?: string;
    transformDescription?: string;
  }
  type SchemaObject = {
    name: string;
    physicalName?: string;
    properties: Column[];
    semanticConcepts?: SemanticConcept[];
    // Extended UC metadata
    description?: string;
    tableType?: string;
    owner?: string;
    createdAt?: string;
    updatedAt?: string;
    tableProperties?: Record<string, any>;
    // ODCS v3.1.0 fields
    businessName?: string;
    physicalType?: string; // table, view, materialized_view, etc.
    dataGranularityDescription?: string;
  }
  const [schemaObjects, setSchemaObjects] = useState<SchemaObject[]>(initial?.schemaObjects || [])
  const [contractSemanticConcepts, setContractSemanticConcepts] = useState<SemanticConcept[]>(initial?.contractSemanticConcepts || [])

  type QualityRule = {
    name: string;
    dimension: string;
    type: string;
    severity: string;
    businessImpact: string;
    description?: string;
    query?: string; // for SQL-based rules
    rule?: string; // for library-based rules
    engine?: string; // for custom rules
    implementation?: string; // for custom rules
    mustBe?: string;
    mustNotBe?: string;
    mustBeGt?: string;
    mustBeLt?: string;
    mustBeBetweenMin?: string;
    mustBeBetweenMax?: string;
  }
  const [qualityRules, setQualityRules] = useState<QualityRule[]>(initial?.qualityRules || [])

  type ServerConfig = {
    server: string;
    type: string;
    description?: string;
    environment: string;
    host?: string;
    port?: number;
    database?: string;
    schema?: string;
    location?: string;
    properties?: Record<string, string>;
  }
  const [serverConfigs, setServerConfigs] = useState<ServerConfig[]>(initial?.serverConfigs || [])

  // SLA Requirements state
  const [slaRequirements, setSlaRequirements] = useState({
    uptimeTarget: initial?.sla?.uptimeTarget || 0,
    maxDowntimeMinutes: initial?.sla?.maxDowntimeMinutes || 0,
    queryResponseTimeMs: initial?.sla?.queryResponseTimeMs || 0,
    dataFreshnessMinutes: initial?.sla?.dataFreshnessMinutes || 0,
    queryResponseTimeUnit: 'seconds',
    dataFreshnessUnit: 'minutes'
  })

  const [lookupOpen, setLookupOpen] = useState(false)
  const wasOpenRef = useRef(false)

  // Initialize wizard state only when the dialog transitions from closed -> open
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      wasOpenRef.current = true
      if (!initial) {
        // Reset to defaults for new contract
        setStep(1)
        setName('')
        setVersion('1.0.0')
        setStatus('draft')
        setOwner('')
        setDomainIds([])
        setPrimaryDomainId(null)
        setTenant('')
        setDataProduct('')
        setDescriptionUsage('')
        setDescriptionPurpose('')
        setDescriptionLimitations('')
        setSchemaObjects([])
        setQualityRules([])
        setServerConfigs([])
        setSlaRequirements({
          uptimeTarget: 0,
          maxDowntimeMinutes: 0,
          queryResponseTimeMs: 0,
          dataFreshnessMinutes: 0,
          queryResponseTimeUnit: 'seconds',
          dataFreshnessUnit: 'minutes'
        })
        setIsSubmitting(false)
      } else {
        // Initialize from provided data for editing
        setStep(1)
        setName(initial.name || '')
        setVersion(initial.version || '1.0.0')
        setStatus(initial.status || 'draft')
        setOwner(initial.owner || '')
        setDomainIds(initial.domainIds || (initial.domainId ? [initial.domainId] : (initial.domain ? [initial.domain] : [])))
        setPrimaryDomainId(initial.primaryDomainId ?? initial.domainId ?? initial.domain ?? null)
        setTenant(initial.tenant || '')
        setDataProduct(initial.dataProduct || '')
        setDescriptionUsage(initial.descriptionUsage || '')
        setDescriptionPurpose(initial.descriptionPurpose || '')
        setDescriptionLimitations(initial.descriptionLimitations || '')
        setSchemaObjects(initial.schemaObjects || [])
        setQualityRules(initial.qualityRules || [])
        setServerConfigs(initial.serverConfigs || [])
        setSlaRequirements({
          uptimeTarget: initial.sla?.uptimeTarget || 0,
          maxDowntimeMinutes: initial.sla?.maxDowntimeMinutes || 0,
          queryResponseTimeMs: initial.sla?.queryResponseTimeMs || 0,
          dataFreshnessMinutes: initial.sla?.dataFreshnessMinutes || 0,
          queryResponseTimeUnit: 'seconds',
          dataFreshnessUnit: 'minutes'
        })
        setIsSubmitting(false)
      }
    } else if (!isOpen && wasOpenRef.current) {
      // Mark as closed to allow re-initialization on next open
      wasOpenRef.current = false
    }
  }, [isOpen, initial])

  const addObject = () => setSchemaObjects((prev) => [...prev, { name: '', properties: [] }])
  const removeObject = (idx: number) => setSchemaObjects((prev) => prev.filter((_, i) => i !== idx))
  const addColumn = (objIdx: number) => setSchemaObjects((prev) => prev.map((o, i) => i === objIdx ? { ...o, properties: [...o.properties, { name: '', physicalType: '', logicalType: 'string', classification: '', examples: '' }] } : o))
  const removeColumn = (objIdx: number, colIdx: number) => setSchemaObjects((prev) => prev.map((o, i) => i === objIdx ? { ...o, properties: o.properties.filter((_, j) => j !== colIdx) } : o))

  const addQualityRule = () => setQualityRules((prev) => [...prev, {
    name: '',
    dimension: 'completeness',
    type: 'library',
    severity: 'warning',
    businessImpact: 'operational',
    description: '',
    level: 'object',
    rule: '',
    query: '',
    engine: '',
    implementation: '',
    mustBe: '',
    mustNotBe: '',
    mustBeGt: '',
    mustBeLt: '',
    mustBeBetweenMin: '',
    mustBeBetweenMax: ''
  }])
  const removeQualityRule = (idx: number) => setQualityRules((prev) => prev.filter((_, i) => i !== idx))

  const addServerConfig = () => setServerConfigs((prev) => [...prev, { server: '', type: 'postgresql', environment: 'production' }])
  const removeServerConfig = (idx: number) => setServerConfigs((prev) => prev.filter((_, i) => i !== idx))

  const handleInferFromAsset = (schemas: InferredSchemaObject[]) => {
    const baseIndex = schemaObjects.length
    const newObjects = schemas.map(s => ({
      name: s.name,
      physicalName: s.physicalName,
      description: s.description || undefined,
      properties: s.properties.map(p => ({
        name: p.name,
        physicalType: p.physicalType,
        logicalType: p.logicalType || 'string',
        required: p.required,
        description: p.description,
        partitioned: p.partitioned,
      })),
    }))
    setSchemaObjects((prev) => [...prev, ...newObjects])
    setStep(2)

    const totalCols = schemas.reduce((sum, s) => sum + s.properties.length, 0)
    toast({
      title: t('data-contracts:wizard.toast.schemaInferred.title', 'Schema inferred successfully'),
      description: t('data-contracts:wizard.toast.schemaInferred.description', 'Added {{count}} schema with {{columnCount}} columns', { count: schemas.length, columnCount: totalCols }),
    })

    setTimeout(() => {
      const el = document.getElementById(`schema-object-${baseIndex}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 0)
  }

  const handleNext = () => {
    // Validate Step 1 before proceeding - ODCS required + app required fields
    if (step === 1) {
      if (!name || !name.trim()) {
        toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.nameRequired', 'Contract name is required'), variant: 'destructive' as any })
        return
      }
      if (!version || !version.trim()) {
        toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.versionRequired', 'Version is required'), variant: 'destructive' as any })
        return
      }
      if (!status || !status.trim()) {
        toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.statusRequired', 'Status is required'), variant: 'destructive' as any })
        return
      }
    }

    if (step < totalSteps) setStep(step + 1)
  }
  const handlePrev = () => { if (step > 1) setStep(step - 1) }

  const handleSubmit = async () => {
    // Validation - ODCS required + app required fields
    if (!name || !name.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.nameRequired', 'Contract name is required'), variant: 'destructive' as any })
      return
    }
    if (!version || !version.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.versionRequired', 'Version is required'), variant: 'destructive' as any })
      return
    }
    if (!status || !status.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.statusRequired', 'Status is required'), variant: 'destructive' as any })
      return
    }

    setIsSubmitting(true)
    try {
      // Helper function to convert semantic concepts to ODCS authoritativeDefinitions format
      const convertSemanticConcepts = (concepts: SemanticConcept[] = []) => {
        return concepts.map(concept => ({
          url: concept.iri,
          type: "http://databricks.com/ontology/uc/semanticAssignment"
        }))
      }

      const payload = {
        name,
        version,
        status: status, // Use user-selected status
        owner,
        domainIds: domainIds, // Multi-domain assignment (primary included)
        primaryDomainId: primaryDomainId,
        tenant,
        dataProduct,
        description: { usage: descriptionUsage, purpose: descriptionPurpose, limitations: descriptionLimitations },
        // ODCS v3.2.0 contract-level context block (RFC-0038). Omitted entirely
        // when empty so older-version contracts stay clean.
        context: (contextInstructions.trim() || contextVerifiedStatements.length || contextConstraints.length)
          ? {
              instructions: contextInstructions.trim() || undefined,
              verifiedStatements: contextVerifiedStatements
                .filter((s) => s.question.trim())
                .map((s) => ({ question: s.question.trim(), answer: s.answer.trim() || undefined })),
              constraints: contextConstraints
                .filter((c) => c.trim())
                .map((c) => ({ constraint: c.trim() })),
            }
          : undefined,
        // Phase 4 stakeholder / access / support fields — previously
        // rendered but unwired in the wizard.
        consumers,
        subjectMatterExperts,
        accessControl: { readGroups, writeGroups },
        support: { primaryEmail: primarySupportEmail },
        // Include contract-level semantic assignments as authoritativeDefinitions
        authoritativeDefinitions: convertSemanticConcepts(contractSemanticConcepts),
        schema: schemaObjects.map((o) => ({
          name: o.name,
          physicalName: o.physicalName,
          // ODCS v3.1.0 schema object fields
          businessName: o.businessName,
          physicalType: o.physicalType,
          description: o.description,
          dataGranularityDescription: o.dataGranularityDescription,
          // Include schema-level semantic assignments
          authoritativeDefinitions: convertSemanticConcepts(o.semanticConcepts),
          properties: o.properties.map(p => ({
            ...p,
            // Include property-level semantic assignments
            authoritativeDefinitions: convertSemanticConcepts(p.semanticConcepts)
          }))
        })),
        qualityRules: qualityRules,
        serverConfigs: serverConfigs,
        sla: {
          uptimeTarget: slaRequirements.uptimeTarget,
          maxDowntimeMinutes: slaRequirements.maxDowntimeMinutes,
          queryResponseTimeMs: slaRequirements.queryResponseTimeMs,
          dataFreshnessMinutes: slaRequirements.dataFreshnessMinutes
        },
      }
      await onSubmit(payload)
      // Don't close here - let the parent component handle closing on success
    } catch (error) {
      // Handle domain-specific errors gracefully
      const wasDomainError = await handleDomainError(error)

      if (!wasDomainError) {
        // Generic error handling for non-domain errors
        toast({
          title: t('data-contracts:wizard.toast.submissionError.title', 'Submission Error'),
          description: t('data-contracts:wizard.toast.submissionError.description', 'Failed to save contract. Please try again.'),
          variant: 'destructive' as any
        })
        console.error('Failed to submit contract:', error)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSaveDraft = async () => {
    // Validate minimum required fields - ODCS required + app required fields for drafts
    if (!name || !name.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.nameRequiredDraft', 'Contract name is required to save a draft'), variant: 'destructive' as any })
      return
    }
    if (!version || !version.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.versionRequiredDraft', 'Version is required to save a draft'), variant: 'destructive' as any })
      return
    }
    if (!status || !status.trim()) {
      toast({ title: t('data-contracts:wizard.validation.title', 'Validation Error'), description: t('data-contracts:wizard.validation.statusRequiredDraft', 'Status is required to save a draft'), variant: 'destructive' as any })
      return
    }

    setIsSavingDraft(true)
    try {
      // Helper function to convert semantic concepts to ODCS authoritativeDefinitions format
      const convertSemanticConcepts = (concepts: SemanticConcept[] = []) => {
        return concepts.map(concept => ({
          url: concept.iri,
          type: "http://databricks.com/ontology/uc/semanticAssignment"
        }))
      }

      const payload = {
        name,
        version,
        status: 'draft', // Draft status for partial saves
        owner,
        domainIds: domainIds, // Multi-domain assignment (primary included)
        primaryDomainId: primaryDomainId,
        tenant,
        dataProduct,
        description: { usage: descriptionUsage, purpose: descriptionPurpose, limitations: descriptionLimitations },
        // ODCS v3.2.0 contract-level context block (RFC-0038). Omitted entirely
        // when empty so older-version contracts stay clean.
        context: (contextInstructions.trim() || contextVerifiedStatements.length || contextConstraints.length)
          ? {
              instructions: contextInstructions.trim() || undefined,
              verifiedStatements: contextVerifiedStatements
                .filter((s) => s.question.trim())
                .map((s) => ({ question: s.question.trim(), answer: s.answer.trim() || undefined })),
              constraints: contextConstraints
                .filter((c) => c.trim())
                .map((c) => ({ constraint: c.trim() })),
            }
          : undefined,
        // Phase 4 stakeholder / access / support fields — previously
        // rendered but unwired in the wizard.
        consumers,
        subjectMatterExperts,
        accessControl: { readGroups, writeGroups },
        support: { primaryEmail: primarySupportEmail },
        // Include contract-level semantic assignments as authoritativeDefinitions
        authoritativeDefinitions: convertSemanticConcepts(contractSemanticConcepts),
        schema: schemaObjects.map((o) => ({
          name: o.name,
          physicalName: o.physicalName,
          // ODCS v3.1.0 schema object fields
          businessName: o.businessName,
          physicalType: o.physicalType,
          description: o.description,
          dataGranularityDescription: o.dataGranularityDescription,
          // Include schema-level semantic assignments
          authoritativeDefinitions: convertSemanticConcepts(o.semanticConcepts),
          properties: o.properties.map(p => ({
            ...p,
            // Include property-level semantic assignments
            authoritativeDefinitions: convertSemanticConcepts(p.semanticConcepts)
          }))
        })),
        qualityRules: qualityRules,
        serverConfigs: serverConfigs,
        sla: {
          uptimeTarget: slaRequirements.uptimeTarget,
          maxDowntimeMinutes: slaRequirements.maxDowntimeMinutes,
          queryResponseTimeMs: slaRequirements.queryResponseTimeMs,
          dataFreshnessMinutes: slaRequirements.dataFreshnessMinutes
        },
      }
      await onSubmit(payload)
      // Don't close here - let the parent component handle closing on success
    } catch (error) {
      // Handle domain-specific errors gracefully
      const wasDomainError = await handleDomainError(error)

      if (!wasDomainError) {
        // Generic error handling for non-domain errors
        toast({
          title: t('data-contracts:wizard.toast.saveError.title', 'Save Error'),
          description: t('data-contracts:wizard.toast.saveError.description', 'Failed to save draft. Please try again.'),
          variant: 'destructive' as any
        })
        console.error('Failed to save draft:', error)
      }
    } finally {
      setIsSavingDraft(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="w-[90vw] h-[90vh] max-w-none max-h-none flex flex-col">
        <DialogHeader className="flex-shrink-0 pb-4 border-b">
          <DialogTitle className="text-2xl">
            {name ? t('data-contracts:wizard.titleWithName', 'Data Contract Wizard: {{name}}', { name }) : t('data-contracts:wizard.title', 'Data Contract Wizard')}
          </DialogTitle>
          <DialogDescription className="text-base">{t('data-contracts:wizard.description', 'Build a contract incrementally according to ODCS v3.1.0')}</DialogDescription>

          {/* Progress Indicator */}
          <div className="mt-4">
            <div className="flex items-center justify-between text-sm text-muted-foreground mb-2">
              <span>{t('data-contracts:wizard.progress.step', 'Step {{step}} of {{total}}', { step, total: totalSteps })}</span>
              <span>{t('data-contracts:wizard.progress.percentComplete', '{{percent}}% Complete', { percent: Math.round((step / totalSteps) * 100) })}</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-primary h-2 rounded-full transition-all duration-300 ease-out"
                style={{ width: `${(step / totalSteps) * 100}%` }}
              />
            </div>
            <div className="flex justify-between mt-2 text-xs text-muted-foreground">
              <button
                onClick={() => setStep(1)}
                className={`cursor-pointer hover:text-primary transition-colors ${step === 1 ? 'text-primary font-medium' : ''}`}
              >
                {t('data-contracts:wizard.steps.fundamentals.tab', 'Fundamentals')}
              </button>
              <button
                onClick={() => setStep(2)}
                className={`cursor-pointer hover:text-primary transition-colors ${step === 2 ? 'text-primary font-medium' : ''}`}
              >
                {t('data-contracts:wizard.steps.schema.tab', 'Schema')}
              </button>
              <button
                onClick={() => setStep(3)}
                className={`cursor-pointer hover:text-primary transition-colors ${step === 3 ? 'text-primary font-medium' : ''}`}
              >
                {t('data-contracts:wizard.steps.quality.tab', 'Quality')}
              </button>
              <button
                onClick={() => setStep(4)}
                className={`cursor-pointer hover:text-primary transition-colors ${step === 4 ? 'text-primary font-medium' : ''}`}
              >
                {t('data-contracts:wizard.steps.team.tab', 'Team & Roles')}
              </button>
              <button
                onClick={() => setStep(5)}
                className={`cursor-pointer hover:text-primary transition-colors ${step === 5 ? 'text-primary font-medium' : ''}`}
              >
                {t('data-contracts:wizard.steps.sla.tab', 'SLA & Infrastructure')}
              </button>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-grow overflow-y-auto p-6">
          {/* Step 1: Fundamentals */}
          <div className={step === 1 ? 'block space-y-6' : 'hidden'}>
            <div className="text-lg font-semibold text-foreground mb-4">{t('data-contracts:wizard.steps.fundamentals.title', 'Contract Fundamentals')}</div>

            {/* Basic Information Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div>
                  <Label htmlFor="dc-name" className="text-sm font-medium">{t('data-contracts:wizard.fields.contractName', 'Contract Name *')}</Label>
                  <Input
                    id="dc-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('data-contracts:wizard.fields.contractNamePlaceholder', 'e.g., Customer Data Contract')}
                    className="mt-1"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label htmlFor="dc-version" className="text-sm font-medium">{t('data-contracts:wizard.fields.version', 'Version *')}</Label>
                    <Input
                      id="dc-version"
                      value={version}
                      onChange={(e) => setVersion(e.target.value)}
                      placeholder={t('data-contracts:wizard.fields.versionPlaceholder', 'e.g., v1.0')}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.status', 'Status *')}</Label>
                    <Select value={status} onValueChange={setStatus}>
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder={t('common:placeholders.selectStatus', 'Select status')} />
                      </SelectTrigger>
                      <SelectContent>
                        {statuses.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label htmlFor="dc-owner" className="text-sm font-medium">{t('data-contracts:wizard.fields.contractOwner', 'Contract Owner')}</Label>
                  <div className="mt-1">
                    <PrincipalPicker
                      id="dc-owner"
                      accepts={['user']}
                      value={owner || null}
                      onChange={(next) => setOwner(next ?? '')}
                      placeholder={t('data-contracts:wizard.fields.contractOwnerPlaceholder', 'e.g., data-team@company.com')}
                      aria-label={t('data-contracts:wizard.fields.contractOwner', 'Contract Owner')}
                    />
                  </div>
                </div>
              </div>

              {/* Metadata Panel */}
              <div className="space-y-4">
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.domains', 'Domains')}</Label>
                  <DomainMultiSelector
                    className="mt-1"
                    value={domainIds}
                    primaryDomainId={primaryDomainId}
                    onChange={(nextIds, nextPrimary) => {
                      setDomainIds(nextIds)
                      setPrimaryDomainId(nextPrimary)
                    }}
                    placeholder={t('data-contracts:wizard.fields.domainsPlaceholder', 'Select data domains')}
                  />
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.tenant', 'Tenant')}</Label>
                  <Input
                    placeholder={t('data-contracts:wizard.fields.tenantPlaceholder', 'e.g., production, staging')}
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.dataProduct', 'Data Product')}</Label>
                  <Input
                    placeholder={t('data-contracts:wizard.fields.dataProductPlaceholder', 'Associated data product name')}
                    value={dataProduct}
                    onChange={(e) => setDataProduct(e.target.value)}
                    className="mt-1"
                  />
                </div>
              </div>
            </div>

            {/* Description Section */}
            <div className="border-t pt-6">
              <div className="text-base font-medium mb-4">{t('data-contracts:wizard.steps.fundamentals.descriptionSection', 'Contract Description')}</div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.usage', 'Usage')}</Label>
                  <Textarea
                    value={descriptionUsage}
                    onChange={(e) => setDescriptionUsage(e.target.value)}
                    placeholder={t('data-contracts:wizard.fields.usagePlaceholder', 'Describe how this data should be used...')}
                    className="mt-1 min-h-[100px]"
                  />
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.purpose', 'Purpose')}</Label>
                  <Textarea
                    value={descriptionPurpose}
                    onChange={(e) => setDescriptionPurpose(e.target.value)}
                    placeholder={t('data-contracts:wizard.fields.purposePlaceholder', 'Describe the business purpose and goals...')}
                    className="mt-1 min-h-[100px]"
                  />
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.limitations', 'Limitations')}</Label>
                  <Textarea
                    value={descriptionLimitations}
                    onChange={(e) => setDescriptionLimitations(e.target.value)}
                    placeholder={t('data-contracts:wizard.fields.limitationsPlaceholder', 'Describe any limitations or constraints...')}
                    className="mt-1 min-h-[100px]"
                  />
                </div>
              </div>
            </div>

            {/* ODCS v3.2.0 Context (RFC-0038): AI / semantic guidance */}
            <div className="border-t pt-6 space-y-3">
              <div>
                <Label className="text-sm font-medium">Context — AI / Semantic Guidance</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  ODCS v3.2.0 context: instructions, verified Q&amp;A, and constraints for LLMs and BI tools.
                </p>
              </div>
              <div>
                <Label className="text-xs">Instructions</Label>
                <Textarea
                  value={contextInstructions}
                  onChange={(e) => setContextInstructions(e.target.value)}
                  placeholder="Guidance for consumers / AI agents using this contract..."
                  className="mt-1 min-h-[70px]"
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Verified Statements (Q&amp;A)</Label>
                  <Button type="button" variant="outline" size="sm" className="h-7"
                    onClick={() => setContextVerifiedStatements((p) => [...p, { question: '', answer: '' }])}>
                    Add
                  </Button>
                </div>
                {contextVerifiedStatements.map((s, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-start">
                    <Input value={s.question} placeholder="Question"
                      onChange={(e) => setContextVerifiedStatements((p) => p.map((x, j) => j === i ? { ...x, question: e.target.value } : x))} />
                    <Input value={s.answer} placeholder="Answer"
                      onChange={(e) => setContextVerifiedStatements((p) => p.map((x, j) => j === i ? { ...x, answer: e.target.value } : x))} />
                    <Button type="button" variant="ghost" size="sm" className="h-9"
                      onClick={() => setContextVerifiedStatements((p) => p.filter((_, j) => j !== i))}>
                      Remove
                    </Button>
                  </div>
                ))}
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Constraints</Label>
                  <Button type="button" variant="outline" size="sm" className="h-7"
                    onClick={() => setContextConstraints((p) => [...p, ''])}>
                    Add
                  </Button>
                </div>
                {contextConstraints.map((c, i) => (
                  <div key={i} className="grid grid-cols-[1fr_auto] gap-2 items-start">
                    <Input value={c} placeholder="e.g. Do not join to marketing_events"
                      onChange={(e) => setContextConstraints((p) => p.map((x, j) => j === i ? e.target.value : x))} />
                    <Button type="button" variant="ghost" size="sm" className="h-9"
                      onClick={() => setContextConstraints((p) => p.filter((_, j) => j !== i))}>
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {/* Contract-Level Business Concepts */}
            <div className="border-t pt-6">
              <div className="text-sm text-muted-foreground mb-3">
                {t('data-contracts:wizard.fields.businessConceptsHint', 'Link business concepts to this data contract for better discoverability and context')}
              </div>
              <BusinessConceptsDisplay
                concepts={contractSemanticConcepts}
                onConceptsChange={setContractSemanticConcepts}
                entityType="data_contract"
                entityId={name || 'contract'}
                conceptType="class"
                entityName={name || undefined}
              />
            </div>
          </div>

          {/* Step 2: Schema Definition */}
          <div className={step === 2 ? 'block space-y-4' : 'hidden'}>
            <div className="text-lg font-semibold text-foreground mb-4">{t('data-contracts:wizard.steps.schema.title', 'Data Schema Definition')}</div>

            <div className="flex justify-between items-center p-4 bg-muted/50 rounded-lg">
              <div>
                <div className="font-medium">{t('data-contracts:wizard.steps.schema.subtitle', 'Define your data structure')}</div>
                <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.schema.subtitleHint', 'Add schema objects that represent tables, views, or data assets')}</div>
              </div>
              <div className="flex gap-3">
                <Button type="button" variant="outline" onClick={() => setLookupOpen(true)} className="gap-2">
                  <span>🔍</span> {t('data-contracts:wizard.actions.inferFromAsset', 'Infer from Asset')}
                </Button>
                <Button type="button" variant="default" onClick={addObject} className="gap-2">
                  <span>➕</span> {t('data-contracts:wizard.actions.addSchemaObject', 'Add Schema Object')}
                </Button>
              </div>
            </div>

            {schemaObjects.length === 0 ? (
              <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
                <div className="text-muted-foreground mb-2">{t('data-contracts:wizard.steps.schema.emptyTitle', 'No schema objects defined yet')}</div>
                <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.schema.emptyHint', 'Start by adding a schema object or inferring from an existing asset')}</div>
              </div>
            ) : (
              <div className="space-y-6">
                {schemaObjects.map((obj, objIndex) => (
                  <div key={objIndex} id={`schema-object-${objIndex}`} className="border rounded-lg p-6 bg-card">
                    {/* Object Header */}
                    <div className="flex items-center justify-between mb-4">
                      <div className="text-base font-medium">{t('data-contracts:wizard.steps.schema.objectLabel', 'Schema Object {{index}}', { index: objIndex + 1 })}</div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeObject(objIndex)}
                        className="text-destructive hover:text-destructive"
                      >
                        {t('data-contracts:wizard.actions.removeObject', 'Remove Object')}
                      </Button>
                    </div>

                    {/* Object Names */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.logicalName', 'Logical Name *')}</Label>
                        <Input
                          placeholder={t('data-contracts:wizard.fields.logicalNamePlaceholder', 'e.g., customers, orders')}
                          value={obj.name}
                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, name: e.target.value } : x))}
                          className="mt-1"
                        />
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.physicalName', 'Physical Name (Optional)')}</Label>
                        <Input
                          placeholder={t('data-contracts:wizard.fields.physicalNamePlaceholder', 'e.g., catalog.schema.table_name')}
                          value={obj.physicalName || ''}
                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, physicalName: e.target.value } : x))}
                          className="mt-1"
                        />
                      </div>
                    </div>

                    {/* ODCS v3.1.0 Schema Object Fields */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.businessNameOdcs', 'Business Name (ODCS)')}</Label>
                        <Input
                          placeholder={t('data-contracts:wizard.fields.businessNamePlaceholder', 'Business-friendly name')}
                          value={obj.businessName || ''}
                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, businessName: e.target.value } : x))}
                          className="mt-1"
                        />
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.physicalTypeOdcs', 'Physical Type (ODCS)')}</Label>
                        <Select
                          value={obj.physicalType || 'table'}
                          onValueChange={(v) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, physicalType: v } : x))}
                        >
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('data-contracts:wizard.fields.selectPhysicalType', 'Select physical type')} />
                          </SelectTrigger>
                          <SelectContent>
                            {PHYSICAL_TYPES.map((t) => (
                              <SelectItem key={t} value={t}>{t.replace(/_/g, ' ')}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.schemaDescriptionOdcs', 'Schema Description (ODCS)')}</Label>
                        <Textarea
                          placeholder={t('data-contracts:wizard.fields.schemaDescriptionPlaceholder', 'Describe this schema object...')}
                          value={obj.description || ''}
                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, description: e.target.value } : x))}
                          className="mt-1 min-h-[80px]"
                        />
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.dataGranularityOdcs', 'Data Granularity Description (ODCS)')}</Label>
                        <Textarea
                          placeholder={t('data-contracts:wizard.fields.dataGranularityPlaceholder', 'e.g., One row per customer per day')}
                          value={obj.dataGranularityDescription || ''}
                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, dataGranularityDescription: e.target.value } : x))}
                          className="mt-1 min-h-[80px]"
                        />
                      </div>
                    </div>

                    {/* Schema-Level Business Concepts */}
                    <div className="mb-6">
                      <BusinessConceptsDisplay
                        concepts={obj.semanticConcepts || []}
                        onConceptsChange={(concepts) =>
                          setSchemaObjects((prev) =>
                            prev.map((x, i) => i === objIndex ? { ...x, semanticConcepts: concepts } : x)
                          )
                        }
                        entityType="data_contract_schema"
                        entityId={`${name || 'contract'}#${obj.name}`}
                        conceptType="class"
                        entityName={obj.name || undefined}
                      />
                    </div>

                    {/* Columns Section */}
                    <div className="border-t pt-4">
                      <div className="flex justify-between items-center mb-4">
                        <div className="font-medium text-sm">{t('data-contracts:wizard.fields.columnsCount', 'Columns ({{count}})', { count: obj.properties.length })}</div>
                        <Button type="button" variant="outline" size="sm" onClick={() => addColumn(objIndex)} className="gap-1 h-8 px-2 text-xs">
                          ➕ {t('data-contracts:wizard.actions.addColumn', 'Add Column')}
                        </Button>
                      </div>

                      {obj.properties.length === 0 ? (
                        <div className="text-center py-6 border border-dashed border-muted-foreground/25 rounded">
                          <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.schema.noColumns', 'No columns defined')}</div>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {obj.properties.map((col, colIndex) => (
                            <div key={colIndex} className="space-y-2">
                              <div className="grid grid-cols-1 lg:grid-cols-12 gap-2 p-2 border rounded bg-muted/30">
                                <div className="lg:col-span-3">
                                  <Label className="text-[11px]">{t('data-contracts:wizard.fields.columnName', 'Column Name *')}</Label>
                                  <div className="mt-0.5 flex items-center gap-[3px]">
                                    <span className="text-[11px] text-muted-foreground select-none">#{colIndex + 1}</span>
                                    <Input
                                      placeholder={t('data-contracts:wizard.fields.columnNamePlaceholder', 'column_name')}
                                      value={col.name}
                                      onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, name: e.target.value } : y) } : x))}
                                      className="h-8 text-xs w-full flex-1"
                                    />
                                  </div>
                                </div>
                                <div className="lg:col-span-3">
                                  <Label className="text-[11px]">{t('data-contracts:wizard.fields.physicalTypeShort', 'Physical Type')}</Label>
                                  <Input
                                    placeholder={t('data-contracts:wizard.fields.columnPhysicalTypePlaceholder', 'e.g., VARCHAR(255), BIGINT')}
                                    value={(col as any).physicalType || ''}
                                    onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, physicalType: e.target.value } : y) } : x))}
                                    className="mt-0.5 h-8 text-xs"
                                  />
                                </div>
                                <div className="lg:col-span-3">
                                  <Label className="text-[11px]">{t('data-contracts:wizard.fields.logicalType', 'Logical Type *')}</Label>
                                  <Select value={(col as any).logicalType} onValueChange={(v) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, logicalType: v } : y) } : x))}>
                                    <SelectTrigger className="mt-0.5 h-8 text-xs">
                                      <SelectValue placeholder={t('common:placeholders.selectType', 'Select type')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {LOGICAL_TYPES.map((t) => (
                                        <SelectItem key={t} value={t} className="text-xs h-7">{t}</SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="lg:col-span-2 flex items-end justify-end">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => removeColumn(objIndex, colIndex)}
                                    className="text-destructive hover:text-destructive p-1 h-8"
                                  >
                                    🗑️
                                  </Button>
                                </div>

                                {/* Logical Type Constraints */}
                                {(col as any).logicalType === 'string' && (
                                  <div className="lg:col-span-12 mt-2 p-3 bg-muted/20 rounded border">
                                    <div className="text-[11px] font-medium mb-2">{t('data-contracts:wizard.constraints.string', 'String Constraints')}</div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.minLength', 'Min Length')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="0"
                                          value={(col as any).minLength || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, minLength: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.maxLength', 'Max Length')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="255"
                                          value={(col as any).maxLength || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, maxLength: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.pattern', 'Pattern (Regex)')}</Label>
                                        <Input
                                          placeholder="^[a-zA-Z]+$"
                                          value={(col as any).pattern || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, pattern: e.target.value || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {(col as any).logicalType === 'number' && (
                                  <div className="lg:col-span-12 mt-2 p-3 bg-muted/20 rounded border">
                                    <div className="text-[11px] font-medium mb-2">{t('data-contracts:wizard.constraints.number', 'Number Constraints')}</div>
                                    <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.minimum', 'Minimum')}</Label>
                                        <Input
                                          type="number"
                                          step="any"
                                          placeholder="0"
                                          value={(col as any).minimum || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, minimum: parseFloat(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.maximum', 'Maximum')}</Label>
                                        <Input
                                          type="number"
                                          step="any"
                                          placeholder="100"
                                          value={(col as any).maximum || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, maximum: parseFloat(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.multipleOf', 'Multiple Of')}</Label>
                                        <Input
                                          type="number"
                                          step="any"
                                          placeholder="1"
                                          value={(col as any).multipleOf || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, multipleOf: parseFloat(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.precision', 'Precision')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="2"
                                          value={(col as any).precision || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, precision: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {(col as any).logicalType === 'integer' && (
                                  <div className="lg:col-span-12 mt-2 p-3 bg-muted/20 rounded border">
                                    <div className="text-[11px] font-medium mb-2">{t('data-contracts:wizard.constraints.integer', 'Integer Constraints')}</div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.minimum', 'Minimum')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="0"
                                          value={(col as any).minimum || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, minimum: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.maximum', 'Maximum')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="100"
                                          value={(col as any).maximum || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, maximum: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {(col as any).logicalType === 'date' && (
                                  <div className="lg:col-span-12 mt-2 p-3 bg-muted/20 rounded border">
                                    <div className="text-[11px] font-medium mb-2">{t('data-contracts:wizard.constraints.date', 'Date Constraints')}</div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.format', 'Format')}</Label>
                                        <Select
                                          value={(col as any).format || 'date'}
                                          onValueChange={(v) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, format: v } : y) } : x))}
                                        >
                                          <SelectTrigger className="mt-0.5 h-7 text-xs">
                                            <SelectValue placeholder={t('data-contracts:form.selectFormat', 'Select format')} />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="date" className="text-xs">{t('data-contracts:wizard.constraints.dateFormats.dateYmd', 'YYYY-MM-DD')}</SelectItem>
                                            <SelectItem value="date-time" className="text-xs">{t('data-contracts:wizard.constraints.dateFormats.iso8601', 'ISO 8601')}</SelectItem>
                                            <SelectItem value="time" className="text-xs">{t('data-contracts:wizard.constraints.dateFormats.timeHms', 'HH:MM:SS')}</SelectItem>
                                            <SelectItem value="timestamp" className="text-xs">{t('data-contracts:wizard.constraints.dateFormats.unixTimestamp', 'Unix timestamp')}</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.timezone', 'Timezone')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.constraints.timezonePlaceholder', 'UTC, America/New_York')}
                                          value={(col as any).timezone || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, timezone: e.target.value || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.customFormat', 'Custom Format')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.constraints.customFormatPlaceholder', '%Y-%m-%d %H:%M:%S')}
                                          value={(col as any).customFormat || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, customFormat: e.target.value || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {(col as any).logicalType === 'array' && (
                                  <div className="lg:col-span-12 mt-2 p-3 bg-muted/20 rounded border">
                                    <div className="text-[11px] font-medium mb-2">{t('data-contracts:wizard.constraints.array', 'Array Constraints')}</div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.itemType', 'Item Type')}</Label>
                                        <Select
                                          value={(col as any).itemType || 'string'}
                                          onValueChange={(v) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, itemType: v } : y) } : x))}
                                        >
                                          <SelectTrigger className="mt-0.5 h-7 text-xs">
                                            <SelectValue placeholder={t('data-contracts:wizard.constraints.selectItemType', 'Select item type')} />
                                          </SelectTrigger>
                                          <SelectContent>
                                            {LOGICAL_TYPES.filter(t => t !== 'array').map((t) => (
                                              <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.minItems', 'Min Items')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="0"
                                          value={(col as any).minItems || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, minItems: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-[10px]">{t('data-contracts:wizard.constraints.maxItems', 'Max Items')}</Label>
                                        <Input
                                          type="number"
                                          placeholder="100"
                                          value={(col as any).maxItems || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, maxItems: parseInt(e.target.value) || undefined } : y) } : x))}
                                          className="mt-0.5 h-7 text-xs"
                                        />
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {/* Row 2: Description + Flags */}
                                <div className="lg:col-span-8">
                                  <Label className="text-[11px]">{t('data-contracts:wizard.fields.columnDescription', 'Description')}</Label>
                                  <Input
                                    placeholder={t('data-contracts:wizard.fields.columnDescriptionPlaceholder', 'Column description...')}
                                    value={col.description || ''}
                                    onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, description: e.target.value } : y) } : x))}
                                    className="mt-0.5 h-8 text-xs"
                                  />
                                </div>
                                <div className="lg:col-span-4 flex items-end gap-2">
                                  <label className="flex items-center gap-1 text-[11px]">
                                    <input
                                      type="checkbox"
                                      checked={!!col.required}
                                      onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, required: e.target.checked } : y) } : x))}
                                    />
                                    {t('data-contracts:wizard.fields.required', 'Required')}
                                  </label>
                                  <label className="flex items-center gap-1 text-[11px]">
                                    <input
                                      type="checkbox"
                                      checked={!!col.unique}
                                      onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, unique: e.target.checked } : y) } : x))}
                                    />
                                    {t('data-contracts:wizard.fields.unique', 'Unique')}
                                  </label>
                                  <label className="flex items-center gap-1 text-[11px]">
                                    <input
                                      type="checkbox"
                                      checked={!!col.primaryKey}
                                      onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, primaryKey: e.target.checked, primaryKeyPosition: e.target.checked ? j + 1 : -1 } : y) } : x))}
                                    />
                                    {t('data-contracts:wizard.fields.primaryKey', 'Primary Key')}
                                  </label>
                                </div>

                                {/* Row 3: Advanced */}
                                <div className="lg:col-span-12 col-span-1 pt-1">
                                  <details>
                                    <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">{t('data-contracts:wizard.fields.advanced', 'Advanced')}</summary>
                                    <div className="mt-2 grid grid-cols-1 lg:grid-cols-12 gap-2">
                                      <div className="lg:col-span-3">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.classification', 'Classification')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.classificationPlaceholder', 'confidential, pii, internal')}
                                          value={(col as any).classification || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, classification: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>
                                      <div className="lg:col-span-3">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.partition', 'Partition')}</Label>
                                        <div className="mt-0.5">
                                          <label className="flex items-center gap-1 text-[11px]">
                                            <input
                                              type="checkbox"
                                              checked={!!col.partitioned}
                                              onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, partitioned: e.target.checked, partitionKeyPosition: e.target.checked ? j + 1 : -1 } : y) } : x))}
                                            />
                                            {t('data-contracts:wizard.fields.partitionKey', 'Partition Key')}
                                          </label>
                                        </div>
                                      </div>
                                      <div className="lg:col-span-9">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.examples', 'Examples (comma-separated)')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.examplesPlaceholder', '123, 456, 789')}
                                          value={(col as any).examples || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, examples: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>

                                      {/* ODCS v3.1.0 Property Fields */}
                                      <div className="lg:col-span-4">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.businessNameOdcs', 'Business Name (ODCS)')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.businessNamePlaceholder', 'Business-friendly name')}
                                          value={(col as any).businessName || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, businessName: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>
                                      <div className="lg:col-span-4">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.encryptedNameOdcs', 'Encrypted Name (ODCS)')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.encryptedNamePlaceholder', 'Encrypted field name')}
                                          value={(col as any).encryptedName || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, encryptedName: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>
                                      <div className="lg:col-span-4">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.criticalDataElement', 'Critical Data Element')}</Label>
                                        <div className="mt-0.5">
                                          <label className="flex items-center gap-1 text-[11px]">
                                            <input
                                              type="checkbox"
                                              checked={!!(col as any).criticalDataElement}
                                              onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, criticalDataElement: e.target.checked } : y) } : x))}
                                            />
                                            {t('data-contracts:wizard.fields.isCriticalDataElement', 'Is Critical Data Element')}
                                          </label>
                                        </div>
                                      </div>

                                      <div className="lg:col-span-6">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.transformLogicOdcs', 'Transform Logic (ODCS)')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.transformLogicPlaceholder', 'Transformation SQL or logic')}
                                          value={(col as any).transformLogic || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, transformLogic: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>
                                      <div className="lg:col-span-6">
                                        <Label className="text-[11px]">{t('data-contracts:wizard.fields.transformSourceObjectsOdcs', 'Transform Source Objects (ODCS)')}</Label>
                                        <Input
                                          placeholder={t('data-contracts:wizard.fields.transformSourceObjectsPlaceholder', 'Source table/column references')}
                                          value={(col as any).transformSourceObjects || ''}
                                          onChange={(e) => setSchemaObjects((prev) => prev.map((x, i) => i === objIndex ? { ...x, properties: x.properties.map((y, j) => j === colIndex ? { ...y, transformSourceObjects: e.target.value } : y) } : x))}
                                          className="mt-0.5 h-8 text-xs"
                                        />
                                      </div>

                                      <div className="lg:col-span-12 pt-2">
                                        <div className="mt-0.5">
                                          <BusinessConceptsDisplay
                                            concepts={col.semanticConcepts || []}
                                            onConceptsChange={(concepts) =>
                                              setSchemaObjects((prev) =>
                                                prev.map((x, i) =>
                                                  i === objIndex
                                                    ? {
                                                        ...x,
                                                        properties: x.properties.map((y, j) =>
                                                          j === colIndex ? { ...y, semanticConcepts: concepts } : y
                                                        ),
                                                      }
                                                    : x
                                                )
                                              )
                                            }
                                            entityType="data_contract_property"
                                            entityId={`${name || 'contract'}#${obj.name}#${col.name}`}
                                            conceptType="property"
                                            entityName={col.name || undefined}
                                            entityTypeLabel={col.logicalType || undefined}
                                            parentEntityName={obj.name || undefined}
                                          />
                                        </div>
                                      </div>
                                    </div>
                                  </details>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Step 3: Data Quality */}
          <div className={step === 3 ? 'block space-y-4' : 'hidden'}>
            <div className="text-lg font-semibold text-foreground mb-4">{t('data-contracts:wizard.steps.quality.title', 'Data Quality & Validation')}</div>

            <div className="flex justify-between items-center p-4 bg-muted/50 rounded-lg">
              <div>
                <div className="font-medium">{t('data-contracts:wizard.steps.quality.frameworkTitle', 'ODCS Quality Framework')}</div>
                <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.quality.frameworkHint', 'Define quality rules using ODCS v3.1.0 dimensions and types')}</div>
              </div>
              <Button type="button" variant="default" onClick={addQualityRule} className="gap-2">
                <span>➕</span> {t('data-contracts:wizard.actions.addQualityRule', 'Add Quality Rule')}
              </Button>
            </div>

            {qualityRules.length === 0 ? (
              <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
                <div className="text-muted-foreground mb-2">{t('data-contracts:wizard.steps.quality.emptyTitle', 'No quality rules defined yet')}</div>
                <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.quality.emptyHint', 'Start by adding quality rules to ensure data integrity')}</div>
              </div>
            ) : (
              <div className="space-y-4">
                {qualityRules.map((rule, index) => (
                  <div key={index} className="border rounded-lg p-4 bg-card">
                    <div className="flex items-center justify-between mb-4">
                      <div className="text-base font-medium">{t('data-contracts:wizard.steps.quality.ruleLabel', 'Quality Rule {{index}}', { index: index + 1 })}</div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeQualityRule(index)}
                        className="text-destructive hover:text-destructive"
                      >
                        {t('data-contracts:wizard.actions.removeRule', 'Remove Rule')}
                      </Button>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.ruleName', 'Rule Name *')}</Label>
                        <Input
                          placeholder={t('data-contracts:wizard.fields.ruleNamePlaceholder', 'e.g., Email Format Validation')}
                          value={rule.name}
                          onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, name: e.target.value } : r))}
                          className="mt-1"
                        />
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.qualityDimension', 'Quality Dimension *')}</Label>
                        <Select
                          value={rule.dimension}
                          onValueChange={(v) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, dimension: v } : r))}
                        >
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('data-contracts:wizard.fields.selectDimension', 'Select dimension')} />
                          </SelectTrigger>
                          <SelectContent>
                            {QUALITY_DIMENSIONS.map((dim) => (
                              <SelectItem key={dim} value={dim}>{dim}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.ruleType', 'Rule Type *')}</Label>
                        <Select
                          value={rule.type}
                          onValueChange={(v) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, type: v } : r))}
                        >
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('common:placeholders.selectType', 'Select type')} />
                          </SelectTrigger>
                          <SelectContent>
                            {QUALITY_TYPES.map((type) => (
                              <SelectItem key={type} value={type}>{type}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.severity', 'Severity *')}</Label>
                        <Select
                          value={rule.severity}
                          onValueChange={(v) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, severity: v } : r))}
                        >
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('common:placeholders.selectSeverity', 'Select severity')} />
                          </SelectTrigger>
                          <SelectContent>
                            {QUALITY_SEVERITIES.map((sev) => (
                              <SelectItem key={sev} value={sev}>{sev}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.businessImpact', 'Business Impact *')}</Label>
                        <Select
                          value={rule.businessImpact}
                          onValueChange={(v) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, businessImpact: v } : r))}
                        >
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('data-contracts:wizard.fields.selectImpact', 'Select impact')} />
                          </SelectTrigger>
                          <SelectContent>
                            {BUSINESS_IMPACTS.map((impact) => (
                              <SelectItem key={impact} value={impact}>{impact}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.description', 'Description')}</Label>
                        <Input
                          placeholder={t('data-contracts:wizard.fields.ruleDescriptionPlaceholder', 'Describe the quality rule...')}
                          value={rule.description || ''}
                          onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, description: e.target.value } : r))}
                          className="mt-1"
                        />
                      </div>
                    </div>

                    {rule.type === 'library' && (
                      <div className="mt-4 space-y-3">
                        <div>
                          <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.libraryRule', 'Library Rule *')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.libraryRulePlaceholder', 'e.g., not_null, unique, range_check')}
                            value={rule.rule || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, rule: e.target.value } : r))}
                            className="mt-1"
                          />
                          <div className="text-xs text-muted-foreground mt-1">
                            {t('data-contracts:wizard.fields.libraryRuleHint', 'Library-defined rule name or identifier')}
                          </div>
                        </div>
                      </div>
                    )}

                    {rule.type === 'sql' && (
                      <div className="mt-4 space-y-3">
                        <div>
                          <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.sqlQuery', 'SQL Query *')}</Label>
                          <Textarea
                            placeholder={t('data-contracts:wizard.fields.sqlQueryPlaceholder', 'SELECT COUNT(*) FROM table WHERE condition...')}
                            value={rule.query || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, query: e.target.value } : r))}
                            className="mt-1 min-h-[80px]"
                          />
                          <div className="text-xs text-muted-foreground mt-1">
                            {t('data-contracts:wizard.fields.sqlQueryHint', 'SQL query should return a numeric result for validation')}
                          </div>
                        </div>
                      </div>
                    )}

                    {rule.type === 'custom' && (
                      <div className="mt-4 space-y-3">
                        <div>
                          <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.engine', 'Engine *')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.enginePlaceholder', 'e.g., great_expectations, deequ, pydantic')}
                            value={rule.engine || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, engine: e.target.value } : r))}
                            className="mt-1"
                          />
                          <div className="text-xs text-muted-foreground mt-1">
                            {t('data-contracts:wizard.fields.engineHint', 'Custom quality engine or framework name')}
                          </div>
                        </div>
                        <div>
                          <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.implementation', 'Implementation')}</Label>
                          <Textarea
                            placeholder={t('data-contracts:wizard.fields.implementationPlaceholder', 'Implementation details (JSON config, code, etc.)')}
                            value={rule.implementation || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, implementation: e.target.value } : r))}
                            className="mt-1 min-h-[80px]"
                          />
                          <div className="text-xs text-muted-foreground mt-1">
                            {t('data-contracts:wizard.fields.implementationHint', 'Engine-specific implementation configuration or code')}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Common comparators for all types */}
                    <div className="mt-4">
                      <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.fields.validationCriteria', 'Validation Criteria (Optional)')}</div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.mustBe', 'Must Be')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.mustBePlaceholder', 'Expected value')}
                            value={rule.mustBe || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustBe: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.mustNotBe', 'Must Not Be')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.mustNotBePlaceholder', 'Forbidden value')}
                            value={rule.mustNotBe || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustNotBe: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.mustBeGt', 'Must Be Greater Than')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.mustBeGtPlaceholder', 'Minimum value')}
                            value={rule.mustBeGt || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustBeGt: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.mustBeLt', 'Must Be Less Than')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.mustBeLtPlaceholder', 'Maximum value')}
                            value={rule.mustBeLt || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustBeLt: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.rangeMin', 'Range Min')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.rangeMinPlaceholder', 'Range minimum')}
                            value={rule.mustBeBetweenMin || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustBeBetweenMin: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.rangeMax', 'Range Max')}</Label>
                          <Input
                            placeholder={t('data-contracts:wizard.fields.rangeMaxPlaceholder', 'Range maximum')}
                            value={rule.mustBeBetweenMax || ''}
                            onChange={(e) => setQualityRules((prev) => prev.map((r, i) => i === index ? { ...r, mustBeBetweenMax: e.target.value } : r))}
                            className="mt-1"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Step 4: Team & Roles */}
          <div className={step === 4 ? 'block space-y-6' : 'hidden'}>
            <div className="text-lg font-semibold text-foreground mb-4">{t('data-contracts:wizard.steps.team.title', 'Team & Access Control')}</div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Team Members */}
              <div className="space-y-4">
                <div className="font-medium">{t('data-contracts:wizard.steps.team.teamMembers', 'Team Members')}</div>

                <div className="space-y-3">
                  <div className="p-4 border rounded-lg">
                    <div className="flex items-center justify-between mb-3">
                      <div className="font-medium text-sm">{t('data-contracts:wizard.steps.team.dataStewards', 'Data Stewards')}</div>
                      <Button variant="outline" size="sm">{t('data-contracts:wizard.actions.add', '+ Add')}</Button>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between p-2 bg-muted/30 rounded">
                        <div className="text-sm">{owner || t('data-contracts:wizard.fields.contractOwner', 'Contract Owner')}</div>
                        <div className="text-xs text-muted-foreground">{t('data-contracts:wizard.steps.team.ownerBadge', 'Owner')}</div>
                      </div>
                    </div>
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.team.dataConsumers', 'Data Consumers')}</div>
                    <PrincipalPicker
                      multiple
                      accepts={['user', 'group']}
                      value={consumers}
                      onChange={setConsumers}
                      placeholder={t('data-contracts:wizard.steps.team.consumersPlaceholder', 'consumer-team@company.com')}
                      aria-label={t('data-contracts:wizard.steps.team.dataConsumers', 'Data Consumers')}
                    />
                    <div className="text-xs text-muted-foreground mt-2">
                      {t('data-contracts:wizard.steps.team.consumersHint', 'Stakeholders who will consume this data.')}
                    </div>
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.team.subjectMatterExperts', 'Subject Matter Experts')}</div>
                    <PrincipalPicker
                      multiple
                      accepts={['user']}
                      value={subjectMatterExperts}
                      onChange={setSubjectMatterExperts}
                      placeholder={t('data-contracts:wizard.steps.team.smePlaceholder', 'expert@company.com')}
                      aria-label={t('data-contracts:wizard.steps.team.subjectMatterExperts', 'Subject Matter Experts')}
                    />
                    <div className="text-xs text-muted-foreground mt-2">
                      {t('data-contracts:wizard.steps.team.smeHint', 'Domain experts for business context and validation.')}
                    </div>
                  </div>
                </div>
              </div>

              {/* Access Controls */}
              <div className="space-y-4">
                <div className="font-medium">{t('data-contracts:wizard.steps.team.accessControl', 'Access Control & Permissions')}</div>

                <div className="space-y-3">
                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.team.readAccess', 'Read Access')}</div>
                    <PrincipalPicker
                      multiple
                      accepts={['group']}
                      value={readGroups}
                      onChange={setReadGroups}
                      placeholder={t('data-contracts:wizard.steps.team.readGroupsPlaceholder', 'data-consumers-group')}
                      aria-label={t('data-contracts:wizard.steps.team.readGroupsAria', 'Read access groups')}
                    />
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.team.writeAccess', 'Write Access')}</div>
                    <PrincipalPicker
                      multiple
                      accepts={['group']}
                      value={writeGroups}
                      onChange={setWriteGroups}
                      placeholder={t('data-contracts:wizard.steps.team.writeGroupsPlaceholder', 'data-engineers-group')}
                      aria-label={t('data-contracts:wizard.steps.team.writeGroupsAria', 'Write access groups')}
                    />
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.team.adminAccess', 'Admin Access')}</div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between p-2 bg-muted/30 rounded">
                        <div className="text-sm">{owner || t('data-contracts:wizard.fields.contractOwner', 'Contract Owner')}</div>
                        <div className="text-xs text-muted-foreground">{t('data-contracts:wizard.steps.team.ownerBadge', 'Owner')}</div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="border-t pt-4">
                  <div className="font-medium mb-3">{t('data-contracts:wizard.steps.team.securityClassifications', 'Security Classifications')}</div>
                  <div className="space-y-3">
                    <div>
                      <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.dataClassification', 'Data Classification')}</Label>
                      <Select>
                        <SelectTrigger className="mt-1">
                          <SelectValue placeholder={t('data-contracts:wizard.fields.selectClassification', 'Select classification')} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="public">{t('data-contracts:wizard.classifications.public', 'Public')}</SelectItem>
                          <SelectItem value="internal">{t('data-contracts:wizard.classifications.internal', 'Internal')}</SelectItem>
                          <SelectItem value="confidential">{t('data-contracts:wizard.classifications.confidential', 'Confidential')}</SelectItem>
                          <SelectItem value="restricted">{t('data-contracts:wizard.classifications.restricted', 'Restricted')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-2">
                      <input type="checkbox" className="rounded" />
                      <Label className="text-sm">{t('data-contracts:wizard.steps.team.containsPii', 'Contains PII (Personally Identifiable Information)')}</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input type="checkbox" className="rounded" />
                      <Label className="text-sm">{t('data-contracts:wizard.steps.team.requiresEncryption', 'Requires encryption at rest')}</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input type="checkbox" className="rounded" />
                      <Label className="text-sm">{t('data-contracts:wizard.steps.team.regulatoryCompliance', 'Subject to regulatory compliance (GDPR, HIPAA, etc.)')}</Label>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Support & Communication */}
            <div className="border-t pt-6">
              <div className="font-medium mb-4">{t('data-contracts:wizard.steps.team.supportChannels', 'Support & Communication Channels')}</div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.primarySupportEmail', 'Primary Support Email')}</Label>
                  <div className="mt-1">
                    <PrincipalPicker
                      accepts={['user']}
                      value={primarySupportEmail || null}
                      onChange={(next) => setPrimarySupportEmail(next ?? '')}
                      placeholder={t('data-contracts:wizard.fields.primarySupportEmailPlaceholder', 'data-support@company.com')}
                      aria-label={t('data-contracts:wizard.fields.primarySupportEmail', 'Primary Support Email')}
                    />
                  </div>
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.slackChannel', 'Slack Channel')}</Label>
                  <Input placeholder={t('data-contracts:wizard.fields.slackChannelPlaceholder', '#data-contracts-support')} className="mt-1" />
                </div>
                <div>
                  <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.documentationUrl', 'Documentation URL')}</Label>
                  <Input placeholder={t('data-contracts:wizard.fields.documentationUrlPlaceholder', 'https://company.com/data-docs')} className="mt-1" />
                </div>
              </div>
            </div>
          </div>

          {/* Step 5: SLA & Infrastructure */}
          <div className={step === 5 ? 'block space-y-6' : 'hidden'}>
            <div className="text-lg font-semibold text-foreground mb-4">{t('data-contracts:wizard.steps.sla.title', 'Service Level Agreement & Infrastructure')}</div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* SLA Requirements */}
              <div className="space-y-4">
                <div className="font-medium">{t('data-contracts:wizard.steps.sla.slaSection', 'Service Level Agreement')}</div>

                <div className="space-y-4">
                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.sla.availabilityRequirements', 'Availability Requirements')}</div>
                    <div className="space-y-3">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.uptimeTarget', 'Uptime Target')}</Label>
                        <div className="flex items-center gap-2 mt-1">
                          <Input
                            type="number"
                            placeholder="99.9"
                            className="w-20"
                            value={slaRequirements.uptimeTarget || ''}
                            onChange={(e) => setSlaRequirements(prev => ({ ...prev, uptimeTarget: parseFloat(e.target.value) || 0 }))}
                          />
                          <span className="text-sm text-muted-foreground">{t('data-contracts:wizard.units.percentAvailability', '% availability')}</span>
                        </div>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.maxDowntime', 'Maximum Downtime per Month')}</Label>
                        <div className="flex items-center gap-2 mt-1">
                          <Input
                            type="number"
                            placeholder="43"
                            className="w-20"
                            value={slaRequirements.maxDowntimeMinutes || ''}
                            onChange={(e) => setSlaRequirements(prev => ({ ...prev, maxDowntimeMinutes: parseInt(e.target.value) || 0 }))}
                          />
                          <span className="text-sm text-muted-foreground">{t('data-contracts:wizard.units.minutes', 'minutes')}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.sla.performanceRequirements', 'Performance Requirements')}</div>
                    <div className="space-y-3">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.queryResponseTime', 'Query Response Time (P95)')}</Label>
                        <div className="flex items-center gap-2 mt-1">
                          <Input
                            type="number"
                            placeholder="2"
                            className="w-20"
                            value={slaRequirements.queryResponseTimeMs ? (
                              slaRequirements.queryResponseTimeUnit === 'ms' ? slaRequirements.queryResponseTimeMs :
                              slaRequirements.queryResponseTimeUnit === 'seconds' ? Math.round(slaRequirements.queryResponseTimeMs / 1000) :
                              Math.round(slaRequirements.queryResponseTimeMs / 60000)
                            ) : ''}
                            onChange={(e) => {
                              const value = parseInt(e.target.value) || 0
                              // Convert to milliseconds based on unit
                              let ms = value
                              if (slaRequirements.queryResponseTimeUnit === 'seconds') ms = value * 1000
                              else if (slaRequirements.queryResponseTimeUnit === 'minutes') ms = value * 60000
                              setSlaRequirements(prev => ({ ...prev, queryResponseTimeMs: ms }))
                            }}
                          />
                          <Select
                            value={slaRequirements.queryResponseTimeUnit}
                            onValueChange={(value) => setSlaRequirements(prev => ({ ...prev, queryResponseTimeUnit: value }))}
                          >
                            <SelectTrigger className="w-24">
                              <SelectValue placeholder={t('data-contracts:wizard.units.seconds', 'seconds')} />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="ms">{t('data-contracts:wizard.units.ms', 'ms')}</SelectItem>
                              <SelectItem value="seconds">{t('data-contracts:wizard.units.seconds', 'seconds')}</SelectItem>
                              <SelectItem value="minutes">{t('data-contracts:wizard.units.minutes', 'minutes')}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.dataFreshness', 'Data Freshness')}</Label>
                        <div className="flex items-center gap-2 mt-1">
                          <Input
                            type="number"
                            placeholder="15"
                            className="w-20"
                            value={slaRequirements.dataFreshnessMinutes ? (
                              slaRequirements.dataFreshnessUnit === 'minutes' ? slaRequirements.dataFreshnessMinutes :
                              slaRequirements.dataFreshnessUnit === 'hours' ? Math.round(slaRequirements.dataFreshnessMinutes / 60) :
                              Math.round(slaRequirements.dataFreshnessMinutes / 1440)
                            ) : ''}
                            onChange={(e) => {
                              const value = parseInt(e.target.value) || 0
                              // Convert to minutes based on unit
                              let minutes = value
                              if (slaRequirements.dataFreshnessUnit === 'hours') minutes = value * 60
                              else if (slaRequirements.dataFreshnessUnit === 'days') minutes = value * 1440
                              setSlaRequirements(prev => ({ ...prev, dataFreshnessMinutes: minutes }))
                            }}
                          />
                          <Select
                            value={slaRequirements.dataFreshnessUnit}
                            onValueChange={(value) => setSlaRequirements(prev => ({ ...prev, dataFreshnessUnit: value }))}
                          >
                            <SelectTrigger className="w-24">
                              <SelectValue placeholder={t('data-contracts:wizard.units.minutes', 'minutes')} />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="minutes">{t('data-contracts:wizard.units.minutes', 'minutes')}</SelectItem>
                              <SelectItem value="hours">{t('data-contracts:wizard.units.hours', 'hours')}</SelectItem>
                              <SelectItem value="days">{t('data-contracts:wizard.units.days', 'days')}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.sla.supportResponseTimes', 'Support Response Times')}</div>
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.criticalIssues', 'Critical Issues')}</Label>
                          <div className="flex items-center gap-1 mt-1">
                            <Input type="number" placeholder="2" className="w-16 text-sm" />
                            <span className="text-xs text-muted-foreground">{t('data-contracts:wizard.units.hours', 'hours')}</span>
                          </div>
                        </div>
                        <div>
                          <Label className="text-sm">{t('data-contracts:wizard.fields.standardIssues', 'Standard Issues')}</Label>
                          <div className="flex items-center gap-1 mt-1">
                            <Input type="number" placeholder="24" className="w-16 text-sm" />
                            <span className="text-xs text-muted-foreground">{t('data-contracts:wizard.units.hours', 'hours')}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Infrastructure & Servers */}
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <div className="font-medium">{t('data-contracts:wizard.steps.sla.serverConfig', 'ODCS Server Configuration')}</div>
                  <Button type="button" variant="default" onClick={addServerConfig} className="gap-2">
                    <span>➕</span> {t('data-contracts:wizard.actions.addServer', 'Add Server')}
                  </Button>
                </div>

                {serverConfigs.length === 0 ? (
                  <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
                    <div className="text-muted-foreground mb-2">{t('data-contracts:wizard.steps.sla.emptyServersTitle', 'No servers configured yet')}</div>
                    <div className="text-sm text-muted-foreground">{t('data-contracts:wizard.steps.sla.emptyServersHint', 'Add server configurations to define data sources')}</div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {serverConfigs.map((server, index) => (
                      <div key={index} className="p-4 border rounded-lg">
                        <div className="flex items-center justify-between mb-4">
                          <div className="font-medium text-sm">{t('data-contracts:wizard.steps.sla.serverLabel', 'Server {{index}}', { index: index + 1 })}</div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => removeServerConfig(index)}
                            className="text-destructive hover:text-destructive"
                          >
                            {t('common:actions.remove', 'Remove')}
                          </Button>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                          <div>
                            <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.serverIdentifier', 'Server Identifier *')}</Label>
                            <Input
                              placeholder={t('data-contracts:wizard.fields.serverIdentifierPlaceholder', 'e.g., production-db, analytics-warehouse')}
                              value={server.server}
                              onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, server: e.target.value } : s))}
                              className="mt-1"
                            />
                          </div>
                          <div>
                            <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.serverType', 'Server Type *')}</Label>
                            <Select
                              value={server.type}
                              onValueChange={(v) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, type: v } : s))}
                            >
                              <SelectTrigger className="mt-1">
                                <SelectValue placeholder={t('data-contracts:wizard.fields.selectServerType', 'Select server type')} />
                              </SelectTrigger>
                              <SelectContent>
                                {ODCS_SERVER_TYPES.map((type) => (
                                  <SelectItem key={type} value={type}>{type}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div>
                            <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.environment', 'Environment *')}</Label>
                            <Select
                              value={server.environment}
                              onValueChange={(v) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, environment: v } : s))}
                            >
                              <SelectTrigger className="mt-1">
                                <SelectValue placeholder={t('data-contracts:wizard.fields.selectEnvironment', 'Select environment')} />
                              </SelectTrigger>
                              <SelectContent>
                                {ENVIRONMENTS.map((env) => (
                                  <SelectItem key={env} value={env}>{env}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div>
                            <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.description', 'Description')}</Label>
                            <Input
                              placeholder={t('data-contracts:wizard.fields.serverDescriptionPlaceholder', 'Describe this server...')}
                              value={server.description || ''}
                              onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, description: e.target.value } : s))}
                              className="mt-1"
                            />
                          </div>

                          {/* Common server properties */}
                          {(server.type === 'postgresql' || server.type === 'mysql' || server.type === 'databricks' || server.type === 'snowflake') && (
                            <>
                              <div>
                                <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.host', 'Host')}</Label>
                                <Input
                                  placeholder={t('data-contracts:wizard.fields.hostPlaceholder', 'server.example.com')}
                                  value={server.host || ''}
                                  onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, host: e.target.value } : s))}
                                  className="mt-1"
                                />
                              </div>
                              <div>
                                <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.database', 'Database')}</Label>
                                <Input
                                  placeholder={t('data-contracts:wizard.fields.databasePlaceholder', 'database_name')}
                                  value={server.database || ''}
                                  onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, database: e.target.value } : s))}
                                  className="mt-1"
                                />
                              </div>
                            </>
                          )}

                          {(server.type === 'api') && (
                            <div className="lg:col-span-2">
                              <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.apiLocation', 'API Location')}</Label>
                              <Input
                                placeholder={t('data-contracts:wizard.fields.apiLocationPlaceholder', 'https://api.example.com/v1')}
                                value={server.location || ''}
                                onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, location: e.target.value } : s))}
                                className="mt-1"
                              />
                            </div>
                          )}

                          {(server.type === 's3') && (
                            <div className="lg:col-span-2">
                              <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.s3Location', 'S3 Location')}</Label>
                              <Input
                                placeholder={t('data-contracts:wizard.fields.s3LocationPlaceholder', 's3://bucket-name/path/*.json')}
                                value={server.location || ''}
                                onChange={(e) => setServerConfigs((prev) => prev.map((s, i) => i === index ? { ...s, location: e.target.value } : s))}
                                className="mt-1"
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Additional Infrastructure Settings */}
            <div className="space-y-4">
              <div className="font-medium">{t('data-contracts:wizard.steps.sla.infrastructureManagement', 'Infrastructure Management')}</div>

              <div className="space-y-4">
                <div className="p-4 border rounded-lg">
                  <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.sla.backupRecovery', 'Backup & Recovery')}</div>
                    <div className="space-y-3">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.backupFrequency', 'Backup Frequency')}</Label>
                        <Select>
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('data-contracts:wizard.fields.selectFrequency', 'Select frequency')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="realtime">{t('data-contracts:wizard.frequencies.realtime', 'Real-time')}</SelectItem>
                            <SelectItem value="hourly">{t('data-contracts:wizard.frequencies.hourly', 'Hourly')}</SelectItem>
                            <SelectItem value="daily">{t('data-contracts:wizard.frequencies.daily', 'Daily')}</SelectItem>
                            <SelectItem value="weekly">{t('data-contracts:wizard.frequencies.weekly', 'Weekly')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.retentionPeriod', 'Retention Period')}</Label>
                        <div className="flex items-center gap-2 mt-1">
                          <Input type="number" placeholder="30" className="w-20" />
                          <Select>
                            <SelectTrigger className="w-24">
                              <SelectValue placeholder={t('data-contracts:wizard.units.days', 'days')} />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="days">{t('data-contracts:wizard.units.days', 'days')}</SelectItem>
                              <SelectItem value="months">{t('data-contracts:wizard.units.months', 'months')}</SelectItem>
                              <SelectItem value="years">{t('data-contracts:wizard.units.years', 'years')}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="p-4 border rounded-lg">
                    <div className="font-medium text-sm mb-3">{t('data-contracts:wizard.steps.sla.costPricing', 'Cost & Pricing')}</div>
                    <div className="space-y-3">
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.pricingModel', 'Pricing Model')}</Label>
                        <Select>
                          <SelectTrigger className="mt-1">
                            <SelectValue placeholder={t('data-contracts:wizard.fields.selectPricingModel', 'Select pricing model')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="free">{t('data-contracts:wizard.pricingModels.free', 'Free')}</SelectItem>
                            <SelectItem value="per-query">{t('data-contracts:wizard.pricingModels.perQuery', 'Per Query')}</SelectItem>
                            <SelectItem value="per-user">{t('data-contracts:wizard.pricingModels.perUser', 'Per User')}</SelectItem>
                            <SelectItem value="per-gb">{t('data-contracts:wizard.pricingModels.perGb', 'Per GB')}</SelectItem>
                            <SelectItem value="monthly">{t('data-contracts:wizard.pricingModels.monthly', 'Monthly Subscription')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm font-medium">{t('data-contracts:wizard.fields.costCenter', 'Cost Center / Budget Code')}</Label>
                        <Input placeholder={t('data-contracts:wizard.fields.costCenterPlaceholder', 'DEPT-DATA-001')} className="mt-1" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

        <DialogFooter className="mt-4">
          <div className="flex justify-between w-full">
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={handlePrev} disabled={step === 1}>{t('common:actions.previous', 'Previous')}</Button>
              <Button
                type="button"
                variant="secondary"
                onClick={handleSaveDraft}
                disabled={isSavingDraft || isSubmitting}
                className="flex items-center gap-2"
              >
                {isSavingDraft ? t('common:actions.saving', 'Saving...') : (initial ? t('common:actions.save', 'Save') : t('data-contracts:wizard.actions.saveDraft', 'Save Draft'))}
              </Button>
            </div>
            <div className="flex gap-2">
              {step < totalSteps ? (
                <Button type="button" onClick={handleNext}>{t('common:actions.next', 'Next')}</Button>
              ) : (
                <Button type="button" onClick={handleSubmit} disabled={isSubmitting || isSavingDraft}>{isSubmitting ? t('common:actions.saving', 'Saving...') : t('data-contracts:wizard.actions.saveContract', 'Save Contract')}</Button>
              )}
            </div>
          </div>
        </DialogFooter>

        <InferFromAssetDialog isOpen={lookupOpen} onOpenChange={setLookupOpen} onInfer={handleInferFromAsset} />
      </DialogContent>
    </Dialog>
  )
}


