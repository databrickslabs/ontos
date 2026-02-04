import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, Table2, Loader2, Server } from 'lucide-react'
import type { DatasetListItem, DatasetInstance } from '@/types/dataset'
import { DATASET_STATUS_LABELS, DATASET_STATUS_COLORS, DATASET_INSTANCE_ROLE_LABELS, DATASET_INSTANCE_ENVIRONMENT_LABELS } from '@/types/dataset'

interface DatasetInstanceLookupDialogProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (instance: DatasetInstance, dataset: DatasetListItem) => void
  title?: string
  description?: string
}

export default function DatasetInstanceLookupDialog({ 
  isOpen, 
  onOpenChange, 
  onSelect,
  title = 'Select Dataset Instance',
  description = 'Choose a dataset and one of its physical instances'
}: DatasetInstanceLookupDialogProps) {
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Step 1: Dataset list
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  
  // Step 2: Selected dataset and its instances
  const [selectedDataset, setSelectedDataset] = useState<DatasetListItem | null>(null)
  const [instances, setInstances] = useState<DatasetInstance[]>([])
  const [loadingInstances, setLoadingInstances] = useState(false)

  const fetchDatasets = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch('/api/datasets')
      if (!res.ok) throw new Error('Failed to load datasets')
      const data = await res.json()
      setDatasets(Array.isArray(data) ? data : [])
    } catch (e) {
      setError('Failed to load datasets')
      setDatasets([])
    } finally {
      setLoading(false)
    }
  }

  const fetchInstances = async (datasetId: string) => {
    try {
      setLoadingInstances(true)
      setError(null)
      const res = await fetch(`/api/datasets/${datasetId}/instances`)
      if (!res.ok) throw new Error('Failed to load instances')
      const data = await res.json()
      setInstances(Array.isArray(data.instances) ? data.instances : [])
    } catch (e) {
      setError('Failed to load dataset instances')
      setInstances([])
    } finally {
      setLoadingInstances(false)
    }
  }

  const handleDatasetSelect = async (dataset: DatasetListItem) => {
    setSelectedDataset(dataset)
    await fetchInstances(dataset.id)
  }

  const handleInstanceSelect = (instance: DatasetInstance) => {
    if (selectedDataset) {
      onSelect(instance, selectedDataset)
      onOpenChange(false)
    }
  }

  const handleBack = () => {
    setSelectedDataset(null)
    setInstances([])
    setSearch('')
  }

  const handleClose = () => {
    setSelectedDataset(null)
    setInstances([])
    setSearch('')
    onOpenChange(false)
  }

  useEffect(() => {
    if (isOpen) {
      fetchDatasets()
      setSelectedDataset(null)
      setInstances([])
      setSearch('')
    }
  }, [isOpen])

  // Filter datasets by search term
  const filteredDatasets = datasets.filter((d) => {
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return (
      d.name.toLowerCase().includes(q) ||
      d.description?.toLowerCase().includes(q) ||
      d.owner_team_name?.toLowerCase().includes(q)
    )
  })

  // Filter instances by search term
  const filteredInstances = instances.filter((i) => {
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return (
      i.physical_path.toLowerCase().includes(q) ||
      i.display_name?.toLowerCase().includes(q) ||
      i.role?.toLowerCase().includes(q)
    )
  })

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl w-full">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {selectedDataset && (
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-6 w-6 p-0 mr-1" 
                onClick={handleBack}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
            )}
            {selectedDataset ? `Select Instance from ${selectedDataset.name}` : title}
          </DialogTitle>
          <DialogDescription>
            {selectedDataset 
              ? `This dataset has ${instances.length} instance${instances.length !== 1 ? 's' : ''}. Select one to use for schema inference.`
              : description
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Input 
            className="h-8 text-sm" 
            placeholder={selectedDataset ? "Filter instances..." : "Filter datasets..."} 
            value={search} 
            onChange={(e) => setSearch(e.target.value)} 
          />
          
          {error && <div className="text-sm text-destructive">{error}</div>}
          
          <div className="h-80 overflow-y-auto border rounded">
            {loading || loadingInstances ? (
              <div className="flex justify-center items-center h-full">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : selectedDataset ? (
              // Step 2: Show instances
              filteredInstances.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                  <Server className="h-8 w-8 mb-2 opacity-50" />
                  <p>No instances found for this dataset</p>
                  <p className="text-sm">Add instances to the dataset first</p>
                </div>
              ) : (
                <div className="p-2 space-y-2">
                  {filteredInstances.map((instance) => (
                    <div
                      key={instance.id}
                      className="p-3 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => handleInstanceSelect(instance)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="font-mono text-sm font-medium truncate">
                            {instance.physical_path}
                          </div>
                          {instance.display_name && (
                            <div className="text-sm text-muted-foreground mt-0.5">
                              {instance.display_name}
                            </div>
                          )}
                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            <Badge variant="outline" className="text-xs">
                              {DATASET_INSTANCE_ROLE_LABELS[instance.role] || instance.role}
                            </Badge>
                            {instance.environment && (
                              <Badge variant="secondary" className="text-xs">
                                {DATASET_INSTANCE_ENVIRONMENT_LABELS[instance.environment] || instance.environment}
                              </Badge>
                            )}
                            <Badge 
                              variant="secondary" 
                              className={`text-xs ${instance.status === 'active' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' : ''}`}
                            >
                              {instance.status}
                            </Badge>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : (
              // Step 1: Show datasets
              filteredDatasets.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                  <Table2 className="h-8 w-8 mb-2 opacity-50" />
                  <p>No datasets found</p>
                </div>
              ) : (
                <div className="p-2 space-y-2">
                  {filteredDatasets.map((dataset) => (
                    <div
                      key={dataset.id}
                      className="p-3 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => handleDatasetSelect(dataset)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium">{dataset.name}</div>
                          {dataset.description && (
                            <p className="text-sm text-muted-foreground mt-0.5 line-clamp-1">
                              {dataset.description}
                            </p>
                          )}
                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            {dataset.version && (
                              <Badge variant="outline" className="text-xs">
                                v{dataset.version}
                              </Badge>
                            )}
                            <Badge 
                              variant="secondary" 
                              className={`text-xs ${DATASET_STATUS_COLORS[dataset.status] || ''}`}
                            >
                              {DATASET_STATUS_LABELS[dataset.status] || dataset.status}
                            </Badge>
                            {dataset.instance_count !== undefined && (
                              <span className="text-xs text-muted-foreground">
                                {dataset.instance_count} instance{dataset.instance_count !== 1 ? 's' : ''}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleClose}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

