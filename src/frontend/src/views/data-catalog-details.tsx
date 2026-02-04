/**
 * Data Catalog Details View
 * 
 * Shows detailed information for a specific table:
 * - Overview tab: metadata, owner, dates
 * - Data Details tab: column list with types and descriptions
 * - Lineage tab: interactive lineage visualization
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  // BookOpen, // Available for future use
  Table as TableIcon,
  Eye,
  User,
  Calendar,
  // Database, // Available for future use
  Info,
  Columns,
  GitBranch,
  // Loader2, // Available for future use
  AlertCircle,
  Copy,
  Check,
  // ExternalLink, // Available for future use
  HardDrive,
  FileType,
  Tag
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import LineageGraphComponent from '@/components/data-catalog/lineage-graph';

import type { 
  TableInfo, 
  // ColumnInfo, // Available for future use
  LineageGraph,
  LineageDirection,
  ImpactAnalysis
} from '@/types/data-catalog';

// =============================================================================
// Component
// =============================================================================

const DataCatalogDetails: React.FC = () => {
  const { '*': tableFqn } = useParams<{ '*': string }>();
  const navigate = useNavigate();
  const { t } = useTranslation(['data-catalog', 'common']);
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  // State
  const [tableInfo, setTableInfo] = useState<TableInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('overview');
  
  // Lineage state
  const [lineageGraph, setLineageGraph] = useState<LineageGraph | null>(null);
  const [lineageDirection, setLineageDirection] = useState<LineageDirection>('both');
  const [isLineageLoading, setIsLineageLoading] = useState(false);
  const [lineageError, setLineageError] = useState<string | null>(null);
  
  // Impact state
  const [impact, setImpact] = useState<ImpactAnalysis | null>(null);
  const [_isImpactLoading, setIsImpactLoading] = useState(false);
  
  // Copy state
  const [copiedFqn, setCopiedFqn] = useState(false);

  // Decode the table FQN
  const decodedFqn = tableFqn ? decodeURIComponent(tableFqn) : '';

  // Set breadcrumbs
  useEffect(() => {
    setStaticSegments([
      { label: t('common:home'), path: '/' },
      { label: t('data-catalog:title', 'Data Catalog'), path: '/data-catalog' }
    ]);
    setDynamicTitle(tableInfo?.name || decodedFqn.split('.').pop() || 'Details');
  }, [setStaticSegments, setDynamicTitle, t, tableInfo, decodedFqn]);

  // Fetch table details
  const fetchTableDetails = useCallback(async () => {
    if (!decodedFqn) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/data-catalog/tables/${encodeURIComponent(decodedFqn)}`);
      
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Table not found');
        }
        throw new Error(`Failed to fetch table: ${response.statusText}`);
      }
      
      const data: TableInfo = await response.json();
      setTableInfo(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [decodedFqn]);

  // Fetch lineage
  const fetchLineage = useCallback(async () => {
    if (!decodedFqn) return;
    
    setIsLineageLoading(true);
    setLineageError(null);
    
    try {
      const response = await fetch(
        `/api/data-catalog/tables/${encodeURIComponent(decodedFqn)}/lineage?direction=${lineageDirection}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch lineage');
      }
      
      const data: LineageGraph = await response.json();
      setLineageGraph(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load lineage';
      setLineageError(message);
    } finally {
      setIsLineageLoading(false);
    }
  }, [decodedFqn, lineageDirection]);

  // Fetch impact analysis
  const fetchImpact = useCallback(async () => {
    if (!decodedFqn) return;
    
    setIsImpactLoading(true);
    
    try {
      const response = await fetch(
        `/api/data-catalog/tables/${encodeURIComponent(decodedFqn)}/impact`
      );
      
      if (response.ok) {
        const data: ImpactAnalysis = await response.json();
        setImpact(data);
      }
    } catch (err) {
      console.error('Failed to fetch impact:', err);
    } finally {
      setIsImpactLoading(false);
    }
  }, [decodedFqn]);

  // Initial load
  useEffect(() => {
    fetchTableDetails();
  }, [fetchTableDetails]);

  // Fetch lineage when tab changes or direction changes
  useEffect(() => {
    if (activeTab === 'lineage') {
      fetchLineage();
      fetchImpact();
    }
  }, [activeTab, fetchLineage, fetchImpact]);

  // Copy FQN to clipboard
  const handleCopyFqn = async () => {
    if (!tableInfo) return;
    
    try {
      await navigator.clipboard.writeText(tableInfo.full_name);
      setCopiedFqn(true);
      setTimeout(() => setCopiedFqn(false), 2000);
      toast({
        title: t('common:copied'),
        description: tableInfo.full_name
      });
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Format date
  const formatDate = (dateStr: string | null | undefined): string => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  // Format bytes
  const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
  };

  if (isLoading) {
    return (
      <div className="flex flex-col h-full p-6 gap-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded" />
          <div>
            <Skeleton className="h-6 w-64 mb-2" />
            <Skeleton className="h-4 w-96" />
          </div>
        </div>
        <Skeleton className="h-12 w-full" />
        <Skeleton className="flex-1" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6">
        <AlertCircle className="h-12 w-12 text-destructive mb-4" />
        <h2 className="text-xl font-semibold mb-2">{t('common:error')}</h2>
        <p className="text-muted-foreground mb-4">{error}</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate('/data-catalog')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            {t('common:back')}
          </Button>
          <Button onClick={fetchTableDetails}>
            {t('common:retry', 'Retry')}
          </Button>
        </div>
      </div>
    );
  }

  if (!tableInfo) {
    return null;
  }

  const isView = tableInfo.table_type === 'VIEW';

  return (
    <div className="flex flex-col h-full p-6 gap-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/data-catalog')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          
          <div className="flex items-center gap-3">
            {isView ? (
              <Eye className="h-8 w-8 text-green-600 dark:text-green-400" />
            ) : (
              <TableIcon className="h-8 w-8 text-blue-600 dark:text-blue-400" />
            )}
            
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-semibold">{tableInfo.name}</h1>
                <Badge variant={isView ? 'secondary' : 'default'}>
                  {tableInfo.table_type}
                </Badge>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground">
                <code className="text-sm bg-muted px-2 py-0.5 rounded">
                  {tableInfo.full_name}
                </code>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopyFqn}>
                      {copiedFqn ? (
                        <Check className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('common:copy')}</TooltipContent>
                </Tooltip>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
        <TabsList className="grid w-full max-w-md grid-cols-3">
          <TabsTrigger value="overview" className="flex items-center gap-2">
            <Info className="h-4 w-4" />
            {t('data-catalog:tabs.overview', 'Overview')}
          </TabsTrigger>
          <TabsTrigger value="columns" className="flex items-center gap-2">
            <Columns className="h-4 w-4" />
            {t('data-catalog:tabs.dataDetails', 'Data Details')}
          </TabsTrigger>
          <TabsTrigger value="lineage" className="flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            {t('data-catalog:tabs.lineage', 'Lineage')}
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="flex-1 mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Basic Info */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('data-catalog:overview.basicInfo', 'Basic Information')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">{t('data-catalog:overview.catalog', 'Catalog')}</p>
                    <p className="font-medium">{tableInfo.catalog_name}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">{t('data-catalog:overview.schema', 'Schema')}</p>
                    <p className="font-medium">{tableInfo.schema_name}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <User className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.owner', 'Owner')}
                    </p>
                    <p className="font-medium">{tableInfo.owner || '—'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">{t('data-catalog:overview.type', 'Type')}</p>
                    <Badge variant="outline">{tableInfo.table_type}</Badge>
                  </div>
                </div>
                
                <Separator />
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.created', 'Created')}
                    </p>
                    <p className="text-sm">{formatDate(tableInfo.created_at)}</p>
                    {tableInfo.created_by && (
                      <p className="text-xs text-muted-foreground">by {tableInfo.created_by}</p>
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.updated', 'Updated')}
                    </p>
                    <p className="text-sm">{formatDate(tableInfo.updated_at)}</p>
                    {tableInfo.updated_by && (
                      <p className="text-xs text-muted-foreground">by {tableInfo.updated_by}</p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Storage & Stats */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('data-catalog:overview.storage', 'Storage & Statistics')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <Columns className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.columns', 'Columns')}
                    </p>
                    <p className="font-medium">{tableInfo.columns.length}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">{t('data-catalog:overview.rows', 'Rows')}</p>
                    <p className="font-medium">
                      {tableInfo.row_count?.toLocaleString() || '—'}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <HardDrive className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.size', 'Size')}
                    </p>
                    <p className="font-medium">{formatBytes(tableInfo.size_bytes)}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <FileType className="h-3.5 w-3.5" />
                      {t('data-catalog:overview.format', 'Format')}
                    </p>
                    <p className="font-medium">{tableInfo.data_source_format || '—'}</p>
                  </div>
                </div>
                
                {tableInfo.storage_location && (
                  <>
                    <Separator />
                    <div>
                      <p className="text-sm text-muted-foreground mb-1">
                        {t('data-catalog:overview.location', 'Storage Location')}
                      </p>
                      <code className="text-xs bg-muted px-2 py-1 rounded block truncate">
                        {tableInfo.storage_location}
                      </code>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Description */}
            {tableInfo.comment && (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-lg">{t('data-catalog:overview.description', 'Description')}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm whitespace-pre-wrap">{tableInfo.comment}</p>
                </CardContent>
              </Card>
            )}

            {/* Tags */}
            {tableInfo.tags && Object.keys(tableInfo.tags).length > 0 && (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Tag className="h-4 w-4" />
                    {t('data-catalog:overview.tags', 'Tags')}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(tableInfo.tags).map(([key, value]) => (
                      <Badge key={key} variant="secondary">
                        {key}: {value}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Columns Tab */}
        <TabsContent value="columns" className="flex-1 mt-6">
          <Card className="h-full flex flex-col">
            <CardHeader>
              <CardTitle className="text-lg">
                {t('data-catalog:dataDetails.title', 'Columns')}
                <Badge variant="secondary" className="ml-2">{tableInfo.columns.length}</Badge>
              </CardTitle>
              <CardDescription>
                {t('data-catalog:dataDetails.description', 'Column definitions and metadata')}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex-1 p-0 min-h-0">
              <ScrollArea className="h-full">
                <Table>
                  <TableHeader className="sticky top-0 bg-background">
                    <TableRow>
                      <TableHead className="w-[50px]">#</TableHead>
                      <TableHead>{t('data-catalog:dataDetails.columnName', 'Column Name')}</TableHead>
                      <TableHead>{t('data-catalog:dataDetails.type', 'Type')}</TableHead>
                      <TableHead className="w-[80px]">{t('data-catalog:dataDetails.nullable', 'Nullable')}</TableHead>
                      <TableHead>{t('data-catalog:dataDetails.description', 'Description')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tableInfo.columns.map((col, idx) => (
                      <TableRow key={col.name}>
                        <TableCell className="text-muted-foreground text-sm">
                          {idx + 1}
                        </TableCell>
                        <TableCell>
                          <code className="text-sm font-medium">{col.name}</code>
                          {col.partition_index !== null && col.partition_index !== undefined && (
                            <Badge variant="outline" className="ml-2 text-xs">
                              Partition {col.partition_index}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="font-mono text-xs">
                            {col.type_text}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {col.nullable ? (
                            <Badge variant="outline" className="text-xs">Yes</Badge>
                          ) : (
                            <Badge variant="destructive" className="text-xs">No</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-md">
                          {col.comment || '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Lineage Tab */}
        <TabsContent value="lineage" className="flex-1 mt-6">
          <Card className="h-full flex flex-col">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <GitBranch className="h-5 w-5" />
                {t('data-catalog:lineage.title', 'Data Lineage')}
              </CardTitle>
              <CardDescription>
                {t('data-catalog:lineage.description', 'Visualize upstream and downstream dependencies')}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex-1">
              <LineageGraphComponent
                graph={lineageGraph}
                isLoading={isLineageLoading}
                error={lineageError}
                direction={lineageDirection}
                onDirectionChange={setLineageDirection}
                onRefresh={fetchLineage}
              />
              
              {/* Impact Summary */}
              {impact && impact.total_impacted_count > 0 && (
                <Card className="mt-6 border-orange-200 dark:border-orange-800">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base text-orange-700 dark:text-orange-300">
                      {t('data-catalog:lineage.impactSummary', 'Impact Summary')}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground mb-2">
                      {t('data-catalog:lineage.impactWarning', 'Changes to this table may affect:')}
                    </p>
                    <div className="flex gap-4">
                      {impact.impacted_tables.length > 0 && (
                        <Badge variant="outline">{impact.impacted_tables.length} tables</Badge>
                      )}
                      {impact.impacted_views.length > 0 && (
                        <Badge variant="outline">{impact.impacted_views.length} views</Badge>
                      )}
                      {impact.impacted_external.length > 0 && (
                        <Badge variant="outline">{impact.impacted_external.length} external</Badge>
                      )}
                    </div>
                    {impact.affected_owners.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-2">
                        {t('data-catalog:lineage.notifyOwners', 'Owners to notify')}: {impact.affected_owners.join(', ')}
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default DataCatalogDetails;

