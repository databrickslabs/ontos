import * as React from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { ActionSpinner } from "@/components/ui/action-spinner"

export interface TreeDataItem {
  id: string
  name: string
  icon?: React.ReactNode
  children?: TreeDataItem[]
  onClick?: () => void
  selected?: boolean
  expanded?: boolean
  onExpand?: () => void
  onCollapse?: () => void
  loading?: boolean
  hasChildren: boolean
}

export interface TreeViewProps {
  data: TreeDataItem[]
  initialSelectedItemId?: string
  onSelectChange?: (item: TreeDataItem) => void
  className?: string
}

/**
 * Imperative handle methods exposed via ref
 */
export interface TreeViewHandle {
  /**
   * Programmatically expand a node by its ID.
   * This will trigger the onExpand callback if defined on the item.
   */
  expandNode: (nodeId: string) => void;
  
  /**
   * Programmatically collapse a node by its ID.
   * This will trigger the onCollapse callback if defined on the item.
   */
  collapseNode: (nodeId: string) => void;
  
  /**
   * Programmatically select a node by its ID.
   * This will trigger the onClick and onSelectChange callbacks.
   */
  selectNode: (nodeId: string) => void;
  
  /**
   * Expand all nodes in a path (e.g., ["catalog", "catalog.schema"])
   * Each node's onExpand callback will be triggered.
   */
  expandPath: (nodeIds: string[]) => void;
  
  /**
   * Get the currently selected node ID.
   */
  getSelectedId: () => string | undefined;
  
  /**
   * Get the set of expanded node IDs.
   */
  getExpandedIds: () => Set<string>;
  
  /**
   * Clear selection
   */
  clearSelection: () => void;
}

/**
 * Helper function to find a node by ID in the tree data
 */
function findNodeById(data: TreeDataItem[], id: string): TreeDataItem | undefined {
  for (const item of data) {
    if (item.id === id) {
      return item;
    }
    if (item.children) {
      const found = findNodeById(item.children, id);
      if (found) return found;
    }
  }
  return undefined;
}

export const TreeView = React.forwardRef<TreeViewHandle, TreeViewProps>(
  function TreeView({
    data,
    initialSelectedItemId,
    onSelectChange,
    className,
  }, ref) {
    const [expandedItems, setExpandedItems] = React.useState<Set<string>>(new Set())
    // Track items explicitly collapsed by user to override parent's expanded prop
    const [collapsedItems, setCollapsedItems] = React.useState<Set<string>>(new Set())
    const [selectedItemId, setSelectedItemId] = React.useState<string | undefined>(initialSelectedItemId)

    const handleToggle = React.useCallback((item: TreeDataItem) => {
      if (item.loading) return;

      // Check if currently expanded (considering both internal state, collapsed override, and parent prop)
      const isCurrentlyExpanded = expandedItems.has(item.id) || 
        (item.expanded && !collapsedItems.has(item.id));
      
      if (isCurrentlyExpanded) {
        // Collapsing
        setExpandedItems((prev) => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
        // Mark as explicitly collapsed to override parent's expanded prop
        setCollapsedItems((prev) => {
          const next = new Set(prev);
          next.add(item.id);
          return next;
        });
        // Notify parent of collapse so it can sync its state
        if (item.onCollapse) {
          item.onCollapse();
        }
      } else {
        // Expanding
        setExpandedItems((prev) => {
          const next = new Set(prev);
          next.add(item.id);
          return next;
        });
        // Remove from collapsed set since user is expanding
        setCollapsedItems((prev) => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
        if (item.onExpand) {
          item.onExpand();
        }
      }
    }, [expandedItems, collapsedItems]);

    const handleSelect = React.useCallback((item: TreeDataItem) => {
      setSelectedItemId(item.id)
      if (onSelectChange) {
        onSelectChange(item)
      }
      if (item.onClick) {
        item.onClick()
      }
    }, [onSelectChange]);

    // Expose imperative methods via ref
    React.useImperativeHandle(ref, () => ({
      expandNode: (nodeId: string) => {
        const item = findNodeById(data, nodeId);
        if (item && !expandedItems.has(nodeId)) {
          setExpandedItems((prev) => {
            const next = new Set(prev);
            next.add(nodeId);
            return next;
          });
          setCollapsedItems((prev) => {
            const next = new Set(prev);
            next.delete(nodeId);
            return next;
          });
          if (item.onExpand) {
            item.onExpand();
          }
        }
      },
      
      collapseNode: (nodeId: string) => {
        const item = findNodeById(data, nodeId);
        if (item) {
          setExpandedItems((prev) => {
            const next = new Set(prev);
            next.delete(nodeId);
            return next;
          });
          setCollapsedItems((prev) => {
            const next = new Set(prev);
            next.add(nodeId);
            return next;
          });
          if (item.onCollapse) {
            item.onCollapse();
          }
        }
      },
      
      selectNode: (nodeId: string) => {
        const item = findNodeById(data, nodeId);
        if (item) {
          handleSelect(item);
        }
      },
      
      expandPath: (nodeIds: string[]) => {
        // Expand each node in the path sequentially
        nodeIds.forEach((nodeId) => {
          const item = findNodeById(data, nodeId);
          if (item && !expandedItems.has(nodeId)) {
            setExpandedItems((prev) => {
              const next = new Set(prev);
              next.add(nodeId);
              return next;
            });
            setCollapsedItems((prev) => {
              const next = new Set(prev);
              next.delete(nodeId);
              return next;
            });
            if (item.onExpand) {
              item.onExpand();
            }
          }
        });
      },
      
      getSelectedId: () => selectedItemId,
      
      getExpandedIds: () => new Set(expandedItems),
      
      clearSelection: () => {
        setSelectedItemId(undefined);
      },
    }), [data, expandedItems, collapsedItems, selectedItemId, handleSelect]);

    const renderItem = (item: TreeDataItem, level: number = 0) => {
      const hasChildren = item.hasChildren || (item.children && item.children.length > 0);
      // Item is expanded if: in internal expanded set, OR parent says expanded AND not explicitly collapsed
      const isExpanded = expandedItems.has(item.id) || 
        (item.expanded && !collapsedItems.has(item.id));
      const isSelected = selectedItemId === item.id || item.selected;

      return (
        <div key={item.id} className="space-y-1">
          <div
            data-node-id={item.id}
            className={cn(
              "flex items-center justify-between p-2 hover:bg-muted rounded-md cursor-pointer",
              isSelected && "bg-muted"
            )}
            style={{ paddingLeft: `${level * 16}px` }}
            onClick={() => handleSelect(item)}
          >
            <div className="flex items-center space-x-2 min-w-0">
              {hasChildren && (
                <button
                  className="h-4 w-4 flex-shrink-0 flex items-center justify-center"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggle(item);
                  }}
                >
                  {item.loading ? (
                    <ActionSpinner />
                  ) : isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
              )}
              {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
              <span className="truncate">{item.name}</span>
            </div>
          </div>
          {hasChildren && isExpanded && (
            <div className="ml-4">
              {item.children?.map((child) => renderItem(child, level + 1))}
            </div>
          )}
        </div>
      );
    }

    return (
      <div className={cn("space-y-1 overflow-auto h-full", className)}>
        <div className="min-w-full inline-block">
          {data.map((item) => renderItem(item))}
        </div>
      </div>
    )
  }
)
