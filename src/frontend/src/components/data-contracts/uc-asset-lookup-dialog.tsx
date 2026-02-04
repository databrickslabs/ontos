/**
 * UC Asset Lookup Dialog
 * 
 * A reusable dialog for browsing and selecting Unity Catalog assets.
 * Supports:
 * - Hierarchical navigation (catalog -> schema -> objects)
 * - Smart dot-syntax search (e.g., "lars.te.taa" matches "lars_george.test_db.table_a")
 * - Type prefix filtering (e.g., "t:lars.te" filters to tables only)
 * - All UC securables (tables, views, functions, models, volumes, metrics)
 * - Configurable allowed types via props
 */

import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  Folder, 
  FolderOpen, 
  Table, 
  Layout, 
  Code, 
  Brain, 
  HardDrive, 
  BarChart3,
  Layers,
  Radio,
  ChevronDown,
  ChevronRight,
  Loader2
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { 
  UCAssetInfo, 
  UCAssetType, 
  CatalogTreeItem, 
  ALL_ASSET_TYPES,
  isSelectableType,
} from '@/types/uc-asset'
import { 
  parseSearchQuery, 
  getTypeFilterDisplayName
} from '@/lib/uc-search-parser'

// ============================================================================
// Props and Types
// ============================================================================

export interface UCAssetLookupDialogProps {
  /** Whether the dialog is open */
  isOpen: boolean;
  /** Callback when dialog open state changes */
  onOpenChange: (open: boolean) => void;
  /** Callback when an asset is selected */
  onSelect: (asset: UCAssetInfo) => void;
  /** Optional list of allowed asset types. Defaults to all types. */
  allowedTypes?: UCAssetType[];
  /** Optional dialog title. Defaults to "Find UC Asset" */
  title?: string;
}

// ============================================================================
// Icon Helper
// ============================================================================

/**
 * Get the appropriate icon for an asset type
 */
function getIcon(type: UCAssetType | string): React.ReactNode {
  switch (type) {
    case UCAssetType.CATALOG:
    case 'catalog':
      return <Folder className="h-4 w-4 text-blue-500" />
    case UCAssetType.SCHEMA:
    case 'schema':
      return <FolderOpen className="h-4 w-4 text-green-500" />
    case UCAssetType.TABLE:
    case 'table':
      return <Table className="h-4 w-4 text-orange-500" />
    case UCAssetType.VIEW:
    case 'view':
      return <Layout className="h-4 w-4 text-purple-500" />
    case UCAssetType.MATERIALIZED_VIEW:
    case 'materialized_view':
      return <Layers className="h-4 w-4 text-purple-600" />
    case UCAssetType.STREAMING_TABLE:
    case 'streaming_table':
      return <Radio className="h-4 w-4 text-orange-600" />
    case UCAssetType.FUNCTION:
    case 'function':
      return <Code className="h-4 w-4 text-cyan-500" />
    case UCAssetType.MODEL:
    case 'model':
      return <Brain className="h-4 w-4 text-pink-500" />
    case UCAssetType.VOLUME:
    case 'volume':
      return <HardDrive className="h-4 w-4 text-gray-500" />
    case UCAssetType.METRIC:
    case 'metric':
      return <BarChart3 className="h-4 w-4 text-amber-500" />
    default:
      return null
  }
}

/**
 * Map backend type string to UCAssetType enum
 */
function mapToAssetType(typeStr: string): UCAssetType {
  switch (typeStr.toLowerCase()) {
    case 'catalog':
      return UCAssetType.CATALOG;
    case 'schema':
      return UCAssetType.SCHEMA;
    case 'table':
      return UCAssetType.TABLE;
    case 'view':
      return UCAssetType.VIEW;
    case 'materialized_view':
      return UCAssetType.MATERIALIZED_VIEW;
    case 'streaming_table':
      return UCAssetType.STREAMING_TABLE;
    case 'function':
      return UCAssetType.FUNCTION;
    case 'model':
      return UCAssetType.MODEL;
    case 'volume':
      return UCAssetType.VOLUME;
    case 'metric':
      return UCAssetType.METRIC;
    default:
      return UCAssetType.TABLE;
  }
}

// ============================================================================
// Main Component
// ============================================================================

export default function UCAssetLookupDialog({ 
  isOpen, 
  onOpenChange, 
  onSelect,
  allowedTypes = ALL_ASSET_TYPES,
  title = 'Find UC Asset'
}: UCAssetLookupDialogProps) {
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Tree state
  const [items, setItems] = useState<CatalogTreeItem[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set())
  
  // Track the highlighted (first matching) item for scrolling
  const [highlightedId, setHighlightedId] = useState<string | null>(null)
  
  // Ref for the tree container to scroll into view
  const treeContainerRef = useRef<HTMLDivElement>(null)
  
  // Refs for highlighted items
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  
  // Ref to track the last processed search to prevent infinite loops
  const lastProcessedSearchRef = useRef<string>('')
  
  // Ref to track the current search operation version (incremented on each new search)
  const searchVersionRef = useRef<number>(0)
  
  // Ref to track the latest items without causing re-renders
  const itemsRef = useRef<CatalogTreeItem[]>(items)

  // Keep itemsRef in sync with items state
  useEffect(() => {
    itemsRef.current = items
  }, [items])

  // Reset search processing refs when dialog opens to ensure fresh processing
  useEffect(() => {
    if (isOpen) {
      lastProcessedSearchRef.current = ''
      searchVersionRef.current = 0
    }
  }, [isOpen])

  // ============================================================================
  // Parse Search Query
  // ============================================================================
  
  const parsedSearch = useMemo(() => parseSearchQuery(search), [search])

  // ============================================================================
  // API Calls
  // ============================================================================

  const fetchCatalogs = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch('/api/catalogs')
      if (!res.ok) throw new Error('Failed to load catalogs')
      const data = await res.json()
      setItems(Array.isArray(data) ? data.map((c: CatalogTreeItem) => ({
        ...c,
        type: UCAssetType.CATALOG
      })) : [])
    } catch (e) {
      setError('Failed to load catalogs')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchSchemas = useCallback(async (catalogName: string): Promise<CatalogTreeItem[]> => {
    const res = await fetch(`/api/catalogs/${catalogName}/schemas`)
    if (!res.ok) return []
    const data = await res.json()
    return data.map((s: CatalogTreeItem) => ({
      ...s,
      type: UCAssetType.SCHEMA
    }))
  }, [])

  const fetchObjects = useCallback(async (
    catalogName: string, 
    schemaName: string,
    typeFilter: UCAssetType | null
  ): Promise<CatalogTreeItem[]> => {
    // Build query params for type filtering
    let url = `/api/catalogs/${catalogName}/schemas/${schemaName}/objects`
    
    // If we have a type filter, pass it to the API
    if (typeFilter) {
      url += `?asset_types=${typeFilter}`
    } else if (allowedTypes.length < ALL_ASSET_TYPES.length) {
      // Pass allowed types as filter
      url += `?asset_types=${allowedTypes.join(',')}`
    }
    
    const res = await fetch(url)
    if (!res.ok) return []
    const data = await res.json()
    return data.map((obj: CatalogTreeItem) => ({
      ...obj,
      type: mapToAssetType(obj.type as string)
    }))
  }, [allowedTypes])

  // ============================================================================
  // Tree Node Management
  // ============================================================================

  const updateNodeChildren = useCallback((
    nodes: CatalogTreeItem[], 
    id: string, 
    children: CatalogTreeItem[]
  ): CatalogTreeItem[] => {
    return nodes.map((n) => 
      n.id === id 
        ? { ...n, children } 
        : (n.children?.length ? { ...n, children: updateNodeChildren(n.children, id, children) } : n)
    )
  }, [])

  // Find a node by ID in the tree
  const findNodeById = useCallback((nodes: CatalogTreeItem[], id: string): CatalogTreeItem | null => {
    for (const node of nodes) {
      if (node.id === id) return node
      if (node.children) {
        const found = findNodeById(node.children, id)
        if (found) return found
      }
    }
    return null
  }, [])

  // Expand a node and return the updated items with children loaded
  const expandNode = useCallback(async (
    currentItems: CatalogTreeItem[],
    nodeId: string,
    typeFilter: UCAssetType | null
  ): Promise<CatalogTreeItem[]> => {
    const node = findNodeById(currentItems, nodeId)
    if (!node) return currentItems
    
    // Already has children loaded
    if (node.children && node.children.length > 0) {
      return currentItems
    }
    
    let children: CatalogTreeItem[] = []
    
    if (node.type === UCAssetType.CATALOG) {
      children = await fetchSchemas(node.name)
    } else if (node.type === UCAssetType.SCHEMA) {
      const [catalogName] = node.id.split('.')
      children = await fetchObjects(catalogName, node.name, typeFilter)
    }
    
    return updateNodeChildren(currentItems, nodeId, children)
  }, [findNodeById, fetchSchemas, fetchObjects, updateNodeChildren])

  const handleExpand = useCallback(async (item: CatalogTreeItem) => {
    if (loadingNodes.has(item.id)) return
    
    setLoadingNodes((prev) => new Set(prev).add(item.id))
    
    try {
      const updatedItems = await expandNode(items, item.id, parsedSearch.typeFilter)
      setItems(updatedItems)
      setExpanded((prev) => { 
        const next = new Set(prev)
        next.add(item.id)
        return next 
      })
    } finally {
      setLoadingNodes((prev) => { 
        const next = new Set(prev)
        next.delete(item.id)
        return next 
      })
    }
  }, [items, loadingNodes, expandNode, parsedSearch.typeFilter])

  const handleCollapse = useCallback((itemId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.delete(itemId)
      return next
    })
  }, [])

  const handleSelectItem = useCallback((item: CatalogTreeItem) => {
    // Only allow selection of leaf objects (not catalogs/schemas)
    if (!isSelectableType(item.type as UCAssetType)) {
      return
    }
    
    const parts = item.id.split('.')
    if (parts.length !== 3) return
    
    const [catalog_name, schema_name, object_name] = parts
    
    const assetInfo: UCAssetInfo = {
      catalog_name,
      schema_name,
      object_name,
      full_name: item.id,
      asset_type: item.type as UCAssetType,
      description: item.description
    }
    
    onSelect(assetInfo)
    onOpenChange(false)
  }, [onSelect, onOpenChange])

  // Accept the currently highlighted selection
  const handleAcceptSelection = useCallback(() => {
    if (!highlightedId) return
    
    const highlightedItem = findNodeById(items, highlightedId)
    if (highlightedItem) {
      handleSelectItem(highlightedItem)
    }
  }, [highlightedId, items, findNodeById, handleSelectItem])

  // Check if the current highlighted item is selectable
  const canAcceptSelection = useMemo(() => {
    if (!highlightedId) return false
    const highlightedItem = findNodeById(items, highlightedId)
    if (!highlightedItem) return false
    return isSelectableType(highlightedItem.type as UCAssetType)
  }, [highlightedId, items, findNodeById])

  // Handle keyboard events on the search input
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && canAcceptSelection) {
      e.preventDefault()
      handleAcceptSelection()
    }
  }, [canAcceptSelection, handleAcceptSelection])

  // ============================================================================
  // Smart Search - Auto-expand and highlight based on search
  // ============================================================================

  // Helper to load children for a node if not already loaded
  // Takes current tree state and returns [children, updatedTree]
  const loadChildrenForNode = useCallback(async (
    currentTree: CatalogTreeItem[],
    node: CatalogTreeItem,
    typeFilter: UCAssetType | null
  ): Promise<[CatalogTreeItem[], CatalogTreeItem[]]> => {
    // Find the node in the current tree to check for existing children
    const nodeInTree = findNodeById(currentTree, node.id)
    if (nodeInTree?.children && nodeInTree.children.length > 0) {
      return [nodeInTree.children, currentTree]
    }
    
    let children: CatalogTreeItem[] = []
    
    if (node.type === UCAssetType.CATALOG) {
      children = await fetchSchemas(node.name)
    } else if (node.type === UCAssetType.SCHEMA) {
      const [catalogName] = node.id.split('.')
      children = await fetchObjects(catalogName, node.name, typeFilter)
    }
    
    // Return children and updated tree
    const updatedTree = updateNodeChildren(currentTree, node.id, children)
    return [children, updatedTree]
  }, [findNodeById, fetchSchemas, fetchObjects, updateNodeChildren])

  // Process search when search string changes
  useEffect(() => {
    const { segments, typeFilter, endsWithDot } = parsedSearch
    
    if (segments.length === 0) {
      setHighlightedId(null)
      lastProcessedSearchRef.current = ''
      return
    }
    
    // Skip if we've already processed this exact search
    if (lastProcessedSearchRef.current === search) {
      return
    }
    
    // Mark this search as being processed immediately
    lastProcessedSearchRef.current = search
    
    // Increment version for this search operation
    const thisVersion = ++searchVersionRef.current
    
    // Helper to check if this operation is still current
    const isCurrent = () => searchVersionRef.current === thisVersion
    
    const processSearch = async () => {
      // Get current items state from ref to avoid stale closure
      let currentTree = itemsRef.current
      
      // Level 0: Find matching catalog
      const catalogSegment = segments[0]
      const matchingCatalog = currentTree.find(c => 
        c.name.toLowerCase().startsWith(catalogSegment.toLowerCase())
      )
      
      if (!matchingCatalog) {
        if (isCurrent()) setHighlightedId(null)
        return
      }
      
      // Should we go deeper? (more segments or ends with dot)
      const goToSchemas = segments.length > 1 || endsWithDot
      
      if (!goToSchemas) {
        if (isCurrent()) setHighlightedId(matchingCatalog.id)
        return
      }
      
      // Check if catalog already has children loaded
      const catalogInTree = findNodeById(currentTree, matchingCatalog.id)
      const needToLoadSchemas = !catalogInTree?.children || catalogInTree.children.length === 0
      
      if (needToLoadSchemas) {
        // Mark as loading
        if (isCurrent()) setLoadingNodes(prev => new Set(prev).add(matchingCatalog.id))
        
        try {
          const [schemas, updatedTree] = await loadChildrenForNode(
            currentTree, 
            matchingCatalog, 
            typeFilter
          )
          
          if (!isCurrent()) return
          
          currentTree = updatedTree
          // Update itemsRef immediately so subsequent reads get the updated tree
          itemsRef.current = updatedTree
          setItems(updatedTree)
          setExpanded(prev => new Set(prev).add(matchingCatalog.id))
          
          if (schemas.length === 0) {
            setHighlightedId(matchingCatalog.id)
            return
          }
        } finally {
          if (isCurrent()) {
            setLoadingNodes(prev => {
              const next = new Set(prev)
              next.delete(matchingCatalog.id)
              return next
            })
          }
        }
      } else {
        // Already expanded, ensure it shows as expanded
        if (isCurrent()) setExpanded(prev => new Set(prev).add(matchingCatalog.id))
      }
      
      // Get schemas from current tree state (re-read from ref in case we just updated)
      currentTree = itemsRef.current
      const catalogWithChildren = findNodeById(currentTree, matchingCatalog.id)
      const schemas = catalogWithChildren?.children || []
      
      if (schemas.length === 0) {
        if (isCurrent()) setHighlightedId(matchingCatalog.id)
        return
      }
      
      // Level 1: Find matching schema
      const schemaSegment = segments[1] || ''
      const matchingSchema = schemaSegment
        ? schemas.find(s => s.name.toLowerCase().startsWith(schemaSegment.toLowerCase()))
        : schemas[0]
      
      if (!matchingSchema) {
        if (isCurrent()) setHighlightedId(matchingCatalog.id)
        return
      }
      
      // Should we go to objects?
      const goToObjects = segments.length > 2 || (segments.length >= 2 && endsWithDot)
      
      if (!goToObjects) {
        if (isCurrent()) setHighlightedId(matchingSchema.id)
        return
      }
      
      // Check if schema already has children loaded
      const schemaInTree = findNodeById(currentTree, matchingSchema.id)
      const needToLoadObjects = !schemaInTree?.children || schemaInTree.children.length === 0
      
      if (needToLoadObjects) {
        // Mark as loading
        if (isCurrent()) setLoadingNodes(prev => new Set(prev).add(matchingSchema.id))
        
        try {
          const [objects, updatedTree] = await loadChildrenForNode(
            currentTree, 
            matchingSchema, 
            typeFilter
          )
          
          if (!isCurrent()) return
          
          currentTree = updatedTree
          // Update itemsRef immediately
          itemsRef.current = updatedTree
          setItems(updatedTree)
          setExpanded(prev => new Set(prev).add(matchingSchema.id))
          
          if (objects.length === 0) {
            setHighlightedId(matchingSchema.id)
            return
          }
        } finally {
          if (isCurrent()) {
            setLoadingNodes(prev => {
              const next = new Set(prev)
              next.delete(matchingSchema.id)
              return next
            })
          }
        }
      } else {
        // Already expanded, ensure it shows as expanded
        if (isCurrent()) setExpanded(prev => new Set(prev).add(matchingSchema.id))
      }
      
      // Get objects from current tree state
      currentTree = itemsRef.current
      const schemaWithChildren = findNodeById(currentTree, matchingSchema.id)
      const objects = schemaWithChildren?.children || []
      
      if (objects.length === 0) {
        if (isCurrent()) setHighlightedId(matchingSchema.id)
        return
      }
      
      // Level 2: Find matching object
      const objectSegment = segments[2] || ''
      const matchingObject = objectSegment
        ? objects.find(o => o.name.toLowerCase().startsWith(objectSegment.toLowerCase()))
        : objects[0]
      
      if (matchingObject) {
        if (isCurrent()) setHighlightedId(matchingObject.id)
      } else {
        if (isCurrent()) setHighlightedId(matchingSchema.id)
      }
    }
    
    processSearch()
  }, [search, parsedSearch, findNodeById, loadChildrenForNode])

  // ============================================================================
  // Scroll highlighted item into view
  // ============================================================================

  useEffect(() => {
    if (highlightedId) {
      const element = itemRefs.current.get(highlightedId)
      if (element && treeContainerRef.current) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }
  }, [highlightedId])

  // ============================================================================
  // Initial Load
  // ============================================================================

  useEffect(() => { 
    if (isOpen) {
      fetchCatalogs()
      setSearch('')
      setExpanded(new Set())
      setHighlightedId(null)
      itemRefs.current.clear()
    }
  }, [isOpen, fetchCatalogs])

  // ============================================================================
  // Filter Logic - Applied on every render based on current search
  // ============================================================================

  const filterNodes = useCallback((
    nodes: CatalogTreeItem[],
    level: number
  ): CatalogTreeItem[] => {
    const { segments, typeFilter, endsWithDot } = parsedSearch
    
    // Determine which level the user is currently typing at
    // If ends with dot, user has moved past the last segment
    const typingLevel = endsWithDot ? segments.length : Math.max(0, segments.length - 1)
    
    // Get the segment for this level (might be undefined if we're past typed levels)
    const currentSegment = segments[level]
    
    return nodes.filter((node) => {
      // Type filter for leaf nodes (always applied)
      if (isSelectableType(node.type as UCAssetType)) {
        if (!allowedTypes.includes(node.type as UCAssetType)) {
          return false
        }
        if (typeFilter && node.type !== typeFilter) {
          return false
        }
      }
      
      // If no segment at this level, show all
      if (!currentSegment) {
        return true
      }
      
      // If this level is BEFORE the typing level, check for exact prefix match
      // to only show the path we've navigated through
      if (level < typingLevel) {
        return node.name.toLowerCase().startsWith(currentSegment.toLowerCase())
      }
      
      // If this is the typing level, filter by what user is typing
      if (level === typingLevel) {
        return node.name.toLowerCase().startsWith(currentSegment.toLowerCase())
      }
      
      // If beyond typing level (shouldn't normally happen), show all
      return true
    })
  }, [parsedSearch, allowedTypes])

  // ============================================================================
  // Render Tree Item
  // ============================================================================

  const renderTreeItem = useCallback((
    node: CatalogTreeItem,
    level: number
  ): React.ReactNode => {
    // parsedSearch accessed via closure for filtering
    const isExpanded = expanded.has(node.id)
    const isLoading = loadingNodes.has(node.id)
    const hasChildren = node.hasChildren || (node.children && node.children.length > 0)
    const isHighlighted = node.id === highlightedId
    const isSelectable = isSelectableType(node.type as UCAssetType)
    
    // Filter and render children
    let filteredChildren: CatalogTreeItem[] = []
    if (node.children && isExpanded) {
      filteredChildren = filterNodes(node.children, level + 1)
    }
    
    return (
      <div key={node.id}>
        <div
          ref={(el) => {
            if (el) {
              itemRefs.current.set(node.id, el)
            } else {
              itemRefs.current.delete(node.id)
            }
          }}
          className={cn(
            "flex items-center gap-2 py-1.5 px-2 rounded-md cursor-pointer text-sm",
            "hover:bg-muted/50 transition-colors",
            isHighlighted && "bg-primary/10 ring-1 ring-primary/30",
            isSelectable && "hover:bg-muted"
          )}
          style={{ marginLeft: `${level * 20}px` }}
          onClick={() => {
            if (isSelectable) {
              handleSelectItem(node)
            } else if (hasChildren) {
              if (isExpanded) {
                handleCollapse(node.id)
              } else {
                handleExpand(node)
              }
            }
          }}
        >
          {/* Expand/collapse icon */}
          <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
            {hasChildren ? (
              isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : (
                <button
                  className="hover:bg-muted rounded p-0.5"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (isExpanded) {
                      handleCollapse(node.id)
                    } else {
                      handleExpand(node)
                    }
                  }}
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
              )
            ) : (
              <span className="w-4" /> 
            )}
          </div>
          
          {/* Type icon */}
          <span className="flex-shrink-0">{getIcon(node.type)}</span>
          
          {/* Name */}
          <span className="truncate flex-1" title={node.name}>{node.name}</span>
        </div>
        
        {/* Children */}
        {isExpanded && filteredChildren.length > 0 && (
          <div>
            {filteredChildren.map((child) => renderTreeItem(child, level + 1))}
          </div>
        )}
      </div>
    )
  }, [parsedSearch, expanded, loadingNodes, highlightedId, filterNodes, handleExpand, handleCollapse, handleSelectItem])

  // ============================================================================
  // Get filtered root items
  // ============================================================================

  const filteredRootItems = useMemo(() => {
    return filterNodes(items, 0)
  }, [items, filterNodes])

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="w-[80vw] max-w-4xl h-[80vh] max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        
        <div className="flex-1 flex flex-col min-h-0 space-y-3 text-sm">
          {/* Search Input */}
          <div className="flex gap-2 flex-shrink-0">
            <Input 
              className="h-9 text-sm" 
              placeholder="Search: t:catalog.schema.table" 
              value={search} 
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <Button 
              className="h-9 px-3" 
              type="button" 
              variant="outline" 
              onClick={fetchCatalogs} 
              disabled={loading}
            >
              Refresh
            </Button>
          </div>
          
          {/* Type filter indicator */}
          {parsedSearch.typeFilter && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-xs text-muted-foreground">Filtering:</span>
              <Badge variant="secondary" className="text-xs">
                {getTypeFilterDisplayName(parsedSearch.typeFilter)}
              </Badge>
            </div>
          )}
          
          {/* Search hint */}
          <div className="text-xs text-muted-foreground flex-shrink-0">
            Type prefix for filtering: t:table, v:view, f:function, m:model, vol:volume
          </div>
          
          {/* Error display */}
          {error && <div className="text-sm text-destructive flex-shrink-0">{error}</div>}
          
          {/* Tree view - takes remaining space */}
          <div 
            ref={treeContainerRef}
            className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden border rounded p-2"
          >
            {loading ? (
              <div className="p-3 text-sm text-muted-foreground">Loading catalogs...</div>
            ) : filteredRootItems.length === 0 ? (
              <div className="p-3 text-sm text-muted-foreground">No matching items found</div>
            ) : (
              filteredRootItems.map((item) => renderTreeItem(item, 0))
            )}
          </div>
        </div>
        
        <DialogFooter className="flex-shrink-0">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button 
            type="button" 
            onClick={handleAcceptSelection}
            disabled={!canAcceptSelection}
          >
            Select
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ============================================================================
// Legacy Export for Backward Compatibility
// ============================================================================

/**
 * Legacy interface for backward compatibility with MetastoreTableInfo
 */
export interface MetastoreTableInfo {
  catalog_name: string;
  schema_name: string;
  table_name: string;
  full_name: string;
}

/**
 * Legacy DatasetLookupDialog component for backward compatibility.
 * This wraps UCAssetLookupDialog with the old interface.
 */
export function DatasetLookupDialog({
  isOpen,
  onOpenChange,
  onSelect,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (table: MetastoreTableInfo) => void;
}) {
  const handleSelect = (asset: UCAssetInfo) => {
    // Convert to legacy format
    onSelect({
      catalog_name: asset.catalog_name,
      schema_name: asset.schema_name,
      table_name: asset.object_name,
      full_name: asset.full_name,
    })
  }
  
  return (
    <UCAssetLookupDialog
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      onSelect={handleSelect}
      allowedTypes={[UCAssetType.TABLE, UCAssetType.VIEW]}
      title="Find existing dataset"
    />
  )
}
