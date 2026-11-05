import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import { Checkbox } from '@/components/ui/checkbox';
import { AlertCircle, Loader2, FileText, LayoutDashboard } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useDataProductTypes } from '@/hooks/use-data-product-types';
import {
  dataProductTypeLabel,
  defaultDataProductTypeKey,
  pickableDataProductTypes,
} from '@/lib/data-product-types';

interface CreateFromContractDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName: string;
  onSuccess?: (productId: string) => void;
}

interface ContractDashboard {
  id: string;
  name: string;
  location?: string | null;
  url?: string | null;
}

const CreateFromContractDialog: React.FC<CreateFromContractDialogProps> = ({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  onSuccess,
}) => {
  const { get, post } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['data-products', 'common']);

  const { types: productTypeList, loading: productTypesLoading } = useDataProductTypes(isOpen);
  const productTypeOptions = pickableDataProductTypes(productTypeList);

  const [productName, setProductName] = useState('');
  // The type the user picked; until they pick one, the default type is shown
  // and sent. With neither, no type is sent (the backend then uses no type).
  const [chosenProductType, setChosenProductType] = useState<string>('');
  const productType = chosenProductType || defaultDataProductTypeKey(productTypeList) || '';
  const [version, setVersion] = useState('v1.0.0');
  const [outputPortName, setOutputPortName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Dashboards built on the contract's semantic models, offered as extra deliverables
  const [dashboards, setDashboards] = useState<ContractDashboard[]>([]);
  const [includeDashboards, setIncludeDashboards] = useState(true);

  const handleSubmit = async () => {
    // Validation
    if (!productName.trim()) {
      setError(t('data-products:createFromContract.errors.nameRequired'));
      return;
    }

    if (!version.trim()) {
      setError(t('data-products:createFromContract.errors.versionRequired'));
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      const response = await post('/api/data-products/from-contract', {
        contract_id: contractId,
        product_name: productName.trim(),
        product_type: productType || undefined,
        version: version.trim(),
        output_port_name: outputPortName.trim() || undefined,
        include_dashboards: dashboards.length > 0 && includeDashboards,
      });

      if (response.error) {
        // A coded refusal (e.g. the type was deactivated meanwhile) in the user's language
        throw new Error(
          response.errorCode
            ? t(`data-products:createFromContract.errors.${response.errorCode}`, {
                ...(response.errorParams || {}),
                defaultValue: response.error,
              })
            : response.error,
        );
      }

      toast({
        title: t('data-products:createFromContract.messages.productCreated'),
        description: t('data-products:createFromContract.messages.productCreatedDesc', { productName }),
      });

      // Call success callback with product ID
      const productData = response.data as { id?: string };
      if (onSuccess && productData?.id) {
        onSuccess(productData.id);
      }

      // Reset form and close dialog
      handleClose();

    } catch (e: any) {
      setError(e.message || t('data-products:createFromContract.errors.createError'));
      toast({
        title: t('common:toast.error'),
        description: e.message || t('data-products:createFromContract.errors.createError'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setProductName('');
    setChosenProductType('');
    setVersion('v1.0.0');
    setOutputPortName('');
    setError(null);
    onOpenChange(false);
  };

  // Reset form when dialog opens
  React.useEffect(() => {
    if (isOpen) {
      setProductName('');
      setChosenProductType('');
      setVersion('v1.0.0');
      setOutputPortName('');
      setError(null);
      setIncludeDashboards(true);
      setDashboards([]);
      get<ContractDashboard[]>(`/api/data-products/from-contract/${encodeURIComponent(contractId)}/dashboards`)
        .then(res => setDashboards(res.data || []))
        .catch(() => setDashboards([]));
    }
  }, [isOpen, contractId, get]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            {t('data-products:createFromContract.title')}
          </DialogTitle>
          <DialogDescription>
            {t('data-products:createFromContract.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Contract Information */}
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">{t('data-products:createFromContract.contractLabel')}</span>
              <span className="font-mono">{contractId}</span>
            </div>
            <div className="text-sm font-medium mt-1">{contractName}</div>
          </div>

          {/* Product Name */}
          <div className="space-y-2">
            <Label htmlFor="product-name" className="text-sm font-medium">
              {t('data-products:createFromContract.productNameLabel')}
            </Label>
            <Input
              id="product-name"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder={t('data-products:createFromContract.productNamePlaceholder')}
              disabled={submitting}
            />
          </div>

          {/* Product Type */}
          <div className="space-y-2">
            <Label htmlFor="product-type" className="text-sm font-medium">
              {t('data-products:createFromContract.productTypeLabel')}
            </Label>
            <Select
              value={productType || undefined}
              onValueChange={setChosenProductType}
              disabled={submitting || productTypesLoading}
            >
              <SelectTrigger id="product-type">
                <SelectValue placeholder={t('data-products:createFromContract.productTypePlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {productTypeOptions.map((type) => (
                  <SelectItem key={type.key} value={type.key}>
                    {dataProductTypeLabel(type, t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Version */}
          <div className="space-y-2">
            <Label htmlFor="version" className="text-sm font-medium">
              {t('data-products:createFromContract.versionLabel')}
            </Label>
            <Input
              id="version"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder={t('data-products:createFromContract.versionPlaceholder')}
              disabled={submitting}
            />
          </div>

          {/* Output Port Name (Optional) */}
          <div className="space-y-2">
            <Label htmlFor="output-port-name" className="text-sm font-medium">
              {t('data-products:createFromContract.deliverableNameLabel')}
            </Label>
            <Input
              id="output-port-name"
              value={outputPortName}
              onChange={(e) => setOutputPortName(e.target.value)}
              placeholder={t('data-products:createFromContract.deliverableNamePlaceholder', { contractName })}
              disabled={submitting}
            />
            <div className="text-xs text-muted-foreground">
              {t('data-products:createFromContract.deliverableNameHint')}
            </div>
          </div>

          {dashboards.length > 0 && (
            <div className="space-y-2 rounded-lg border p-3">
              <div className="flex items-start gap-2">
                <Checkbox
                  id="include-dashboards"
                  checked={includeDashboards}
                  onCheckedChange={(value) => setIncludeDashboards(value === true)}
                  disabled={submitting}
                />
                <div className="space-y-1">
                  <Label htmlFor="include-dashboards" className="text-sm font-medium">
                    {t('data-products:createFromContract.includeDashboardsLabel')}
                  </Label>
                  <div className="text-xs text-muted-foreground">
                    {t('data-products:createFromContract.includeDashboardsHint')}
                  </div>
                </div>
              </div>
              <ul className="ml-6 space-y-1 text-sm">
                {dashboards.map(d => (
                  <li key={d.id} className="flex items-center gap-2">
                    <LayoutDashboard className="h-3.5 w-3.5 text-muted-foreground" />
                    {d.url ? (
                      <a href={d.url} target="_blank" rel="noreferrer" className="hover:underline">{d.name}</a>
                    ) : d.name}
                  </li>
                ))}
              </ul>
            </div>
          )}

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
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !productName.trim() || !version.trim()}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? t('data-products:createFromContract.creating') : t('data-products:createFromContract.createButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default CreateFromContractDialog;
