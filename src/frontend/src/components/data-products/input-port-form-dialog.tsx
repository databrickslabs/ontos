import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import type { InputPort } from '@/types/data-product';

type InputPortFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (port: InputPort) => Promise<void>;
  initial?: InputPort;
};

export default function InputPortFormDialog({ isOpen, onOpenChange, onSubmit, initial }: InputPortFormProps) {
  const { toast } = useToast();
  const { t } = useTranslation(['data-products', 'common']);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [name, setName] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [contractId, setContractId] = useState('');
  const [assetType, setAssetType] = useState('');
  const [assetIdentifier, setAssetIdentifier] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '');
      setVersion(initial.version || '1.0.0');
      setContractId(initial.contractId || '');
      setAssetType(initial.assetType || '');
      setAssetIdentifier(initial.assetIdentifier || '');
    } else if (isOpen && !initial) {
      setName('');
      setVersion('1.0.0');
      setContractId('');
      setAssetType('');
      setAssetIdentifier('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: 'Validation Error', description: 'Port name is required', variant: 'destructive' });
      return;
    }

    if (!version.trim()) {
      toast({ title: 'Validation Error', description: 'Port version is required', variant: 'destructive' });
      return;
    }

    if (!contractId.trim()) {
      toast({
        title: 'Validation Error',
        description: 'Contract ID is required (ODPS v1.0.0 requirement)',
        variant: 'destructive'
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const port: InputPort = {
        name: name.trim(),
        version: version.trim(),
        contractId: contractId.trim(),
        assetType: assetType.trim() || undefined,
        assetIdentifier: assetIdentifier.trim() || undefined,
      };

      await onSubmit(port);
      onOpenChange(false);
      toast({
        title: 'Success',
        description: initial ? 'Consumable updated' : 'Consumable added',
      });
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save consumable',
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? t('data-products:inputPortForm.editTitle') : t('data-products:inputPortForm.addTitle')}</DialogTitle>
          <DialogDescription>
            {t('data-products:inputPortForm.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              {t('data-products:inputPortForm.labels.consumableName')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-products:inputPortForm.placeholders.name')}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="version">
              {t('common:labels.version')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="version"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
            />
            <p className="text-xs text-muted-foreground">
              Version of this consumable (e.g., 1.0.0, 2.1.3)
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="contractId">
              {t('data-products:inputPortForm.labels.contractId')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="contractId"
              value={contractId}
              onChange={(e) => setContractId(e.target.value)}
              placeholder={t('data-products:inputPortForm.placeholders.contractId')}
            />
            <p className="text-xs text-muted-foreground">
              Reference to the data contract ID (REQUIRED in ODPS v1.0.0)
            </p>
          </div>

          <div className="border-t pt-4">
            <h4 className="text-sm font-medium mb-3">{t('data-products:inputPortForm.labels.databricksExtensions')}</h4>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="assetType">{t('data-products:inputPortForm.labels.assetType')}</Label>
                <Input
                  id="assetType"
                  value={assetType}
                  onChange={(e) => setAssetType(e.target.value)}
                  placeholder={t('data-products:inputPortForm.placeholders.assetType')}
                />
                <p className="text-xs text-muted-foreground">
                  Type of Databricks asset
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="assetIdentifier">{t('data-products:inputPortForm.labels.assetIdentifier')}</Label>
                <Input
                  id="assetIdentifier"
                  value={assetIdentifier}
                  onChange={(e) => setAssetIdentifier(e.target.value)}
                  placeholder={t('data-products:inputPortForm.placeholders.assetIdentifier')}
                />
                <p className="text-xs text-muted-foreground">
                  Unique identifier for the Databricks asset
                </p>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : initial ? 'Save Changes' : 'Add Consumable'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
