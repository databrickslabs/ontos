import React, { useState } from 'react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, Loader2, FileText } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

interface CreateFromContractDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName: string;
  onSuccess?: (productId: string) => void;
}

const PRODUCT_TYPES = [
  { value: 'source', label: 'Source' },
  { value: 'source-aligned', label: 'Source Aligned' },
  { value: 'aggregate', label: 'Aggregate' },
  { value: 'consumer-aligned', label: 'Consumer Aligned' },
  { value: 'sink', label: 'Sink' },
];

const CreateFromContractDialog: React.FC<CreateFromContractDialogProps> = ({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  onSuccess,
}) => {
  const { post } = useApi();
  const { toast } = useToast();

  const [productName, setProductName] = useState('');
  const [productType, setProductType] = useState<string>('source-aligned');
  const [version, setVersion] = useState('v1.0.0');
  const [outputPortName, setOutputPortName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    // Validation
    if (!productName.trim()) {
      setError('Product name is required');
      return;
    }

    if (!version.trim()) {
      setError('Version is required');
      return;
    }

    if (!productType) {
      setError('Product type is required');
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      const response = await post('/api/data-products/from-contract', {
        contract_id: contractId,
        product_name: productName.trim(),
        product_type: productType,
        version: version.trim(),
        output_port_name: outputPortName.trim() || undefined,
      });

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: 'Product Created',
        description: `Data Product "${productName}" created successfully from contract.`,
      });

      // Call success callback with product ID
      const productData = response.data as { id?: string };
      if (onSuccess && productData?.id) {
        onSuccess(productData.id);
      }

      // Reset form and close dialog
      handleClose();

    } catch (e: any) {
      setError(e.message || 'Failed to create product from contract');
      toast({
        title: 'Error',
        description: e.message || 'Failed to create product from contract',
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setProductName('');
    setProductType('source-aligned');
    setVersion('v1.0.0');
    setOutputPortName('');
    setError(null);
    onOpenChange(false);
  };

  // Reset form when dialog opens
  React.useEffect(() => {
    if (isOpen) {
      setProductName('');
      setProductType('source-aligned');
      setVersion('v1.0.0');
      setOutputPortName('');
      setError(null);
    }
  }, [isOpen]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            Create Data Product from Contract
          </DialogTitle>
          <DialogDescription>
            Create a new Data Product that uses this contract to govern one output port.
            The product will inherit the contract's domain, owner team, and project.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Contract Information */}
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">Contract:</span>
              <span className="font-mono">{contractId}</span>
            </div>
            <div className="text-sm font-medium mt-1">{contractName}</div>
          </div>

          {/* Product Name */}
          <div className="space-y-2">
            <Label htmlFor="product-name" className="text-sm font-medium">
              Product Name *
            </Label>
            <Input
              id="product-name"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="e.g., Customer Analytics Product"
              disabled={submitting}
            />
          </div>

          {/* Product Type */}
          <div className="space-y-2">
            <Label htmlFor="product-type" className="text-sm font-medium">
              Product Type *
            </Label>
            <Select
              value={productType}
              onValueChange={setProductType}
              disabled={submitting}
            >
              <SelectTrigger id="product-type">
                <SelectValue placeholder="Select product type" />
              </SelectTrigger>
              <SelectContent>
                {PRODUCT_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

          {/* Output Port Name (Optional) */}
          <div className="space-y-2">
            <Label htmlFor="output-port-name" className="text-sm font-medium">
              Output Port Name (Optional)
            </Label>
            <Input
              id="output-port-name"
              value={outputPortName}
              onChange={(e) => setOutputPortName(e.target.value)}
              placeholder={`Defaults to: ${contractName}`}
              disabled={submitting}
            />
            <div className="text-xs text-muted-foreground">
              If not specified, the output port will use the contract name
            </div>
          </div>

          {/* Error Alert */}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !productName.trim() || !version.trim()}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? 'Creating...' : 'Create Product'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default CreateFromContractDialog;
