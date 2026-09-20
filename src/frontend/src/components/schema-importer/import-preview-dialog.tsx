import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  MinusCircle,
  ChevronRight,
  ChevronDown,
  Table2,
  Eye,
  Columns3,
  Box,
  FolderOpen,
  Database,
  Library,
  Server,
  Link2,
  Unlink,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { AssetSelector, type SelectedAsset } from '@/components/common/asset-selector';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  ImportPreviewItem,
  ImportResultItem,
  ImportRequest,
  ImportResult,
  ImportDepth,
  StartImportRunResponse,
  SchemaImportRunDetail,
} from '@/types/schema-import';

// ---------------------------------------------------------------------------
// Tree helpers
// ---------------------------------------------------------------------------

interface TreeNode<T> {
  item: T;
  children: TreeNode<T>[];
  isExpanded: boolean;
  level: number;
}

function buildTree<T>(
  items: T[],
  getPath: (item: T) => string,
  getParentPath: (item: T) => string | null,
): TreeNode<T>[] {
  const nodeMap = new Map<string, TreeNode<T>>();
  const roots: TreeNode<T>[] = [];

  for (const item of items) {
    nodeMap.set(getPath(item), {
      item,
      children: [],
      isExpanded: true,
      level: 0,
    });
  }

  for (const item of items) {
    const parentPath = getParentPath(item);
    const node = nodeMap.get(getPath(item))!;
    const parent = parentPath ? nodeMap.get(parentPath) : undefined;

    if (parent) {
      node.level = parent.level + 1;
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortChildren = (nodes: TreeNode<T>[]) => {
    nodes.sort((a, b) => getPath(a.item).localeCompare(getPath(b.item)));
    for (const n of nodes) sortChildren(n.children);
  };
  sortChildren(roots);

  return roots;
}

// ---------------------------------------------------------------------------
// Icon map (mirrors schema-browser.tsx)
// ---------------------------------------------------------------------------

const assetTypeIconMap: Record<string, typeof Database> = {
  table: Table2,
  view: Eye,
  column: Columns3,
  catalog: Library,
  schema: FolderOpen,
  dataset: FolderOpen,
  database: Database,
  'ml model': Box,
  dashboard: Box,
  system: Server,
};

function getAssetIcon(assetType: string) {
  const Icon = assetTypeIconMap[assetType.toLowerCase()] || Box;
  return <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

// ---------------------------------------------------------------------------
// Mapped asset info (id + display name)
// ---------------------------------------------------------------------------

interface MappedAsset {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ImportPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectionId?: string;
  selectedPaths?: string[];
  depth?: ImportDepth;
  // Result-only mode: when provided, the dialog opens straight into the result
  // view for a completed run (skips preview/import). Used to re-open a finished
  // background import from its notification.
  initialResult?: ImportResult | null;
}

export default function ImportPreviewDialog({
  open,
  onOpenChange,
  connectionId = '',
  selectedPaths = [],
  depth = 'full_recursive',
  initialResult = null,
}: ImportPreviewDialogProps) {
  const { post: apiPost, get: apiGet } = useApi();
  const { toast } = useToast();

  const [previewItems, setPreviewItems] = useState<ImportPreviewItem[]>([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  // Async (background) import state
  const [asyncThreshold, setAsyncThreshold] = useState<number>(200);
  const [isStartingAsync, setIsStartingAsync] = useState(false);
  const [asyncRun, setAsyncRun] = useState<SchemaImportRunDetail | null>(null);

  // Toggle / map-to-existing state
  const [excludedPaths, setExcludedPaths] = useState<Set<string>>(new Set());
  const [pathMappings, setPathMappings] = useState<Record<string, MappedAsset>>({});
  const [selectorOpenForPath, setSelectorOpenForPath] = useState<string | null>(null);

  const loadPreview = async () => {
    setIsLoadingPreview(true);
    setImportResult(null);
    try {
      const payload: ImportRequest = {
        connection_id: connectionId,
        selected_paths: selectedPaths,
        depth,
        dry_run: true,
      };
      const resp = await apiPost<ImportPreviewItem[]>('/api/schema-import/preview', payload);
      if (resp.data) {
        setPreviewItems(resp.data);
        setHasLoaded(true);
      }
    } catch (err) {
      console.error('Preview failed:', err);
      toast({ title: 'Preview failed', description: String(err), variant: 'destructive' });
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const executeImport = async () => {
    setIsImporting(true);
    try {
      const mappingsForApi: Record<string, string> = {};
      for (const [path, asset] of Object.entries(pathMappings)) {
        mappingsForApi[path] = asset.id;
      }
      const payload: ImportRequest = {
        connection_id: connectionId,
        selected_paths: selectedPaths,
        depth,
        excluded_paths: Array.from(excludedPaths),
        path_mappings: Object.keys(mappingsForApi).length > 0 ? mappingsForApi : undefined,
      };
      const resp = await apiPost<ImportResult>('/api/schema-import/import', payload);
      if (resp.data) {
        setImportResult(resp.data);
        setCollapsed(new Set());
        toast({
          title: 'Import complete',
          description: `Created ${resp.data.created}, skipped ${resp.data.skipped}, errors ${resp.data.errors}`,
        });
      }
    } catch (err) {
      console.error('Import failed:', err);
      toast({ title: 'Import failed', description: String(err), variant: 'destructive' });
    } finally {
      setIsImporting(false);
    }
  };

  const startAsyncImport = async () => {
    setIsStartingAsync(true);
    try {
      const mappingsForApi: Record<string, string> = {};
      for (const [path, asset] of Object.entries(pathMappings)) {
        mappingsForApi[path] = asset.id;
      }
      const payload: ImportRequest = {
        connection_id: connectionId,
        selected_paths: selectedPaths,
        depth,
        excluded_paths: Array.from(excludedPaths),
        path_mappings: Object.keys(mappingsForApi).length > 0 ? mappingsForApi : undefined,
      };
      const resp = await apiPost<StartImportRunResponse>('/api/schema-import/import-async', payload);
      if (resp.data) {
        setAsyncRun({
          id: resp.data.run_id,
          status: resp.data.status,
          processed_items: 0,
          created_count: 0,
          skipped_count: 0,
          error_count: 0,
        });
        toast({
          title: 'Import started',
          description: 'Running in the background — progress appears here and in your notifications.',
        });
      }
    } catch (err) {
      console.error('Async import failed to start:', err);
      toast({ title: 'Could not start background import', description: String(err), variant: 'destructive' });
    } finally {
      setIsStartingAsync(false);
    }
  };

  const cancelAsyncImport = async () => {
    if (!asyncRun) return;
    try {
      await apiPost(`/api/schema-import/runs/${asyncRun.id}/cancel`, {});
    } catch (err) {
      console.error('Cancel failed:', err);
    }
  };

  // Poll the background run until it reaches a terminal state.
  useEffect(() => {
    if (!asyncRun || (asyncRun.status !== 'pending' && asyncRun.status !== 'running')) {
      return;
    }
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const resp = await apiGet<SchemaImportRunDetail>(`/api/schema-import/runs/${asyncRun.id}`);
        if (cancelled || !resp.data) return;
        setAsyncRun(resp.data);
        if (resp.data.status === 'completed' || resp.data.status === 'failed' || resp.data.status === 'cancelled') {
          if (resp.data.result) setImportResult(resp.data.result);
          if (resp.data.status === 'completed') {
            toast({
              title: 'Import complete',
              description: `Created ${resp.data.created_count}, skipped ${resp.data.skipped_count}, errors ${resp.data.error_count}`,
            });
          } else if (resp.data.status === 'failed') {
            toast({ title: 'Import failed', description: resp.data.error || 'See run details', variant: 'destructive' });
          }
        }
      } catch (err) {
        console.error('Run poll failed:', err);
      }
    }, 2000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [asyncRun?.id, asyncRun?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the async threshold once when the dialog opens.
  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const resp = await apiGet<{ schema_import_async_threshold?: number }>('/api/settings');
        if (resp.data?.schema_import_async_threshold) {
          setAsyncThreshold(resp.data.schema_import_async_threshold);
        }
      } catch {
        /* keep default */
      }
    })();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setPreviewItems([]);
      setImportResult(null);
      setHasLoaded(false);
      setCollapsed(new Set());
      setExcludedPaths(new Set());
      setPathMappings({});
      setSelectorOpenForPath(null);
      setAsyncRun(null);
    }
    onOpenChange(nextOpen);
  };

  useEffect(() => {
    if (open && !hasLoaded && !isLoadingPreview) {
      // Result-only mode (e.g. reopened from a completed import notification):
      // show the stored result directly instead of running a fresh preview.
      if (initialResult) {
        setImportResult(initialResult);
        setHasLoaded(true);
      } else {
        loadPreview();
      }
    }
  }, [open, hasLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const previewTree = useMemo(
    () => buildTree(previewItems, (i) => i.path, (i) => i.parent_path),
    [previewItems],
  );

  const resultTree = useMemo(
    () => (importResult ? buildTree(importResult.items, (i) => i.path, (i) => i.parent_path) : []),
    [importResult],
  );

  const toggleCollapse = (path: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const toggleExclude = useCallback((path: string) => {
    setExcludedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
        setPathMappings((pm) => {
          if (path in pm) {
            const { [path]: _, ...rest } = pm;
            return rest;
          }
          return pm;
        });
      }
      return next;
    });
  }, []);

  const handleAssetSelected = useCallback((assets: SelectedAsset[]) => {
    if (!selectorOpenForPath || assets.length === 0) return;
    const picked = assets[0];
    setPathMappings((prev) => ({
      ...prev,
      [selectorOpenForPath]: { id: picked.id, name: picked.name },
    }));
    setExcludedPaths((prev) => {
      if (prev.has(selectorOpenForPath)) {
        const next = new Set(prev);
        next.delete(selectorOpenForPath);
        return next;
      }
      return prev;
    });
    setSelectorOpenForPath(null);
  }, [selectorOpenForPath]);

  const clearMapping = useCallback((path: string) => {
    setPathMappings((prev) => {
      const { [path]: _, ...rest } = prev;
      return rest;
    });
  }, []);

  const activeItems = useMemo(
    () => previewItems.filter((i) => !excludedPaths.has(i.path)),
    [previewItems, excludedPaths],
  );
  const toCreate = activeItems.filter((i) => i.will_create && !(i.path in pathMappings)).length;
  const toSkip = activeItems.filter((i) => !i.will_create || i.path in pathMappings).length;

  // Resolve the asset type for the selector target
  const selectorTargetType = useMemo(() => {
    if (!selectorOpenForPath) return undefined;
    const item = previewItems.find((i) => i.path === selectorOpenForPath);
    return item ? [item.asset_type] : undefined;
  }, [selectorOpenForPath, previewItems]);

  // ---------------------------------------------------------------------------
  // Tree renderers
  // ---------------------------------------------------------------------------

  function renderPreviewNode(node: TreeNode<ImportPreviewItem>) {
    const { item, children, level } = node;
    const hasKids = children.length > 0;
    const isCollapsed = collapsed.has(item.path);
    const isExcluded = excludedPaths.has(item.path);
    const mapped = pathMappings[item.path];
    const isMapped = !!mapped;
    const canLink = item.is_ancestor && item.will_create && !isExcluded;

    return (
      <div key={item.path}>
        <div
          className={`flex items-center gap-2 py-1.5 px-3 text-sm rounded-sm hover:bg-muted/50 ${isExcluded ? 'opacity-40' : ''}`}
          style={{ paddingLeft: `${level * 20 + 12}px` }}
        >
          {hasKids ? (
            <button
              onClick={() => toggleCollapse(item.path)}
              className="p-0.5 hover:bg-muted rounded shrink-0"
            >
              {isCollapsed ? (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              )}
            </button>
          ) : (
            <span className="w-[22px] shrink-0" />
          )}

          {item.is_ancestor && (
            <Checkbox
              checked={!isExcluded}
              onCheckedChange={() => toggleExclude(item.path)}
              className="shrink-0"
            />
          )}

          {isExcluded ? (
            <MinusCircle className="h-4 w-4 text-muted-foreground shrink-0" />
          ) : isMapped ? (
            <Link2 className="h-4 w-4 text-blue-500 shrink-0" />
          ) : item.will_create ? (
            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
          ) : (
            <MinusCircle className="h-4 w-4 text-yellow-500 shrink-0" />
          )}

          {getAssetIcon(item.asset_type)}

          {isMapped ? (
            <span className="truncate flex-1 text-blue-500">
              {mapped.name}
            </span>
          ) : (
            <span className={`truncate flex-1 ${item.is_ancestor ? 'text-muted-foreground' : ''}`}>
              {item.name}
            </span>
          )}

          {/* Link / unlink icon for ancestors that would be created */}
          {canLink && !isMapped && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setSelectorOpenForPath(item.path)}
                  className="p-1 rounded hover:bg-muted shrink-0"
                >
                  <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top">Link to existing asset</TooltipContent>
            </Tooltip>
          )}
          {isMapped && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => clearMapping(item.path)}
                  className="p-1 rounded hover:bg-muted shrink-0"
                >
                  <Unlink className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top">Unlink — create new instead</TooltipContent>
            </Tooltip>
          )}

          <Badge variant="outline" className="text-xs shrink-0">
            {item.asset_type}
          </Badge>

          {isExcluded ? (
            <span className="text-xs text-muted-foreground shrink-0">skip</span>
          ) : isMapped ? (
            <span className="text-xs text-blue-500 shrink-0">linked</span>
          ) : (
            <span className="text-xs text-muted-foreground shrink-0">
              {item.will_create
                ? (item.is_ancestor ? 'auto' : 'new')
                : 'exists'}
            </span>
          )}
        </div>

        {hasKids && !isCollapsed && children.map(renderPreviewNode)}
      </div>
    );
  }

  function renderResultNode(node: TreeNode<ImportResultItem>) {
    const { item, children, level } = node;
    const hasKids = children.length > 0;
    const isCollapsed = collapsed.has(item.path);

    return (
      <div key={item.path}>
        <div
          className="flex items-center gap-2 py-1.5 px-3 text-sm rounded-sm hover:bg-muted/50"
          style={{ paddingLeft: `${level * 20 + 12}px` }}
        >
          {hasKids ? (
            <button
              onClick={() => toggleCollapse(item.path)}
              className="p-0.5 hover:bg-muted rounded shrink-0"
            >
              {isCollapsed ? (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              )}
            </button>
          ) : (
            <span className="w-[22px] shrink-0" />
          )}

          {item.action === 'created' ? (
            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
          ) : item.action === 'skipped' ? (
            <MinusCircle className="h-4 w-4 text-yellow-500 shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 text-destructive shrink-0" />
          )}

          {getAssetIcon(item.asset_type)}
          <span className="truncate flex-1">{item.name}</span>

          <Badge variant="outline" className="text-xs shrink-0">
            {item.asset_type}
          </Badge>
          <Badge
            variant={
              item.action === 'created'
                ? 'default'
                : item.action === 'error'
                  ? 'destructive'
                  : 'secondary'
            }
            className="text-xs shrink-0"
          >
            {item.action}
          </Badge>
        </div>

        {hasKids && !isCollapsed && children.map(renderResultNode)}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {importResult ? 'Import Results' : 'Import Preview'}
            </DialogTitle>
            <DialogDescription>
              {importResult
                ? `${importResult.created} created, ${importResult.skipped} skipped, ${importResult.errors} errors`
                : `${toCreate} to create, ${toSkip} already exist`}
            </DialogDescription>
          </DialogHeader>

          {isLoadingPreview ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
              <span className="ml-2 text-sm text-muted-foreground">Analyzing resources...</span>
            </div>
          ) : importResult ? (
            <ScrollArea className="max-h-[400px]">
              <div className="space-y-0.5 py-1">
                {resultTree.map(renderResultNode)}
                {resultTree.length === 0 && (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    No items in import result
                  </div>
                )}
              </div>
            </ScrollArea>
          ) : (
            <ScrollArea className="max-h-[400px]">
              <div className="space-y-0.5 py-1">
                {previewTree.map(renderPreviewNode)}
                {previewTree.length === 0 && (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    No importable resources found at the selected paths
                  </div>
                )}
              </div>
            </ScrollArea>
          )}

          {/* Background-run progress (while an async import is in flight) */}
          {asyncRun && !importResult && (
            <div className="rounded-md border bg-muted/30 p-3 text-sm space-y-1">
              <div className="flex items-center gap-2">
                {(asyncRun.status === 'pending' || asyncRun.status === 'running') && (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                )}
                <span className="font-medium capitalize">{asyncRun.status}</span>
                {asyncRun.total_items ? (
                  <span className="text-muted-foreground">
                    — {asyncRun.processed_items}/{asyncRun.total_items} processed
                    ({asyncRun.created_count} created, {asyncRun.skipped_count} skipped
                    {asyncRun.error_count ? `, ${asyncRun.error_count} errors` : ''})
                  </span>
                ) : (
                  <span className="text-muted-foreground">{asyncRun.progress_message || 'Starting…'}</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                You can close this dialog — the import keeps running and completion is reported in your notifications.
              </p>
            </div>
          )}

          <DialogFooter>
            {importResult ? (
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Close
              </Button>
            ) : asyncRun && (asyncRun.status === 'pending' || asyncRun.status === 'running') ? (
              <>
                <Button variant="outline" onClick={cancelAsyncImport}>
                  Cancel import
                </Button>
                <Button variant="outline" onClick={() => handleOpenChange(false)}>
                  Close (keep running)
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => handleOpenChange(false)}>
                  Cancel
                </Button>
                {toCreate >= asyncThreshold && (
                  <Button
                    variant="secondary"
                    onClick={startAsyncImport}
                    disabled={isStartingAsync || isImporting || toCreate === 0}
                  >
                    {isStartingAsync && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Run in background
                  </Button>
                )}
                <Button
                  onClick={executeImport}
                  disabled={isImporting || isStartingAsync || toCreate === 0}
                >
                  {isImporting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Import {toCreate} asset{toCreate !== 1 ? 's' : ''}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Asset selector opened from a link icon */}
      <AssetSelector
        isOpen={!!selectorOpenForPath}
        onOpenChange={(open) => { if (!open) setSelectorOpenForPath(null); }}
        onConfirm={handleAssetSelected}
        targetAssetTypes={selectorTargetType}
        title="Link to existing asset"
        description="Pick an existing asset to use instead of creating a new one"
        confirmLabel="Use selected"
      />
    </>
  );
}
