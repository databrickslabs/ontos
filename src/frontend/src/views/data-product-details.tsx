import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
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
import { useApprovalWizardTrigger } from '@/hooks/use-approval-wizard-trigger';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Loader2, Pencil, Trash2, AlertCircle, Sparkles, CopyPlus, ArrowLeft, Package, KeyRound, Plus, FileText, Download, Bell, BellOff, Users, ShieldCheck, Globe } from 'lucide-react';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import TagChip from '@/components/ui/tag-chip';
import { useToast } from '@/hooks/use-toast';
import { Label } from '@/components/ui/label';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import { FeatureAccessLevel } from '@/types/settings';
import * as Settings from '@/types/settings';
import { useNotificationsStore } from '@/stores/notifications-store';
import CreateVersionDialog from '@/components/data-products/create-version-dialog';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import type { EntitySemanticLink } from '@/types/semantic-link';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import { CommentSidebar } from '@/components/comments';
import { RatingPanel } from '@/components/ratings';
import AccessGrantsPanel from '@/components/access/access-grants-panel';
import { useDomains } from '@/hooks/use-domains';
import RequestProductActionDialog from '@/components/data-products/request-product-action-dialog';
import CommitDraftDialog from '@/components/data-products/commit-draft-dialog';
import ApprovalWizardDialog from '@/components/workflows/approval-wizard-dialog';
import EntityCostsPanel from '@/components/costs/entity-costs-panel';
import EntityQualityPanel from '@/components/quality/entity-quality-panel';
import LinkContractToPortDialog from '@/components/data-products/link-contract-to-port-dialog';
import VersioningRecommendationDialog from '@/components/common/versioning-recommendation-dialog';
import { Link2, Unlink, GitBranch } from 'lucide-react';
import { AssetSelector } from '@/components/common/asset-selector';
import { EntityTreePanel } from '@/components/common/entity-tree-panel';
import { BusinessLineageView } from '@/components/lineage';
import { ReadinessChecklist } from '@/components/data-products/readiness-checklist';
import { LineageEditor } from '@/components/common/lineage-editor';
import { useCopilotContext } from '@/hooks/use-copilot-context';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Progress } from '@/components/ui/progress';
import type { QualitySummary } from '@/types/quality';
import LifecycleSummaryPanel from '@/components/common/lifecycle-summary-panel';
import { DirectCertifyDialog, DirectPublishDialog } from '@/components/common/direct-lifecycle-dialogs';
import type { CertificationLevel, PublicationScope } from '@/types/lifecycle';
import { userHasApprovalPrivilege } from '@/lib/permissions';
import { ApprovalEntity } from '@/types/settings';

/**
 * ODPS v1.0.0 Data Product Details View
 *
 * Displays product with sections for all ODPS entities.
 * Complex nested entities are edited via form dialogs (to be created).
 */

type ViewMode = 'minimal' | 'medium' | 'large'
const VIEW_MODE_STORAGE_KEY = 'data-product-view-mode'

const VIEW_MODES: ReadonlyArray<ViewMode> = ['minimal', 'medium', 'large'];

/**
 * Parse a value retrieved from `localStorage[VIEW_MODE_STORAGE_KEY]`. Returns
 * the value when it's one of the known modes, otherwise `null` so the caller
 * can apply its default.
 */
export function parseStoredViewMode(stored: string | null | undefined): ViewMode | null {
  if (!stored) return null;
  return (VIEW_MODES as ReadonlyArray<string>).includes(stored) ? (stored as ViewMode) : null;
}

/**
 * Pure helper that maps (product owner team membership, permission level)
 * to the default ViewMode. Owner-team members get the full 'large' view;
 * write/admin users get 'medium'; everyone else 'minimal'.
 */
export function computeDefaultViewMode(args: {
  ownerTeamId?: string | null;
  userGroups?: ReadonlyArray<string> | null;
  permissionLevel?: FeatureAccessLevel | null;
}): ViewMode {
  const { ownerTeamId, userGroups, permissionLevel } = args;
  if (ownerTeamId && userGroups && userGroups.includes(ownerTeamId)) {
    return 'large';
  }
  if (
    permissionLevel === FeatureAccessLevel.READ_WRITE ||
    permissionLevel === FeatureAccessLevel.ADMIN ||
    permissionLevel === FeatureAccessLevel.FULL
  ) {
    return 'medium';
  }
  return 'minimal';
}

/**
 * Pure ViewMode → section visibility predicate. The component-level wrapper
 * just closes over the current `viewMode`.
 */
export function shouldShowSectionForViewMode(viewMode: ViewMode, section: string): boolean {
  switch (viewMode) {
    case 'minimal':
      return ['deliverables', 'description', 'hierarchy'].includes(section);
    case 'medium':
      return !['management-ports', 'support-channels', 'metadata-panel', 'ratings', 'costs', 'quality'].includes(section);
    case 'large':
      return true;
    default:
      return false;
  }
}

/**
 * Format an ISO date string for display. Falls back to `fallback` when input
 * is empty / undefined, and to a literal `Invalid Date` when `Date` rejects it.
 */
export function formatDateString(dateString: string | undefined | null, fallback: string = 'N/A'): string {
  if (!dateString) return fallback;
  try {
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return 'Invalid Date';
    return d.toLocaleString();
  } catch {
    return 'Invalid Date';
  }
}

/**
 * Map a Data Product status string to a Shadcn Badge variant.
 * Lower-cased internally so `Active`, `ACTIVE`, `active` all map identically.
 */
export function getStatusBadgeVariant(
  status: string | undefined | null,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  const lowerStatus = status?.toLowerCase() || '';
  if (lowerStatus === 'active') return 'default';
  if (lowerStatus === 'draft' || lowerStatus === 'proposed') return 'secondary';
  if (lowerStatus === 'retired' || lowerStatus === 'deprecated') return 'outline';
  return 'default';
}

/**
 * Statuses where a Data Product can still be edited in-place. Anything with a
 * higher lifecycle status (`active`, `retired`, `deprecated`) must be cloned
 * for editing instead.
 */
export const IN_PLACE_EDITABLE_STATUSES: ReadonlyArray<string> = [
  'draft',
  'sandbox',
  'proposed',
  'under_review',
  'approved',
];

export function isStatusEditableInPlace(status: string | undefined | null): boolean {
  if (!status) return false;
  return IN_PLACE_EDITABLE_STATUSES.includes(status.toLowerCase());
}

/**
 * A "personal draft" is a product owned by a single user (not a team) — these
 * stay editable for that user even when the product status would otherwise be
 * locked. The signal is a non-null `draftOwnerId` on the product.
 */
export function isPersonalDraftProduct(product: { draftOwnerId?: string | null } | null | undefined): boolean {
  return product != null && product.draftOwnerId != null;
}

/**
 * Read-only iff the user is not an admin AND the product is neither
 * editable-in-place nor a personal draft. Pure function over the three flags.
 */
export function isProductReadOnly(args: {
  canAdmin: boolean;
  canEditInPlace: boolean;
  isPersonalDraft: boolean;
}): boolean {
  return !args.canAdmin && !args.canEditInPlace && !args.isPersonalDraft;
}

/**
 * Final "can the user modify this product" gate combining role + status flags.
 * Admins can always modify; write-class users can modify when the product is
 * editable-in-place or a personal draft.
 */
export function canUserModifyProduct(args: {
  canAdmin: boolean;
  canWrite: boolean;
  canEditInPlace: boolean;
  isPersonalDraft: boolean;
}): boolean {
  if (args.canAdmin) return true;
  return args.canWrite && (args.canEditInPlace || args.isPersonalDraft);
}

/**
 * Resolve the human-readable domain label for a product. Falls back to the
 * raw domain id when the lookup misses, and to a "not assigned" sentinel when
 * the product has no domain at all.
 */
export function resolveDomainLabel(args: {
  domain: string | undefined | null;
  resolveName: (id: string) => string | undefined | null;
  notAssignedLabel: string;
}): string {
  const { domain, resolveName, notAssignedLabel } = args;
  if (!domain) return notAssignedLabel;
  return resolveName(domain) || domain;
}

/**
 * Whether the product is in the "active" lifecycle state. Centralised so the
 * "active" magic string lives in one place — used by the lifecycle approve /
 * deprecate gates.
 */
export function isProductActive(status: string | undefined | null): boolean {
  return (status?.toLowerCase() || '') === 'active';
}

/**
 * Output port → asset relationship predicates.
 *
 * Mirrors the `portHas*` predicates declared in `ontos-ontology.ttl` (lines
 * 838–891). The ontology intentionally restricts these relationships to
 * *deliverable* asset types — not container types like Catalog or Schema.
 * The picker filter and the POST predicate selection both flow from this map,
 * so they stay in lock-step with the ontology.
 *
 * If a new deliverable type is added to the TTL, add it here. If a caller
 * tries to link an unsupported type the POST is skipped with a warning;
 * the backend at `entity_relationships_manager.py` is the actual security
 * gate and will return 422 for any invalid (predicate, range) tuple.
 */
export const PORT_TO_ASSET_PREDICATE: Readonly<Record<string, string>> = {
  Table: 'portHasTable',
  View: 'portHasView',
  Dataset: 'portHasDataset',
  APIEndpoint: 'portHasEndpoint',
  MLModel: 'portHasModel',
};

const PORT_DELIVERABLE_ASSET_TYPES = Object.keys(PORT_TO_ASSET_PREDICATE);

/**
 * Look up the ontology predicate for a port → asset relationship.
 * Returns `undefined` for unsupported / missing asset types so callers can
 * skip the POST instead of building a `portHas<X>` the backend will 422 on.
 */
export function selectPortAssetPredicate(assetTypeName: string | undefined | null): string | undefined {
  if (!assetTypeName) return undefined;
  return PORT_TO_ASSET_PREDICATE[assetTypeName];
}

/**
 * Build the POST body for `/api/entity-relationships` from an asset and the
 * owning port id. Returns `null` when the asset type has no port predicate
 * in the ontology — caller should skip + warn rather than send the request.
 */
export function buildLinkAssetRequestBody(
  asset: any,
  portId: string,
): { source_type: string; source_id: string; target_type: string; target_id: string; relationship_type: string } | null {
  const predicate = selectPortAssetPredicate(asset?.asset_type_name);
  if (!predicate) return null;
  return {
    source_type: 'OutputPort',
    source_id: portId,
    target_type: asset.asset_type_name,
    target_id: asset.id,
    relationship_type: predicate,
  };
}

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

/**
 * Per-port linked assets sub-component.
 * Shows assets linked to a specific output port via entity relationships,
 * and provides a button to link new assets.
 */
function PortLinkedAssets({ portId, portName, canEdit }: { portId: string; portName: string; canEdit: boolean }) {
  const [relationships, setRelationships] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAssetSelectorOpen, setIsAssetSelectorOpen] = useState(false);
  const { toast } = useToast();
  const navigate = useNavigate();

  const fetchRelationships = useCallback(async () => {
    try {
      const res = await fetch(`/api/entities/OutputPort/${portId}/relationships`);
      if (!res.ok) return;
      const data = await res.json();
      const rels = Array.isArray(data)
        ? data
        : [...(data.outgoing || []), ...(data.incoming || [])];
      setRelationships(rels);
    } catch {
      // Silently fail for non-critical display
    } finally {
      setIsLoading(false);
    }
  }, [portId]);

  useEffect(() => {
    fetchRelationships();
  }, [fetchRelationships]);

  const handleLinkAssets = async (assets: any[]) => {
    try {
      let linkedCount = 0;
      for (const asset of assets) {
        // The picker is filtered to deliverable types, but be defensive:
        // if an asset of an unsupported type slips through, skip + warn rather
        // than build a `portHas<X>` predicate that the backend will 422 on.
        const body = buildLinkAssetRequestBody(asset, portId);
        if (!body) {
          // eslint-disable-next-line no-console
          console.warn(
            `[link-asset] Skipping asset ${asset.id}: type "${asset.asset_type_name}" has no port relationship in the ontology.`
          );
          continue;
        }
        const res = await fetch('/api/entity-relationships', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`Failed to link asset: ${res.statusText}`);
        linkedCount += 1;
      }
      toast({ title: 'Assets linked', description: `${linkedCount} asset(s) linked to ${portName}` });
      fetchRelationships();
    } catch (error: any) {
      toast({ title: 'Error', description: error?.message || 'Failed to link assets', variant: 'destructive' });
    }
  };

  const handleUnlinkAsset = async (relId: string) => {
    try {
      const res = await fetch(`/api/entity-relationships/${relId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to unlink asset');
      toast({ title: 'Asset unlinked' });
      fetchRelationships();
    } catch (error: any) {
      toast({ title: 'Error', description: error?.message || 'Failed to unlink asset', variant: 'destructive' });
    }
  };

  if (isLoading) return null;

  const linkedAssets = relationships.filter(r => r.source_id === portId);

  return (
    <div className="mt-2 space-y-1">
      {linkedAssets.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {linkedAssets.map((rel) => (
            <Badge
              key={rel.id}
              variant="outline"
              className="text-xs cursor-pointer hover:bg-accent group"
              onClick={() => {
                if (rel.target_type && rel.target_id) {
                  navigate(`/assets/${rel.target_id}`);
                }
              }}
            >
              {rel.target_name || rel.target_id}
              {canEdit && (
                <button
                  className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleUnlinkAsset(rel.id);
                  }}
                >
                  ×
                </button>
              )}
            </Badge>
          ))}
        </div>
      )}
      {canEdit && (
        <>
          <Button
            size="sm"
            variant="ghost"
            className="text-xs h-7 text-muted-foreground"
            onClick={() => setIsAssetSelectorOpen(true)}
          >
            <Plus className="mr-1 h-3 w-3" />
            Link Asset
          </Button>
          <AssetSelector
            isOpen={isAssetSelectorOpen}
            onOpenChange={setIsAssetSelectorOpen}
            onConfirm={handleLinkAssets}
            relationshipLabel="linked to port"
            targetAssetTypes={PORT_DELIVERABLE_ASSET_TYPES}
            title={`Link Assets to "${portName}"`}
            description="Only deliverable asset types (Table, View, Dataset, API Endpoint, ML Model) can be linked to an output port."
          />
        </>
      )}
    </div>
  );
}

export default function DataProductDetails() {
  const { t } = useTranslation(['data-products', 'common']);
  const { productId } = useParams<{ productId: string }>();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const listPath = pathname.replace(/\/[^/]+$/, '');
  const api = useApi();
  const { get, post, delete: deleteApi } = api;
  const { lookupWorkflowId } = useApprovalWizardTrigger();
  const { toast } = useToast();
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const {
    hasPermission,
    isLoading: permissionsLoading,
    getPermissionLevel,
    availableRoles,
    appliedRoleId,
  } = usePermissions();
  const { userInfo, fetchUserInfo } = useUserStore();
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
  const [isLineageEditorOpen, setIsLineageEditorOpen] = useState(false);
  const [selectedPortForLinking, setSelectedPortForLinking] = useState<number | null>(null);

  // Subscription state
  const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionResponse | null>(null);
  const [subscribers, setSubscribers] = useState<SubscribersListResponse | null>(null);
  const [subscriptionLoading, setSubscriptionLoading] = useState(false);
  const [subscriptionWizardOpen, setSubscriptionWizardOpen] = useState(false);
  const [subscriptionWorkflowId, setSubscriptionWorkflowId] = useState<string | null>(null);

  // Quality summary for sidebar
  const [qualitySummary, setQualitySummary] = useState<QualitySummary | null>(null);

  // Lifecycle direct actions
  const [certificationLevels, setCertificationLevels] = useState<CertificationLevel[]>([]);
  const [certifyDialogOpen, setCertifyDialogOpen] = useState(false);
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [selectedCertifyLevel, setSelectedCertifyLevel] = useState<number | null>(null);
  const [selectedPublishScope, setSelectedPublishScope] = useState<PublicationScope>('organization');
  const [lifecycleActionSubmitting, setLifecycleActionSubmitting] = useState(false);

  // Clone/Commit draft states
  const [isCommitDraftDialogOpen, setIsCommitDraftDialogOpen] = useState(false);
  const [isCloning, setIsCloning] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);

  // Permissions
  const featureId = 'data-products';
  const canRead = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, Settings.FeatureAccessLevel.ADMIN);

  const canApproveProductLifecycle = userHasApprovalPrivilege(
    ApprovalEntity.PRODUCTS,
    userInfo?.groups,
    availableRoles,
    appliedRoleId
  );

  // Versioned editing: determine if product can be edited in place based on status
  // Products with status 'draft', 'sandbox', 'proposed' can be edited directly
  // Products with status 'active' and above must be cloned for editing
  const canEditInPlace = isStatusEditableInPlace(product?.status);
  const isPersonalDraft = isPersonalDraftProduct(product);
  const isReadOnly = isProductReadOnly({ canAdmin, canEditInPlace, isPersonalDraft });

  // Combined permission check: admin can always edit; others need write + editable status
  const canModify = canUserModifyProduct({ canAdmin, canWrite, canEditInPlace, isPersonalDraft });

  // View mode state for filtering sections - initialize from localStorage
  const [viewMode, setViewMode] = useState<ViewMode>(
    () => parseStoredViewMode(localStorage.getItem(VIEW_MODE_STORAGE_KEY)) ?? 'minimal',
  );

  const getDefaultViewMode = useCallback((): ViewMode => {
    return computeDefaultViewMode({
      ownerTeamId: product?.owner_team_id,
      userGroups: userInfo?.groups,
      permissionLevel: getPermissionLevel('data-products'),
    });
  }, [product?.owner_team_id, userInfo?.groups, getPermissionLevel]);

  useEffect(() => {
    if (!userInfo) {
      fetchUserInfo();
    }
  }, [userInfo, fetchUserInfo]);

  useEffect(() => {
    const stored = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
    if (!stored) {
      setViewMode(getDefaultViewMode());
    }
  }, [getDefaultViewMode]);

  useEffect(() => {
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    get<CertificationLevel[]>('/api/certification-levels').then(({ data }) => {
      if (Array.isArray(data)) setCertificationLevels(data);
    });
  }, [get]);

  useCopilotContext(
    'Data Product Details',
    `/data-products/${productId}`,
    product ? { type: 'data_product', name: product.name || 'Unnamed', id: productId || '' } : null,
  );

  const formatDate = (dateString: string | undefined, fallback: string = 'N/A'): string =>
    formatDateString(dateString, fallback);

  const getStatusColor = getStatusBadgeVariant;

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
    setStaticSegments([{ label: t('title'), path: listPath }]);
    setDynamicTitle(t('details.loading'));

    try {
      const [productResp, linksResp, qualityResp] = await Promise.all([
        get<DataProduct>(`/api/data-products/${productId}`),
        get<EntitySemanticLink[]>(`/api/semantic-links/entity/data_product/${productId}`),
        get<QualitySummary>(`/api/data-products/${productId}/quality-summary`).catch(() => ({ data: null, error: null })),
      ]);

      const productData = checkApiResponse(productResp, 'Product Details');
      setProduct(productData);
      setLinks(Array.isArray(linksResp.data) ? linksResp.data : []);
      setQualitySummary(qualityResp.data ?? null);

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

  const handleDirectCertify = async () => {
    if (!productId || selectedCertifyLevel == null) return;
    setLifecycleActionSubmitting(true);
    try {
      const response = await post<unknown>(`/api/data-products/${productId}/certify`, {
        certification_level: selectedCertifyLevel,
      });
      if (response.error) {
        throw new Error(typeof response.error === 'string' ? response.error : 'Certify failed');
      }
      toast({ title: 'Certified', description: 'Certification level has been applied.' });
      setCertifyDialogOpen(false);
      await fetchProductDetails();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to certify';
      toast({ title: 'Error', description: msg, variant: 'destructive' });
    } finally {
      setLifecycleActionSubmitting(false);
    }
  };

  const handleDirectPublish = async () => {
    if (!productId) return;
    setLifecycleActionSubmitting(true);
    try {
      const response = await post<unknown>(`/api/data-products/${productId}/set-publication-scope`, {
        scope: selectedPublishScope,
      });
      if (response.error) {
        throw new Error(typeof response.error === 'string' ? response.error : 'Publish scope update failed');
      }
      toast({ title: 'Publication updated', description: 'Publication scope has been saved.' });
      setPublishDialogOpen(false);
      await fetchProductDetails();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to set publication scope';
      toast({ title: 'Error', description: msg, variant: 'destructive' });
    } finally {
      setLifecycleActionSubmitting(false);
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
      navigate(listPath);
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
        navigate(`${listPath}/${response.data.id}`);
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
        navigate(`${listPath}/${product.parentProductId}`);
      } else {
        navigate(listPath);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to discard draft';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setIsDiscarding(false);
    }
  };

  // Subscription: open approval wizard (or fallback to direct subscribe)
  const handleSubscribeClick = async () => {
    if (!productId) return;
    const workflowId = await lookupWorkflowId('for_subscribe');
    if (workflowId) {
      setSubscriptionWorkflowId(workflowId);
      setSubscriptionWizardOpen(true);
    } else {
      toast({
        title: 'Approval workflow not configured',
        description: 'Subscribing directly. Load default workflows in Settings to use the approval flow.',
        variant: 'default',
      });
      await handleSubscribeDirect();
    }
  };

  const handleSubscribeDirect = async () => {
    if (!productId) return;
    setSubscriptionLoading(true);
    try {
      const response = await post<SubscriptionResponse>(`/api/data-products/${productId}/subscribe`, {});
      if (response.data) {
        setSubscriptionStatus(response.data);
        toast({ title: 'Subscribed', description: 'You will now receive notifications about this product.' });
        if (canWrite || canAdmin) {
          const subscribersResp = await get<SubscribersListResponse>(`/api/data-products/${productId}/subscribers`);
          if (subscribersResp.data) setSubscribers(subscribersResp.data);
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to subscribe';
      toast({ title: 'Error', description: errorMessage, variant: 'destructive' });
    } finally {
      setSubscriptionLoading(false);
    }
  };

  const handleSubscriptionWizardComplete = async () => {
    setSubscriptionWizardOpen(false);
    setSubscriptionWorkflowId(null);
    toast({ title: 'Subscribed', description: 'You will now receive notifications about this product.' });
    if (!productId) return;
    try {
      const subscriptionResp = await get<SubscriptionResponse>(`/api/data-products/${productId}/subscription`);
      if (subscriptionResp.data) setSubscriptionStatus(subscriptionResp.data);
      if (canWrite || canAdmin) {
        const subscribersResp = await get<SubscribersListResponse>(`/api/data-products/${productId}/subscribers`);
        if (subscribersResp.data) setSubscribers(subscribersResp.data);
      }
    } catch (err) {
      setSubscriptionStatus({ subscribed: true });
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
      if (!res.ok) throw new Error(`Failed to add consumable (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add consumable');
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
      if (!res.ok) throw new Error(`Failed to update consumable (${res.status})`);
      await fetchProductDetails();
      setEditingInputPortIndex(null);
      toast({ title: 'Consumable Updated', description: 'Consumable updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update consumable', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteInputPort = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this consumable?')) return;
    try {
      const updatedPorts = (product.inputPorts || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, inputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to delete consumable (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Consumable Deleted', description: 'Consumable deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete consumable', variant: 'destructive' });
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
      if (!res.ok) throw new Error(`Failed to add deliverable (${res.status})`);
      await fetchProductDetails();
    } catch (e: any) {
      throw new Error(e?.message || 'Failed to add deliverable');
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
      if (!res.ok) throw new Error(`Failed to update deliverable (${res.status})`);
      await fetchProductDetails();
      setEditingOutputPortIndex(null);
      toast({ title: 'Deliverable Updated', description: 'Deliverable updated successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to update deliverable', variant: 'destructive' });
      throw e;
    }
  };

  const handleDeleteOutputPort = async (index: number) => {
    if (!productId || !product) return;
    if (!confirm('Delete this deliverable?')) return;
    try {
      const updatedPorts = (product.outputPorts || []).filter((_, i) => i !== index);
      const res = await fetch(`/api/data-products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...product, outputPorts: updatedPorts }),
      });
      if (!res.ok) throw new Error(`Failed to delete deliverable (${res.status})`);
      await fetchProductDetails();
      toast({ title: 'Deliverable Deleted', description: 'Deliverable deleted successfully.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to delete deliverable', variant: 'destructive' });
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
    if (!confirm('Unlink contract from this deliverable?')) return;
    
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
        description: 'Contract successfully unlinked from deliverable',
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
      navigate(`${listPath}/${newProduct.id}`);
    } catch (err: any) {
      toast({ title: 'Error', description: err.message || 'Failed to create version.', variant: 'destructive' });
    }
  };

  const shouldShowSection = (section: string): boolean =>
    shouldShowSectionForViewMode(viewMode, section);

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

  const domainLabel = resolveDomainLabel({
    domain: product.domain,
    resolveName: getDomainName,
    notAssignedLabel: t('common:states.notAssigned'),
  });

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => navigate(listPath)} size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to List
          </Button>

          {/* View Mode Toggle */}
          <div className="inline-flex items-stretch h-8 gap-px border rounded-md bg-background overflow-hidden">
            <Button
              variant={viewMode === 'minimal' ? 'default' : 'ghost'}
              onClick={() => setViewMode('minimal')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.smallView')}
            >
              S
            </Button>
            <Button
              variant={viewMode === 'medium' ? 'default' : 'ghost'}
              onClick={() => setViewMode('medium')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.mediumView')}
            >
              M
            </Button>
            <Button
              variant={viewMode === 'large' ? 'default' : 'ghost'}
              onClick={() => setViewMode('large')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.largeView')}
            >
              L
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setIsRequestDialogOpen(true)} size="sm">
            <KeyRound className="mr-2 h-4 w-4" /> Request...
          </Button>
          {isProductActive(product.status) && canApproveProductLifecycle && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const first = certificationLevels[0]?.level_order ?? null;
                setSelectedCertifyLevel(first);
                setCertifyDialogOpen(true);
              }}
            >
              <ShieldCheck className="mr-2 h-4 w-4" /> Certify
            </Button>
          )}
          {isProductActive(product.status) && canWrite && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const cur = (product.publication_scope || 'none') as PublicationScope;
                setSelectedPublishScope(cur === 'none' ? 'organization' : cur);
                setPublishDialogOpen(true);
              }}
            >
              <Globe className="mr-2 h-4 w-4" /> Publish
            </Button>
          )}
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
                onClick={handleSubscribeClick}
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

      {/* Basic Info + Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
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
              {(viewMode !== 'minimal' || product.domain) && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground min-w-[4rem]">Domain:</Label>
                  {product.domain && getDomainIdByName(domainLabel) ? (
                    <span
                      className="text-xs cursor-pointer text-primary hover:underline truncate"
                      onClick={() => navigate(`/settings/data-domains/${getDomainIdByName(domainLabel)}`)}
                    >
                      {domainLabel}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">{domainLabel}</span>
                  )}
                </div>
              )}
              {(viewMode !== 'minimal' || ((product as any).project_id && product.project_name)) && (
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
              )}
              {(viewMode !== 'minimal' || product.tenant) && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground min-w-[4rem]">Tenant:</Label>
                  <span className="text-xs text-muted-foreground truncate">{product.tenant || t('common:states.notAssigned')}</span>
                </div>
              )}
              {(viewMode !== 'minimal' || (product.owner_team_id && product.owner_team_name)) && (
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
              )}
              {viewMode !== 'minimal' && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground min-w-[4rem]">API Ver:</Label>
                  {product.apiVersion ? (
                    <Badge variant="outline" className="text-xs">{product.apiVersion}</Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground">N/A</span>
                  )}
                </div>
              )}
              {(viewMode !== 'minimal' || product.created_at) && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground min-w-[4rem]">Created:</Label>
                  <span className="text-xs text-muted-foreground truncate">{formatDate(product.created_at)}</span>
                </div>
              )}
              {(viewMode !== 'minimal' || product.updated_at) && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-muted-foreground min-w-[4rem]">Updated:</Label>
                  <span className="text-xs text-muted-foreground truncate">{formatDate(product.updated_at)}</span>
                </div>
              )}
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

        {/* Sidebar: Contacts + Quality */}
        <div className="space-y-4">
          {/* Contacts */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Contacts</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {(() => {
                const contacts = product.team?.members?.filter(
                  (m) => m.role && ['owner', 'data owner', 'data steward', 'steward'].includes(m.role.toLowerCase())
                );
                if (contacts && contacts.length > 0) {
                  return contacts.map((member, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <Avatar className="h-8 w-8">
                        <AvatarFallback className="text-xs bg-primary/10 text-primary">
                          {(member.name || member.username || '?')
                            .split(/[\s.@]+/)
                            .filter(Boolean)
                            .slice(0, 2)
                            .map((p) => p[0].toUpperCase())
                            .join('')}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{member.name || member.username}</div>
                        <div className="text-xs text-muted-foreground">{member.role}</div>
                      </div>
                    </div>
                  ));
                }
                if (product.owner_team_name) {
                  return (
                    <div className="flex items-center gap-2">
                      <Avatar className="h-8 w-8">
                        <AvatarFallback className="text-xs bg-primary/10 text-primary">
                          {product.owner_team_name.split(/\s+/).slice(0, 2).map((p) => p[0].toUpperCase()).join('')}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{product.owner_team_name}</div>
                        <div className="text-xs text-muted-foreground">Owner Team</div>
                      </div>
                    </div>
                  );
                }
                return <span className="text-xs text-muted-foreground">No contacts assigned</span>;
              })()}
            </CardContent>
          </Card>

          <LifecycleSummaryPanel
            status={(product.status || 'draft').toLowerCase()}
            certificationLevel={product.certification_level}
            inheritedCertificationLevel={product.inherited_certification_level}
            certifiedAt={product.certified_at}
            certifiedBy={product.certified_by}
            certificationExpiresAt={product.certification_expires_at}
            publicationScope={product.publication_scope}
            publishedAt={product.published_at}
            publishedBy={product.published_by}
            certificationLevels={certificationLevels}
          />

          {/* Overall Data Quality */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Overall Data Quality (0-100%)</CardTitle>
            </CardHeader>
            <CardContent>
              {qualitySummary && qualitySummary.items_count > 0 ? (
                <div className="space-y-2">
                  <div
                    style={{
                      '--progress-color': qualitySummary.overall_score_percent >= 80
                        ? '#22c55e'
                        : qualitySummary.overall_score_percent >= 50
                          ? '#eab308'
                          : '#ef4444',
                    } as React.CSSProperties}
                  >
                    <Progress
                      value={qualitySummary.overall_score_percent}
                      className="h-3 [&>div]:!bg-[var(--progress-color)]"
                    />
                  </div>
                  <div className="text-lg font-semibold">
                    {Math.round(qualitySummary.overall_score_percent)}%
                  </div>
                </div>
              ) : (
                <span className="text-xs text-muted-foreground">No quality data available</span>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Deliverables (Output Ports) – primary composition surface */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Deliverables ({product.outputPorts?.length || 0})</span>
            {canModify && <Button size="sm" onClick={() => setIsOutputPortDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Deliverable</Button>}
          </CardTitle>
          <CardDescription>
            Define deliverables and their delivery methods. Link assets and contracts to each deliverable.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {product.outputPorts && product.outputPorts.length > 0 ? (
            <div className="space-y-3">
              {product.outputPorts.map((port, idx) => (
                <div key={port.id || idx} className="border rounded-lg p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{port.name}</span>
                        <Badge variant="outline" className="text-xs">v{port.version}</Badge>
                        {port.deliveryMethodName && (
                          <Badge variant="secondary" className="text-xs">{port.deliveryMethodName}</Badge>
                        )}
                        {port.status && (
                          <Badge variant="outline" className="text-xs">{port.status}</Badge>
                        )}
                        {port.containsPii && (
                          <Badge variant="destructive" className="text-xs">PII</Badge>
                        )}
                      </div>
                      {port.description && <p className="text-sm text-muted-foreground">{port.description}</p>}
                      {port.contractId ? (
                        <div className="flex items-center gap-2">
                          <Badge 
                            variant="secondary" 
                            className="cursor-pointer hover:bg-secondary/80"
                            onClick={() => navigate(`/data-contracts/${port.contractId}`)}
                          >
                            Contract: {port.contractName || port.contractId}
                          </Badge>
                          {canModify && (
                            <Button size="sm" variant="ghost" className="h-6 px-1" onClick={() => handleUnlinkContract(idx)} title="Unlink contract">
                              <Unlink className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      ) : canModify && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-xs text-muted-foreground h-7"
                          onClick={() => handleLinkContract(idx)}
                        >
                          <Link2 className="mr-1 h-3 w-3" />
                          Link contract
                        </Button>
                      )}

                      {/* Per-port linked assets */}
                      {port.id && (
                        <PortLinkedAssets
                          portId={port.id}
                          portName={port.name}
                          canEdit={canModify}
                        />
                      )}
                    </div>
                    {canModify && (
                      <div className="flex gap-1 ml-3 shrink-0">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setEditingOutputPortIndex(idx);
                            setIsOutputPortDialogOpen(true);
                          }}
                          title="Edit deliverable"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDeleteOutputPort(idx)}
                          className="text-destructive hover:text-destructive"
                          title="Delete deliverable"
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
            <p className="text-sm text-muted-foreground">
              No deliverables defined.{canModify ? ' Add deliverables and link assets when ready.' : ''}
            </p>
          )}
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

      {/* Business Lineage Graph */}
      {shouldShowSection('lineage') && productId && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <GitBranch className="h-4 w-4" />
                Business Lineage
              </span>
              {canModify && (
                <Button size="sm" variant="outline" onClick={() => setIsLineageEditorOpen(true)}>
                  <GitBranch className="mr-2 h-3.5 w-3.5" /> Manage Lineage
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BusinessLineageView
              entityType="DataProduct"
              entityId={productId}
              className="h-[500px]"
            />
          </CardContent>
        </Card>
      )}

      {/* Production Readiness Checklist */}
      {shouldShowSection('readiness') && productId && <ReadinessChecklist productId={productId} />}

      {/* Consumables (Input Ports) */}
      {shouldShowSection('consumables') && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Consumables ({product.inputPorts?.length || 0})</span>
              {canModify && <Button size="sm" onClick={() => setIsInputPortDialogOpen(true)}><Plus className="mr-2 h-4 w-4" />Add Consumable</Button>}
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
              <p className="text-sm text-muted-foreground">No consumables defined</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Management Ports Section (NEW in ODPS v1.0.0) */}
      {shouldShowSection('management-ports') && (
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
      )}

      {/* Team Section */}
      {shouldShowSection('team') && (
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
      )}

      {/* Support Channels */}
      {shouldShowSection('support-channels') && (
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
      )}

      {/* Subscribers Section (only visible to owners/admins) */}
      {shouldShowSection('subscribers') && (canWrite || canAdmin) && subscribers && (
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
      {shouldShowSection('access-grants') && productId && (
        <AccessGrantsPanel
          entityType="data_product"
          entityId={productId}
          canManage={canModify}
          showPendingRequests={canModify}
        />
      )}

      {/* Ownership Panel */}
      {shouldShowSection('ownership') && (
        <OwnershipPanel objectType="data_product" objectId={productId!} canAssign={canModify} className="mb-6" />
      )}

      {/* Entity Relationships Panel (tree-based with drill-down) */}
      {shouldShowSection('entity-relationships') && (
        <EntityTreePanel
          entityType="DataProduct"
          entityId={productId!}
          title="Related Entities"
          canEdit={canModify}
        />
      )}

      {/* Metadata Panel */}
      {shouldShowSection('metadata-panel') && (
        <EntityMetadataPanel entityId={productId!} entityType="data_product" />
      )}

      {/* Ratings Panel */}
      {shouldShowSection('ratings') && (
        <RatingPanel
          entityType="data_product"
          entityId={productId!}
          title={t('details.ratings.title', 'Ratings & Reviews')}
          showDistribution
          allowSubmit={canRead}
        />
      )}

      {/* Costs Panel */}
      {shouldShowSection('costs') && (
        <EntityCostsPanel entityId={productId!} entityType="data_product" />
      )}

      {/* Quality Panel */}
      {shouldShowSection('quality') && (
        <EntityQualityPanel entityId={productId!} entityType="data_product" productAggregation />
      )}

      {/* Lineage Editor */}
      {productId && product && (
        <LineageEditor
          isOpen={isLineageEditorOpen}
          onOpenChange={setIsLineageEditorOpen}
          entityType="DataProduct"
          entityId={productId}
          entityName={product.name || productId}
          onSuccess={() => fetchProductDetails()}
        />
      )}

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

      {/* Subscription approval wizard */}
      {subscriptionWizardOpen && productId && subscriptionWorkflowId && (
        <ApprovalWizardDialog
          isOpen={subscriptionWizardOpen}
          onOpenChange={setSubscriptionWizardOpen}
          entityType="data_product"
          entityId={productId}
          preselectedWorkflowId={subscriptionWorkflowId}
          completionAction="subscribe"
          autoStartWithPreselected
          onComplete={handleSubscriptionWizardComplete}
        />
      )}

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

      <DirectCertifyDialog
        open={certifyDialogOpen}
        onOpenChange={setCertifyDialogOpen}
        certificationLevels={certificationLevels}
        selectedLevelOrder={selectedCertifyLevel}
        onSelectedLevelOrderChange={setSelectedCertifyLevel}
        isSubmitting={lifecycleActionSubmitting}
        onConfirm={handleDirectCertify}
      />
      <DirectPublishDialog
        open={publishDialogOpen}
        onOpenChange={setPublishDialogOpen}
        selectedScope={selectedPublishScope}
        onSelectedScopeChange={setSelectedPublishScope}
        isSubmitting={lifecycleActionSubmitting}
        onConfirm={handleDirectPublish}
      />
    </div>
  );
}
