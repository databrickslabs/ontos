import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Badge } from '@/components/ui/badge';
import { Loader2, Table2 } from 'lucide-react';
import { DATASET_STATUS_LABELS, DATASET_STATUS_COLORS } from '@/types/dataset';
import type { DatasetListItem } from '@/types/dataset';

type LinkDatasetToContractDialogProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName: string;
  onSuccess: () => void;
};

export default function LinkDatasetToContractDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  onSuccess
}: LinkDatasetToContractDialogProps) {
  const { toast } = useToast();
  const { get, post } = useApi();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [datasets, setDatasets] = useState<DatasetListItem[]>([]);
  const [filteredDatasets, setFilteredDatasets] = useState<DatasetListItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchDatasets();
      resetForm();
    }
  }, [isOpen]);

  useEffect(() => {
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      setFilteredDatasets(
        datasets.filter(
          (d) =>
            d.name.toLowerCase().includes(query) ||
            d.description?.toLowerCase().includes(query) ||
            d.owner_team_name?.toLowerCase().includes(query)
        )
      );
    } else {
      setFilteredDatasets(datasets);
    }
  }, [searchQuery, datasets]);

  const resetForm = () => {
    setSelectedDatasetId(null);
    setSearchQuery('');
  };

  const fetchDatasets = async () => {
    setIsLoading(true);
    try {
      const response = await get('/api/datasets');
      if (response.error) throw new Error(response.error);
      
      // Filter to show only datasets without a contract already linked
      const dataArray = Array.isArray(response.data) ? response.data : [];
      const availableDatasets = dataArray.filter(
        (d: DatasetListItem) => !d.contract_id
      );
      setDatasets(availableDatasets);
      setFilteredDatasets(availableDatasets);
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to load datasets',
        variant: 'destructive'
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!selectedDatasetId) {
      toast({
        title: 'Validation Error',
        description: 'Please select a dataset',
        variant: 'destructive'
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await post(`/api/datasets/${selectedDatasetId}/contract/${contractId}`, {});
      
      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: 'Contract Linked',
        description: `Contract "${contractName}" successfully linked to dataset`
      });

      onSuccess();
      onOpenChange(false);
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to link contract to dataset',
        variant: 'destructive'
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedDataset = datasets.find(d => d.id === selectedDatasetId);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>Link Contract to Existing Dataset</DialogTitle>
          <DialogDescription>
            Link <strong>{contractName}</strong> to an existing dataset
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-hidden flex flex-col space-y-4 py-4">
          {/* Search */}
          <div className="space-y-2">
            <Label htmlFor="search">Search Datasets</Label>
            <Input
              id="search"
              placeholder="Search by name, description, or owner..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Dataset List */}
          <div className="flex-1 overflow-y-auto border rounded-lg">
            {isLoading ? (
              <div className="flex items-center justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : filteredDatasets.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-8 text-muted-foreground">
                <Table2 className="h-8 w-8 mb-2 opacity-50" />
                <p>{datasets.length === 0 ? 'No datasets available for linking' : 'No datasets match your search'}</p>
                <p className="text-xs mt-1">Only datasets without an existing contract are shown</p>
              </div>
            ) : (
              <div className="divide-y">
                {filteredDatasets.map((dataset) => (
                  <div
                    key={dataset.id}
                    className={`p-3 cursor-pointer transition-colors ${
                      selectedDatasetId === dataset.id
                        ? 'bg-primary/10 border-l-2 border-l-primary'
                        : 'hover:bg-muted/50'
                    }`}
                    onClick={() => setSelectedDatasetId(dataset.id)}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{dataset.name}</div>
                        {dataset.description && (
                          <p className="text-sm text-muted-foreground line-clamp-1 mt-0.5">
                            {dataset.description}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-1.5">
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
                          {dataset.instance_count !== undefined && dataset.instance_count > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {dataset.instance_count} instance{dataset.instance_count !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>
                      {dataset.owner_team_name && (
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {dataset.owner_team_name}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Selected Dataset Summary */}
          {selectedDataset && (
            <div className="rounded-lg bg-muted p-4 space-y-2">
              <Label className="text-sm font-medium">Selected Dataset</Label>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Table2 className="h-4 w-4 text-primary" />
                  <span className="font-medium">{selectedDataset.name}</span>
                  {selectedDataset.version && (
                    <Badge variant="outline">v{selectedDataset.version}</Badge>
                  )}
                </div>
                {selectedDataset.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {selectedDataset.description}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting || !selectedDatasetId}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Linking...
              </>
            ) : (
              'Link to Dataset'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

