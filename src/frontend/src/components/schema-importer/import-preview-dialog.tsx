import { useState, useEffect, useMemo } from 'react';
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
import { ScrollArea } from '@/components/ui/scroll-area';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  ImportPreviewItem,
  ImportResultItem,
  ImportRequest,
  ImportResult,
  ImportDepth,
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
// Props
// ---------------------------------------------------------------------------

interface ImportPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectionId: string;
  selectedPaths: string[];
  depth: ImportDepth;
}

export default function ImportPreviewDialog({
  open,
  onOpenChange,
  connectionId,
  selectedPaths,
  depth,
}: ImportPreviewDialogProps) {
  const { post: apiPost } = useApi();
  const { toast } = useToast();

  const [previewItems, setPreviewItems] = useState<ImportPreviewItem[]>([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

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
      const payload: ImportRequest = {
        connection_id: connectionId,
        selected_paths: selectedPaths,
        depth,
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

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setPreviewItems([]);
      setImportResult(null);
      setHasLoaded(false);
      setCollapsed(new Set());
    }
    onOpenChange(nextOpen);
  };

  useEffect(() => {
    if (open && !hasLoaded && !isLoadingPreview) {
      loadPreview();
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

  const toCreate = previewItems.filter((i) => i.will_create).length;
  const toSkip = previewItems.filter((i) => !i.will_create).length;

  // ---------------------------------------------------------------------------
  // Tree renderers
  // ---------------------------------------------------------------------------

  function renderPreviewNode(node: TreeNode<ImportPreviewItem>) {
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

          {item.will_create ? (
            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
          ) : (
            <MinusCircle className="h-4 w-4 text-yellow-500 shrink-0" />
          )}

          {getAssetIcon(item.asset_type)}
          <span className="truncate flex-1">{item.name}</span>

          <Badge variant="outline" className="text-xs shrink-0">
            {item.asset_type}
          </Badge>
          <span className="text-xs text-muted-foreground shrink-0">
            {item.will_create ? 'new' : 'exists'}
          </span>
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

        <DialogFooter>
          {importResult ? (
            <Button variant="outline" onClick={() => handleOpenChange(false)}>
              Close
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              <Button
                onClick={executeImport}
                disabled={isImporting || toCreate === 0}
              >
                {isImporting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Import {toCreate} asset{toCreate !== 1 ? 's' : ''}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
