import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { useToast } from '@/hooks/use-toast';
import { Badge } from '@/components/ui/badge';
import { Loader2 } from 'lucide-react';
import type { DataProduct, OutputPort } from '@/types/data-product';

type LinkProductToContractDialogProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName: string;
  onSuccess: () => void;
};

export default function LinkProductToContractDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  onSuccess
}: LinkProductToContractDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingProducts, setIsLoadingProducts] = useState(false);
  const [products, setProducts] = useState<DataProduct[]>([]);
  const [selectedProductId, setSelectedProductId] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<DataProduct | null>(null);
  const [assignmentMode, setAssignmentMode] = useState<'existing' | 'new'>('existing');
  const [selectedPortIndex, setSelectedPortIndex] = useState<string>('');
  const [newPortName, setNewPortName] = useState('');
  const [newPortVersion, setNewPortVersion] = useState('1.0.0');

  const availablePorts = selectedProduct?.outputPorts?.filter(port => !port.contractId) || [];

  useEffect(() => {
    if (isOpen) {
      fetchProducts();
      resetForm();
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedProductId) {
      fetchProductDetails(selectedProductId);
    } else {
      setSelectedProduct(null);
    }
  }, [selectedProductId]);

  const resetForm = () => {
    setSelectedProductId('');
    setSelectedProduct(null);
    setAssignmentMode('existing');
    setSelectedPortIndex('');
    setNewPortName('');
    setNewPortVersion('1.0.0');
  };

  const fetchProducts = async () => {
    setIsLoadingProducts(true);
    try {
      const response = await fetch('/api/data-products');
      if (!response.ok) throw new Error('Failed to fetch products');

      const data: DataProduct[] = await response.json();
      setProducts(data);
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:linkProduct.loadProductsError', 'Failed to load products'),
        variant: 'destructive'
      });
    } finally {
      setIsLoadingProducts(false);
    }
  };

  const fetchProductDetails = async (productId: string) => {
    try {
      const response = await fetch(`/api/data-products/${productId}`);
      if (!response.ok) throw new Error('Failed to fetch product details');

      const data: DataProduct = await response.json();
      setSelectedProduct(data);

      // Reset port selection when product changes
      setSelectedPortIndex('');

      // Auto-select mode based on available ports
      if (data.outputPorts && data.outputPorts.some(p => !p.contractId)) {
        setAssignmentMode('existing');
      } else {
        setAssignmentMode('new');
      }
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:linkProduct.loadDetailsError', 'Failed to load product details'),
        variant: 'destructive'
      });
    }
  };

  const handleSubmit = async () => {
    if (!selectedProductId || !selectedProduct) {
      toast({
        title: t('data-contracts:linkProduct.validationError', 'Validation Error'),
        description: t('data-contracts:linkProduct.selectProductError', 'Please select a product'),
        variant: 'destructive'
      });
      return;
    }

    if (assignmentMode === 'existing' && selectedPortIndex === '') {
      toast({
        title: t('data-contracts:linkProduct.validationError', 'Validation Error'),
        description: t('data-contracts:linkProduct.selectDeliverableError', 'Please select a deliverable'),
        variant: 'destructive'
      });
      return;
    }

    if (assignmentMode === 'new') {
      if (!newPortName.trim()) {
        toast({
          title: t('data-contracts:linkProduct.validationError', 'Validation Error'),
          description: t('data-contracts:linkProduct.portNameRequired', 'Port name is required'),
          variant: 'destructive'
        });
        return;
      }
      if (!newPortVersion.trim()) {
        toast({
          title: t('data-contracts:linkProduct.validationError', 'Validation Error'),
          description: t('data-contracts:linkProduct.portVersionRequired', 'Port version is required'),
          variant: 'destructive'
        });
        return;
      }
    }

    setIsSubmitting(true);
    try {
      let updatedPorts: OutputPort[];

      if (assignmentMode === 'existing') {
        // Update existing port
        const portIdx = parseInt(selectedPortIndex);
        updatedPorts = [...(selectedProduct.outputPorts || [])];
        updatedPorts[portIdx] = {
          ...updatedPorts[portIdx],
          contractId: contractId
        };
      } else {
        // Create new port with contract
        const newPort: OutputPort = {
          name: newPortName.trim(),
          version: newPortVersion.trim(),
          contractId: contractId
        };
        updatedPorts = [...(selectedProduct.outputPorts || []), newPort];
      }

      // Normalize tags to FQN strings or tag_id objects for backend compatibility
      const normalizedTags = selectedProduct.tags?.map((tag: any) =>
        typeof tag === 'string' ? tag : (tag.fully_qualified_name || { tag_id: tag.tag_id, assigned_value: tag.assigned_value })
      );

      // Update product
      const updateResponse = await fetch(`/api/data-products/${selectedProductId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...selectedProduct,
          tags: normalizedTags,
          outputPorts: updatedPorts
        })
      });

      if (!updateResponse.ok) throw new Error('Failed to link contract to product');

      toast({
        title: t('data-contracts:linkProduct.contractLinked', 'Contract Linked'),
        description: t('data-contracts:linkProduct.linkSuccess', 'Contract "{{contractName}}" successfully linked to product deliverable', { contractName })
      });

      onSuccess();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:linkProduct.linkError', 'Failed to link contract to product'),
        variant: 'destructive'
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('data-contracts:linkProduct.title', 'Link Contract to Existing Product')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:linkProduct.descriptionBefore', 'Link')} <strong>{contractName}</strong> {t('data-contracts:linkProduct.descriptionAfter', 'to a deliverable of an existing data product')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Product Selection */}
          <div className="space-y-2">
            <Label htmlFor="product">
              {t('data-contracts:linkProduct.selectProductLabel', 'Select Product')} <span className="text-destructive">*</span>
            </Label>
            {isLoadingProducts ? (
              <div className="flex items-center justify-center p-4">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : (
              <Select value={selectedProductId} onValueChange={setSelectedProductId}>
                <SelectTrigger id="product">
                  <SelectValue placeholder={t('data-contracts:linkProduct.chooseProductPlaceholder', 'Choose a product...')} />
                </SelectTrigger>
                <SelectContent>
                  {products.length === 0 ? (
                    <div className="p-2 text-sm text-muted-foreground text-center">
                      {t('data-contracts:linkProduct.noProducts', 'No products available')}
                    </div>
                  ) : (
                    products.map((product) => (
                      <SelectItem key={product.id} value={product.id}>
                        <div className="flex items-center gap-2">
                          <span>{product.name || t('data-contracts:linkProduct.unnamedProduct', 'Unnamed Product')}</span>
                          <Badge variant="secondary" className="text-xs">v{product.version || t('common:states.notAvailable')}</Badge>
                          <Badge variant="outline" className="text-xs">{product.status}</Badge>
                        </div>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            )}
          </div>

          {/* Port Assignment Section - only show after product selected */}
          {selectedProduct && (
            <>
              <div className="border-t pt-4 space-y-4">
                <Label>{t('data-contracts:linkProduct.deliverableAssignment', 'Deliverable Assignment')}</Label>

                <RadioGroup value={assignmentMode} onValueChange={(value: 'existing' | 'new') => setAssignmentMode(value)}>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="existing" id="existing" disabled={availablePorts.length === 0} />
                    <Label htmlFor="existing" className={availablePorts.length === 0 ? 'text-muted-foreground' : ''}>
                      {t('data-contracts:linkProduct.assignExisting', 'Assign to Existing Deliverable')} {availablePorts.length === 0 && t('data-contracts:linkProduct.noAvailableDeliverables', '(no available deliverables)')}
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="new" id="new" />
                    <Label htmlFor="new">{t('data-contracts:linkProduct.createNew', 'Create New Deliverable')}</Label>
                  </div>
                </RadioGroup>

                {assignmentMode === 'existing' && availablePorts.length > 0 && (
                  <div className="space-y-2 ml-6">
                    <Label htmlFor="port">{t('data-contracts:linkProduct.selectDeliverableLabel', 'Select Deliverable')}</Label>
                    <Select value={selectedPortIndex} onValueChange={setSelectedPortIndex}>
                      <SelectTrigger id="port">
                        <SelectValue placeholder={t('data-contracts:linkProduct.chooseDeliverablePlaceholder', 'Choose a deliverable...')} />
                      </SelectTrigger>
                      <SelectContent>
                        {availablePorts.map((port) => {
                          // Find the actual index in the full outputPorts array
                          const actualIndex = selectedProduct.outputPorts?.findIndex(p => p === port) ?? -1;
                          return (
                            <SelectItem key={actualIndex} value={actualIndex.toString()}>
                              <div className="flex items-center gap-2">
                                <span>{port.name}</span>
                                <Badge variant="outline" className="text-xs">v{port.version}</Badge>
                              </div>
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {t('data-contracts:linkProduct.onlyUnassigned', 'Only showing deliverables without an assigned contract')}
                    </p>
                  </div>
                )}

                {assignmentMode === 'new' && (
                  <div className="space-y-4 ml-6">
                    <div className="space-y-2">
                      <Label htmlFor="portName">
                        {t('data-contracts:linkProduct.deliverableNameLabel', 'Deliverable Name')} <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="portName"
                        value={newPortName}
                        onChange={(e) => setNewPortName(e.target.value)}
                        placeholder={t('data-contracts:linkProduct.deliverableNamePlaceholder', 'e.g., analytics-output')}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="portVersion">
                        {t('data-contracts:linkProduct.deliverableVersionLabel', 'Deliverable Version')} <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="portVersion"
                        value={newPortVersion}
                        onChange={(e) => setNewPortVersion(e.target.value)}
                        placeholder={t('data-contracts:linkProduct.deliverableVersionPlaceholder', '1.0.0')}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Product Info Summary */}
              <div className="rounded-lg bg-muted p-4 space-y-2">
                <Label className="text-sm font-medium">{t('data-contracts:linkProduct.selectedProduct', 'Selected Product')}</Label>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{selectedProduct.name}</span>
                    <Badge variant="outline">v{selectedProduct.version}</Badge>
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {t('data-contracts:linkProduct.currentDeliverables', 'Current deliverables: {{total}} ({{available}} available for linking)', { total: selectedProduct.outputPorts?.length || 0, available: availablePorts.length })}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
          >
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting || !selectedProductId}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('data-contracts:linkProduct.linking', 'Linking...')}
              </>
            ) : (
              t('data-contracts:linkProduct.linkButton', 'Link to Product')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
