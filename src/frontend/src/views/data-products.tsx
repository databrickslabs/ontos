import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import TagChip from '@/components/ui/tag-chip';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Plus, Pencil, Trash2, AlertCircle, Package, ChevronDown, Upload, Loader2, Sparkles, KeyRound, Table as TableIcon, Workflow, Bell, BellOff, HelpCircle } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ViewModeToggle } from '@/components/common/view-mode-toggle';
import {
  Column,
  ColumnDef,
} from "@tanstack/react-table"
import { useApi } from '@/hooks/use-api';
import { DataProduct, DataProductStatus, DataProductOwner } from '@/types/data-product';
import { useToast } from "@/hooks/use-toast"
import { Toaster } from "@/components/ui/toaster"
import { RelativeDate } from '@/components/common/relative-date';
import { useNavigate } from 'react-router-dom';
import { DataTable } from "@/components/ui/data-table";
import DataProductCreateDialog from '@/components/data-products/data-product-create-dialog';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useNotificationsStore } from '@/stores/notifications-store';
import DataProductGraphView from '@/components/data-products/data-product-graph-view';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useDomains } from '@/hooks/use-domains';
import { useProjectContext } from '@/stores/project-store';

// --- Helper Function Type Definition --- 
type CheckApiResponseFn = <T>(
    response: { data?: T | { detail?: string }, error?: string | null | undefined },
    name: string
) => T;

// --- Helper Function Implementation (outside component) --- 
const checkApiResponse: CheckApiResponseFn = (response, name) => {
    if (response.error) {
        throw new Error(`${name} fetch failed: ${response.error}`);
    }
    // Check if data itself contains a FastAPI error detail
    if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(`${name} fetch failed: ${response.data.detail}`);
    }
    // Ensure data is not null/undefined before returning
    if (response.data === null || response.data === undefined) {
        throw new Error(`${name} fetch returned null or undefined data.`);
    }
    // Type assertion after checks - implicit from signature
    return response.data as any; // Use 'as any' temporarily if needed, but the signature defines T
};

// --- Component Code ---

export default function DataProducts() {
  const { t } = useTranslation(['data-products', 'common']);
  const [products, setProducts] = useState<DataProduct[]>([]);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [productToEdit, setProductToEdit] = useState<DataProduct | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Use the imported types for state (values loaded but not directly consumed by UI)
  const [_statuses, setStatuses] = useState<DataProductStatus[]>([]);
  const [_owners, setOwners] = useState<DataProductOwner[]>([]);

  // Add state for product types (reserved for future use)
  // const [productTypes, setProductTypes] = useState<string[]>([]);

  const [viewMode, setViewMode] = useState<'table' | 'graph'>('table');

  // Subscription filter state
  const [showMySubscriptions, setShowMySubscriptions] = useState(false);
  const [mySubscribedProductIds, setMySubscribedProductIds] = useState<Set<string>>(new Set());
  const [_subscriptionsLoading, _setSubscriptionsLoading] = useState(false);

  const api = useApi();
  const { get, post, delete: deleteApi } = api;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  const navigate = useNavigate();
  const { getDomainIdByName } = useDomains();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  // Get permissions
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const featureId = 'data-products'; // ID for this feature

  // Get project context
  const { currentProject, hasProjectContext } = useProjectContext();

  // Determine if user has specific access levels
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  // Fetch initial data for the table and dropdowns
  useEffect(() => {
    // Set breadcrumbs for this top-level view
    setStaticSegments([]); // No static parents other than Home
    setDynamicTitle(t('title'));

    const loadInitialData = async () => {
      setLoading(true);
      setError(null);
      try {
        // Build URL with project context if available
        let productsEndpoint = '/api/data-products';
        if (hasProjectContext && currentProject) {
          productsEndpoint += `?project_id=${currentProject.id}`;
        }

        // Fetch products and dropdown values concurrently
        const [productsResp, statusesResp, ownersResp/*, typesResp*/] = await Promise.all([
          get<DataProduct[]>(productsEndpoint),
          get<DataProductStatus[]>('/api/data-products/statuses'),
          get<DataProductOwner[]>('/api/data-products/owners'),
          // get<string[]>('/api/data-products/types'), // Fetch product types (reserved for future use)
        ]);

        // Check responses using the helper
        const productsData = checkApiResponse(productsResp, 'Products');
        const statusesData = checkApiResponse(statusesResp, 'Statuses');
        const ownersData = checkApiResponse(ownersResp, 'Owners');
        // const typesData = checkApiResponse(typesResp, 'Product Types'); // (reserved for future use)

        setProducts(Array.isArray(productsData) ? productsData : []);
        setStatuses(Array.isArray(statusesData) ? statusesData : []);
        setOwners(Array.isArray(ownersData) ? ownersData : []);
        // setProductTypes(Array.isArray(typesData) ? typesData : []); // Set product types (reserved for future use)

      } catch (err: any) {
        console.error('Error fetching initial data:', err);
        setError(err.message || 'Failed to load initial data');
        // Reset state on error
        setProducts([]);
        setStatuses([]);
        // setProductTypes([]); // Reset types on error (reserved for future use)
        setOwners([]);
      } finally {
        setLoading(false);
      }
    };
    // Only load initial data if the user has permission and permissions are loaded
    if (!permissionsLoading && canRead) {
        loadInitialData();
    } else if (!permissionsLoading && !canRead) {
        // Ensure loading is stopped if permissions are loaded but access denied.
        // The permission denied message is handled by the render logic.
        setLoading(false);
        // Clear breadcrumbs if no permission
        setStaticSegments([]);
        setDynamicTitle(null);
    }

    // Cleanup breadcrumbs on unmount
    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [get, canRead, permissionsLoading, setStaticSegments, setDynamicTitle, hasProjectContext, currentProject]);

  // Fetch user's subscriptions
  useEffect(() => {
    const fetchMySubscriptions = async () => {
      if (!canRead) return;
      try {
        const response = await get<DataProduct[]>('/api/data-products/my-subscriptions');
        if (response.data && Array.isArray(response.data)) {
          setMySubscribedProductIds(new Set(response.data.map(p => p.id)));
        }
      } catch (err) {
        console.warn('Failed to fetch subscriptions:', err);
      }
    };
    
    if (!permissionsLoading && canRead) {
      fetchMySubscriptions();
    }
  }, [get, canRead, permissionsLoading]);

  // Toggle subscription filter
  const handleToggleMySubscriptions = () => {
    setShowMySubscriptions(!showMySubscriptions);
  };

  // Filtered products based on subscription filter
  const displayedProducts = useMemo(() => {
    if (!showMySubscriptions) return products;
    return products.filter(p => mySubscribedProductIds.has(p.id));
  }, [products, showMySubscriptions, mySubscribedProductIds]);

  // Function to refetch products list
  const fetchProducts = async () => {
    if (!canRead) return;
    try {
      // Build URL with project context if available
      let endpoint = '/api/data-products';
      if (hasProjectContext && currentProject) {
        endpoint += `?project_id=${currentProject.id}`;
      }

      const response = await get<DataProduct[]>(endpoint);
      const productsData = checkApiResponse(response, 'Products Refetch');
      setProducts(Array.isArray(productsData) ? productsData : []);
    } catch (err: any) {
      console.error('Error refetching products:', err);
      setError(err.message || 'Failed to refresh products list');
      toast({ title: t('messages.error'), description: `${t('messages.fetchError')}: ${err.message}`, variant: 'destructive' });
    }
  };

  // --- Create Dialog Open Handler ---
  const handleOpenCreateDialog = (product?: DataProduct) => {
      if (!canWrite && !product) { // Need write permission to create
          toast({ title: t('permissions.denied'), description: t('permissions.noCreate'), variant: "destructive" });
          return;
      }
       if (!canWrite && product) { // Need write permission to edit
          toast({ title: t('permissions.denied'), description: t('permissions.noEdit'), variant: "destructive" });
          return;
      }
      setProductToEdit(product || null);
      setIsCreateDialogOpen(true);
  };

  // --- Create Dialog Success Handler ---
  const handleCreateSuccess = (savedProduct: DataProduct) => {
    fetchProducts();
    // Navigate to details view for newly created product
    if (savedProduct.id && !productToEdit) {
      navigate(`/data-products/${savedProduct.id}`);
    }
  };

  // --- CRUD Handlers (Keep Delete and Upload here) ---
  const handleDeleteProduct = async (id: string, skipConfirm = false) => {
      if (!canAdmin) {
          toast({ title: t('permissions.denied'), description: t('permissions.noDelete'), variant: "destructive" });
          return;
      }
      if (!skipConfirm && !confirm(t('messages.deleteConfirm'))) {
          return;
      }
      try {
          await deleteApi(`/api/data-products/${id}`);
          toast({ title: t('messages.success'), description: t('messages.deleteSuccess') });
          fetchProducts();
      } catch (err: any) {
          const errorMsg = err.message || t('messages.deleteError');
          toast({ title: t('messages.error'), description: errorMsg, variant: 'destructive' });
          setError(errorMsg);
          if (skipConfirm) throw err;
      }
  };

  // Bulk Delete Handler
  const handleBulkDelete = async (selectedRows: DataProduct[]) => {
      if (!canAdmin) {
          toast({ title: t('permissions.denied'), description: t('permissions.noBulkDelete'), variant: "destructive" });
          return;
      }
      const selectedIds = selectedRows.map(r => r.id).filter((id): id is string => !!id);
      if (selectedIds.length === 0) return;
      if (!confirm(t('bulk.deleteConfirm', { count: selectedIds.length }))) return;

      // Track individual delete statuses
      const results = await Promise.allSettled(selectedIds.map(async (id) => {
          try {
              await deleteApi(`/api/data-products/${id}`);
              // If deleteApi throws on error, we won't reach here on failure
              // If it returns an object like { error: string } on failure, 
              // we need to check that, but the current structure assumes throw.
              return id; // Return ID on success
          } catch (err: any) {
              // Re-throw the error with the ID for better context in the main handler
              throw new Error(`ID ${id}: ${err.message || 'Unknown delete error'}`);
          }
      }));

      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
          toast({ title: t('bulk.deleteSuccess'), description: t('bulk.deleteSuccessCount', { count: successes }) });
      }
      if (failures > 0) {
          const firstError = (results.find(r => r.status === 'rejected') as PromiseRejectedResult)?.reason?.message || t('messages.error');
          toast({ 
              title: t('bulk.deleteError'), 
              description: t('bulk.deleteErrorCount', { count: failures, error: firstError }), 
              variant: 'destructive' 
          });
      }
      fetchProducts();
  };

  // Bulk Request Access
  const handleBulkRequestAccess = async (selectedRows: DataProduct[]) => {
      const selectedIds = selectedRows.map(r => r.id).filter((id): id is string => !!id);
      if (selectedIds.length === 0) return;
      try {
          toast({ title: t('access.submitting'), description: t('access.requestingAccess', { count: selectedIds.length }) });
          // Submit individual requests for each entity (Access Grants API requires single entity_id)
          const results = await Promise.all(
            selectedIds.map(id =>
              fetch('/api/access-grants/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_type: 'data_product', entity_id: id, permission_level: 'READ' })
              })
            )
          );
          const failed = results.filter(r => !r.ok);
          if (failed.length > 0) throw new Error(t('access.requestError'));
          toast({ title: t('access.requestSent'), description: t('access.requestSubmitted') });
          refreshNotifications();
      } catch (e: any) {
          toast({ title: t('messages.error'), description: e.message || t('access.requestError'), variant: 'destructive' });
      }
  };

  // Helper to extract human-readable error message from API error responses
  const extractErrorMessage = (error: any): string => {
    if (!error) return 'Unknown error';
    if (typeof error === 'string') return error;
    if (typeof error === 'object') {
      // Handle structured error objects from the API
      if (error.message) return error.message;
      if (error.detail) {
        if (typeof error.detail === 'string') return error.detail;
        if (error.detail.message) return error.detail.message;
      }
      // Handle array of errors
      if (error.errors && Array.isArray(error.errors)) {
        const firstError = error.errors[0];
        if (typeof firstError === 'string') return firstError;
        if (firstError?.message) return firstError.message;
        return `${error.errors.length} validation error(s) occurred`;
      }
      // Try to stringify, but limit length
      try {
        const str = JSON.stringify(error);
        return str.length > 200 ? str.substring(0, 200) + '...' : str;
      } catch {
        return 'Unknown error format';
      }
    }
    return String(error);
  };

  // Keep File Upload Handlers
  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!canWrite) {
      toast({ title: "Permission Denied", description: "You do not have permission to upload data products.", variant: "destructive" });
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    const file = event.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setError(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await post<{ count: number }>('/api/data-products/upload', formData);

      if (response.error) {
        // Extract meaningful message from potentially complex error object
        const errorMsg = extractErrorMessage(response.error);
        
        // Check if this might be a Data Contract file uploaded by mistake
        const isLikelyODCSContract = errorMsg.toLowerCase().includes('validation') || 
          errorMsg.toLowerCase().includes('schema') ||
          errorMsg.toLowerCase().includes('odcs');
        
        if (isLikelyODCSContract) {
          throw new Error(
            `${errorMsg}\n\nHint: This page is for Data Products (ODPS format). ` +
            `If you're trying to upload a Data Contract (ODCS format), please use the Data Contracts page instead.`
          );
        }
        throw new Error(errorMsg);
      }

      const count = response.data?.count ?? 0;
      toast({
        title: t('upload.success'),
        description: t('upload.successMessage', { filename: file.name, count }),
      });
      await fetchProducts();

    } catch (err: any) {
      console.error('Error uploading file:', err);
      const errorMsg = err.message || t('upload.unexpectedError');
      toast({
          title: t('upload.failed'),
          description: errorMsg,
          variant: "destructive",
          duration: 10000, // Show longer for detailed errors
      });
      setError(errorMsg);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const triggerFileUpload = () => {
    fileInputRef.current?.click();
  };

  // --- Genie Space Handler ---
  const handleCreateGenieSpace = async (selectedRows: DataProduct[]) => {
      if (!canWrite) {
          toast({ title: t('permissions.denied'), description: t('permissions.noGenieSpace'), variant: "destructive" });
          return;
      }
      const selectedIds = selectedRows.map(r => r.id).filter((id): id is string => !!id);
      if (selectedIds.length === 0) {
          toast({ title: t('genie.noSelection'), description: t('genie.selectAtLeastOne'), variant: "default" });
          return;
      }

      if (!confirm(t('genie.createConfirm', { count: selectedIds.length }))) {
          return;
      }

      toast({ title: t('genie.initiating'), description: t('genie.requestingCreation', { count: selectedIds.length }) });

      try {
          const response = await post('/api/data-products/genie-space', { product_ids: selectedIds });
          
          if (response.error) {
              throw new Error(response.error);
          }
          if (response.data && typeof response.data === 'object' && 'detail' in response.data) {
              throw new Error(response.data.detail as string);
          }

          toast({ title: t('genie.requestSubmitted'), description: t('genie.willBeNotified') });
          refreshNotifications();

      } catch (err: any) {
          console.error('Error initiating Genie Space creation:', err);
          const errorMsg = err.message || t('genie.creationError');
          toast({ title: t('messages.error'), description: errorMsg, variant: 'destructive' });
          setError(errorMsg);
      }
  };

  // --- Define these outside the columns definition --- 
  const handleEditClick = (product: DataProduct) => {
      handleOpenCreateDialog(product);
  };

  const handleDeleteClick = (product: DataProduct) => {
       if (product.id) {
          handleDeleteProduct(product.id, false);
       }
  };

  // Keep Status Color Helper (used by table column)
  const getStatusColor = (status: string | undefined): "default" | "secondary" | "destructive" | "outline" => {
    const lowerStatus = status?.toLowerCase() || '';
    if (lowerStatus.includes('active')) return 'default';
    if (lowerStatus.includes('development')) return 'secondary';
    if (lowerStatus.includes('retired') || lowerStatus.includes('deprecated')) return 'outline';
    if (lowerStatus.includes('deleted') || lowerStatus.includes('archived')) return 'destructive';
    return 'default';
  };

  // --- Column Definitions (Keep as they are for the DataTable) ---
  const columns = useMemo<ColumnDef<DataProduct>[]>(() => [
    {
      accessorKey: "info.title",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.title')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const product = row.original;
        const domainName = product.domain;
        const domainId = getDomainIdByName(domainName);
        return (
          <div>
            <div className="font-medium">{product.name || 'Unnamed Product'}</div>
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
      accessorKey: "team.members",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.owner')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const owner = row.original.team?.members?.find(m => m.role === 'owner');
        return <div>{owner?.name || owner?.username || t('common:states.notAvailable')}</div>;
      },
    },
    {
      accessorKey: "version",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.version')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => <Badge variant="secondary">{row.original.version}</Badge>,
    },
    {
      accessorKey: "outputPorts",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.type')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const firstOutputPort = row.original.outputPorts?.[0];
        const productType = firstOutputPort?.type;
        return productType ? 
          <Badge variant="outline">{productType}</Badge> : t('common:states.notAvailable');
      },
    },
    {
      accessorKey: "status",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.status')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        row.original.status ? (
          <div className="flex items-center gap-1.5">
            <Badge variant={getStatusColor(row.original.status)}>{row.original.status}</Badge>
            {row.original.draftOwnerId && (
              <Badge variant="secondary" className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">Personal Draft</Badge>
            )}
          </div>
        ) : t('common:states.notAvailable')
      ),
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
      accessorKey: "created_at",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.created')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => row.original.created_at ? <RelativeDate date={row.original.created_at} /> : t('common:states.notAvailable'),
    },
    {
      accessorKey: "updated_at",
      header: ({ column }: { column: Column<DataProduct, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.updated')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => <RelativeDate date={row.original.updated_at} />,
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const product = row.original;
        return (
          <div className="flex space-x-1 justify-end">
            <Button
                variant="ghost"
                size="icon"
                onClick={() => handleEditClick(product)}
                disabled={!canWrite || permissionsLoading}
                title={canWrite ? "Edit" : "Edit (Permission Denied)"}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            {product.id && (
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive hover:text-destructive"
                onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteClick(product);
                }}
                disabled={!canAdmin || permissionsLoading}
                title={canAdmin ? "Delete" : "Delete (Permission Denied)"}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        );
      },
    },
  ], [handleOpenCreateDialog, handleDeleteProduct, getStatusColor, canWrite, canAdmin, permissionsLoading, navigate]);

  // --- Button Variant Logic (Moved outside) ---
  // --- Render Logic ---
  return (
    <div className="py-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Package className="w-8 h-8" />
          {t('title')}
        </h1>
      </div>

      {/* 1. Check Permissions Loading */}
      {permissionsLoading ? (
        <ListViewSkeleton columns={7} rows={5} toolbarButtons={3} />
      ) : !canRead ? (
        // 2. Check Read Permission (if permissions loaded)
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t('permissions.noView')}</AlertDescription>
        </Alert>
      ) : loading ? (
        // 3. Check Data Loading (if permissions OK)
        <ListViewSkeleton columns={7} rows={5} toolbarButtons={3} />
      ) : (
        // 5. Render Content (if permissions OK and data loaded)
        <div className="space-y-4">
          {/* Show dismissible error alert if there's an error (e.g., upload failure) */}
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
          <div className="flex items-center justify-end">
            <ViewModeToggle
              currentView={viewMode}
              onViewChange={setViewMode}
              tableViewIcon={<TableIcon className="h-4 w-4" />}
              graphViewIcon={<Workflow className="h-4 w-4" />}
            />
          </div>

          {viewMode === 'table' ? (
            <DataTable
              columns={columns}
              data={displayedProducts}
              searchColumn="info.title"
              storageKey="data-products-sort"
              toolbarActions={
                <>
                  {/* My Subscriptions Filter Toggle */}
                  <Button
                    onClick={handleToggleMySubscriptions}
                    className="gap-2 h-9"
                    variant={showMySubscriptions ? "default" : "outline"}
                    title={showMySubscriptions ? t('toolbar.showAll') : t('toolbar.showSubscriptions')}
                  >
                    {showMySubscriptions ? (
                      <Bell className="h-4 w-4" />
                    ) : (
                      <BellOff className="h-4 w-4" />
                    )}
                    {showMySubscriptions ? t('toolbar.mySubscriptionsCount', { count: mySubscribedProductIds.size }) : t('filters.mySubscriptions')}
                  </Button>
                  {/* Create Button - Conditionally enabled */}
                  <Button
                      onClick={() => handleOpenCreateDialog()}
                      className="gap-2 h-9"
                      disabled={!canWrite || permissionsLoading}
                      title={canWrite ? t('toolbar.createProduct') : t('permissions.denied')}
                  >
                    <Plus className="h-4 w-4" />
                    {t('toolbar.createProduct')}
                  </Button>
                  {/* Upload Button - Conditionally enabled */}
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                            onClick={triggerFileUpload}
                            className="gap-2 h-9"
                            variant="outline"
                            disabled={isUploading || !canWrite || permissionsLoading}
                        >
                          <Upload className="h-4 w-4" />
                          {isUploading ? (<><Loader2 className="mr-2 h-4 w-4 animate-spin" /> {t('upload.uploading')}</>) : t('toolbar.uploadFile')}
                          <HelpCircle className="h-3 w-3 ml-1 opacity-50" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="max-w-xs">
                        <p className="font-medium">{t('upload.tooltipTitle')}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('upload.tooltipDescription')}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('upload.tooltipHint')}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileChange}
                    accept=".json,.yaml,.yml"
                    style={{ display: 'none' }}
                  />
                </>
              }
            bulkActions={(selectedRows) => {
              // Remove view toggle logic from here
              return (
                <>
                  <Button
                      variant="outline"
                      size="sm"
                      className="h-9 gap-1"
                      onClick={() => handleBulkRequestAccess(selectedRows)}
                      disabled={selectedRows.length === 0}
                      title={t('bulk.requestAccessTitle')}
                  >
                      <KeyRound className="w-4 h-4 mr-1" />
                      {t('bulk.requestAccess', { count: selectedRows.length })}
                  </Button>
                  <Button
                      variant="outline"
                      size="sm"
                      className="h-9 gap-1"
                      onClick={() => handleCreateGenieSpace(selectedRows)}
                      disabled={selectedRows.length === 0 || !canWrite}
                      title={canWrite ? t('bulk.createGenieSpaceTitle') : t('permissions.denied')}
                  >
                      <Sparkles className="w-4 h-4 mr-1" />
                      {t('bulk.createGenieSpace', { count: selectedRows.length })}
                  </Button>
                  <Button
                      variant="destructive"
                      size="sm"
                      className="h-9 gap-1"
                      onClick={() => handleBulkDelete(selectedRows)}
                      disabled={selectedRows.length === 0 || !canAdmin}
                      title={canAdmin ? t('bulk.deleteTitle') : t('permissions.denied')}
                  >
                      <Trash2 className="w-4 h-4 mr-1" />
                      {t('bulk.deleteSelected', { count: selectedRows.length })}
                  </Button>
                </>
              );
            }}
            onRowClick={(row) => {
              const productId = row.original.id;
              if (productId) {
                navigate(`/data-products/${productId}`);
              } else {
                console.warn("Cannot navigate: Product ID is missing.", row.original);
                toast({ title: t('navigation.error'), description: t('navigation.missingId'), variant: "default" });
              }
            }}
          />
          ) : (
            <DataProductGraphView 
                products={displayedProducts} 
                viewMode={viewMode}
                setViewMode={setViewMode}
                navigate={navigate}
            />
          )}
        </div>
      )}

      {/* Render the Simple Create Dialog */}
      <DataProductCreateDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
        onSuccess={handleCreateSuccess}
        product={productToEdit || undefined}
        mode={productToEdit ? 'edit' : 'create'}
      />

      {/* Render Toaster component (ideally place in root layout like App.tsx) */}
      <Toaster />
    </div>
  );
} 