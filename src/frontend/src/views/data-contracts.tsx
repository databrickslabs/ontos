import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { DataContractListItem, DataContractCreate } from '@/types/data-contract';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useNavigate } from 'react-router-dom'
import { useDomains } from '@/hooks/use-domains'
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import TagChip from '@/components/ui/tag-chip';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Plus, Pencil, Trash2, AlertCircle, Upload, ChevronDown, KeyRound, HelpCircle, FileText, Table2, Loader2 } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import DataContractBasicFormDialog from '@/components/data-contracts/data-contract-basic-form-dialog'
import CreateContractFromDatasetDialog from '@/components/datasets/create-contract-from-dataset-dialog'
import { useDropzone } from 'react-dropzone';
import { ColumnDef } from "@tanstack/react-table"
import { useToast } from "@/hooks/use-toast"
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useProjectContext } from '@/stores/project-store';
import { DataTable } from '@/components/ui/data-table';
import { RelativeDate } from '@/components/common/relative-date';

export default function DataContracts() {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { toast } = useToast();
  const { getDomainName } = useDomains();
  const [contracts, setContracts] = useState<DataContractListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openWizard, setOpenWizard] = useState(false);
  const [openUploadDialog, setOpenUploadDialog] = useState(false);
  const [openFromDatasetDialog, setOpenFromDatasetDialog] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [odcsPaste, setOdcsPaste] = useState<string>('')

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
  const { currentProject, hasProjectContext } = useProjectContext();
  const navigate = useNavigate();

  useEffect(() => {
    fetchContracts();
    // Set breadcrumbs
    setStaticSegments([]);
    setDynamicTitle(t('title'));

    // Cleanup breadcrumbs on unmount
    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle, hasProjectContext, currentProject, t]);

  // Removed ODCS schema load for inline JSON validation
  // Removed inline JSON validation

  // Persist draft to store on form changes
  // Removed draft persistence for inline editor

  const fetchContracts = async () => {
    try {
      setLoading(true);

      // Build URL with project context if available
      let endpoint = '/api/data-contracts';
      if (hasProjectContext && currentProject) {
        endpoint += `?project_id=${currentProject.id}`;
      }

      const response = await fetch(endpoint);
      if (!response.ok) throw new Error('Failed to fetch contracts');
      const data = await response.json();
      setContracts(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch contracts');
    } finally {
      setLoading(false);
    }
  };

  // Removed per-row fetch for modal; navigation handles details

  const createContract = async (formData: DataContractCreate) => {
    try {
      const response = await fetch('/api/data-contracts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to create contract: ${errorText}`);
      }
      await fetchContracts();
      toast({ 
        title: 'Success', 
        description: 'Data contract created successfully' 
      });
      setOpenWizard(false); // Close the wizard on success
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create contract';
      setError(message);
      toast({ 
        title: 'Error', 
        description: message, 
        variant: 'destructive' 
      });
      throw err; // Re-throw so wizard can handle it
    }
  };

  const deleteContract = async (id: string) => {
    try {
      const response = await fetch(`/api/data-contracts/${id}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete contract');
      await fetchContracts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete contract');
    }
  };

  const handleBulkDelete = async (selectedIds: string[]) => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedIds.length} selected contract(s)?`)) return;
    try {
      const results = await Promise.allSettled(selectedIds.map(async (id) => {
        const res = await fetch(`/api/data-contracts/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`ID ${id}: delete failed`);
        return id;
      }));
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;
      if (successes > 0) {
        toast({ title: 'Bulk Delete Success', description: `${successes} contract(s) deleted.` });
      }
      if (failures > 0) {
        const firstError = (results.find(r => r.status === 'rejected') as PromiseRejectedResult)?.reason?.message || 'Unknown error';
        toast({ title: 'Bulk Delete Error', description: `${failures} contract(s) could not be deleted. First error: ${firstError}`, variant: 'destructive' });
      }
      await fetchContracts();
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to bulk delete', variant: 'destructive' });
    }
  };

  const handleBulkRequestAccess = async (selectedIds: string[]) => {
    if (selectedIds.length === 0) return;
    try {
      // Submit individual requests for each entity (Access Grants API requires single entity_id)
      const results = await Promise.all(
        selectedIds.map(id =>
          fetch('/api/access-grants/request', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_type: 'data_contract', entity_id: id, permission_level: 'READ' })
          })
        )
      );
      const failed = results.filter(r => !r.ok);
      if (failed.length > 0) throw new Error('Failed to submit access requests');
      toast({ title: 'Request Sent', description: 'Access request submitted. You will be notified.' });
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to submit', variant: 'destructive' });
    }
  };

  const handleDeleteContract = async (id: string) => {
    if (!confirm('Are you sure you want to delete this contract?')) return;
    await deleteContract(id);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: async (acceptedFiles) => {
      if (acceptedFiles.length === 0) return;

      const file = acceptedFiles[0];
      if (!file.type.startsWith('text/') && file.type !== 'application/json' && file.type !== 'application/x-yaml') {
        setUploadError('Please upload a text file (JSON, YAML, etc)');
        return;
      }

      try {
        setUploading(true);
        setUploadError(null);

        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/data-contracts/upload', {
          method: 'POST',
          body: formData
        });

        if (!response.ok) {
          // Parse error response for detailed message
          let errorMsg = 'Failed to upload contract';
          try {
            const contentType = response.headers.get('Content-Type');
            if (contentType?.includes('application/json')) {
              const errorBody = await response.json();
              if (errorBody?.detail) {
                errorMsg = typeof errorBody.detail === 'string' 
                  ? errorBody.detail 
                  : errorBody.detail.message || JSON.stringify(errorBody.detail);
              } else if (errorBody?.message) {
                errorMsg = errorBody.message;
              }
            } else {
              errorMsg = await response.text() || errorMsg;
            }
          } catch {
            // Keep default error message
          }
          
          // Check if this might be a Data Product file uploaded by mistake
          const isLikelyODPS = errorMsg.toLowerCase().includes('validation') || 
            errorMsg.toLowerCase().includes('odps') ||
            errorMsg.toLowerCase().includes('outputports');
          
          if (isLikelyODPS) {
            errorMsg += '\n\nHint: This page is for Data Contracts (ODCS format). If you\'re trying to upload a Data Product (ODPS format), please use the Data Products page instead.';
          }
          
          throw new Error(errorMsg);
        }

        await fetchContracts();
        setOpenUploadDialog(false);
        toast({ title: 'Success', description: 'Contract uploaded successfully' });
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : 'Failed to upload contract');
      } finally {
        setUploading(false);
      }
    },
    accept: {
      'text/*': ['.json', '.yaml', '.yml', '.txt'],
      'application/json': ['.json'],
      'application/x-yaml': ['.yaml', '.yml']
    },
    multiple: false
  });

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'draft':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
      case 'active':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
      case 'deprecated':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    }
  };

  const columns: ColumnDef<DataContractListItem>[] = [
    {
      accessorKey: "name",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.name')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => {
        const contract = row.original;
        const domainId = (contract as any).domain_id || (contract as any).domainId;
        const domainName = getDomainName(domainId);
        return (
          <div>
            <div className="font-medium">{row.getValue("name")}</div>
            {domainName && domainId && (
              <div
                className="text-xs text-muted-foreground cursor-pointer hover:underline"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/data-domains/${domainId}`);
                }}
              >
                ↳ Domain: {domainName}
              </div>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "owner_team_id",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.owner')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => {
        const teamName = row.original.owner_team_name;
        return <div>{teamName || t('common:states.notAvailable')}</div>;
      },
    },
    {
      accessorKey: "version",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.version')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => <Badge variant="secondary">{row.getValue("version")}</Badge>,
    },
    {
      accessorKey: "status",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.status')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => {
        const contract = row.original;
        return (
          <div className="flex items-center gap-1">
            {contract.draftOwnerId && (
              <Badge variant="outline" className="text-xs bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200">
                Personal
              </Badge>
            )}
            <Badge variant="outline" className={getStatusColor(row.getValue("status"))}>
              {row.getValue("status")}
            </Badge>
          </div>
        );
      },
    },
    {
      accessorKey: "tags",
      header: t('table.tags'),
      cell: ({ row }) => {
        const tags = row.original.tags || [];
        return (
          <div className="flex flex-wrap gap-1">
            {tags.map((tag, index) => (
              <TagChip key={index} tag={tag} size="sm" />
            ))}
          </div>
        );
      },
      enableSorting: false,
    },
    {
      accessorKey: "created",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.created')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => row.original.created ? <RelativeDate date={row.original.created} /> : t('common:states.notAvailable'),
    },
    {
      accessorKey: "updated",
      header: ({ column }) => {
        return (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            {t('table.updated')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        );
      },
      cell: ({ row }) => row.original.updated ? <RelativeDate date={row.original.updated} /> : t('common:states.notAvailable'),
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const contract = row.original;
        return (
          <div className="flex space-x-1 justify-end">
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); contract.id && navigate(`/data-contracts/${contract.id}`) }}
              title={t('common:tooltips.edit')}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            {contract.id && (
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive hover:text-destructive"
                onClick={(e) => { e.stopPropagation(); handleDeleteContract(contract.id as string) }}
                title={t('common:tooltips.delete')}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <FileText className="w-8 h-8" />
        {t('title')}
      </h1>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <AlertDescription className="whitespace-pre-wrap flex-1">{error}</AlertDescription>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 ml-2 hover:bg-destructive/20"
            onClick={() => setError(null)}
            title={t('common:tooltips.dismiss')}
          >
            <span className="sr-only">Dismiss</span>
            ×
          </Button>
        </Alert>
      )}

      {loading ? (
        <ListViewSkeleton columns={6} rows={5} toolbarButtons={3} />
      ) : (
        <DataTable
          columns={columns}
          data={contracts}
          searchColumn="name"
          storageKey="data-contracts-sort"
          toolbarActions={
            <>
              <Button onClick={() => setOpenWizard(true)} className="gap-2 h-9" title={t('common:tooltips.createDataContract')}>
                <Plus className="h-4 w-4" />
                {t('newContract')}
              </Button>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button onClick={() => setOpenFromDatasetDialog(true)} variant="outline" className="gap-2 h-9">
                      <Table2 className="h-4 w-4" />
                      From Dataset
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">
                    <p className="font-medium">Create from Dataset</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Create a new Data Contract from an existing Dataset, optionally inferring the schema from one of its instances.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button onClick={() => setOpenUploadDialog(true)} variant="outline" className="gap-2 h-9">
                      <Upload className="h-4 w-4" />
                      {t('uploadFile')}
                      <HelpCircle className="h-3 w-3 ml-1 opacity-50" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs">
                    <p className="font-medium">Upload Data Contract (ODCS format)</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Accepts JSON, YAML, or text files following the ODCS (Open Data Contract Standard) schema.
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      For Data Products (ODPS), use the Data Products page instead.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </>
          }
          bulkActions={(selectedRows) => (
            <>
              <Button
                variant="outline"
                size="sm"
                className="h-9 gap-1"
                onClick={() => handleBulkRequestAccess(selectedRows.map(r => r.id!).filter(Boolean))}
                title={t('common:tooltips.requestAccessForSelected')}
              >
                <KeyRound className="w-4 h-4 mr-1" />
                Request Access ({selectedRows.length})
              </Button>
              <Button
                variant="destructive"
                size="sm"
                className="h-9 gap-1"
                onClick={() => handleBulkDelete(selectedRows.map(r => r.id!).filter(Boolean))}
                title={t('common:tooltips.deleteSelected')}
              >
                <Trash2 className="w-4 h-4 mr-1" />
                Delete Selected ({selectedRows.length})
              </Button>
            </>
          )}
          onRowClick={(row) => {
            const id = row.original.id;
            if (id) navigate(`/data-contracts/${id}`);
          }}
        />
      )}

      {/* Upload Dialog */}
      <Dialog open={openUploadDialog} onOpenChange={setOpenUploadDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Data Contract</DialogTitle>
          </DialogHeader>
          {uploadError && (
            <Alert variant="destructive" className="mb-4">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <AlertDescription className="whitespace-pre-wrap flex-1">{uploadError}</AlertDescription>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 ml-2 hover:bg-destructive/20"
                onClick={() => setUploadError(null)}
                title={t('common:tooltips.dismiss')}
              >
                <span className="sr-only">Dismiss</span>
                ×
              </Button>
            </Alert>
          )}
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-md p-6 text-center cursor-pointer ${
              isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'
            }`}
          >
            <input {...getInputProps()} />
            {uploading ? (
              <div className="flex justify-center">
                <Loader2 className="animate-spin h-8 w-8 text-primary" />
              </div>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  {isDragActive
                    ? 'Drop the file here'
                    : 'Drag and drop a contract file here, or click to select'}
                </p>
                <p className="text-xs text-muted-foreground mt-2">
                  Supported formats: JSON, YAML, or plain text
                </p>
              </>
            )}
          </div>
          <div className="mt-4">
            <Label htmlFor="odcsPaste">Or paste ODCS JSON</Label>
            <textarea
              id="odcsPaste"
              placeholder={t('common:placeholders.pasteODCSJSON')}
              className="flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={odcsPaste}
              onChange={(e) => setOdcsPaste(e.target.value)}
              onBlur={async () => {
                const value = odcsPaste.trim()
                if (!value) return
                try {
                  const body = JSON.parse(value)
                  const res = await fetch('/api/data-contracts/odcs/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                  })
                  if (!res.ok) throw new Error('Failed to import ODCS JSON')
                  await fetchContracts()
                  setOpenUploadDialog(false)
                  setOdcsPaste('')
                  toast({ title: 'Imported', description: 'ODCS JSON imported successfully' })
                } catch (err) {
                  setUploadError(err instanceof Error ? err.message : 'Failed to import ODCS JSON')
                }
              }}
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Basic Form Dialog */}
      <DataContractBasicFormDialog
        isOpen={openWizard}
        onOpenChange={setOpenWizard}
        onSubmit={createContract}
      />

      {/* Create from Dataset Dialog */}
      <CreateContractFromDatasetDialog
        isOpen={openFromDatasetDialog}
        onOpenChange={setOpenFromDatasetDialog}
        onSuccess={(contractId) => {
          fetchContracts();
          setOpenFromDatasetDialog(false);
          navigate(`/data-contracts/${contractId}`);
        }}
      />
    </div>
  );
} 