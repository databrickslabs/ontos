import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, AlertCircle, Pencil, Trash2,
  MapPin, Globe, Calendar, User, Tag, FileJson, Network, GitBranch,
  LayoutGrid, Share2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AssetDeleteDialog } from '@/components/assets/asset-delete-dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AssetRead } from '@/types/asset';
import { EntityTypeDefinition } from '@/types/ontology-schema';
import { AssetFormDialog } from '@/components/common/asset-form-dialog';
import { BusinessLineageGraph } from '@/components/common/business-lineage-graph';
import { ImpactAnalysisPanel } from '@/components/common/impact-analysis-panel';
import { BusinessLineageView } from '@/components/lineage';
import { LineageEditor } from '@/components/common/lineage-editor';
import { useApi } from '@/hooks/use-api';
import { RelativeDate } from '@/components/common/relative-date';
import { EntityTreePanel } from '@/components/common/entity-tree-panel';
import { OwnershipPanel } from '@/components/common/ownership-panel';
import { CommentSidebar } from '@/components/comments';
import { RatingPanel } from '@/components/ratings';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import EntityCostsPanel from '@/components/costs/entity-costs-panel';
import EntityQualityPanel from '@/components/quality/entity-quality-panel';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import useBreadcrumbStore from '@/stores/breadcrumb-store';

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
};

function PropertyValue({ value }: { value: any }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground italic">null</span>;
  }
  if (typeof value === 'boolean') {
    return <Badge variant={value ? 'default' : 'secondary'}>{value ? 'Yes' : 'No'}</Badge>;
  }
  if (typeof value === 'object') {
    return (
      <pre className="text-xs bg-muted p-2 rounded-md overflow-auto max-h-40 font-mono">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <span className="text-sm">{String(value)}</span>;
}

function PropertiesCard({ properties }: { properties?: Record<string, any> | null }) {
  if (!properties || Object.keys(properties).length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <FileJson className="h-4 w-4" />
          Properties
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3">
          {Object.entries(properties).map(([key, value]) => (
            <div key={key} className="grid grid-cols-3 gap-2 items-start">
              <Label className="text-sm font-medium text-muted-foreground col-span-1 pt-1">
                {key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              </Label>
              <div className="col-span-2">
                <PropertyValue value={value} />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function AssetDetailView() {
  const { assetId } = useParams<{ assetId: string }>();
  const navigate = useNavigate();

  const [asset, setAsset] = useState<AssetRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false);
  const [ontologyIri, setOntologyIri] = useState<string | null>(null);
  const [isLineageEditorOpen, setIsLineageEditorOpen] = useState(false);
  const [relViewMode, setRelViewMode] = useState<'table' | 'graph'>('table');

  const { get: apiGet } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const featureId = 'assets';
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const entityType = asset?.asset_type_name || 'Asset';

  const ontologyTypeName = useMemo(() => {
    const typeMap: Record<string, string> = {
      'Business Term': 'BusinessTerm',
      'Logical Entity': 'LogicalEntity',
      'Logical Attribute': 'LogicalAttribute',
      'Delivery Channel': 'DeliveryChannel',
      'Table': 'Table',
      'View': 'View',
      'Column': 'Column',
      'ML Model': 'MLModel',
      'API Endpoint': 'APIEndpoint',
    };
    return typeMap[entityType] || entityType.replace(/\s+/g, '');
  }, [entityType]);

  const showLineageTab = true;

  const isBusinessTerm = ontologyTypeName === 'BusinessTerm';
  const isPolicy = ontologyTypeName === 'Policy';
  const isLogicalEntity = ontologyTypeName === 'LogicalEntity';

  const fetchAsset = useCallback(async () => {
    if (!assetId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await apiGet<AssetRead>(`/api/assets/${assetId}`);
      if (response.error) throw new Error(response.error);
      setAsset(response.data ?? null);
    } catch (err: any) {
      setError(err.message || 'Failed to load asset');
    } finally {
      setLoading(false);
    }
  }, [assetId, apiGet]);

  useEffect(() => {
    fetchAsset();
  }, [fetchAsset]);

  useEffect(() => {
    if (asset) {
      setStaticSegments([
        { label: 'Asset Explorer', path: '/assets' },
      ]);
      setDynamicTitle(asset.name);
      // Resolve ontology IRI for the asset type
      (async () => {
        try {
          const resp = await apiGet<EntityTypeDefinition[]>('/api/ontology/entity-types?tier=asset');
          if (!resp.error && Array.isArray(resp.data)) {
            const match = resp.data.find(
              (t) => t.label === asset.asset_type_name || t.local_name === asset.asset_type_name
            );
            setOntologyIri(match?.iri ?? null);
          }
        } catch { /* non-critical */ }
      })();
    }
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [asset, setStaticSegments, setDynamicTitle]);

  if (loading) {
    return (
      <div className="py-6 space-y-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded-md" />
          <div className="space-y-2">
            <Skeleton className="h-7 w-64" />
            <Skeleton className="h-4 w-40" />
          </div>
        </div>
        <div className="grid gap-6">
          <Skeleton className="h-48 w-full rounded-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  if (error || !asset) {
    return (
      <div className="py-6 space-y-4">
        <Button variant="outline" onClick={() => navigate(-1)} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back
        </Button>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error || 'Asset not found'}</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate(-1)} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-2">
          <CommentSidebar
            entityType="asset"
            entityId={assetId!}
            isOpen={isCommentSidebarOpen}
            onToggle={() => setIsCommentSidebarOpen(!isCommentSidebarOpen)}
            className="h-8"
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/hierarchy?type=${ontologyTypeName}&id=${assetId}`)}
          >
            <Network className="mr-2 h-4 w-4" /> View in Hierarchy
          </Button>
          {showLineageTab && canWrite && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsLineageEditorOpen(true)}
            >
              <GitBranch className="mr-2 h-4 w-4" /> Manage Lineage
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={!canWrite} onClick={() => setIsEditOpen(true)}>
            <Pencil className="mr-2 h-4 w-4" /> Edit
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-red-600 hover:text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
            disabled={!canAdmin}
            onClick={() => setIsDeleteDialogOpen(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" /> Delete
          </Button>
        </div>
      </div>

      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{asset.name}</h1>
          <Badge variant={STATUS_VARIANT[asset.status] ?? 'outline'}>
            {asset.status}
          </Badge>
        </div>
        <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
          <Badge variant="outline" className="text-xs">{entityType}</Badge>
          {asset.platform && (
            <>
              <span className="text-muted-foreground">&middot;</span>
              <span>{asset.platform}</span>
            </>
          )}
        </div>
        {asset.description && (
          <p className="text-sm text-muted-foreground mt-2 max-w-2xl">{asset.description}</p>
        )}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="relationships">Relationships</TabsTrigger>
          {showLineageTab && (
            <TabsTrigger value="lineage">
              <GitBranch className="mr-1 h-3.5 w-3.5" />
              Lineage
            </TabsTrigger>
          )}
          {(isPolicy || isBusinessTerm) && (
            <TabsTrigger value="impact">Impact Analysis</TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="overview" className="mt-4 space-y-6">
          {/* Core metadata card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {asset.location && (
                  <div>
                    <Label className="text-xs text-muted-foreground flex items-center gap-1">
                      <MapPin className="h-3 w-3" /> Location
                    </Label>
                    <p className="text-sm font-mono mt-1 truncate">{asset.location}</p>
                  </div>
                )}
                {asset.platform && (
                  <div>
                    <Label className="text-xs text-muted-foreground flex items-center gap-1">
                      <Globe className="h-3 w-3" /> Platform
                    </Label>
                    <p className="text-sm mt-1">{asset.platform}</p>
                  </div>
                )}
                {asset.domain_id && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Domain</Label>
                    <p className="text-sm mt-1">{asset.domain_id}</p>
                  </div>
                )}
                {asset.created_by && (
                  <div>
                    <Label className="text-xs text-muted-foreground flex items-center gap-1">
                      <User className="h-3 w-3" /> Created By
                    </Label>
                    <p className="text-sm mt-1">{asset.created_by}</p>
                  </div>
                )}
                <div>
                  <Label className="text-xs text-muted-foreground flex items-center gap-1">
                    <Calendar className="h-3 w-3" /> Created
                  </Label>
                  <div className="text-sm mt-1">
                    <RelativeDate date={asset.created_at} />
                  </div>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground flex items-center gap-1">
                    <Calendar className="h-3 w-3" /> Updated
                  </Label>
                  <div className="text-sm mt-1">
                    <RelativeDate date={asset.updated_at} />
                  </div>
                </div>
              </div>

              {/* Tags */}
              {asset.tags && asset.tags.length > 0 && (
                <>
                  <Separator className="my-4" />
                  <div>
                    <Label className="text-xs text-muted-foreground flex items-center gap-1 mb-2">
                      <Tag className="h-3 w-3" /> Tags
                    </Label>
                    <div className="flex flex-wrap gap-1">
                      {asset.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* Type-specific: BusinessTerm - Definition & Synonyms */}
          {isBusinessTerm && asset.properties && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Business Definition</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {asset.properties.definition && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Definition</Label>
                    <p className="text-sm mt-1">{asset.properties.definition}</p>
                  </div>
                )}
                {asset.properties.synonyms && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Synonyms</Label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {String(asset.properties.synonyms).split(',').map((s) => (
                        <Badge key={s.trim()} variant="secondary" className="text-xs">{s.trim()}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {asset.properties.examples && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Examples</Label>
                    <p className="text-sm mt-1 text-muted-foreground">{asset.properties.examples}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Type-specific: LogicalEntity - Domain & Supertype */}
          {isLogicalEntity && asset.properties && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Logical Model</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {asset.properties.entityDomain && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Domain</Label>
                    <p className="text-sm mt-1">{asset.properties.entityDomain}</p>
                  </div>
                )}
                {asset.properties.entitySupertype && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Supertype</Label>
                    <p className="text-sm mt-1">{asset.properties.entitySupertype}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Type-specific: Policy - Type & Enforcement */}
          {isPolicy && asset.properties && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Policy Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {asset.properties.policyType && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Policy Type</Label>
                    <Badge variant="outline" className="ml-2">{asset.properties.policyType}</Badge>
                  </div>
                )}
                {asset.properties.enforcementLevel && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Enforcement</Label>
                    <Badge variant="outline" className="ml-2">{asset.properties.enforcementLevel}</Badge>
                  </div>
                )}
                {asset.properties.policyContent && (
                  <div>
                    <Label className="text-xs text-muted-foreground">Content</Label>
                    <p className="text-sm mt-1 whitespace-pre-wrap">{asset.properties.policyContent}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Properties (non-type-specific fields) */}
          {!isBusinessTerm && <PropertiesCard properties={asset.properties} />}

          {/* Quick relationship summary on overview */}
          <EntityTreePanel
            entityType={ontologyTypeName}
            entityId={asset.id}
            title="Relationships"
            canEdit={canWrite}
          />
        </TabsContent>

        <TabsContent value="relationships" className="mt-4 space-y-3">
          <div className="flex items-center gap-1">
            <Button
              variant={relViewMode === 'table' ? 'default' : 'outline'}
              size="icon"
              className="h-8 w-8"
              onClick={() => setRelViewMode('table')}
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              variant={relViewMode === 'graph' ? 'default' : 'outline'}
              size="icon"
              className="h-8 w-8"
              onClick={() => setRelViewMode('graph')}
            >
              <Share2 className="h-4 w-4" />
            </Button>
          </div>
          {relViewMode === 'table' ? (
            <EntityTreePanel
              entityType={ontologyTypeName}
              entityId={asset.id}
              title="All Entity Relationships"
              canEdit={canWrite}
            />
          ) : (
            <BusinessLineageGraph
              entityType={ontologyTypeName}
              entityId={asset.id}
              entityName={asset.name}
              className="h-[600px]"
              source="relationships"
            />
          )}
        </TabsContent>

        {showLineageTab && (
          <TabsContent value="lineage" className="mt-4">
            <BusinessLineageView
              entityType={ontologyTypeName}
              entityId={asset.id}
              className="h-[600px]"
            />
          </TabsContent>
        )}

        {(isPolicy || isBusinessTerm) && (
          <TabsContent value="impact" className="mt-4">
            <ImpactAnalysisPanel
              entityType={ontologyTypeName}
              entityId={asset.id}
              maxDepth={4}
            />
          </TabsContent>
        )}
      </Tabs>

      {/* Ownership Panel */}
      <OwnershipPanel objectType="asset" objectId={assetId!} canAssign={canWrite} className="mb-6" />

      {/* Metadata Panel */}
      <EntityMetadataPanel entityId={assetId!} entityType="asset" />

      {/* Ratings Panel */}
      <RatingPanel
        entityType="asset"
        entityId={assetId!}
        title="Ratings & Reviews"
        showDistribution
        allowSubmit
      />

      {/* Costs Panel */}
      <EntityCostsPanel entityId={assetId!} entityType="asset" />

      {/* Quality Panel */}
      <EntityQualityPanel entityId={assetId!} entityType="asset" />

      {/* Edit dialog */}
      {asset && (
        <AssetFormDialog
          isOpen={isEditOpen}
          onOpenChange={setIsEditOpen}
          onSuccess={() => fetchAsset()}
          assetTypeId={asset.asset_type_id}
          assetTypeName={asset.asset_type_name || 'Asset'}
          assetTypeIri={ontologyIri}
          asset={asset}
        />
      )}

      {/* Lineage Editor */}
      {showLineageTab && asset && (
        <LineageEditor
          isOpen={isLineageEditorOpen}
          onOpenChange={setIsLineageEditorOpen}
          entityType={ontologyTypeName}
          entityId={asset.id}
          entityName={asset.name}
          onSuccess={() => fetchAsset()}
        />
      )}

      {/* Delete confirmation */}
      {assetId && (
        <AssetDeleteDialog
          open={isDeleteDialogOpen}
          onOpenChange={setIsDeleteDialogOpen}
          assetId={assetId}
          assetName={asset?.name || ''}
          onDeleted={() => navigate(-1)}
        />
      )}
    </div>
  );
}
