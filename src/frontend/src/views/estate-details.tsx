import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ArrowLeft, Globe, Edit3, PlusCircle, Trash2, Share2, Database, Zap, ZapOff, Settings2, ShieldCheck, ListFilter } from 'lucide-react';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import AddSharingPolicyDialog from '@/components/estates/add-sharing-policy-dialog';

// --- TypeScript Interfaces (Consider moving to a shared types/estate.ts file later) ---
type CloudType = 'aws' | 'azure' | 'gcp';
type SyncStatus = 'pending' | 'running' | 'success' | 'failed';
type ConnectionType = 'delta_share' | 'database';
export type SharingResourceType = 'data_product' | 'business_glossary';
export type SharingRuleOperator = 'equals' | 'contains' | 'starts_with' | 'regex';

export interface SharingRule {
  filter_type: string;
  operator: SharingRuleOperator;
  filter_value: string;
}

export interface SharingPolicy {
  id?: string;
  name: string;
  description?: string;
  resource_type: SharingResourceType;
  rules: SharingRule[];
  is_enabled: boolean;
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

export interface Estate {
  id: string;
  name: string;
  description: string;
  workspace_url: string;
  cloud_type: CloudType;
  metastore_name: string;
  connection_type: ConnectionType;
  sharing_policies: SharingPolicy[];
  is_enabled: boolean;
  sync_schedule: string;
  last_sync_time?: string; // ISO datetime string
  last_sync_status?: SyncStatus;
  last_sync_error?: string;
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}
// --- End TypeScript Interfaces ---

export default function EstateDetailsView() {
  const { t } = useTranslation(['estates', 'common']);
  const { estateId } = useParams<{ estateId: string }>();
  const navigate = useNavigate();
  const { get, put } = useApi();
  const { toast } = useToast();
  
  // Destructure actions from the store
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const [estate, setEstate] = useState<Estate | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAddPolicyDialogOpen, setIsAddPolicyDialogOpen] = useState(false); // State for Add Policy Dialog

  useEffect(() => {
    // Set static breadcrumb for Estate Manager parent
    setStaticSegments([{ label: t('estates:title'), path: '/estate-manager' }]);

    if (estateId) {
      fetchEstateDetails(estateId);
      // Initial dynamic title while loading specific estate
      setDynamicTitle(t('common:states.loading'));
    } else {
      // If no estateId, this is an invalid state or direct access to a generic details page
      setDynamicTitle(t('estates:details.pageTitle'));
    }
    
    // Cleanup breadcrumbs on unmount
    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  // Use stable setters in dependency array
  }, [estateId, setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    if (estate) {
      setDynamicTitle(estate.name);
    } else if (!isLoading && error) {
      setDynamicTitle(t('common:states.error'));
    } else if (!isLoading && !estateId) {
      setDynamicTitle(t('estates:details.pageTitle'));
    }
  // Use stable setters in dependency array
  }, [estate, isLoading, error, setDynamicTitle, estateId, setStaticSegments]);

  const fetchEstateDetails = async (id: string) => {
    setIsLoading(true);
    setError(null);
    // setDynamicTitle('Loading...'); // Moved to useEffect for initial load state
    try {
      const response = await get<Estate>(`/api/estates/${id}`);
      if (response.data) {
        setEstate(response.data);
        // setDynamicTitle(response.data.name); // Moved to useEffect
      } else {
        throw new Error(response.error || t('estates:details.notFound'));
      }
    } catch (err: any) {
      setError(err.message || t('estates:details.errors.fetchFailed'));
      toast({
        title: t('estates:details.errors.fetchTitle'),
        description: err.message || t('estates:details.errors.couldNotLoad'),
        variant: 'destructive',
      });
      setEstate(null); // Clear estate on error
      // setDynamicTitle('Error'); // Moved to useEffect
    }
    setIsLoading(false);
  };

  // Handler to be called when a new policy is successfully added
  const handlePolicyAdded = async (newPolicy: SharingPolicy) => {
    if (!estate || !estateId) {
      toast({
        title: t('common:toast.error'),
        description: t('estates:details.errors.noEstateData'),
        variant: 'destructive',
      });
      return;
    }

    // Ensure the new policy has an ID if the backend doesn't assign one on creation within the estate
    // (Assuming backend handles ID generation for policies within an estate update)
    // If not, generate a UUID client-side: import { v4 as uuidv4 } from 'uuid'; newPolicy.id = uuidv4();

    const updatedPolicies = [...estate.sharing_policies, newPolicy];
    const updatedEstate: Estate = {
      ...estate,
      sharing_policies: updatedPolicies,
    };

    try {
      // Optimistically update UI first
      // setEstate(updatedEstate); // Consider if optimistic update here is best or after API success

      const response = await put<Estate>(`/api/estates/${estateId}`, updatedEstate);

      if (response.data) {
        setEstate(response.data); // Update with response from server, which should include the new policy with its ID
        toast({
          title: t('estates:details.policies.addedTitle'),
          description: t('estates:details.policies.addedDescription', { name: newPolicy.name }),
        });
        setIsAddPolicyDialogOpen(false); // Close the dialog
      } else {
        // Revert optimistic update if it was done before API call
        // setEstate(estate);
        throw new Error(response.error || t('estates:details.policies.saveFailedNoData'));
      }
    } catch (err: any) {
      // Revert optimistic update if it was done before API call
      // setEstate(estate);
      console.error('Failed to add policy:', err);
      toast({
        title: t('estates:details.policies.addErrorTitle'),
        description: err.message || t('estates:details.policies.addErrorDescription'),
        variant: 'destructive',
      });
    }
  };

  if (isLoading) {
    return <DetailViewSkeleton cards={3} actionButtons={2} />;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-red-600">
        <p>{error}</p>
        <Button variant="outline" onClick={() => navigate('/estate-manager')} className="mt-4">
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('estates:details.backToEstateManager')}
        </Button>
      </div>
    );
  }

  if (!estate) {
    return (
        <div className="flex flex-col items-center justify-center h-64">
            <p className="text-muted-foreground">{t('estates:details.notFoundOrLoad')}</p>
            <Button variant="outline" onClick={() => navigate('/estate-manager')} className="mt-4">
                <ArrowLeft className="mr-2 h-4 w-4" /> {t('estates:details.backToEstateManager')}
            </Button>
        </div>
    );
  }

  const InfoItem = ({ label, value, children }: { label: string; value?: string | React.ReactNode; children?: React.ReactNode }) => (
    <div className="mb-3">
      <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</p>
      {value && <p className="text-md text-gray-900 dark:text-gray-100">{value}</p>}
      {children}
    </div>
  );

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate('/estate-manager')} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t('estates:details.backToListButton')}
        </Button>
        <div className="flex gap-2">
            <Button variant="outline" size="sm">
                <Settings2 className="mr-2 h-4 w-4" /> {t('estates:details.configureSyncJob')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => alert(t('estates:details.editNotImplemented'))}>
                <Edit3 className="mr-2 h-4 w-4" /> {t('estates:editEstate')}
            </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div>
                <CardTitle className="text-2xl font-bold flex items-center">
                    <Globe className="mr-3 h-7 w-7 text-primary" />{estate.name}
                </CardTitle>
                <CardDescription>{estate.description}</CardDescription>
            </div>
            <Badge variant={estate.is_enabled ? 'default' : 'secondary'} className="capitalize text-sm px-3 py-1">
                {estate.is_enabled ? <Zap className="mr-1 h-4 w-4"/> : <ZapOff className="mr-1 h-4 w-4"/>}
                {estate.is_enabled ? t('estates:details.syncEnabled') : t('estates:details.syncDisabled')}
            </Badge>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
            <InfoItem label={t('common:labels.workspaceUrl')} value={estate.workspace_url} />
            <InfoItem label={t('estates:details.labels.cloudProvider')}>
                <Badge variant={estate.cloud_type === 'aws' ? 'secondary' : estate.cloud_type === 'azure' ? 'default' : 'outline'} className="capitalize">
                    {estate.cloud_type}
                </Badge>
            </InfoItem>
            <InfoItem label={t('estates:form.metastoreName')} value={estate.metastore_name} />
            <InfoItem label={t('estates:form.connectionType')}>
                <div className="flex items-center gap-1 capitalize">
                    {estate.connection_type === 'delta_share' ? 
                    <Share2 className="h-4 w-4 text-blue-500" /> : 
                    <Database className="h-4 w-4 text-green-500" />}
                    {estate.connection_type.replace('_', ' ')}
                </div>
            </InfoItem>
            <InfoItem label={t('estates:form.syncSchedule')} value={estate.sync_schedule} />
            <InfoItem label={t('estates:details.labels.lastSyncTime')} value={estate.last_sync_time ? new Date(estate.last_sync_time).toLocaleString() : t('estates:details.never')} />
            <InfoItem label={t('estates:details.labels.lastSyncStatus')}>
              {estate.last_sync_status ? (
                <Badge 
                    variant={estate.last_sync_status === 'success' ? 'default' : estate.last_sync_status === 'failed' ? 'destructive' : 'secondary'}
                    className="capitalize"
                >
                  {estate.last_sync_status}
                </Badge>
              ) : (
                <Badge variant="outline">{t('common:states.unknown')}</Badge>
              )}
            </InfoItem>
            {estate.last_sync_status === 'failed' && estate.last_sync_error && (
              <InfoItem label={t('estates:details.labels.lastSyncError')} value={estate.last_sync_error} />
            )}
            <InfoItem label={t('common:labels.createdAt')} value={new Date(estate.created_at).toLocaleString()} />
            <InfoItem label={t('estates:details.labels.lastUpdatedAt')} value={new Date(estate.updated_at).toLocaleString()} />
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Sharing Policies Section */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-xl flex items-center"><ShieldCheck className="mr-2 h-6 w-6 text-primary"/> {t('estates:details.policies.title')}</CardTitle>
            <Button variant="outline" size="sm" onClick={() => setIsAddPolicyDialogOpen(true)}>
                <PlusCircle className="mr-2 h-4 w-4" /> {t('estates:details.policies.add')}
            </Button>
          </div>
          <CardDescription>
            {t('estates:details.policies.sectionDescription')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {estate.sharing_policies.length > 0 ? (
            <div className="space-y-4">
              {estate.sharing_policies.map((policy, index) => (
                <Card key={policy.id || index} className="bg-muted/30 dark:bg-muted/50">
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-start">
                        <CardTitle className="text-lg">{policy.name}</CardTitle>
                        <div className="flex items-center gap-2">
                            <Badge variant={policy.is_enabled ? 'default' : 'secondary'} className="capitalize">
                                {policy.is_enabled ? t('common:labels.enabled') : t('common:labels.disabled')}
                            </Badge>
                            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => alert(t('estates:details.policies.editPolicyAlert', { name: policy.name }))}>
                                <Edit3 className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500 hover:text-red-600" onClick={() => alert(t('estates:details.policies.deletePolicyAlert', { name: policy.name }))}>
                                <Trash2 className="h-4 w-4" />
                            </Button>
                        </div>
                    </div>
                    {policy.description && <CardDescription className="pt-1">{policy.description}</CardDescription>}
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm font-semibold mb-1">{t('estates:details.policies.resourceTypeLabel')} <Badge variant="outline" className="capitalize">{policy.resource_type.replace('_', ' ')}</Badge></p>
                    <p className="text-sm font-semibold mb-1">{t('estates:details.policies.rulesLabel', { count: policy.rules.length })}</p>
                    {policy.rules.length > 0 ? (
                        <ul className="list-disc list-inside pl-2 space-y-1 text-sm text-muted-foreground">
                        {policy.rules.map((rule, ruleIndex) => (
                            <li key={ruleIndex}>
                            {t('estates:details.policies.filterBy')} <span className="font-medium text-foreground">{rule.filter_type}</span> {t('estates:details.policies.whereValue')} <span className="font-medium text-foreground">{rule.operator.replace('_', ' ')}</span> <span className="font-medium text-foreground">'{rule.filter_value}'</span>
                            </li>
                        ))}
                        </ul>
                    ) : (
                        <p className="text-sm text-muted-foreground italic">{t('estates:details.policies.noRules')}</p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="text-center text-muted-foreground py-8">
              <ListFilter className="mx-auto h-12 w-12 text-gray-400 mb-2" />
              <p className="font-semibold">{t('estates:details.policies.emptyTitle')}</p>
              <p className="text-sm">{t('estates:details.policies.emptyHint')}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Sharing Policy Dialog */}
      {isAddPolicyDialogOpen && (
        <AddSharingPolicyDialog
          isOpen={isAddPolicyDialogOpen}
          onOpenChange={setIsAddPolicyDialogOpen}
          currentPolicies={estate.sharing_policies} // Pass current policies for validation if needed (e.g., unique names)
          onSaveSuccess={handlePolicyAdded} // Pass the handler
          estateId={estate.id} // Pass estateId if the dialog needs to make its own calls or for context
        />
      )}
    </div>
  );
} 