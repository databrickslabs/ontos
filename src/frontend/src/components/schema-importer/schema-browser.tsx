import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Loader2,
  Database,
  Table2,
  Eye,
  Columns3,
  Box,
  FolderOpen,
  Braces,
  Library,
  HardDrive,
  X,
  Search,
  AlertCircle,
} from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { useApi } from '@/hooks/use-api';
import { parseSearchQuery, matchesSegment } from '@/lib/uc-search-parser';
import type { BrowseNode, BrowseResponse } from '@/types/schema-import';

interface TreeNode extends BrowseNode {
  children?: TreeNode[];
  isExpanded: boolean;
  isLoading: boolean;
  level: number;
}

interface SchemaBrowserProps {
  connectionId: string | null;
  selectedPaths: Set<string>;
  onSelectionChange: (paths: Set<string>) => void;
}

interface LoadResult {
  nodes: TreeNode[];
  error?: string | null;
  errorDetail?: string | null;
}

const nodeIconMap: Record<string, typeof Database> = {
  catalog: Library,
  schema: FolderOpen,
  dataset: FolderOpen,
  database: Database,
  project: Database,
  table: Table2,
  view: Eye,
  column: Columns3,
  routine: Braces,
  function: Braces,
  procedure: Braces,
  model: Box,
  volume: HardDrive,
};

function getNodeIcon(nodeType: string) {
  const Icon = nodeIconMap[nodeType.toLowerCase()] || Box;
  return <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

/** Container node types that are navigational, not leaf assets */
const CONTAINER_TYPES = new Set(['catalog', 'schema', 'database', 'dataset', 'project']);

function findNodeByPath(nodes: TreeNode[], path: string): TreeNode | undefined {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children) {
      const found = findNodeByPath(n.children, path);
      if (found) return found;
    }
  }
  return undefined;
}

function updateNode(
  nodes: TreeNode[],
  path: string,
  updater: (n: TreeNode) => TreeNode,
): TreeNode[] {
  return nodes.map((n) => {
    if (n.path === path) return updater(n);
    if (n.children) return { ...n, children: updateNode(n.children, path, updater) };
    return n;
  });
}

export default function SchemaBrowser({
  connectionId,
  selectedPaths,
  onSelectionChange,
}: SchemaBrowserProps) {
  const { get: apiGet } = useApi();
  const [roots, setRoots] = useState<TreeNode[]>([]);
  const [isInitialLoading, setIsInitialLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [browseErrorDetail, setBrowseErrorDetail] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [highlightedPath, setHighlightedPath] = useState<string | null>(null);
  const apiGetRef = useRef(apiGet);
  apiGetRef.current = apiGet;
  const rootsRef = useRef(roots);
  rootsRef.current = roots;
  const searchVersionRef = useRef(0);
  const lastProcessedSearchRef = useRef('');

  const loadChildren = useCallback(
    async (connId: string, path: string | null): Promise<LoadResult> => {
      const url = path
        ? `/api/schema-import/browse/${connId}?path=${encodeURIComponent(path)}`
        : `/api/schema-import/browse/${connId}`;
      const resp = await apiGetRef.current<BrowseResponse>(url);
      if (resp.error) {
        return { nodes: [], error: resp.error, errorDetail: resp.error };
      }
      const nodes = (resp.data?.nodes ?? []).map((n) => ({
        ...n,
        children: undefined,
        isExpanded: false,
        isLoading: false,
        level: path ? path.split('.').length : 0,
      }));
      return {
        nodes,
        error: resp.data?.error,
        errorDetail: resp.data?.error_detail,
      };
    },
    [],
  );

  // Load root nodes when connectionId changes
  useEffect(() => {
    if (!connectionId) {
      setRoots([]);
      setBrowseError(null);
      setBrowseErrorDetail(null);
      return;
    }
    let cancelled = false;
    setIsInitialLoading(true);
    setBrowseError(null);
    setBrowseErrorDetail(null);
    setSearch('');
    setHighlightedPath(null);
    loadChildren(connectionId, null)
      .then((result) => {
        if (!cancelled) {
          setRoots(result.nodes);
          setBrowseError(result.error ?? null);
          setBrowseErrorDetail(result.errorDetail ?? null);
        }
      })
      .catch((err) => {
        if (!cancelled) console.error('Failed to load root nodes:', err);
      })
      .finally(() => {
        if (!cancelled) setIsInitialLoading(false);
      });
    return () => { cancelled = true; };
  }, [connectionId, loadChildren]);

  const toggleExpand = useCallback(
    async (path: string) => {
      if (!connectionId) return;

      setRoots((prev) => {
        const node = findNodeByPath(prev, path);
        if (!node) return prev;
        if (node.isExpanded) return updateNode(prev, path, (n) => ({ ...n, isExpanded: false }));
        if (node.children) return updateNode(prev, path, (n) => ({ ...n, isExpanded: true }));
        return updateNode(prev, path, (n) => ({ ...n, isLoading: true }));
      });

      const currentNode = findNodeByPath(rootsRef.current, path);
      if (currentNode && !currentNode.children && currentNode.has_children && !currentNode.isExpanded) {
        try {
          const result = await loadChildren(connectionId, path);
          setRoots((prev) =>
            updateNode(prev, path, (n) => ({ ...n, children: result.nodes, isExpanded: true, isLoading: false })),
          );
        } catch {
          setRoots((prev) => updateNode(prev, path, (n) => ({ ...n, isLoading: false })));
        }
      }
    },
    [connectionId, loadChildren],
  );

  /**
   * Ensure a node is expanded and its children are loaded.
   * Returns the updated tree and the children of that node.
   */
  const ensureExpanded = useCallback(
    async (connId: string, tree: TreeNode[], nodePath: string): Promise<[TreeNode[], TreeNode[]]> => {
      const node = findNodeByPath(tree, nodePath);
      if (!node) return [tree, []];

      if (node.children && node.children.length > 0) {
        const updated = updateNode(tree, nodePath, (n) => ({ ...n, isExpanded: true }));
        return [updated, node.children];
      }

      if (!node.has_children) return [tree, []];

      // Mark loading
      let updated = updateNode(tree, nodePath, (n) => ({ ...n, isLoading: true }));
      setRoots(updated);

      try {
        const result = await loadChildren(connId, nodePath);
        updated = updateNode(updated, nodePath, (n) => ({
          ...n,
          children: result.nodes,
          isExpanded: true,
          isLoading: false,
        }));
        setRoots(updated);
        rootsRef.current = updated;
        return [updated, result.nodes];
      } catch {
        updated = updateNode(updated, nodePath, (n) => ({ ...n, isLoading: false }));
        setRoots(updated);
        rootsRef.current = updated;
        return [updated, []];
      }
    },
    [loadChildren],
  );

  // Debounced auto-expand search
  useEffect(() => {
    if (!connectionId || !search.trim()) {
      setHighlightedPath(null);
      lastProcessedSearchRef.current = '';
      return;
    }

    const timer = setTimeout(() => {
      if (search === lastProcessedSearchRef.current) return;
      lastProcessedSearchRef.current = search;

      const thisVersion = ++searchVersionRef.current;
      const isCurrent = () => searchVersionRef.current === thisVersion;
      const parsed = parseSearchQuery(search);
      const { segments, endsWithDot } = parsed;

      if (segments.length === 0) {
        setHighlightedPath(null);
        return;
      }

      const processSearch = async () => {
        let currentTree = rootsRef.current;

        // Level 0: find matching root (catalog)
        const matchingRoot = currentTree.find((c) =>
          matchesSegment(c.name, segments[0]),
        );
        if (!matchingRoot) {
          if (isCurrent()) setHighlightedPath(null);
          return;
        }

        const goDeeper = segments.length > 1 || endsWithDot;
        if (!goDeeper) {
          if (isCurrent()) setHighlightedPath(matchingRoot.path);
          return;
        }

        // Expand catalog
        const [treeAfterCatalog, schemas] = await ensureExpanded(
          connectionId,
          currentTree,
          matchingRoot.path,
        );
        if (!isCurrent()) return;
        currentTree = treeAfterCatalog;

        if (schemas.length === 0) {
          if (isCurrent()) setHighlightedPath(matchingRoot.path);
          return;
        }

        // Level 1: find matching schema
        const schemaSegment = segments[1] || '';
        const matchingSchema = schemaSegment
          ? schemas.find((s) => matchesSegment(s.name, schemaSegment))
          : schemas[0];
        if (!matchingSchema) {
          if (isCurrent()) setHighlightedPath(matchingRoot.path);
          return;
        }

        const goToObjects = segments.length > 2 || (segments.length >= 2 && endsWithDot);
        if (!goToObjects) {
          if (isCurrent()) setHighlightedPath(matchingSchema.path);
          return;
        }

        // Expand schema
        const [treeAfterSchema, objects] = await ensureExpanded(
          connectionId,
          currentTree,
          matchingSchema.path,
        );
        if (!isCurrent()) return;
        currentTree = treeAfterSchema;

        if (objects.length === 0) {
          if (isCurrent()) setHighlightedPath(matchingSchema.path);
          return;
        }

        // Level 2: find matching object
        const objectSegment = segments[2] || '';
        const matchingObject = objectSegment
          ? objects.find((o) => matchesSegment(o.name, objectSegment))
          : objects[0];
        if (!matchingObject) {
          if (isCurrent()) setHighlightedPath(matchingSchema.path);
          return;
        }

        if (isCurrent()) setHighlightedPath(matchingObject.path);
      };

      processSearch().catch(console.error);
    }, 300);

    return () => clearTimeout(timer);
  }, [search, connectionId, ensureExpanded]);

  const toggleSelect = useCallback(
    (path: string) => {
      const next = new Set(selectedPaths);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      onSelectionChange(next);
    },
    [selectedPaths, onSelectionChange],
  );

  // Client-side filtering of loaded nodes
  const parsed = useMemo(() => parseSearchQuery(search), [search]);

  const filterTree = useCallback(
    (nodes: TreeNode[], level: number): TreeNode[] => {
      const { segments, typeFilter } = parsed;
      if (segments.length === 0 && !typeFilter) return nodes;

      return nodes.reduce<TreeNode[]>((acc, node) => {
        const segment = segments[level];
        const nameMatch = !segment || matchesSegment(node.name, segment);

        // Type filter applies only to non-container leaf nodes
        const isContainer = CONTAINER_TYPES.has(node.node_type.toLowerCase());
        const typeMatch =
          !typeFilter || isContainer || node.node_type.toLowerCase() === typeFilter;

        if (!nameMatch) return acc;

        if (node.children && node.isExpanded) {
          const filteredChildren = filterTree(node.children, level + 1);
          // Keep container if it has matching children or matches the current segment
          if (filteredChildren.length > 0 || isContainer) {
            acc.push({ ...node, children: filteredChildren });
          }
        } else if (typeMatch) {
          acc.push(node);
        } else if (isContainer) {
          acc.push(node);
        }

        return acc;
      }, []);
    },
    [parsed],
  );

  const visibleRoots = useMemo(() => filterTree(roots, 0), [filterTree, roots]);

  const renderNode = (node: TreeNode) => {
    const indent = node.level * 20;
    const isSelected = selectedPaths.has(node.path);
    const isHighlighted = highlightedPath === node.path;

    return (
      <div key={node.path}>
        <div
          className={`flex items-center gap-1.5 py-1 px-2 hover:bg-muted/50 rounded-sm cursor-pointer group ${
            isHighlighted ? 'bg-primary/10 ring-1 ring-primary/30' : ''
          }`}
          style={{ paddingLeft: `${indent + 8}px` }}
        >
          {/* Expand/collapse toggle */}
          {node.has_children ? (
            <button
              onClick={() => toggleExpand(node.path)}
              className="p-0.5 hover:bg-muted rounded"
            >
              {node.isLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              ) : node.isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
              )}
            </button>
          ) : (
            <span className="w-[22px]" />
          )}

          {/* Checkbox */}
          <Checkbox
            checked={isSelected}
            onCheckedChange={() => toggleSelect(node.path)}
            className="shrink-0"
          />

          {/* Icon + label */}
          <div
            className="flex items-center gap-1.5 min-w-0 flex-1"
            onClick={() => node.has_children && toggleExpand(node.path)}
          >
            {getNodeIcon(node.node_type)}
            <span className="text-sm truncate">{node.name}</span>
            <span className="text-xs text-muted-foreground ml-1">{node.node_type}</span>
          </div>
        </div>

        {/* Children */}
        {node.isExpanded && node.children && (
          <div>{node.children.map(renderNode)}</div>
        )}
      </div>
    );
  };

  if (!connectionId) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
        Select a connection to browse its resources
      </div>
    );
  }

  if (isInitialLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        <span className="ml-2 text-sm text-muted-foreground">Loading...</span>
      </div>
    );
  }

  if (roots.length === 0) {
    if (browseError) {
      return (
        <div className="flex items-center justify-center h-64 px-4">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Connection Error</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>{browseError}</p>
              {browseErrorDetail && (
                <Collapsible>
                  <CollapsibleTrigger className="text-xs underline cursor-pointer">
                    Show details
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <pre className="text-xs mt-2 p-2 bg-muted rounded whitespace-pre-wrap break-all">
                      {browseErrorDetail}
                    </pre>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </AlertDescription>
          </Alert>
        </div>
      );
    }
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
        No resources found for this connection
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Search input */}
      <div className="space-y-1">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-9 text-sm pl-8 pr-8"
            placeholder="Search: t:catalog.schema.table"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              onClick={() => { setSearch(''); setHighlightedPath(null); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 hover:bg-muted rounded"
            >
              <X className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground px-1">
          Type prefix for filtering: t:table, v:view, f:function, m:model, vol:volume
        </p>
      </div>

      {/* Tree */}
      {visibleRoots.length === 0 ? (
        <div className="flex items-center justify-center h-48 text-muted-foreground text-sm border rounded-md">
          No matches found
        </div>
      ) : (
        <ScrollArea className="h-[460px] border rounded-md">
          <div className="p-1">{visibleRoots.map(renderNode)}</div>
        </ScrollArea>
      )}
    </div>
  );
}
