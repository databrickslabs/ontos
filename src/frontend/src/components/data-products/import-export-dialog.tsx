import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { Download, Upload, CheckCircle, AlertCircle, FileJson } from 'lucide-react';
import type { DataProduct } from '@/types/data-product';

interface ImportExportDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  currentProduct?: DataProduct | null;
  onImportSuccess?: (product: DataProduct) => void;
}

export default function ImportExportDialog({
  isOpen,
  onOpenChange,
  currentProduct,
  onImportSuccess,
}: ImportExportDialogProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { toast } = useToast();
  const [importJson, setImportJson] = useState('');
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [isValidating, setIsValidating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  /**
   * Validates ODPS v1.0.0 JSON structure
   */
  const validateODPSJson = (data: any): { valid: boolean; errors: string[] } => {
    const errors: string[] = [];

    // Required ODPS v1.0.0 fields
    if (!data.apiVersion) errors.push('Missing required field: apiVersion');
    if (!data.kind) errors.push('Missing required field: kind');
    if (!data.id) errors.push('Missing required field: id');
    if (!data.status) errors.push('Missing required field: status');

    // Validate apiVersion
    if (data.apiVersion && !data.apiVersion.startsWith('v1.')) {
      errors.push(`Invalid apiVersion: ${data.apiVersion}. Must be v1.x.x for ODPS v1.0.0 compatibility`);
    }

    // Validate kind
    if (data.kind && data.kind !== 'DataProduct') {
      errors.push(`Invalid kind: ${data.kind}. Must be 'DataProduct'`);
    }

    // Validate status enum
    const validStatuses = ['proposed', 'draft', 'active', 'deprecated', 'retired'];
    if (data.status && !validStatuses.includes(data.status.toLowerCase())) {
      errors.push(`Invalid status: ${data.status}. Must be one of: ${validStatuses.join(', ')}`);
    }

    // Validate input ports (contractId is required)
    if (data.inputPorts && Array.isArray(data.inputPorts)) {
      data.inputPorts.forEach((port: any, idx: number) => {
        if (!port.contractId) {
          errors.push(`Consumable #${idx + 1} missing required field: contractId`);
        }
      });
    }

    // Validate team members (username is required)
    if (data.team?.members && Array.isArray(data.team.members)) {
      data.team.members.forEach((member: any, idx: number) => {
        if (!member.username) {
          errors.push(`Team member #${idx + 1} missing required field: username`);
        }
      });
    }

    // Validate support channels (channel and url are required)
    if (data.support && Array.isArray(data.support)) {
      data.support.forEach((channel: any, idx: number) => {
        if (!channel.channel) {
          errors.push(`Support channel #${idx + 1} missing required field: channel`);
        }
        if (!channel.url) {
          errors.push(`Support channel #${idx + 1} missing required field: url`);
        }
      });
    }

    return { valid: errors.length === 0, errors };
  };

  /**
   * Handles import validation
   */
  const handleValidate = () => {
    setIsValidating(true);
    setValidationErrors([]);

    try {
      // Parse JSON
      const data = JSON.parse(importJson);

      // Validate ODPS structure
      const validation = validateODPSJson(data);

      if (!validation.valid) {
        setValidationErrors(validation.errors);
        toast({
          title: t('data-products:importExport.validationFailed'),
          description: t('data-products:importExport.errorsFound', { count: validation.errors.length }),
          variant: 'destructive',
        });
      } else {
        toast({
          title: t('data-products:importExport.validationPassed'),
          description: t('data-products:importExport.validationPassedDesc'),
        });
      }
    } catch (error: any) {
      setValidationErrors([`JSON Parse Error: ${error.message}`]);
      toast({
        title: t('data-products:importExport.invalidJson'),
        description: error.message,
        variant: 'destructive',
      });
    } finally {
      setIsValidating(false);
    }
  };

  /**
   * Handles import submission
   */
  const handleImport = async () => {
    setIsImporting(true);
    setValidationErrors([]);

    try {
      // Parse and validate JSON
      const data = JSON.parse(importJson);
      const validation = validateODPSJson(data);

      if (!validation.valid) {
        setValidationErrors(validation.errors);
        toast({
          title: t('data-products:importExport.validationFailed'),
          description: t('data-products:importExport.cannotImportErrors', { count: validation.errors.length }),
          variant: 'destructive',
        });
        return;
      }

      // Import via API
      const response = await fetch('/api/data-products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Import failed');
      }

      const importedProduct: DataProduct = await response.json();

      toast({
        title: t('data-products:importExport.importSuccessful'),
        description: t('data-products:importExport.importSuccessfulDesc', { name: importedProduct.name }),
      });

      if (onImportSuccess) {
        onImportSuccess(importedProduct);
      }

      setImportJson('');
      onOpenChange(false);
    } catch (error: any) {
      toast({
        title: t('data-products:importExport.importFailed'),
        description: error.message || t('data-products:messages.importError'),
        variant: 'destructive',
      });
    } finally {
      setIsImporting(false);
    }
  };

  /**
   * Handles export to JSON
   */
  const handleExport = () => {
    if (!currentProduct) {
      toast({
        title: t('data-products:importExport.noProductSelected'),
        description: t('data-products:importExport.noProductSelectedDesc'),
        variant: 'destructive',
      });
      return;
    }

    try {
      // Remove audit fields for clean ODPS export
      const { created_at, updated_at, project_id, ...odpsProduct } = currentProduct;

      // Format JSON with indentation
      const jsonString = JSON.stringify(odpsProduct, null, 2);

      // Create blob and download
      const blob = new Blob([jsonString], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${currentProduct.id || 'data-product'}-odps-v1.0.0.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast({
        title: t('data-products:importExport.exportSuccessful'),
        description: t('data-products:importExport.exportSuccessfulDesc', { filename: a.download }),
      });
    } catch (error: any) {
      toast({
        title: t('data-products:importExport.exportFailed'),
        description: error.message || t('data-products:importExport.exportFailedDesc'),
        variant: 'destructive',
      });
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileJson className="h-5 w-5" />
            {t('data-products:importExport.title')}
          </DialogTitle>
          <DialogDescription>
            {t('data-products:importExport.description')}
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="import" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="import" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              {t('data-products:import.import')}
            </TabsTrigger>
            <TabsTrigger value="export" className="flex items-center gap-2">
              <Download className="h-4 w-4" />
              {t('common:actions.export')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="import" className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t('data-products:importExport.pasteLabel')}
              </label>
              <Textarea
                value={importJson}
                onChange={(e) => setImportJson(e.target.value)}
                placeholder={`{\n  "apiVersion": "v1.0.0",\n  "kind": "DataProduct",\n  "id": "...",\n  "status": "draft",\n  ...\n}`}
                rows={15}
                className="font-mono text-sm"
              />
            </div>

            {validationErrors.length > 0 && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <strong>{t('data-products:importExport.validationErrors')}</strong>
                  <ul className="list-disc list-inside mt-2">
                    {validationErrors.map((error, idx) => (
                      <li key={idx} className="text-sm">{error}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}

            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={handleValidate}
                disabled={!importJson || isValidating}
              >
                <CheckCircle className="mr-2 h-4 w-4" />
                {t('data-products:importExport.validate')}
              </Button>
              <Button
                onClick={handleImport}
                disabled={!importJson || isImporting}
              >
                {isImporting ? t('data-products:import.importing') : t('data-products:import.import')}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="export" className="space-y-4">
            {currentProduct ? (
              <>
                <Alert>
                  <FileJson className="h-4 w-4" />
                  <AlertDescription>
                    <strong>{t('data-products:importExport.currentProduct')}:</strong> {currentProduct.name || t('data-products:importExport.unnamed')} (ID: {currentProduct.id})
                    <br />
                    <strong>{t('common:labels.status')}:</strong> {currentProduct.status}
                    <br />
                    <strong>{t('common:labels.version')}:</strong> {currentProduct.version || t('common:states.notAvailable')}
                  </AlertDescription>
                </Alert>

                <div className="rounded-lg bg-muted/50 p-4">
                  <p className="text-sm text-muted-foreground">
                    {t('data-products:importExport.exportDescription')}
                  </p>
                </div>

                <Button onClick={handleExport}>
                  <Download className="mr-2 h-4 w-4" />
                  {t('data-products:importExport.exportAsJson')}
                </Button>
              </>
            ) : (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {t('data-products:importExport.noProductDesc')}
                </AlertDescription>
              </Alert>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
