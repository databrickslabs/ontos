import React, { useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { AlertCircle, Loader2, FileText, Table2, Server, ChevronRight } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useApi } from '@/hooks/use-api'
import type { DatasetListItem, DatasetInstance } from '@/types/dataset'
import { DATASET_STATUS_LABELS, DATASET_STATUS_COLORS, DATASET_INSTANCE_ROLE_LABELS, DATASET_INSTANCE_ENVIRONMENT_LABELS } from '@/types/dataset'

interface CreateContractFromDatasetDialogProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  dataset?: DatasetListItem // Pre-selected dataset (optional)
  onSuccess?: (contractId: string, datasetId: string) => void
}

const CreateContractFromDatasetDialog: React.FC<CreateContractFromDatasetDialogProps> = ({
  isOpen,
  onOpenChange,
  dataset: preSelectedDataset,
  onSuccess,
}) => {
  const { post, get } = useApi()
  const { toast } = useToast()

  // Step state
  const [step, setStep] = useState<'dataset' | 'instance' | 'form'>('dataset')
  
  // Dataset selection
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [selectedDataset, setSelectedDataset] = useState<DatasetListItem | null>(null)
  const [datasetSearch, setDatasetSearch] = useState('')
  
  // Instance selection
  const [instances, setInstances] = useState<DatasetInstance[]>([])
  const [loadingInstances, setLoadingInstances] = useState(false)
  const [selectedInstance, setSelectedInstance] = useState<DatasetInstance | null>(null)
  const [instanceSearch, setInstanceSearch] = useState('')
  
  // Form state
  const [contractName, setContractName] = useState('')
  const [version, setVersion] = useState('v1.0.0')
  const [inferSchema, setInferSchema] = useState(true)
  const [linkToDataset, setLinkToDataset] = useState(true)
  
  // Domains for selection
  const [domains, setDomains] = useState<{ id: string; name: string }[]>([])
  const [selectedDomain, setSelectedDomain] = useState<string>('')
  
  // Submission state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch datasets
  const fetchDatasets = async () => {
    setLoadingDatasets(true)
    try {
      const response = await get('/api/datasets')
      setDatasets(Array.isArray(response.data) ? response.data : [])
    } catch (e) {
      console.error('Failed to fetch datasets:', e)
      setDatasets([])
    } finally {
      setLoadingDatasets(false)
    }
  }

  // Fetch instances for a dataset
  const fetchInstances = async (datasetId: string) => {
    setLoadingInstances(true)
    try {
      const response = await get<{ instances?: DatasetInstance[] }>(`/api/datasets/${datasetId}/instances`)
      const data = response.data as { instances?: DatasetInstance[] } | undefined
      setInstances(Array.isArray(data?.instances) ? data.instances : [])
    } catch (e) {
      console.error('Failed to fetch instances:', e)
      setInstances([])
    } finally {
      setLoadingInstances(false)
    }
  }

  // Fetch domains
  const fetchDomains = async () => {
    try {
      const response = await get('/api/domains')
      setDomains(Array.isArray(response) ? response.map((d: any) => ({ id: d.id, name: d.name })) : [])
    } catch (e) {
      console.error('Failed to fetch domains:', e)
      setDomains([])
    }
  }

  // Handle dataset selection
  const handleDatasetSelect = async (dataset: DatasetListItem) => {
    setSelectedDataset(dataset)
    setContractName(dataset.name + ' Contract')
    await fetchInstances(dataset.id)
    setStep('instance')
  }

  // Handle instance selection (optional)
  const handleInstanceSelect = (instance: DatasetInstance | null) => {
    setSelectedInstance(instance)
    setStep('form')
  }

  // Skip instance selection
  const handleSkipInstance = () => {
    setSelectedInstance(null)
    setInferSchema(false)
    setStep('form')
  }

  // Handle form submission
  const handleSubmit = async () => {
    if (!selectedDataset) {
      setError('Please select a dataset')
      return
    }

    if (!contractName.trim()) {
      setError('Contract name is required')
      return
    }

    if (!version.trim()) {
      setError('Version is required')
      return
    }

    setError(null)
    setSubmitting(true)

    try {
      // Build contract payload
      const contractPayload: any = {
        name: contractName.trim(),
        version: version.trim(),
        status: 'draft',
        domain: selectedDomain || undefined,
        owner_team_id: selectedDataset.owner_team_id || undefined,
        project_id: selectedDataset.project_id || undefined,
      }

      // If inferring schema from instance, fetch the schema first
      if (inferSchema && selectedInstance?.physical_path) {
        try {
          interface SchemaResponseData {
            schema?: any[];
            table_info?: { comment?: string; table_type?: string };
          }
          const schemaResponse = await get<SchemaResponseData>(`/api/catalogs/dataset/${encodeURIComponent(selectedInstance.physical_path)}`)
          const schemaData = schemaResponse.data as SchemaResponseData | undefined
          if (schemaData?.schema) {
            const properties = Array.isArray(schemaData.schema)
              ? schemaData.schema.map((c: any) => ({
                  name: String(c.name || ''),
                  physicalType: String(c.physicalType || c.type || ''),
                  logicalType: String(c.logicalType || c.logical_type || 'string'),
                  required: c.nullable === undefined ? undefined : !Boolean(c.nullable),
                  description: String(c.comment || ''),
                  partitioned: Boolean(c.partitioned),
                  partitionKeyPosition: c.partitionKeyPosition || undefined,
                }))
              : []
            
            const logicalName = selectedInstance.physical_path.split('.').pop() || selectedInstance.physical_path
            contractPayload.schema = [{
              name: logicalName,
              physicalName: selectedInstance.physical_path,
              properties: properties,
              description: schemaData.table_info?.comment || undefined,
              physicalType: schemaData.table_info?.table_type || 'table',
            }]
          }
        } catch (schemaError) {
          console.warn('Failed to infer schema, creating contract without schema:', schemaError)
          toast({
            title: 'Schema Inference Warning',
            description: 'Could not infer schema from the dataset. Contract will be created without a schema.',
            variant: 'default',
          })
        }
      }

      // Create the contract
      const createResponse = await post<{ id?: string }>('/api/data-contracts', contractPayload)
      
      if (createResponse.error) {
        throw new Error(createResponse.error)
      }

      const createData = createResponse.data as { id?: string } | undefined
      const contractId = createData?.id

      // Link the contract to the dataset if requested
      if (linkToDataset && contractId) {
        const linkResponse = await post(`/api/datasets/${selectedDataset.id}/contract/${contractId}`, {})
        if (linkResponse.error) {
          console.warn('Failed to link contract to dataset:', linkResponse.error)
          toast({
            title: 'Warning',
            description: 'Contract created but failed to link to dataset. You can link it manually later.',
            variant: 'default',
          })
        }
      }

      toast({
        title: 'Contract Created',
        description: `Data Contract "${contractName}" created successfully${linkToDataset ? ' and linked to dataset' : ''}.`,
      })

      if (onSuccess && contractId) {
        onSuccess(contractId, selectedDataset.id)
      }

      handleClose()

    } catch (e: any) {
      setError(e.message || 'Failed to create contract')
      toast({
        title: 'Error',
        description: e.message || 'Failed to create contract',
        variant: 'destructive',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle dialog close
  const handleClose = () => {
    setStep('dataset')
    setSelectedDataset(null)
    setSelectedInstance(null)
    setContractName('')
    setVersion('v1.0.0')
    setSelectedDomain('')
    setInferSchema(true)
    setLinkToDataset(true)
    setDatasetSearch('')
    setInstanceSearch('')
    setError(null)
    onOpenChange(false)
  }

  // Handle back navigation
  const handleBack = () => {
    if (step === 'form') {
      setStep('instance')
    } else if (step === 'instance') {
      setStep('dataset')
      setSelectedDataset(null)
      setInstances([])
    }
  }

  // Initialize dialog
  useEffect(() => {
    if (isOpen) {
      fetchDomains()
      
      if (preSelectedDataset) {
        // Skip dataset selection step
        setSelectedDataset(preSelectedDataset)
        setContractName(preSelectedDataset.name + ' Contract')
        fetchInstances(preSelectedDataset.id)
        setStep('instance')
      } else {
        fetchDatasets()
        setStep('dataset')
      }
    }
  }, [isOpen, preSelectedDataset])

  // Filter datasets
  const filteredDatasets = datasets.filter((d) => {
    if (!datasetSearch.trim()) return true
    const q = datasetSearch.trim().toLowerCase()
    return (
      d.name.toLowerCase().includes(q) ||
      d.description?.toLowerCase().includes(q)
    )
  })

  // Filter instances
  const filteredInstances = instances.filter((i) => {
    if (!instanceSearch.trim()) return true
    const q = instanceSearch.trim().toLowerCase()
    return (
      i.physical_path.toLowerCase().includes(q) ||
      i.display_name?.toLowerCase().includes(q)
    )
  })

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            Create Data Contract from Dataset
          </DialogTitle>
          <DialogDescription>
            {step === 'dataset' && 'Select a dataset to create a contract from'}
            {step === 'instance' && 'Optionally select an instance to infer the schema'}
            {step === 'form' && 'Configure the new data contract'}
          </DialogDescription>
        </DialogHeader>

        {/* Step indicator */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
          <span className={step === 'dataset' ? 'text-primary font-medium' : ''}>Dataset</span>
          <ChevronRight className="h-4 w-4" />
          <span className={step === 'instance' ? 'text-primary font-medium' : ''}>Instance</span>
          <ChevronRight className="h-4 w-4" />
          <span className={step === 'form' ? 'text-primary font-medium' : ''}>Details</span>
        </div>

        <div className="space-y-4">
          {/* Step 1: Dataset Selection */}
          {step === 'dataset' && (
            <>
              <Input
                placeholder="Search datasets..."
                value={datasetSearch}
                onChange={(e) => setDatasetSearch(e.target.value)}
                className="h-8"
              />
              <div className="h-72 overflow-y-auto border rounded">
                {loadingDatasets ? (
                  <div className="flex justify-center items-center h-full">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  </div>
                ) : filteredDatasets.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                    <Table2 className="h-8 w-8 mb-2 opacity-50" />
                    <p>No datasets found</p>
                  </div>
                ) : (
                  <div className="p-2 space-y-2">
                    {filteredDatasets.map((ds) => (
                      <div
                        key={ds.id}
                        className="p-3 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                        onClick={() => handleDatasetSelect(ds)}
                      >
                        <div className="font-medium">{ds.name}</div>
                        {ds.description && (
                          <p className="text-sm text-muted-foreground line-clamp-1 mt-0.5">
                            {ds.description}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-2">
                          <Badge variant="secondary" className={`text-xs ${DATASET_STATUS_COLORS[ds.status] || ''}`}>
                            {DATASET_STATUS_LABELS[ds.status] || ds.status}
                          </Badge>
                          {ds.instance_count !== undefined && (
                            <span className="text-xs text-muted-foreground">
                              {ds.instance_count} instance{ds.instance_count !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {/* Step 2: Instance Selection */}
          {step === 'instance' && selectedDataset && (
            <>
              <div className="p-3 bg-muted/50 rounded-lg border">
                <div className="flex items-center gap-2 text-sm">
                  <Table2 className="h-4 w-4 text-primary" />
                  <span className="font-medium">{selectedDataset.name}</span>
                </div>
              </div>
              
              <Input
                placeholder="Search instances..."
                value={instanceSearch}
                onChange={(e) => setInstanceSearch(e.target.value)}
                className="h-8"
              />
              
              <div className="h-56 overflow-y-auto border rounded">
                {loadingInstances ? (
                  <div className="flex justify-center items-center h-full">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  </div>
                ) : filteredInstances.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
                    <Server className="h-8 w-8 mb-2 opacity-50" />
                    <p>No instances found</p>
                    <p className="text-sm text-center mt-1">
                      You can skip this step and create a contract without a pre-defined schema
                    </p>
                  </div>
                ) : (
                  <div className="p-2 space-y-2">
                    {filteredInstances.map((inst) => (
                      <div
                        key={inst.id}
                        className="p-3 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                        onClick={() => handleInstanceSelect(inst)}
                      >
                        <div className="font-mono text-sm">{inst.physical_path}</div>
                        {inst.display_name && (
                          <div className="text-sm text-muted-foreground mt-0.5">
                            {inst.display_name}
                          </div>
                        )}
                        <div className="flex items-center gap-2 mt-2">
                          <Badge variant="outline" className="text-xs">
                            {DATASET_INSTANCE_ROLE_LABELS[inst.role] || inst.role}
                          </Badge>
                          {inst.environment && (
                            <Badge variant="secondary" className="text-xs">
                              {DATASET_INSTANCE_ENVIRONMENT_LABELS[inst.environment] || inst.environment}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              
              <Button 
                variant="outline" 
                onClick={handleSkipInstance}
                className="w-full"
              >
                Skip - Create without schema
              </Button>
            </>
          )}

          {/* Step 3: Contract Form */}
          {step === 'form' && selectedDataset && (
            <>
              {/* Selected Dataset & Instance Summary */}
              <div className="p-3 bg-muted/50 rounded-lg border space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <Table2 className="h-4 w-4 text-primary" />
                  <span className="font-medium">Dataset:</span>
                  <span>{selectedDataset.name}</span>
                </div>
                {selectedInstance && (
                  <div className="flex items-center gap-2 text-sm">
                    <Server className="h-4 w-4 text-primary" />
                    <span className="font-medium">Instance:</span>
                    <span className="font-mono text-xs">{selectedInstance.physical_path}</span>
                  </div>
                )}
              </div>

              {/* Contract Name */}
              <div className="space-y-2">
                <Label htmlFor="contract-name" className="text-sm font-medium">
                  Contract Name *
                </Label>
                <Input
                  id="contract-name"
                  value={contractName}
                  onChange={(e) => setContractName(e.target.value)}
                  placeholder="e.g., Customer Data Contract"
                  disabled={submitting}
                />
              </div>

              {/* Version */}
              <div className="space-y-2">
                <Label htmlFor="version" className="text-sm font-medium">
                  Version *
                </Label>
                <Input
                  id="version"
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  placeholder="e.g., v1.0.0"
                  disabled={submitting}
                />
              </div>

              {/* Domain */}
              {domains.length > 0 && (
                <div className="space-y-2">
                  <Label htmlFor="domain" className="text-sm font-medium">
                    Domain (Optional)
                  </Label>
                  <Select
                    value={selectedDomain || "_none"}
                    onValueChange={(v) => setSelectedDomain(v === "_none" ? "" : v)}
                    disabled={submitting}
                  >
                    <SelectTrigger id="domain">
                      <SelectValue placeholder="Select a domain" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="_none">No domain</SelectItem>
                      {domains.map((domain) => (
                        <SelectItem key={domain.id} value={domain.id}>
                          {domain.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Options */}
              <div className="space-y-3 pt-2">
                {selectedInstance && (
                  <div className="flex items-center space-x-2">
                    <Checkbox
                      id="infer-schema"
                      checked={inferSchema}
                      onCheckedChange={(checked) => setInferSchema(checked as boolean)}
                      disabled={submitting}
                    />
                    <Label htmlFor="infer-schema" className="text-sm cursor-pointer">
                      Infer schema from selected instance
                    </Label>
                  </div>
                )}
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="link-dataset"
                    checked={linkToDataset}
                    onCheckedChange={(checked) => setLinkToDataset(checked as boolean)}
                    disabled={submitting}
                  />
                  <Label htmlFor="link-dataset" className="text-sm cursor-pointer">
                    Link contract back to the dataset
                  </Label>
                </div>
              </div>

              {/* Error Alert */}
              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
            </>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          {step !== 'dataset' && !preSelectedDataset && (
            <Button variant="ghost" onClick={handleBack} disabled={submitting}>
              Back
            </Button>
          )}
          <Button variant="outline" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          {step === 'form' && (
            <Button
              onClick={handleSubmit}
              disabled={submitting || !contractName.trim() || !version.trim()}
            >
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {submitting ? 'Creating...' : 'Create Contract'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default CreateContractFromDatasetDialog

