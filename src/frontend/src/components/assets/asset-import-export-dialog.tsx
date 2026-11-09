import { useState, useCallback, useRef } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import {
  Download,
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertCircle,
  Loader2,
  FileDown,
} from 'lucide-react';

// -- Types --

interface ImportPreviewItem {
  row: number;
  name: string;
  asset_type: string;
  action: 'create' | 'update' | 'skip' | 'error';
  message?: string;
  existing_asset_id?: string;
}

interface ImportPreviewResult {
  total_rows: number;
  will_create: number;
  will_update: number;
  will_skip: number;
  errors: number;
  items: ImportPreviewItem[];
  error_messages: string[];
}

interface ImportResultItem {
  row: number;
  name: string;
  asset_type: string;
  action: 'create' | 'update' | 'skip' | 'error';
  asset_id?: string;
  message?: string;
}

interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  items: ImportResultItem[];
  error_messages: string[];
}

// -- Props --

interface AssetImportExportDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  selectedAssetTypeId?: string | null;
  selectedAssetTypeName?: string | null;
  selectedAssetIds?: string[];
  canImport?: boolean;
  currentFilters?: {
    platform?: string;
    domain_id?: string;
    status?: string;
  };
  onImportComplete?: () => void;
}

const ACTION_BADGE: Record<string, { variant: 'default' | 'secondary' | 'outline' | 'destructive'; label: string }> = {
  create: { variant: 'default', label: 'Create' },
  update: { variant: 'secondary', label: 'Update' },
  skip: { variant: 'outline', label: 'Skip' },
  error: { variant: 'destructive', label: 'Error' },
};

export default function AssetImportExportDialog({
  isOpen,
  onOpenChange,
  selectedAssetTypeId,
  selectedAssetTypeName,
  selectedAssetIds = [],
  canImport = false,
  currentFilters,
  onImportComplete,
}: AssetImportExportDialogProps) {
  const { toast } = useToast();
  const { t } = useTranslation(['assets', 'common']);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Export state
  const [exportFormat, setExportFormat] = useState<'csv' | 'xlsx'>('csv');
  const [isExporting, setIsExporting] = useState(false);

  // Import state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importProgress, setImportProgress] = useState(0);

  const resetImportState = useCallback(() => {
    setSelectedFile(null);
    setPreview(null);
    setImportResult(null);
    setIsPreviewLoading(false);
    setIsImporting(false);
    setImportProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  // ------------------------------------------------------------------
  // Export handlers
  // ------------------------------------------------------------------

  const hasSelectedIds = selectedAssetIds.length > 0;

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const params = new URLSearchParams();
      params.set('format', exportFormat);
      if (hasSelectedIds) {
        params.set('ids', selectedAssetIds.join(','));
      } else {
        if (selectedAssetTypeId) params.set('asset_type_id', selectedAssetTypeId);
        if (currentFilters?.platform) params.set('platform', currentFilters.platform);
        if (currentFilters?.domain_id) params.set('domain_id', currentFilters.domain_id);
        if (currentFilters?.status) params.set('status', currentFilters.status);
      }

      const response = await fetch(`/api/assets/bulk/export?${params.toString()}`);
      if (!response.ok) throw new Error('Export failed');

      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition');
      const filename = disposition?.match(/filename="(.+)"/)?.[1] || `assets-export.${exportFormat}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast({ title: t('assets:importExport.toast.exportSuccessTitle'), description: t('assets:importExport.toast.exportSuccessDescription', { filename }) });
    } catch (error: any) {
      toast({ title: t('assets:importExport.toast.exportFailedTitle'), description: error.message, variant: 'destructive' });
    } finally {
      setIsExporting(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const params = new URLSearchParams();
      params.set('format', exportFormat);
      if (selectedAssetTypeName) params.set('asset_type', selectedAssetTypeName);

      const response = await fetch(`/api/assets/bulk/export/template?${params.toString()}`);
      if (!response.ok) throw new Error('Template download failed');

      const blob = await response.blob();
      const filename = `assets-template.${exportFormat}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast({ title: t('assets:importExport.toast.templateDownloadedTitle'), description: filename });
    } catch (error: any) {
      toast({ title: t('assets:importExport.toast.downloadFailedTitle'), description: error.message, variant: 'destructive' });
    }
  };

  // ------------------------------------------------------------------
  // Import handlers
  // ------------------------------------------------------------------

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setPreview(null);
      setImportResult(null);
    }
  };

  const handlePreview = async () => {
    if (!selectedFile) return;
    setIsPreviewLoading(true);
    setPreview(null);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch('/api/assets/bulk/import/preview', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Preview failed');
      }
      const data: ImportPreviewResult = await response.json();
      setPreview(data);
    } catch (error: any) {
      toast({ title: t('assets:importExport.toast.previewFailedTitle'), description: error.message, variant: 'destructive' });
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const handleImport = async () => {
    if (!selectedFile) return;
    setIsImporting(true);
    setImportProgress(10);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      setImportProgress(30);
      const response = await fetch('/api/assets/bulk/import', {
        method: 'POST',
        body: formData,
      });
      setImportProgress(80);

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Import failed');
      }

      const data: ImportResult = await response.json();
      setImportResult(data);
      setImportProgress(100);

      const msg = t('assets:importExport.toast.importSummary', { created: data.created, updated: data.updated, errors: data.errors });
      toast({
        title: data.errors === 0 ? t('assets:importExport.toast.importSuccessTitle') : t('assets:importExport.toast.importErrorsTitle'),
        description: msg,
        variant: data.errors > 0 ? 'destructive' : undefined,
      });

      if (data.errors === 0 && onImportComplete) {
        onImportComplete();
      }
    } catch (error: any) {
      toast({ title: t('assets:importExport.toast.importFailedTitle'), description: error.message, variant: 'destructive' });
    } finally {
      setIsImporting(false);
    }
  };

  // Determine importable count from preview
  const importableCount = preview ? preview.will_create + preview.will_update : 0;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { onOpenChange(open); if (!open) resetImportState(); }}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5" />
            {canImport ? t('assets:importExport.titleImportExport') : t('assets:importExport.titleExport')}
          </DialogTitle>
          <DialogDescription>
            {canImport
              ? t('assets:importExport.descriptionImportExport')
              : t('assets:importExport.descriptionExport')}
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="export" className="flex-1 flex flex-col min-h-0">
          <TabsList className={canImport ? "grid w-full grid-cols-2" : "grid w-full grid-cols-1"}>
            <TabsTrigger value="export" className="flex items-center gap-2">
              <Download className="h-4 w-4" />
              {t('common:actions.export')}
            </TabsTrigger>
            {canImport && (
              <TabsTrigger value="import" className="flex items-center gap-2">
                <Upload className="h-4 w-4" />
                {t('common:actions.import')}
              </TabsTrigger>
            )}
          </TabsList>

          {/* ============================================================ */}
          {/* Export Tab */}
          {/* ============================================================ */}
          <TabsContent value="export" className="space-y-4 mt-4">
            <div className="rounded-lg border p-4 space-y-3">
              <div className="text-sm font-medium">{t('assets:importExport.exportSettings')}</div>
              <div className="flex items-center gap-4">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t('assets:importExport.format')}</label>
                  <Select value={exportFormat} onValueChange={(v) => setExportFormat(v as 'csv' | 'xlsx')}>
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="csv">{t('assets:importExport.formatCsv')}</SelectItem>
                      <SelectItem value="xlsx">{t('assets:importExport.formatXlsx')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t('assets:importExport.scope')}</label>
                  <div className="text-sm flex items-center gap-1.5">
                    {hasSelectedIds
                      ? <Badge variant="default">{t('assets:importExport.selectedScope', { count: selectedAssetIds.length })}</Badge>
                      : selectedAssetTypeName
                        ? <Badge variant="secondary">{selectedAssetTypeName}</Badge>
                        : <Badge variant="outline">{t('assets:importExport.allAssetTypes')}</Badge>
                    }
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-2">
              <Button onClick={handleExport} disabled={isExporting}>
                {isExporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                {isExporting ? t('assets:importExport.exporting') : t('assets:importExport.exportAssets')}
              </Button>
              <Button variant="outline" onClick={handleDownloadTemplate}>
                <FileDown className="mr-2 h-4 w-4" />
                {t('assets:importExport.downloadTemplate')}
              </Button>
            </div>

            <div className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground space-y-1">
              <p>{t('assets:importExport.exportHelp1')}</p>
              <p>{t('assets:importExport.exportHelp2')}</p>
            </div>
          </TabsContent>

          {/* ============================================================ */}
          {/* Import Tab (only for users with write access) */}
          {/* ============================================================ */}
          {canImport && <TabsContent value="import" className="flex-1 flex flex-col min-h-0 space-y-3 mt-4">
            {/* File selection */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="text-sm font-medium">{t('assets:importExport.selectFile')}</div>
              <div className="flex items-center gap-3">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={handleFileSelect}
                  className="text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-primary file:text-primary-foreground hover:file:bg-primary/90 cursor-pointer"
                />
                {selectedFile && (
                  <Badge variant="outline" className="text-xs">
                    {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
                  </Badge>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handlePreview}
                  disabled={!selectedFile || isPreviewLoading}
                >
                  {isPreviewLoading
                    ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    : <RefreshCw className="mr-2 h-4 w-4" />
                  }
                  {t('assets:importExport.preview')}
                </Button>
              </div>
            </div>

            {/* Global errors */}
            {preview?.error_messages && preview.error_messages.length > 0 && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <ul className="list-disc list-inside text-sm">
                    {preview.error_messages.map((msg, i) => <li key={i}>{msg}</li>)}
                  </ul>
                </AlertDescription>
              </Alert>
            )}

            {/* Preview summary */}
            {preview && preview.error_messages.length === 0 && (
              <div className="rounded-lg border p-3">
                <div className="flex items-center gap-4 text-sm">
                  <span className="font-medium">{t('assets:importExport.rows', { count: preview.total_rows })}</span>
                  <span className="flex items-center gap-1">
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                    {t('assets:importExport.willCreate', { count: preview.will_create })}
                  </span>
                  <span className="flex items-center gap-1">
                    <RefreshCw className="h-3.5 w-3.5 text-blue-600" />
                    {t('assets:importExport.willUpdate', { count: preview.will_update })}
                  </span>
                  {preview.errors > 0 && (
                    <span className="flex items-center gap-1 text-destructive">
                      <XCircle className="h-3.5 w-3.5" />
                      {t('assets:importExport.errorsCount', { count: preview.errors })}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Preview / Result table */}
            {(preview || importResult) && (
              <ScrollArea className="flex-1 min-h-0 max-h-[340px] rounded-lg border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/90 backdrop-blur-sm">
                    <tr className="text-left">
                      <th className="px-3 py-2 w-12">{t('assets:importExport.tableRow')}</th>
                      <th className="px-3 py-2">{t('common:labels.name')}</th>
                      <th className="px-3 py-2">{t('common:labels.type')}</th>
                      <th className="px-3 py-2 w-24">{t('assets:importExport.tableAction')}</th>
                      <th className="px-3 py-2">{t('common:labels.message')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(importResult?.items || preview?.items || []).map((item) => {
                      const badge = ACTION_BADGE[item.action] || ACTION_BADGE.error;
                      return (
                        <tr key={item.row} className="border-t hover:bg-muted/30">
                          <td className="px-3 py-1.5 text-muted-foreground">{item.row}</td>
                          <td className="px-3 py-1.5 font-medium truncate max-w-[200px]">{item.name}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">{item.asset_type}</td>
                          <td className="px-3 py-1.5">
                            <Badge variant={badge.variant} className="text-xs">{t(`assets:importExport.actionLabels.${item.action}`, badge.label)}</Badge>
                          </td>
                          <td className="px-3 py-1.5 text-xs text-muted-foreground truncate max-w-[250px]">
                            {item.message || ('asset_id' in item && item.asset_id ? `ID: ${item.asset_id}` : '')}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </ScrollArea>
            )}

            {/* Import progress */}
            {isImporting && (
              <div className="space-y-1">
                <Progress value={importProgress} className="h-2" />
                <p className="text-xs text-muted-foreground">{t('assets:importExport.importingAssets')}</p>
              </div>
            )}

            {/* Import result summary */}
            {importResult && (
              <Alert variant={importResult.errors > 0 ? 'destructive' : 'default'}>
                <AlertDescription className="text-sm">
                  {t('assets:importExport.importComplete', { created: importResult.created, updated: importResult.updated, errors: importResult.errors })}
                </AlertDescription>
              </Alert>
            )}
          </TabsContent>}
        </Tabs>

        <DialogFooter className="flex justify-between sm:justify-between">
          <Button variant="outline" onClick={() => { onOpenChange(false); resetImportState(); }}>
            {t('common:actions.close')}
          </Button>
          {canImport && preview && !importResult && importableCount > 0 && (
            <Button onClick={handleImport} disabled={isImporting}>
              {isImporting
                ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('assets:importExport.importing')}</>
                : <><Upload className="mr-2 h-4 w-4" />{t('assets:importExport.importAssets', { count: importableCount })}</>
              }
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
