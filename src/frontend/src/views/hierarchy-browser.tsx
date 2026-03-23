import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Network, AlertCircle, Search,
  Box, Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain,
  Activity, Server, Shield, BookOpen, Database, FolderOpen, Shapes,
  ExternalLink, RefreshCw, ListTree, GitFork, Layers,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Tooltip, TooltipContent, TooltipTrigger,
} from '@/components/ui/tooltip';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { FeatureAccessLevel } from '@/types/settings';
import { HierarchyTreeNode } from '@/components/hierarchy/hierarchy-tree-node';
import { HierarchyGraphView } from '@/components/hierarchy/hierarchy-graph-view';
import type { InstanceHierarchyNode, HierarchyRootGroup } from '@/types/ontology-schema';
import { cn } from '@/lib/utils';

type DetailViewMode = 'tree' | 'graph';

const ALL_ROOT_TYPES = ['System', 'DataDomain', 'DataProduct'] as const;

const DEPTH_OPTIONS = [
  { value: '2', label: '2 levels' },
  { value: '3', label: '3 levels' },
  { value: '4', label: '4 levels' },
  { value: '6', label: '6 levels' },
  { value: '10', label: 'All' },
];

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box, Network,
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
};

const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
};

function getIconComponent(iconName?: string | null): React.ElementType {
  if (!iconName) return Box;
  return ICON_MAP[iconName] || Box;
}

function getEntityRoute(entityType: string, entityId: string): string {
  const base = TYPE_ROUTE_MAP[entityType];
  if (base) return `${base}/${entityId}`;
  return `/assets/${entityId}`;
}

function TreeSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="space-y-1.5">
          <Skeleton className="h-5 w-32" />
          <div className="pl-6 space-y-1">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-4 w-44" />
          </div>
        </div>
      ))}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96" />
      <div className="space-y-2 mt-6">
        <Skeleton className="h-6 w-48" />
        <div className="pl-4 space-y-1.5">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-5 w-52" />
          <Skeleton className="h-5 w-60" />
        </div>
      </div>
    </div>
  );
}

interface DetailPanelProps {
  node: InstanceHierarchyNode | null;
  loading: boolean;
  detailNode: InstanceHierarchyNode | null;
  viewMode: DetailViewMode;
  onViewModeChange: (mode: DetailViewMode) => void;
  maxDepth: string;
  onMaxDepthChange: (depth: string) => void;
  visibleTypes: Set<string>;
  onVisibleTypesChange: (types: Set<string>) => void;
}

function collectEntityTypes(node: InstanceHierarchyNode): Set<string> {
  const types = new Set<string>();
  function walk(n: InstanceHierarchyNode) {
    types.add(n.entity_type);
    for (const child of n.children || []) walk(child);
  }
  walk(node);
  return types;
}

function filterNodeByTypes(
  node: InstanceHierarchyNode,
  visibleTypes: Set<string>,
): InstanceHierarchyNode | null {
  if (!visibleTypes.has(node.entity_type)) return null;
  const filteredChildren: InstanceHierarchyNode[] = [];
  for (const child of node.children || []) {
    const filtered = filterNodeByTypes(child, visibleTypes);
    if (filtered) filteredChildren.push(filtered);
  }
  return { ...node, children: filteredChildren, child_count: filteredChildren.length };
}

function DetailPanel({
  node, loading, detailNode, viewMode, onViewModeChange,
  maxDepth, onMaxDepthChange, visibleTypes, onVisibleTypesChange,
}: DetailPanelProps) {
  const navigate = useNavigate();

  const rawDisplayNode = detailNode || node;

  const allTypes = useMemo(
    () => rawDisplayNode ? collectEntityTypes(rawDisplayNode) : new Set<string>(),
    [rawDisplayNode],
  );
  const displayNode = useMemo(() => {
    if (!rawDisplayNode) return null;
    if (visibleTypes.size === 0 || visibleTypes.size >= allTypes.size) return rawDisplayNode;
    return filterNodeByTypes(rawDisplayNode, visibleTypes) || rawDisplayNode;
  }, [rawDisplayNode, visibleTypes, allTypes]);

  const toggleType = useCallback((type: string) => {
    const base = visibleTypes.size === 0 ? new Set(allTypes) : new Set(visibleTypes);
    if (base.has(type)) {
      if (base.size > 1) base.delete(type);
    } else {
      base.add(type);
    }
    onVisibleTypesChange(base);
  }, [visibleTypes, allTypes, onVisibleTypesChange]);

  if (loading) return <DetailSkeleton />;

  if (!node || !displayNode) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-24 text-muted-foreground">
        <Network className="h-16 w-16 mb-4 opacity-20" />
        <p className="text-lg font-medium">Select an entity</p>
        <p className="text-sm mt-1">
          Click on any item in the tree to view its hierarchy
        </p>
      </div>
    );
  }

  const Icon = getIconComponent(node.icon);
  const hasChildren = displayNode.children && displayNode.children.length > 0;

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-start justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-semibold">{displayNode.name}</h2>
            <div className="flex items-center gap-2 mt-0.5">
              <Badge variant="outline" className="text-xs">{displayNode.entity_type}</Badge>
              {displayNode.status && (
                <Badge variant={STATUS_VARIANT[displayNode.status] ?? 'outline'} className="text-xs">
                  {displayNode.status}
                </Badge>
              )}
              {displayNode.child_count > 0 && (
                <span className="text-xs text-muted-foreground">
                  {displayNode.child_count} {displayNode.child_count === 1 ? 'child' : 'children'}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hasChildren && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Select value={maxDepth} onValueChange={onMaxDepthChange}>
                      <SelectTrigger className="h-8 w-[100px] text-xs">
                        <Layers className="h-3 w-3 mr-1 flex-shrink-0" />
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {DEPTH_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </TooltipTrigger>
                <TooltipContent>Max hierarchy depth</TooltipContent>
              </Tooltip>
              <div className="flex border rounded-md overflow-hidden">
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn('h-8 px-2.5 rounded-none', viewMode === 'tree' && 'bg-muted')}
                  onClick={() => onViewModeChange('tree')}
                  aria-label="Tree view"
                >
                  <ListTree className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn('h-8 px-2.5 rounded-none', viewMode === 'graph' && 'bg-muted')}
                  onClick={() => onViewModeChange('graph')}
                  aria-label="Graph view"
                >
                  <GitFork className="h-3.5 w-3.5" />
                </Button>
              </div>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(getEntityRoute(displayNode.entity_type, displayNode.entity_id))}
          >
            <ExternalLink className="mr-1 h-3.5 w-3.5" />
            View Detail
          </Button>
        </div>
      </div>

      {displayNode.description && (
        <p className="text-sm text-muted-foreground flex-shrink-0">{displayNode.description}</p>
      )}

      {/* Entity type filter chips */}
      {allTypes.size > 1 && (
        <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
          <span className="text-xs text-muted-foreground mr-1">Show:</span>
          {Array.from(allTypes).map((type) => {
            const isAllVisible = visibleTypes.size === 0;
            const active = isAllVisible || visibleTypes.has(type);
            return (
              <Badge
                key={type}
                variant={active ? 'default' : 'outline'}
                className={cn(
                  'cursor-pointer text-[10px] h-5 px-1.5 transition-opacity',
                  !active && 'opacity-50',
                )}
                onClick={() => toggleType(type)}
              >
                {type}
              </Badge>
            );
          })}
          {visibleTypes.size > 0 && visibleTypes.size < allTypes.size && (
            <Button
              variant="ghost"
              size="sm"
              className="h-5 px-1.5 text-[10px]"
              onClick={() => onVisibleTypesChange(new Set())}
            >
              Show all
            </Button>
          )}
        </div>
      )}

      <Separator className="flex-shrink-0" />

      {/* Children visualization */}
      {hasChildren ? (
        viewMode === 'graph' ? (
          <div className="flex-1 min-h-0">
            <HierarchyGraphView rootNode={displayNode} className="h-full" />
          </div>
        ) : (
          <div className="flex-1 overflow-auto">
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Hierarchy
            </h3>
            <div className="border rounded-lg p-2">
              <div className="flex items-center gap-2 px-2 py-1.5 bg-primary/5 rounded-md mb-1">
                <Icon className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">{displayNode.name}</span>
              </div>
              {displayNode.children.map((child) => (
                <HierarchyTreeNode
                  key={`${child.entity_type}-${child.entity_id}`}
                  node={child}
                  depth={1}
                  isLazy
                />
              ))}
            </div>
          </div>
        )
      ) : (
        <div className="text-center py-8 text-muted-foreground">
          <Box className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No children in the hierarchy</p>
        </div>
      )}
    </div>
  );
}

export default function HierarchyBrowserView() {
  const [rootGroups, setRootGroups] = useState<HierarchyRootGroup[]>([]);
  const [rootsLoading, setRootsLoading] = useState(true);
  const [rootsError, setRootsError] = useState<string | null>(null);

  const [selectedNode, setSelectedNode] = useState<InstanceHierarchyNode | null>(null);
  const selectedRef = useRef<string | null>(null);
  const [detailNode, setDetailNode] = useState<InstanceHierarchyNode | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailViewMode, setDetailViewMode] = useState<DetailViewMode>('tree');
  const [maxDepth, setMaxDepth] = useState('4');
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set());

  const [treeFilter, setTreeFilter] = useState('');
  const [enabledRootTypes, setEnabledRootTypes] = useState<Set<string>>(
    () => new Set(ALL_ROOT_TYPES),
  );

  const [searchParams, setSearchParams] = useSearchParams();

  const { get: apiGet } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const featureId = 'assets';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle('Hierarchy Browser');
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [setStaticSegments, setDynamicTitle]);

  const fetchRoots = useCallback(async () => {
    setRootsLoading(true);
    setRootsError(null);
    try {
      const response = await apiGet<HierarchyRootGroup[]>(
        '/api/entity-hierarchy/roots?types=System,DataDomain,DataProduct'
      );
      if (response.error) throw new Error(response.error);
      setRootGroups(Array.isArray(response.data) ? response.data : []);
    } catch (err: any) {
      setRootsError(err.message || 'Failed to load hierarchy roots');
    } finally {
      setRootsLoading(false);
    }
  }, [apiGet]);

  useEffect(() => { fetchRoots(); }, [fetchRoots]);

  const fetchDetail = useCallback(async (entityType: string, entityId: string, depth: string) => {
    setDetailLoading(true);
    try {
      const response = await apiGet<InstanceHierarchyNode>(
        `/api/entity-hierarchy/${entityType}/${entityId}?max_depth=${depth}`
      );
      if (!response.error && response.data) {
        setDetailNode(response.data);
        setVisibleTypes(new Set());
      } else {
        setDetailNode(null);
      }
    } catch {
      setDetailNode(null);
    } finally {
      setDetailLoading(false);
    }
  }, [apiGet]);

  const handleSelectNode = useCallback(async (node: InstanceHierarchyNode) => {
    selectedRef.current = node.entity_id;
    setSelectedNode(node);
    setVisibleTypes(new Set());
    setSearchParams({ type: node.entity_type, id: node.entity_id }, { replace: true });
    fetchDetail(node.entity_type, node.entity_id, maxDepth);
  }, [setSearchParams, fetchDetail, maxDepth]);

  // Auto-select from URL params (initial load only)
  useEffect(() => {
    const type = searchParams.get('type');
    const id = searchParams.get('id');
    if (type && id && !selectedRef.current) {
      handleSelectNode({ entity_type: type, entity_id: id, name: '', child_count: 0, children: [] });
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleMaxDepthChange = useCallback((depth: string) => {
    setMaxDepth(depth);
    if (selectedNode) {
      fetchDetail(selectedNode.entity_type, selectedNode.entity_id, depth);
    }
  }, [selectedNode, fetchDetail]);

  const toggleRootType = useCallback((type: string) => {
    setEnabledRootTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        if (next.size > 1) next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const filteredGroups = useMemo(() => {
    let groups = rootGroups.filter((g) => enabledRootTypes.has(g.entity_type));
    if (treeFilter.trim()) {
      const q = treeFilter.toLowerCase();
      groups = groups.map((group) => ({
        ...group,
        roots: group.roots.filter((root) => root.name.toLowerCase().includes(q)),
      })).filter((group) => group.roots.length > 0);
    }
    return groups;
  }, [rootGroups, treeFilter, enabledRootTypes]);

  if (!canRead && !permissionsLoading) {
    return (
      <div className="py-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Permission Denied</AlertTitle>
          <AlertDescription>You don't have access to browse the hierarchy.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="py-6">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Network className="w-8 h-8" />
          Hierarchy Browser
        </h1>
        <p className="text-muted-foreground mt-1">
          Navigate data hierarchies from systems and domains down to tables and columns
        </p>
      </div>

      {rootsError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{rootsError}</AlertDescription>
        </Alert>
      )}

      <div className="flex gap-6 h-[calc(100vh-240px)]">
        {/* Left panel: Tree browser */}
        <div className="w-80 flex-shrink-0">
          <Card className="h-full flex flex-col">
            <CardHeader className="pb-3 flex-shrink-0">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">Browse</CardTitle>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={fetchRoots}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              </div>
              {/* Root type filter chips */}
              <div className="flex items-center gap-1 mt-2 flex-wrap">
                {ALL_ROOT_TYPES.map((type) => {
                  const active = enabledRootTypes.has(type);
                  const count = rootGroups.find((g) => g.entity_type === type)?.roots.length ?? 0;
                  return (
                    <Badge
                      key={type}
                      variant={active ? 'default' : 'outline'}
                      className={cn(
                        'cursor-pointer text-[10px] h-5 px-1.5 transition-opacity select-none',
                        !active && 'opacity-40',
                      )}
                      onClick={() => toggleRootType(type)}
                    >
                      {type === 'DataDomain' ? 'Domain' : type === 'DataProduct' ? 'Product' : type}
                      {count > 0 && <span className="ml-0.5 opacity-70">{count}</span>}
                    </Badge>
                  );
                })}
              </div>
              <div className="relative mt-2">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Filter..."
                  value={treeFilter}
                  onChange={(e) => setTreeFilter(e.target.value)}
                  className="h-8 pl-8 text-sm"
                />
              </div>
            </CardHeader>
            <CardContent className="p-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full">
                <div className="px-2 pb-2" role="tree">
                  {rootsLoading ? (
                    <TreeSkeleton />
                  ) : filteredGroups.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                      <Network className="h-8 w-8 mx-auto mb-2 opacity-30" />
                      <p className="text-sm">
                        {treeFilter ? 'No matches found' : 'No root entities found'}
                      </p>
                    </div>
                  ) : (
                    filteredGroups.map((group) => {
                      const GroupIcon = getIconComponent(group.icon);
                      return (
                        <div key={group.entity_type} className="mb-3">
                          <div className="flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                            <GroupIcon className="h-3.5 w-3.5" />
                            {group.label}
                            <span className="ml-auto text-xs font-normal">{group.roots.length}</span>
                          </div>
                          {group.roots.map((root) => (
                            <HierarchyTreeNode
                              key={`${root.entity_type}-${root.entity_id}`}
                              node={root}
                              depth={0}
                              selectedId={selectedNode?.entity_id}
                              onSelect={handleSelectNode}
                              isLazy
                            />
                          ))}
                        </div>
                      );
                    })
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Right panel: Detail / subtree view */}
        <div className="flex-1 min-w-0">
          <Card className="h-full overflow-hidden">
            <DetailPanel
              node={selectedNode}
              loading={detailLoading}
              detailNode={detailNode}
              viewMode={detailViewMode}
              onViewModeChange={setDetailViewMode}
              maxDepth={maxDepth}
              onMaxDepthChange={handleMaxDepthChange}
              visibleTypes={visibleTypes}
              onVisibleTypesChange={setVisibleTypes}
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
