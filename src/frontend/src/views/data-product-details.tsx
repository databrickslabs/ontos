import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { DataProduct, InputPort, OutputPort, ManagementPort, TeamMember, Support, SubscriptionResponse, SubscribersListResponse } from '@/types/data-product';
import DataProductCreateDialog from '@/components/data-products/data-product-create-dialog';
import InputPortFormDialog from '@/components/data-products/input-port-form-dialog';
import OutputPortFormDialog from '@/components/data-products/output-port-form-dialog';
import ManagementPortFormDialog from '@/components/data-products/management-port-form-dialog';
import TeamMemberFormDialog from '@/components/data-products/team-member-form-dialog';
import SupportChannelFormDialog from '@/components/data-products/support-channel-form-dialog';
import ImportExportDialog from '@/components/data-products/import-export-dialog';
import ImportTeamMembersDialog from '@/components/data-contracts/import-team-members-dialog';
import { useApi } from '@/hooks/use-api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Loader2, Pencil, Trash2, AlertCircle, Sparkles, CopyPlus, ArrowLeft, Package, KeyRound, Plus, FileText, Download, Bell, BellOff, Users } from 'lucide-react';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import TagChip from '@/components/ui/tag-chip';
import { useToast } from '@/hooks/use-toast';
import { Label } from '@/components/ui/label';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import * as Settings from '@/types/settings';
import { useNotificationsStore } from '@/stores/notifications-store';
import CreateVersionDialog from '@/components/data-products/create-version-dialog';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import type { EntitySemanticLink } from '@/types/semantic-link';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { CommentSidebar } from '@/components/comments';
import { RatingPanel } from '@/components/ratings';
import AccessGrantsPanel from '@/components/access/access-grants-panel';
import { useDomains } from '@/hooks/use-domains';
import RequestProductActionDialog from '@/components/data-products/request-product-action-dialog';
import CommitDraftDialog from '@/components/data-products/commit-draft-dialog';
import EntityCostsPanel from '@/components/costs/entity-costs-panel';
import LinkContractToPortDialog from '@/components/data-products/link-contract-to-port-dialog';
import VersioningRecommendationDialog from '@/components/common/versioning-recommendation-dialog';
import { Link2, Unlink } from 'lucide-react';

/**
 * ODPS v1.0.0 Data Product Details View
 *
 * Displays product with sections for all ODPS entities.
 * Complex nested entities are edited via form dialogs (to be created).
 */

type CheckApiResponseFn = <T>(
  response: { data?: T | { detail?: string }, error?: string | null | undefined },
  name: string
) => T;

const checkApiResponse: CheckApiResponseFn = (response, name) => {
  if (response.error) {
    throw new Error(`${name} fetch failed: ${response.error}`);
  }
  if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
    throw new Error(`${name} fetch failed: ${response.data.detail}`);
  }
  if (response.data === null || response.data === undefined) {
    throw new Error(`${name} fetch returned null or undefined data.`);
  }
  return response.data as any;
};

export default function DataProductDetails() {
  const { t } = useTranslation(['data-products', 'common']);
  const { productId } = useParams<{ productId: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const { get, post, delete: deleteApi } = api;
  const { toast } = useToast();
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);
  const { getDomainName, getDomainIdByName } = useDomains();

  const [product, setProduct] = useState<DataProduct | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isVersionDialogOpen, setIsVersionDialogOpen] = useState(false);
  const [iriDialogOpen, setIriDialogOpen] = useState(false);
  const [links, setLinks] = useState<EntitySemanticLink[]>([]);
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false);
  const [isRequestDialogOpen, setIsRequestDialogOpen] = useState(false);
  const [isVersioningDialogOpen, setIsVersioningDialogOpen] = useState(false);
  const [versioningAnalysis, setVersioningAnalysis] = useState<any>(null);
  const [versioningUserCanOverride, setVersioningUserCanOverride] = useState(false);
  const [pendingUpdate, setPendingUpdate] = useState<any>(null);

  // Dialog states for nested entities
  const [isInputPortDialogOpen, setIsInputPortDialogOpen] = useState(false);
  const [isOutputPortDialogOpen, setIsOutputPortDialogOpen] = useState(false);
  const [isManagementPortDialogOpen, setIsManagementPortDialogOpen] = useState(false);
  const [isTeamMemberDialogOpen, setIsTeamMemberDialogOpen] = useState(false);
  const [isSupportChannelDialogOpen, setIsSupportChannelDialogOpen] = useState(false);
  const [isImportExportDialogOpen, setIsImportExportDialogOpen] = useState(false);
  const [isImportTeamMembersOpen, setIsImportTeamMembersOpen] = useState(false);

  // Editing state for nested entities
  const [editingInputPortIndex, setEditingInputPortIndex] = useState<number | null>(null);
  const [editingOutputPortIndex, setEditingOutputPortIndex] = useState<number | null>(null);
  const [editingManagementPortIndex, setEditingManagementPortIndex] = useState<number | null>(null);
  const [editingTeamMemberIndex, setEditingTeamMemberIndex] = useState<number | null>(null);
  const [editingSupportChannelIndex, setEditingSupportChannelIndex] = useState<number | null>(null);

  // Contract linking states
  const [isLinkContractDialogOpen, setIsLinkContractDialogOpen] = useState(false);
  const [selectedPortForLinking, setSelectedPortForLinking] = useState<number | null>(null);

  // Subscription state
  const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionResponse | null>(null);
  const [subscribers, setSubscribers] = useState<SubscribersListResponse | null>(null);
  const [subscriptionLoading, setSubscriptionLoading] = useState(false);

  // Clone/Commit draft states
  const [isCommitDraftDialogOpen, setIsCommitDraftDialogOpen] = useState(false);
  const [isCloning, setIsCloning] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);

  // Permissions
  const featureId = 'data-products';
  const canRead = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.ADMIN);

  // Versioned editing: determine if product can be edited in place based on status
  // Products with status 'draft', 'sandbox', 'proposed' can be edited directly
  // Products with status 'active' and above must be cloned for editing
  const canEditInPlace = product?.status && ['draft', 'sandbox', 'proposed', 'under_review', 'approved'].includes(product.status.toLowerCase());
  const isPersonalDraft = product?.draftOwnerId != null;
  const isReadOnly = !canEditInPlace && !isPersonalDraft;

  // Combined permission check: can write AND can edit in place (or is personal draft)
  const canModify = canWrite && (canEditInPlace || isPersonalDraft);

  const formatDate = (dateString: string | undefined, fallback: string = 'N/A'): string => {
    if (!dateString) return fallback;
    try {
      return new Date(dateString).toLocaleString();
    } catch (e) {
      return 'Invalid Date';
    }
  };

  const getStatusColor = (status: string | undefined): 'default' | 'secondary' | 'destructive' | 'outline' => {
    const lowerStatus = status?.toLowerCase() || '';
    if (lowerStatus === 'active') return 'default';
    if (lowerStatus === 'draft' || lowerStatus === 'proposed') return 'secondary';
    if (lowerStatus === 'retired' || lowerStatus === 'deprecated') return 'outline';
    return 'default';
  };

  const fetchProductDetails = async () => {
    if (!productId) {
      setError(t('navigation.missingId'));
      setDynamicTitle(null);
      setLoading(false);
      return;
    }
    if (!canRead && !permissionsLoading) {
      setError(t('permissions.noView'));
      setDynamicTitle(t('permissions.denied'));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setStaticSegments([{ label: t('title'), path: '/data-products' }]);
    setDynamicTitle(t('details.loading'));

    try {
      const [productResp, linksResp] = await Promise.all([
        get<DataProduct>(`/api/data-products/${productId}`),
        get<EntitySemanticLink[]>(`/api/semantic-links/entity/data_product/${productId}`),
      ]);

      const productData = checkApiResponse(productResp, 'Product Details');
      setProduct(productData);
      setLinks(Array.isArray(linksResp.data) ? linksResp.data : []);

      // Fetch subscription status for current user
      try {
        const subscriptionResp = await get<SubscriptionResponse>(`/api/data-products/${productId}/subscription`);
        if (subscriptionResp.data) {
          setSubscriptionStatus(subscriptionResp.data);
        }
      } catch (subErr) {
        console.warn('Failed to fetch subscription status:', subErr);
      }

      // Fetch subscribers (for owners/admins)
      if (canWrite || canAdmin) {
        try {
          const subscribersResp = await get<SubscribersListResponse>(`/api/data-products/${productId}/subscribers`);
          if (subscribersResp.data) {
            setSubscribers(subscribersResp.data);
          }
        } catch (subErr) {
          console.warn('Failed to fetch subscribers:', subErr);
        }
      }

      // ODPS v1.0.0: name is at root level
      setDynamicTitle(productData.name || 'Unnamed Product');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch data';
      setError(errorMessage);
      setProduct(null);
      setDynamicTitle('Error');
      toast({ title: 'Error', description: `Failed to load data: ${errorMessage}`, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProductDetails();
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [productId, canRead, permissionsLoading]);

  const handleEdit = () => {
    if (!canWrite) {
      toast({ title: 'Permission Denied', description: 'You do not have permission to edit.', variant: 'destructive' });
      return;
    }
    setIsEditDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!canAdmin || !productId || !product) return;
    if (!confirm(`Delete data product "${product.name}"?`)) return;

    try {
      await deleteApi(`/api/data-products/${productId}`);
      toast({ title: 'Success', description: 'Data product deleted successfully.' });
      navigate('/data-products');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete product';
      toast({ title: 'Error', description: `Failed to delete: ${errorMessage}`, variant: 'destructive' });
    }
  };

  // Clone for editing (creates personal draft)
  const handleCloneForEditing = async () => {
    if (!canWrite || !productId) return;
    setIsCloning(true);
    try {
      const response = await post<DataProduct>(`/api/data-products/${productId}/clone-for-editing`, {});
      if (response.error) {
        throw new Error(response.error);
      }
      if (response.data) {
        toast({ title: 'Draft Created', description: 'Personal draft created. You can now edit it.' });
        // Navigate to the new draft
        navigate(`/data-products/${response.data.id}`);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create draft';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setIsCloning(false);
    }
  };

  // Discard personal draft
  const handleDiscardDraft = async () => {
    if (!canWrite || !productId || !product) return;
    if (!confirm(`Discard this draft? This action cannot be undone.`)) return;
    setIsDiscarding(true);
    try {
      await deleteApi(`/api/data-products/${productId}/discard`);
      toast({ title: 'Draft Discarded', description: 'Personal draft has been discarded.' });
      // Navigate back to products list or parent product
      if (product.parentProductId) {
        navigate(`/data-products/${product.parentProductId}`);
      } else {
        navigate('/data-products');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to discard draft';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setIsDiscarding(false);
    }
  };

  // Subscription handlers
  const handleSubscribe = async () => {
    if (!productId) return;
    setSubscriptionLoading(true);
    try {
      const response = await post<SubscriptionResponse>(`/api/data-products/${productId}/subscribe`, {});
      if (response.data) {
        setSubscriptionStatus(response.data);
        toast({ title: 'Subscribed', description: 'You will now receive notifications about this product.' });
        // Refresh subscribers count
        if (canWrite || canAdmin) {
          const subscribersResp = await get<SubscribersListResponse>(`/api/data-products/${productId}/subscribers`);
          if (subscribersResp.data) {
            setSubscribers(subscribersResp.data);
          }
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to subscribe';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setSubscriptionLoading(false);
    }
  };

  const handleUnsubscribe = async () => {
    if (!productId) return;
    setSubscriptionLoading(true);
    try {
      const response = await deleteApi<SubscriptionResponse>(`/api/data-products/${productId}/subscribe`);
      if (!response.error) {
        // Handle both cases: server returns SubscriptionResponse or 204 No Content
        const subscriptionData: SubscriptionResponse = response.data && 'subscribed' in response.data 
          ? response.data 
          : { subscribed: false };
        setSubscriptionStatus(subscriptionData);
        toast({ title: 'Unsubscribed', description: 'You will no longer receive notifications about this product.' });
        // Refresh subscribers count
        if (canWrite || canAdmin) {
          const subscribersResp = await get<SubscribersListResponse>(`/api/data-products/${productId}/subscribers`);
          if (subscribersResp.data) {
            setSubscribers(subscribersResp.data);
          }
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to unsubscribe';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setSubscriptionLoading(false);
    }
  };

  // Check if product is subscribable (active or certified)
  const isSubscribable = product?.status && ['active', 'certified'].includes(product.status.toLowerCase());

  // Helper function to update product with 409 handling
  const updateProduct = async (updatedProduct: DataProduct, forceUpdate: boolean = false) => {
    if (!productId) return;
    
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (forceUpdate) {
      headers['X-Force-Update'] = 'true';
    }
    
    const res = await fetch(`/api/data-products/${productId}`, {
      method: 'PUT',
      headers,
      body: JSON.stringify(updatedProduct),
    });
    
    // Handle 409 Conflict - versioning required
    if (res.status === 409) {
      const conflictData = await res.json();
      const detail = conflictData.detail;
      
      if (detail && typeof detail === 'object' && detail.requires_versioning) {
        // Store the pending update and show versioning dialog
        setPendingUpdate(updatedProduct);
        setVersioningAnalysis(detail.change_analysis);
        setVersioningUserCanOverride(detail.user_can_override);
        setIsVersioningDialogOpen(true);
        return; // Don't throw, let the dialog handle it
      }
    }
    
    if (!res.ok) throw new Error(`Update failed (${res.status})`);
    await fetchProductDetails();
  };

  // Handlers for versioning dialog
  const handleVersioningUpdateInPlace = async () => {
    if (!pendingUpdate) return;
    try {
      await updateProduct(pendingUpdate, true); // Force update
      setIsVersioningDialogOpen(false);
      setPendingUpdate(null);
      setVersioningAnalysis(null);
      toast({ title: 'Updated', description: 'Product updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update', variant: 'destructive' });
    }
  };

  const handleVersioningCreateNewVersion = async () => {
    if (!productId) return;
    setIsVersioningDialogOpen(false);
    // Open the version creation dialog instead
    setIsVersionDialogOpen(true);
    // The pending update will be discarded - user needs to apply it to the new version
    toast({
      title: 'Create New Version',
      description: 'Creating a new version will clone this product. Apply your changes to the new version after creation.'
    });
  };

  // Nested entity handlers
  const handleAddInputPort = async (port: InputPort) => {
    if (!productId || !product) return;
    try {
      const updatedPorts = [...(product.inputPorts || []), port];
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, inputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to add input port (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add input port');
    }
  };

  const handleUpdateInputPort = async (port: InputPort) => {
    if (!productId || !product || editingInputPortIndex === null) return;
    try {
      const updatedPorts = [...(product.inputPorts || [])];
      updatedPorts[editingInputPortIndex] = port;
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, inputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to update input port (${res.status})`);
      await fetchProductDetails();
      setEditingInputPortIndex(null);
      toast({ title: 'Input Port Updated', description: 'Input port updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update input port', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteInputPort = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this input port?')) return;
    try {
      const updatedPorts = (product.inputPorts || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, inputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to delete input port (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Input Port Deleted', description: 'Input port deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete input port', variant: 'destructive' });
    }
  };

  const handleAddOutputPort = async (port: OutputPort) => {
    if (!productId || !product) return;
    try {
      const updatedPorts = [...(product.outputPorts || []), port];
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, outputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to add output port (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add output port');
    }
  };

  const handleUpdateOutputPort = async (port: OutputPort) => {
    if (!productId || !product || editingOutputPortIndex === null) return;
    try {
      const updatedPorts = [...(product.outputPorts || [])];
      updatedPorts[editingOutputPortIndex] = port;
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, outputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to update output port (${res.status})`);
      await fetchProductDetails();
      setEditingOutputPortIndex(null);
      toast({ title: 'Output Port Updated', description: 'Output port updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update output port', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteOutputPort = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this output port?')) return;
    try {
      const updatedPorts = (product.outputPorts || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, outputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to delete output port (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Output Port Deleted', description: 'Output port deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete output port', variant: 'destructive' });
    }
  };

  const handleAddManagementPort = async (port: ManagementPort) => {
    if (!productId || !product) return;
    try {
      const updatedPorts = [...(product.managementPorts || []), port];
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, managementPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to add management port (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add management port');
    }
  };

  const handleUpdateManagementPort = async (port: ManagementPort) => {
    if (!productId || !product || editingManagementPortIndex === null) return;
    try {
      const updatedPorts = [...(product.managementPorts || [])];
      updatedPorts[editingManagementPortIndex] = port;
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, managementPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to update management port (${res.status})`);
      await fetchProductDetails();
      setEditingManagementPortIndex(null);
      toast({ title: 'Management Port Updated', description: 'Management port updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update management port', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteManagementPort = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this management port?')) return;
    try {
      const updatedPorts = (product.managementPorts || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, managementPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to delete management port (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Management Port Deleted', description: 'Management port deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete management port', variant: 'destructive' });
    }
  };

  const handleAddTeamMember = async (member: TeamMember) => {
    if (!productId || !product) return;
    try {
      const updatedMembers = [...(product.team?.members || []), member];
      const updatedTeam = { ...product.team, members: updatedMembers };
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, team: updatedTeam }),
      });
      if (!res.ok) throw new Error(`Failed to add team member (${res.status})`);
      await fetchProductDetails();
      toast({
        title: 'Team Member Added',
        description: 'Team member added successfully.',
      });
    } catch (e: any) {
      toast({
        title: 'Error',
        description: e?.message || 'Failed to add team member',
        variant: 'destructive',
      });
      throw new Error(e?.message || 'Failed to add team member');
    }
  };

  const handleUpdateTeamMember = async (member: TeamMember) => {
    if (!productId || !product || editingTeamMemberIndex === null) return;
    try {
      const updatedMembers = [...(product.team?.members || [])];
      updatedMembers[editingTeamMemberIndex] = member;
      const updatedTeam = { ...product.team, members: updatedMembers };
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, team: updatedTeam }),
      });
      if (!res.ok) throw new Error(`Failed to update team member (${res.status})`);
      await fetchProductDetails();
      setEditingTeamMemberIndex(null);
      toast({
        title: 'Team Member Updated',
        description: 'Team member updated successfully.',
      });
    } catch (e: any) {
      toast({
        title: 'Error',
        description: e?.message || 'Failed to update team member',
        variant: 'destructive',
      });
      throw new Error(e?.message || 'Failed to update team member');
    }
  };

  const handleDeleteTeamMember = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Remove this team member?')) return;
    try {
      const updatedMembers = (product.team?.members || []).filter((_, i) => i !== index);
      const updatedTeam = { ...product.team, members: updatedMembers };
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, team: updatedTeam }),
      });
      if (!res.ok) throw new Error(`Failed to delete team member (${res.status})`);
      await fetchProductDetails();
      toast({
        title: 'Team Member Removed',
        description: 'Team member removed successfully.',
      });
    } catch (e: any) {
      toast({
        title: 'Error',
        description: e?.message || 'Failed to delete team member',
        variant: 'destructive',
      });
    }
  };

  const handleImportTeamMembers = async (members: TeamMember[]) => {
    if (!productId || !product) return;
    
    try {
      // Append imported members to existing team members
      const existingMembers = product.team?.members || [];
      const updatedMembers = [...existingMembers, ...members];
      const updatedTeam = { ...product.team, members: updatedMembers };
      
      // Convert tags from objects to strings (tag FQNs) if needed
      const tags = Array.isArray(product.tags) 
        ? product.tags.map((tag: any) => typeof tag === 'string' ? tag : (tag.tag_fqn || tag.tagFQN))
        : [];
      
      // Store team assignment metadata in customProperties
      const teamMetadata = {
        property: 'assigned_team',
        value: JSON.stringify({
          team_id: product.owner_team_id,
          team_name: product.owner_team_name,
          assigned_at: new Date().toISOString(),
          member_count: members.length
        }),
        description: 'App team assignment metadata'
      };
      
      const existingCustomProps = product.customProperties || [];
      const updatedCustomProps = [
        ...existingCustomProps.filter((p: any) => p.property !== 'assigned_team'),
        teamMetadata
      ];
      
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          ...product, 
          team: updatedTeam, 
          customProperties: updatedCustomProps,
          tags // Use converted tags
        }),
      });
      
      if (!res.ok) {
        const errorText = await res.text().catch(() => '');
        throw new Error(`Failed to import team members (${res.status}): ${errorText}`);
      }
      
      await fetchProductDetails();
      setIsImportTeamMembersOpen(false);
      
      toast({
        title: 'Team Members Imported',
        description: `Successfully imported ${members.length} team member(s) from ${product.owner_team_name}`,
      });
    } catch (error) {
      console.error('Failed to import team members:', error);
      toast({
        title: 'Import Failed',
        description: error instanceof Error ? error.message : 'Failed to import team members',
        variant: 'destructive',
      });
      throw error;
    }
  };

  const handleAddSupportChannel = async (channel: Support) => {
    if (!productId || !product) return;
    try {
      const updatedChannels = [...(product.support || []), channel];
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, support: updatedChannels }),
      });
      if (!res.ok) throw new Error(`Failed to add support channel (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add support channel');
    }
  };

  const handleUpdateSupportChannel = async (channel: Support) => {
    if (!productId || !product || editingSupportChannelIndex === null) return;
    try {
      const updatedChannels = [...(product.support || [])];
      updatedChannels[editingSupportChannelIndex] = channel;
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, support: updatedChannels }),
      });
      if (!res.ok) throw new Error(`Failed to update support channel (${res.status})`);
      await fetchProductDetails();
      setEditingSupportChannelIndex(null);
      toast({ title: 'Support Channel Updated', description: 'Support channel updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update support channel', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteSupportChannel = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this support channel?')) return;
    try {
      const updatedChannels = (product.support || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, support: updatedChannels }),
      });
      if (!res.ok) throw new Error(`Failed to delete support channel (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Support Channel Deleted', description: 'Support channel deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete support channel', variant: 'destructive' });
    }
  };

  const handleLinkContract = (portIndex: number) => {
    setSelectedPortForLinking(portIndex);
    setIsLinkContractDialogOpen(true);
  };

  const handleUnlinkContract = async (portIndex: number) => {
    if (!productId || !product) return;
    if (!confirm('Unlink contract from this output port?')) return;
    
    try {
      const updatedPorts = [...(product.outputPorts || [])];
      updatedPorts[portIndex] = { ...updatedPorts[portIndex], contractId: undefined };
      
      // Normalize tags to FQN strings or tag_id objects for backend compatibility
      const normalizedTags = product.tags?.map((tag: any) => 
        typeof tag === 'string' ? tag : (tag.fully_qualified_name || { tag_id: tag.tag_id, assigned_value: tag.assigned_value })
      );
      
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          ...product, 
          tags: normalizedTags,
          outputPorts: updatedPorts 
        }),
      });
      
      if (!res.ok) throw new Error(`Failed to unlink contract (${res.status})`);
      
      await fetchProductDetails();
      toast({
        title: 'Contract Unlinked',
        description: 'Contract successfully unlinked from output port',
      });
    } catch (e: any) {
      toast({
        title: 'Error',
        description: e?.message || 'Failed to unlink contract',
        variant: 'destructive',
      });
    }
  };

  const addIri = async (iri: string) => {
    if (!productId) return;
    try {
      const res = await post<EntitySemanticLink>(`/api/semantic-links/`, {
        entity_id: productId,
        entity_type: 'data_product',
        iri,
      });
      if (res.error) throw new Error(res.error);
      await fetchProductDetails();
      setIriDialogOpen(false);
      toast({ title: 'Linked', description: 'IRI linked to data product.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to link IRI', variant: 'destructive' });
    }
  };

  const removeLink = async (linkId: string) => {
    try {
      const res = await fetch(`/api/semantic-links/${linkId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to remove link');
      await fetchProductDetails();
      toast({ title: 'Removed', description: 'IRI link removed.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to remove link', variant: 'destructive' });
    }
  };

  const handleCreateGenieSpace = async () => {
    if (!canWrite || !productId || !product) return;
    if (!confirm(`Create a Genie Space for "${product.name}"?`)) return;

    toast({ title: 'Initiating Genie Space', description: `Requesting Genie Space creation...` });

    try {
      const response = await post('/api/data-products/genie-space', { product_ids: [productId] });
      if (response.error) throw new Error(response.error);
      toast({ title: 'Request Submitted', description: `Genie Space creation initiated.` });
      refreshNotifications();
    } catch (err: any) {
      toast({ title: 'Error', description: err.message || 'Failed to start Genie Space creation.', variant: 'destructive' });
    }
  };

  const handleCreateNewVersion = () => {
    if (!canWrite || !productId || !product) return;
    setIsVersionDialogOpen(true);
  };

  const submitNewVersion = async (newVersionString: string) => {
    if (!productId) return;
    toast({ title: 'Creating New Version', description: `Creating version ${newVersionString}...` });

    try {
      const response = await post<DataProduct>(`/api/data-products/${productId}/versions`, { new_version: newVersionString.trim() });
      const newProduct = response.data;
      if (!newProduct || !newProduct.id) throw new Error('Invalid response when creating version.');

      toast({ title: 'Success', description: `Version ${newVersionString} created!` });
      navigate(`/data-products/${newProduct.id}`);
    } catch (err: any) {
      toast({ title: 'Error', description: err.message || 'Failed to create version.', variant: 'destructive' });
    }
  };

  if (loading || permissionsLoading) {
    return <DetailViewSkeleton cards={5} actionButtons={5} />;
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!product) {
    return (
      <Alert>
        <AlertDescription>Data product not found.</AlertDescription>
      </Alert>
    );
  }

  const domainLabel = product.domain ? (getDomainName(product.domain) || product.domain) : t('common:states.notAssigned');

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate('/data-products')} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to List
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setIsRequestDialogOpen(true)} size="sm">
            <KeyRound className="mr-2 h-4 w-4" /> Request...
          </Button>
          <CommentSidebar
            entityType="data_product"
            entityId={productId!}
            isOpen={isCommentSidebarOpen}
            onToggle={() => setIsCommentSidebarOpen(!isCommentSidebarOpen)}
            className="h-8"
          />
          <Button variant="outline" onClick={handleCreateGenieSpace} disabled={!canModify} size="sm">
            <Sparkles className="mr-2 h-4 w-4" /> Create Genie Space
          </Button>
          {/* Clone for Editing - shown when product is read-only */}
          {isReadOnly && canWrite && (
            <Button variant="outline" onClick={handleCloneForEditing} disabled={isCloning} size="sm">
              {isCloning ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CopyPlus className="mr-2 h-4 w-4" />
              )}
              Clone for Editing
            </Button>
          )}
          {/* Commit Draft - shown when this is a personal draft */}
          {isPersonalDraft && canWrite && (
            <Button variant="default" onClick={() => setIsCommitDraftDialogOpen(true)} size="sm">
              <FileText className="mr-2 h-4 w-4" /> Commit Changes
            </Button>
          )}
          {/* Discard Draft - shown when this is a personal draft */}
          {isPersonalDraft && canWrite && (
            <Button variant="outline" onClick={handleDiscardDraft} disabled={isDiscarding} size="sm">
              {isDiscarding ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-2 h-4 w-4" />
              )}
              Discard Draft
            </Button>
          )}
          {/* New Version - only for editable products */}
          {!isReadOnly && (
            <Button variant="outline" onClick={handleCreateNewVersion} disabled={!canModify} size="sm">
              <CopyPlus className="mr-2 h-4 w-4" /> New Version
            </Button>
          )}
          <Button variant="outline" onClick={() => setIsImportExportDialogOpen(true)} size="sm">
            <Download className="mr-2 h-4 w-4" /> Export ODPS
          </Button>
          {/* Subscribe/Unsubscribe Button */}
          {isSubscribable && (
            subscriptionStatus?.subscribed ? (
              <Button
                variant="outline"
                onClick={handleUnsubscribe}
                disabled={subscriptionLoading}
                size="sm"
              >
                {subscriptionLoading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <BellOff className="mr-2 h-4 w-4" />
                )}
                Unsubscribe
              </Button>
            ) : (
              <Button
                variant="default"
                onClick={handleSubscribe}
                disabled={subscriptionLoading}
                size="sm"
              >
                {subscriptionLoading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Bell className="mr-2 h-4 w-4" />
                )}
                Subscribe
              </Button>
            )
          )}
          {/* Edit - only enabled for editable products */}
          {canModify && (
            <Button variant="outline" onClick={handleEdit} size="sm">
              <Pencil className="mr-2 h-4 w-4" /> Edit
            </Button>
          )}
          <Button variant="destructive" onClick={handleDelete} disabled={!canAdmin} size="sm">
            <Trash2 className="mr-2 h-4 w-4" /> Delete
          </Button>
        </div>
      </div>

      {/* Personal Draft Banner */}
      {isPersonalDraft && (
        <Alert className="bg-blue-50 border-blue-300 dark:bg-blue-950 dark:border-blue-800">
          <AlertCircle className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          <AlertDescription className="text-blue-800 dark:text-blue-200">
            <strong>Personal Draft</strong> - This is your personal draft. Only you can see it. Commit changes to share with your team.
          </AlertDescription>
        </Alert>
      )}

      {/* Read-Only Banner */}
      {isReadOnly && (
        <Alert className="bg-yellow-50 border-yellow-300 dark:bg-yellow-950 dark:border-yellow-800">
          <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
          <AlertDescription className="text-yellow-800 dark:text-yellow-200">
            <strong>Read-Only</strong> - This product is {product?.status?.toLowerCase()}. Clone to create a personal draft for editing.
          </AlertDescription>
        </Alert>
      )}

      {/* Basic Info Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <Package className="mr-3 h-7 w-7 text-primary" />
            {product.name || 'Unnamed Product'}
          </CardTitle>
          <CardDescription className="pt-1">
            {product.description?.purpose || 'No description provided'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid md:grid-cols-3 gap-x-6 gap-y-2">
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Status:</Label>
              <Badge variant={getStatusColor(product.status)} className="text-xs">
                {product.status || t('common:states.notAvailable')}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Version:</Label>
              <Badge variant="outline" className="text-xs">{product.version || t('common:states.notAvailable')}</Badge>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Domain:</Label>
              {product.domain && getDomainIdByName(domainLabel) ? (
                <span
                  className="text-xs cursor-pointer text-primary hover:underline truncate"
                  onClick={() => navigate(`/data-domains/${getDomainIdByName(domainLabel)}`)}
                >
                  {domainLabel}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">{domainLabel}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Project:</Label>
              {(product as any).project_id && product.project_name ? (
                <span
                  className="text-xs cursor-pointer text-primary hover:underline truncate"
                  onClick={() => navigate(`/projects/${(product as any).project_id}`)}
                  title={`Project ID: ${(product as any).project_id}`}
                >
                  {product.project_name}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">{t('common:states.notAssigned')}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Tenant:</Label>
              <span className="text-xs text-muted-foreground truncate">{product.tenant || t('common:states.notAssigned')}</span>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Owner:</Label>
              {product.owner_team_id && product.owner_team_name ? (
                <span
                  className="text-xs cursor-pointer text-primary hover:underline truncate"
                  onClick={() => navigate(`/teams/${product.owner_team_id}`)}
                  title={`Team ID: ${product.owner_team_id}`}
                >
                  {product.owner_team_name}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">{t('common:states.notAssigned')}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">API Ver:</Label>
              {product.apiVersion ? (
                <Badge variant="outline" className="text-xs">{product.apiVersion}</Badge>
              ) : (
                <span className="text-xs text-muted-foreground">N/A</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Created:</Label>
              <span className="text-xs text-muted-foreground truncate">{formatDate(product.created_at)}</span>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Updated:</Label>
              <span className="text-xs text-muted-foreground truncate">{formatDate(product.updated_at)}</span>
            </div>
          </div>

          <div className="pt-2 border-t">
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="flex-1 min-w-0">
                <Label className="text-xs text-muted-foreground mb-1.5 block">Tags:</Label>
                <div className="flex flex-wrap gap-1">
                  {(product.tags || []).length > 0 ? (
                    (product.tags || []).map((tag, index) => (
                      <TagChip key={index} tag={tag} size="sm" />
                    ))
                  ) : (
                    <span className="text-xs text-muted-foreground">No tags</span>
                  )}
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <Label className="text-xs text-muted-foreground mb-1.5 block">Linked Business Concepts:</Label>
                <LinkedConceptChips
                  links={links}
                  onRemove={canModify ? removeLink : undefined}
                  trailing={canModify ? <Button size="sm" variant="outline" onClick={() => setIriDialogOpen(true)} className="h-6 text-xs">Add</Button> : undefined}
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ODPS Structured Description */}
      {product.description && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center">
                <FileText className="mr-2 h-5 w-5" />
                Description
              </span>
              {canModify && <Button size="sm" variant="outline" onClick={handleEdit}><Pencil className="h-4 w-4" /></Button>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {product.description.purpose && (
              <div>
                <Label>Purpose:</Label>
                <p className="text-sm mt-1">{product.description.purpose}</p>
              </div>
            )}
            {product.description.limitations && (
              <div>
                <Label>Limitations:</Label>
                <p className="text-sm mt-1">{product.description.limitations}</p>
              </div>
            )}
            {product.description.usage && (
              <div>
                <Label>Usage:</Label>
                <p className="text-sm mt-1">{product.description.usage}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Input Ports Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Input Ports ({product.inputPorts?.length || 0})</span>
            {canModify && <Button size="sm" onClick={() => setIsInputPortDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Input Port</Button>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {product.inputPorts && product.inputPorts.length > 0 ? (
            <div className="space-y-2">
              {product.inputPorts.map((port, idx) => (
                <div key={idx} className="flex items-start justify-between border rounded p-3">
                  <div className="flex-1">
                    <div className="font-medium">{port.name} (v{port.version})</div>
                    <div className="text-sm text-muted-foreground">Contract: {port.contractId}</div>
                  </div>
                  {canModify && (
                    <div className="flex gap-2 ml-3">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditingInputPortIndex(idx);
                          setIsInputPortDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteInputPort(idx)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No input ports defined</p>
          )}
        </CardContent>
      </Card>

      {/* Output Ports Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Output Ports ({product.outputPorts?.length || 0})</span>
            {canModify && <Button size="sm" onClick={() => setIsOutputPortDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Output Port</Button>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {product.outputPorts && product.outputPorts.length > 0 ? (
            <div className="space-y-2">
              {product.outputPorts.map((port, idx) => (
                <div key={idx} className="border rounded p-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="font-medium">{port.name} (v{port.version})</div>
                      {port.description && <div className="text-sm text-muted-foreground mt-1">{port.description}</div>}
                      {port.contractId && (
                        <div className="mt-2 flex items-center gap-2">
                          <Badge 
                            variant="secondary" 
                            className="cursor-pointer hover:bg-secondary/80"
                            onClick={() => navigate(`/data-contracts/${port.contractId}`)}
                          >
                            Contract: {port.contractName || port.contractId}
                          </Badge>
                        </div>
                      )}
                    </div>
                    {canModify && (
                      <div className="flex gap-2 ml-3">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setEditingOutputPortIndex(idx);
                            setIsOutputPortDialogOpen(true);
                          }}
                          title={t('common:tooltips.editPort')}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        {port.contractId ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleUnlinkContract(idx)}
                            title={t('common:tooltips.unlinkContract')}
                          >
                            <Unlink className="h-4 w-4" />
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleLinkContract(idx)}
                            title={t('common:tooltips.linkContract')}
                          >
                            <Link2 className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDeleteOutputPort(idx)}
                          className="text-destructive hover:text-destructive"
                          title={t('common:tooltips.deletePort')}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No output ports defined</p>
          )}
        </CardContent>
      </Card>

      {/* Management Ports Section (NEW in ODPS v1.0.0) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Management Ports ({product.managementPorts?.length || 0})</span>
            {canModify && <Button size="sm" onClick={() => setIsManagementPortDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Management Port</Button>}
          </CardTitle>
          <CardDescription>Observability, control, and discoverability endpoints</CardDescription>
        </CardHeader>
        <CardContent>
          {product.managementPorts && product.managementPorts.length > 0 ? (
            <div className="space-y-2">
              {product.managementPorts.map((port, idx) => (
                <div key={idx} className="flex items-start justify-between border rounded p-3">
                  <div className="flex-1">
                    <div className="font-medium">{port.name}</div>
                    <div className="text-sm">Content: {port.content}</div>
                    {port.url && <div className="text-sm text-muted-foreground">URL: {port.url}</div>}
                  </div>
                  {canModify && (
                    <div className="flex gap-2 ml-3">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditingManagementPortIndex(idx);
                          setIsManagementPortDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteManagementPort(idx)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No management ports defined</p>
          )}
        </CardContent>
      </Card>

      {/* Team Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Team ({product.team?.members?.length || 0} members)</span>
            <div className="flex gap-2">
              {canWrite && product.owner_team_id && (
                <Button 
                  size="sm" 
                  variant="outline"
                  onClick={() => setIsImportTeamMembersOpen(true)}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Import from Team
                </Button>
              )}
              {canModify && (
                <Button size="sm" onClick={() => setIsTeamMemberDialogOpen(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Member
                </Button>
              )}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {product.team?.members && product.team.members.length > 0 ? (
            <div className="space-y-2">
              {product.team.members.map((member, idx) => (
                <div key={idx} className="flex items-center justify-between p-3 border rounded-lg">
                  <div className="flex items-center gap-3">
                    <Badge variant="outline">{member.role || 'Member'}</Badge>
                    <span className="text-sm">{member.name || member.username}</span>
                  </div>
                  {canModify && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditingTeamMemberIndex(idx);
                          setIsTeamMemberDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteTeamMember(idx)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No team members defined</p>
          )}
        </CardContent>
      </Card>

      {/* Support Channels */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Support Channels ({product.support?.length || 0})</span>
            {canModify && <Button size="sm" onClick={() => setIsSupportChannelDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Channel</Button>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {product.support && product.support.length > 0 ? (
            <div className="space-y-2">
              {product.support.map((channel, idx) => (
                <div key={idx} className="flex items-start justify-between border rounded p-3">
                  <div className="flex-1">
                    <div className="font-medium">{channel.channel}</div>
                    <div className="text-sm">URL: <a href={channel.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{channel.url}</a></div>
                    {channel.tool && <div className="text-sm text-muted-foreground">Tool: {channel.tool}</div>}
                  </div>
                  {canModify && (
                    <div className="flex gap-2 ml-3">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditingSupportChannelIndex(idx);
                          setIsSupportChannelDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteSupportChannel(idx)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No support channels defined</p>
          )}
        </CardContent>
      </Card>

      {/* Subscribers Section (only visible to owners/admins) */}
      {(canWrite || canAdmin) && subscribers && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              <span>Subscribers ({subscribers.subscriber_count})</span>
            </CardTitle>
            <CardDescription>
              Users subscribed to this product will receive notifications about status changes, compliance issues, and new versions.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {subscribers.subscribers.length > 0 ? (
              <div className="space-y-2">
                {subscribers.subscribers.map((subscriber, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 border rounded-lg">
                    <div className="flex items-center gap-3">
                      <Bell className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <span className="text-sm font-medium">{subscriber.email}</span>
                        {subscriber.reason && (
                          <p className="text-xs text-muted-foreground">{subscriber.reason}</p>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(subscriber.subscribed_at)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No subscribers yet</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Access Grants Panel */}
      {productId && (
        <AccessGrantsPanel
          entityType="data_product"
          entityId={productId}
          canManage={canModify}
          showPendingRequests={canModify}
        />
      )}

      {/* Metadata Panel */}
      <EntityMetadataPanel entityId={productId!} entityType="data_product" />

      {/* Ratings Panel */}
      <RatingPanel
        entityType="data_product"
        entityId={productId!}
        title={t('details.ratings.title', 'Ratings & Reviews')}
        showDistribution
        allowSubmit={canRead}
      />

      {/* Costs Panel */}
      <EntityCostsPanel entityId={productId!} entityType="data_product" />

      {/* Dialogs */}
      <DataProductCreateDialog
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        onSuccess={() => {
          setIsEditDialogOpen(false);
          fetchProductDetails();
        }}
        product={product || undefined}
        mode="edit"
      />

      <CreateVersionDialog
        isOpen={isVersionDialogOpen}
        onOpenChange={setIsVersionDialogOpen}
        onSubmit={submitNewVersion}
        currentVersion={product.version || '1.0.0'}
        productTitle={product.info?.title || product.id || ''}
      />

      <ConceptSelectDialog
        isOpen={iriDialogOpen}
        onOpenChange={setIriDialogOpen}
        onSelect={addIri}
      />

      <RequestProductActionDialog
        isOpen={isRequestDialogOpen}
        onOpenChange={setIsRequestDialogOpen}
        productId={productId!}
        productName={product.name}
        productStatus={product.status}
        onSuccess={() => fetchProductDetails()}
        canDirectStatusChange={canWrite || canAdmin}
      />

      {/* Commit Draft Dialog */}
      <CommitDraftDialog
        isOpen={isCommitDraftDialogOpen}
        onOpenChange={setIsCommitDraftDialogOpen}
        productId={productId!}
        productName={product.name}
        onSuccess={() => fetchProductDetails()}
      />

      {/* Nested Entity Form Dialogs */}
      <InputPortFormDialog
        isOpen={isInputPortDialogOpen}
        onOpenChange={(open) => {
          setIsInputPortDialogOpen(open);
          if (!open) setEditingInputPortIndex(null);
        }}
        onSubmit={editingInputPortIndex !== null ? handleUpdateInputPort : handleAddInputPort}
        initial={editingInputPortIndex !== null ? product?.inputPorts?.[editingInputPortIndex] : undefined}
      />

      <OutputPortFormDialog
        isOpen={isOutputPortDialogOpen}
        onOpenChange={(open) => {
          setIsOutputPortDialogOpen(open);
          if (!open) setEditingOutputPortIndex(null);
        }}
        onSubmit={editingOutputPortIndex !== null ? handleUpdateOutputPort : handleAddOutputPort}
        product={product || undefined}
        initial={editingOutputPortIndex !== null ? product?.outputPorts?.[editingOutputPortIndex] : undefined}
      />

      <ManagementPortFormDialog
        isOpen={isManagementPortDialogOpen}
        onOpenChange={(open) => {
          setIsManagementPortDialogOpen(open);
          if (!open) setEditingManagementPortIndex(null);
        }}
        onSubmit={editingManagementPortIndex !== null ? handleUpdateManagementPort : handleAddManagementPort}
        initial={editingManagementPortIndex !== null ? product?.managementPorts?.[editingManagementPortIndex] : undefined}
      />

      <TeamMemberFormDialog
        isOpen={isTeamMemberDialogOpen}
        onOpenChange={(open) => {
          setIsTeamMemberDialogOpen(open);
          if (!open) setEditingTeamMemberIndex(null);
        }}
        onSubmit={editingTeamMemberIndex !== null ? handleUpdateTeamMember : handleAddTeamMember}
        initial={editingTeamMemberIndex !== null ? product?.team?.members?.[editingTeamMemberIndex] : undefined}
      />

      <SupportChannelFormDialog
        isOpen={isSupportChannelDialogOpen}
        onOpenChange={(open) => {
          setIsSupportChannelDialogOpen(open);
          if (!open) setEditingSupportChannelIndex(null);
        }}
        onSubmit={editingSupportChannelIndex !== null ? handleUpdateSupportChannel : handleAddSupportChannel}
        initial={editingSupportChannelIndex !== null ? product?.support?.[editingSupportChannelIndex] : undefined}
      />

      {/* ODPS v1.0.0 Import/Export */}
      <ImportExportDialog
        isOpen={isImportExportDialogOpen}
        onOpenChange={setIsImportExportDialogOpen}
        currentProduct={product}
      />

      {/* Import Team Members Dialog */}
      {product.owner_team_id && (
        <ImportTeamMembersDialog
          isOpen={isImportTeamMembersOpen}
          onOpenChange={setIsImportTeamMembersOpen}
          entityId={productId!}
          entityType="product"
          teamId={product.owner_team_id}
          teamName={product.owner_team_name || product.owner_team_id}
          onImport={handleImportTeamMembers}
        />
      )}

      {/* Link Contract to Port Dialog */}
      <LinkContractToPortDialog
        isOpen={isLinkContractDialogOpen}
        onOpenChange={setIsLinkContractDialogOpen}
        productId={productId!}
        portIndex={selectedPortForLinking!}
        currentPort={selectedPortForLinking !== null ? product?.outputPorts?.[selectedPortForLinking] : undefined}
        onSuccess={() => {
          fetchProductDetails();
          setIsLinkContractDialogOpen(false);
          setSelectedPortForLinking(null);
        }}
      />

      {/* Versioning Recommendation Dialog */}
      <VersioningRecommendationDialog
        isOpen={isVersioningDialogOpen}
        onOpenChange={setIsVersioningDialogOpen}
        analysis={versioningAnalysis}
        userCanOverride={versioningUserCanOverride}
        onUpdateInPlace={handleVersioningUpdateInPlace}
        onCreateNewVersion={handleVersioningCreateNewVersion}
      />
    </div>
  );
}
