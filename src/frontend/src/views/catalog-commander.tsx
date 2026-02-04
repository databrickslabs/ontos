import React, { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { TreeView } from '@/components/ui/tree-view';
import {
  Folder,
  FolderOpen,
  Table,
  Layout,
  FolderKanban,
  Pencil,
  Trash2,
  Eye,
  ArrowRight,
  ArrowLeft,
  Info,
  Loader2,
  MessageSquare,
  PanelRightClose,
  // PanelRightOpen - unused
  Copy,
  GitCompare,
  RefreshCw,
  Sparkles,
  Send
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable } from '@/components/ui/data-table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
// Tabs imports commented out - not currently used
// import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { CommentTimeline } from '@/components/comments/comment-timeline';
import { cn } from '@/lib/utils';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useToast } from '@/hooks/use-toast';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface CatalogItem {
  id: string;
  name: string;
  type: 'catalog' | 'schema' | 'table' | 'view';
  children: CatalogItem[];
  hasChildren: boolean;
}

interface TreeViewItem {
  id: string;
  name: string;
  icon?: React.ReactNode;
  children?: TreeViewItem[];
  onClick?: () => void;
  selected?: boolean;
  expanded?: boolean;
  onExpand?: () => void;
  hasChildren: boolean;
}

interface DatasetContent {
  schema: Array<{ name: string; type: string; nullable: boolean }>;
  data: any[];
  total_rows: number;
  limit: number;
  offset: number;
}

// Default number of rows to fetch for data preview
const DEFAULT_PAGE_SIZE = 100;

interface Estate {
  id: string;
  name: string;
  description: string;
  workspace_url: string;
  cloud_type: string;
  metastore_name: string;
  is_enabled: boolean;
}

type RightPanelMode = 'hidden' | 'ask' | 'dual-tree' | 'info' | 'comments';

const CatalogCommander: React.FC = () => {
  const { t } = useTranslation(['catalog-commander', 'common']);
  const [searchInput, setSearchInput] = useState('');
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [selectedItems, setSelectedItems] = useState<CatalogItem[]>([]);
  const [sourceItems, setSourceItems] = useState<CatalogItem[]>([]);
  const [targetItems, setTargetItems] = useState<CatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetContent, setDatasetContent] = useState<DatasetContent | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [selectedObjectInfo, setSelectedObjectInfo] = useState<any>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set());
  const [estates, setEstates] = useState<Estate[]>([]);
  const [selectedSourceEstate, setSelectedSourceEstate] = useState<string>('');
  const [selectedTargetEstate, setSelectedTargetEstate] = useState<string>('');
  const [rightPanelMode, setRightPanelMode] = useState<RightPanelMode>('ask');
  
  // Ask Ontos chat state
  const [askInput, setAskInput] = useState('');
  const [askMessages, setAskMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string; timestamp: string }>>([]);
  const [askLoading, setAskLoading] = useState(false);
  const [askSessionId, setAskSessionId] = useState<string | undefined>();
  const askMessagesEndRef = React.useRef<HTMLDivElement>(null);
  const askInputRef = React.useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();

  // Draggable divider state - default to 420px, load from localStorage
  const [leftPaneWidth, setLeftPaneWidth] = useState<number>(() => {
    const stored = localStorage.getItem('catalog-commander-split');
    return stored ? parseInt(stored, 10) : 420;
  });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStartX, setDragStartX] = useState(0);
  const [dragStartWidth, setDragStartWidth] = useState(0);

  const { hasPermission } = usePermissions();
  const canPerformWriteActions = hasPermission('catalog-commander', FeatureAccessLevel.FULL);

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const fetchDatasetPage = useCallback(async (path: string, limit: number, offset: number) => {
    setLoadingData(true);
    try {
      const response = await fetch(
        `/api/catalogs/dataset/${encodeURIComponent(path)}?limit=${limit}&offset=${offset}`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setDatasetContent(data);
    } catch (err) {
      console.error('Error loading dataset:', err);
      setError(err instanceof Error ? err.message : 'Failed to load dataset');
    } finally {
      setLoadingData(false);
    }
  }, []);

  const handleViewDataset = async (path: string) => {
    setSelectedDataset(path);
    setViewDialogOpen(true);
    await fetchDatasetPage(path, DEFAULT_PAGE_SIZE, 0);
  };

  const handleOperation = (operation: string) => {
    console.log(`${operation} operation triggered`);
  };

  const getSelectedNodeDetails = () => {
    if (!selectedObjectInfo) return null;
    const node = findNode(sourceItems, selectedObjectInfo.id) || 
                 findNode(targetItems, selectedObjectInfo.id);
    return node;
  };

  const findNode = (items: CatalogItem[], id: string): CatalogItem | null => {
    for (const item of items) {
      if (item.id === id) return item;
      if (item.children) {
        const found = findNode(item.children, id);
        if (found) return found;
      }
    }
    return null;
  };

  const updateNodeChildren = (items: CatalogItem[], nodeId: string, children: CatalogItem[]): CatalogItem[] => {
    return items.map(item => {
      if (item.id === nodeId) {
        return { ...item, children };
      }
      if (item.children) {
        return { ...item, children: updateNodeChildren(item.children, nodeId, children) };
      }
      return item;
    });
  };

  const fetchChildren = async (nodeId: string, nodeType: string): Promise<CatalogItem[]> => {
    try {
      let url = '';
      if (nodeType === 'catalog') {
        url = `/api/catalogs/${nodeId}/schemas`;
      } else if (nodeType === 'schema') {
        const [catalogName, schemaName] = nodeId.split('.');
        url = `/api/catalogs/${catalogName}/schemas/${schemaName}/tables`;
      }
      
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to fetch children: ${response.status}`);
      }
      const data = await response.json();
      return data;
    } catch (err) {
      console.error('Error fetching children:', err);
      return [];
    }
  };

  const handleNodeExpand = async (nodeId: string, nodeType: string, isSource: boolean) => {
    if (loadingNodes.has(nodeId)) return;

    setLoadingNodes(prev => new Set(prev).add(nodeId));
    try {
      const children = await fetchChildren(nodeId, nodeType);
      if (isSource) {
        setSourceItems(prev => {
          const updated = updateNodeChildren(prev, nodeId, children);
          return updated;
        });
      } else {
        setTargetItems(prev => {
          const updated = updateNodeChildren(prev, nodeId, children);
          return updated;
        });
      }
      setExpandedNodes(prev => {
        const next = new Set(prev);
        next.add(nodeId);
        return next;
      });
    } catch (err) {
      console.error('Error expanding node:', err);
      setExpandedNodes(prev => {
        const next = new Set(prev);
        next.delete(nodeId);
        return next;
      });
    } finally {
      setLoadingNodes(prev => {
        const next = new Set(prev);
        next.delete(nodeId);
        return next;
      });
    }
  };

  useEffect(() => {
    fetchCatalogs();
    fetchEstates();
    setStaticSegments([]);
    setDynamicTitle(t('title'));

    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  const fetchEstates = async () => {
    try {
      const response = await fetch('/api/estates');
      if (!response.ok) {
        throw new Error(`Failed to fetch estates: ${response.status}`);
      }
      const data = await response.json();
      setEstates(data || []);
    } catch (err) {
      console.error('Error fetching estates:', err);
    }
  };

  const fetchCatalogs = async (forceRefresh: boolean = false) => {
    try {
      setIsLoading(true);
      setError(null);
      const url = forceRefresh ? '/api/catalogs?force_refresh=true' : '/api/catalogs';
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to fetch catalogs: ${response.status}`);
      }
      const data = await response.json();
      setSourceItems(data);
      setTargetItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch catalogs');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = (event: React.MouseEvent) => {
    const forceRefresh = event.shiftKey;
    fetchCatalogs(forceRefresh);
  };

  // Handle Ask Ontos chat with catalog context
  const handleAskSend = async () => {
    const messageContent = askInput.trim();
    if (!messageContent || askLoading) return;

    const selectedNode = getSelectedNodeDetails();
    
    // Build context message that includes selected item info
    let contextualMessage = messageContent;
    if (selectedNode) {
      const contextPrefix = `[Context: I'm looking at a ${selectedNode.type} named "${selectedNode.name}" with full path "${selectedNode.id}". Please consider this context when answering.]\n\n`;
      contextualMessage = contextPrefix + messageContent;
    }

    // Add user message to display (without context prefix for cleaner UI)
    setAskMessages(prev => [...prev, {
      role: 'user',
      content: messageContent,
      timestamp: new Date().toISOString()
    }]);
    setAskInput('');
    setAskLoading(true);

    try {
      const response = await fetch('/api/llm-search/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: contextualMessage, session_id: askSessionId }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Chat request failed' }));
        throw new Error(error.detail || 'Chat request failed');
      }

      const data = await response.json();
      setAskSessionId(data.session_id);
      
      // Add assistant response
      setAskMessages(prev => [...prev, {
        role: 'assistant',
        content: data.message.content || 'No response',
        timestamp: data.message.timestamp || new Date().toISOString()
      }]);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      toast({
        title: t('errors.error'),
        description: errorMessage,
        variant: 'destructive',
      });
      // Remove the user message on error
      setAskMessages(prev => prev.slice(0, -1));
    } finally {
      setAskLoading(false);
      askInputRef.current?.focus();
    }
  };

  const handleAskKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAskSend();
    }
  };

  // Handle re-running a previous message
  const handleAskRerun = useCallback(async (messageContent: string) => {
    if (!messageContent || askLoading) return;

    const selectedNode = getSelectedNodeDetails();
    
    // Build context message that includes selected item info
    let contextualMessage = messageContent;
    if (selectedNode) {
      const contextPrefix = `[Context: I'm looking at a ${selectedNode.type} named "${selectedNode.name}" with full path "${selectedNode.id}". Please consider this context when answering.]\n\n`;
      contextualMessage = contextPrefix + messageContent;
    }

    // Add user message to display (without context prefix for cleaner UI)
    setAskMessages(prev => [...prev, {
      role: 'user',
      content: messageContent,
      timestamp: new Date().toISOString()
    }]);
    setAskLoading(true);

    try {
      const response = await fetch('/api/llm-search/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: contextualMessage, session_id: askSessionId }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Chat request failed' }));
        throw new Error(error.detail || 'Chat request failed');
      }

      const data = await response.json();
      setAskSessionId(data.session_id);
      
      // Add assistant response
      setAskMessages(prev => [...prev, {
        role: 'assistant',
        content: data.message.content || 'No response',
        timestamp: data.message.timestamp || new Date().toISOString()
      }]);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      toast({
        title: t('errors.error'),
        description: errorMessage,
        variant: 'destructive',
      });
      // Remove the user message on error
      setAskMessages(prev => prev.slice(0, -1));
    } finally {
      setAskLoading(false);
      askInputRef.current?.focus();
    }
  }, [askLoading, askSessionId, toast, t]);

  // Handle copying a message to the input for editing
  const handleAskCopyToInput = useCallback((content: string) => {
    setAskInput(content);
    askInputRef.current?.focus();
  }, []);

  const handleNewAskSession = () => {
    setAskSessionId(undefined);
    setAskMessages([]);
    askInputRef.current?.focus();
  };

  // Scroll to bottom when ask messages change
  useEffect(() => {
    askMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [askMessages]);

  const handleItemSelect = (item: CatalogItem) => {
    setSelectedItems([item]);
    setSelectedObjectInfo({ id: item.id });
  };

  // Draggable divider handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    setDragStartX(e.clientX);
    setDragStartWidth(leftPaneWidth);
  };

  const handleMouseMove = React.useCallback((e: MouseEvent) => {
    if (!isDragging) return;

    const delta = e.clientX - dragStartX;
    const newWidth = Math.max(300, Math.min(800, dragStartWidth + delta));
    setLeftPaneWidth(newWidth);
  }, [isDragging, dragStartX, dragStartWidth]);

  const handleMouseUp = React.useCallback(() => {
    if (isDragging) {
      setIsDragging(false);
      localStorage.setItem('catalog-commander-split', leftPaneWidth.toString());
    }
  }, [isDragging, leftPaneWidth]);

  // Add mouse event listeners for dragging
  React.useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isDragging, handleMouseMove, handleMouseUp]);

  const getIcon = (type: string) => {
    switch (type) {
      case 'catalog':
        return <Folder className="h-4 w-4 text-blue-500" />;
      case 'schema':
        return <FolderOpen className="h-4 w-4 text-green-500" />;
      case 'table':
        return <Table className="h-4 w-4 text-orange-500" />;
      case 'view':
        return <Layout className="h-4 w-4 text-purple-500" />;
      default:
        return null;
    }
  };

  // Apply filter only at the top level; once navigating deeper, show all children unfiltered
  const renderTree = (items: CatalogItem[], isSource: boolean, bypassFilter: boolean = false): TreeViewItem[] => {
    const filteredItems = items.filter((item) => {
      if (bypassFilter) return true;
      const q = searchInput.trim().toLowerCase();
      if (!q) return true;
      if (expandedNodes.has(item.id)) return true; // Keep expanded nodes visible
      return item.name.toLowerCase().includes(q);
    });

    return filteredItems.map(item => {
      const hasChildren = item.hasChildren || (item.children && item.children.length > 0);
      
      const treeItem = {
        id: item.id,
        name: item.name,
        icon: getIcon(item.type),
        // When a query is active, bypass filter for children (show unfiltered)
        children: item.children ? renderTree(item.children, isSource, Boolean(searchInput.trim())) : [],
        onClick: () => {
          handleItemSelect(item);
        },
        selected: selectedItems.some(selected => selected.id === item.id),
        expanded: expandedNodes.has(item.id),
        onExpand: () => {
          handleNodeExpand(item.id, item.type, isSource);
        },
        loading: loadingNodes.has(item.id),
        hasChildren: hasChildren
      };
      return treeItem;
    });
  };

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <FolderKanban className="w-8 h-8" /> {t('title')}
      </h1>

      {/* Action Toolbar */}
      <div className="flex justify-between items-center mb-4">
        <div className="flex gap-2">
          <Button
            onClick={() => handleViewDataset(getSelectedNodeDetails()?.id || '')}
            disabled={!selectedItems.length || getSelectedNodeDetails()?.type !== 'table'}
            variant="outline"
            size="sm"
            className="h-9"
          >
            <Eye className="h-4 w-4 mr-2" />
            {t('actions.viewData')}
          </Button>
          {canPerformWriteActions && (
            <>
              <Button
                onClick={() => handleOperation('move')}
                variant="outline"
                size="sm"
                className="h-9"
              >
                <ArrowRight className="h-4 w-4 mr-2" />
                {t('actions.move')}
              </Button>
              <Button
                onClick={() => handleOperation('delete')}
                variant="outline"
                size="sm"
                className="h-9 text-destructive hover:text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                {t('actions.delete')}
              </Button>
              <Button
                onClick={() => handleOperation('rename')}
                variant="outline"
                size="sm"
                className="h-9"
              >
                <Pencil className="h-4 w-4 mr-2" />
                {t('actions.rename')}
              </Button>
            </>
          )}
        </div>

        {/* Right Panel Mode Toggle */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 border rounded-lg p-1 bg-muted/30">
            <Button
              variant={rightPanelMode === 'ask' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setRightPanelMode(rightPanelMode === 'ask' ? 'hidden' : 'ask')}
              className={cn(
                "h-8 px-3",
                rightPanelMode === 'ask' && "shadow-sm"
              )}
            >
              <Sparkles className="h-4 w-4 mr-1.5" />
              {t('askOntos')}
            </Button>
            <Button
              variant={rightPanelMode === 'info' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setRightPanelMode(rightPanelMode === 'info' ? 'hidden' : 'info')}
              className={cn(
                "h-8 px-3",
                rightPanelMode === 'info' && "shadow-sm"
              )}
            >
              <Info className="h-4 w-4 mr-1.5" />
              {t('actions.info')}
            </Button>
            {canPerformWriteActions && (
              <Button
                variant={rightPanelMode === 'dual-tree' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setRightPanelMode(rightPanelMode === 'dual-tree' ? 'hidden' : 'dual-tree')}
                className={cn(
                  "h-8 px-3",
                  rightPanelMode === 'dual-tree' && "shadow-sm"
                )}
              >
                <GitCompare className="h-4 w-4 mr-1.5" />
                {t('actions.operations')}
              </Button>
            )}
            <Button
              variant={rightPanelMode === 'comments' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setRightPanelMode(rightPanelMode === 'comments' ? 'hidden' : 'comments')}
              className={cn(
                "h-8 px-3",
                rightPanelMode === 'comments' && "shadow-sm"
              )}
            >
              <MessageSquare className="h-4 w-4 mr-1.5" />
              {t('actions.comments')}
            </Button>
          </div>
          {rightPanelMode !== 'hidden' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRightPanelMode('hidden')}
              className="h-8 w-8 p-0"
            >
              <PanelRightClose className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Main Layout: Resizable Left Tree + Variable Right Panel */}
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        {/* Resizable Left Tree View with horizontal and vertical scrolling */}
        <Card
          className="flex-shrink-0 flex flex-col h-full shadow-sm border-border/50"
          style={{ width: `${leftPaneWidth}px` }}
        >
          <CardHeader className="flex-none pb-3 border-b">
            <CardTitle className="text-lg font-semibold">{t('catalogBrowser')}</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col h-full min-h-0 p-4 space-y-3">
            {estates.length > 1 && (
              <div className="space-y-2 flex-none">
                <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t('labels.metastore')}</Label>
                <Select
                  value={selectedSourceEstate}
                  onValueChange={setSelectedSourceEstate}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder={t('labels.selectEstate')} />
                  </SelectTrigger>
                  <SelectContent>
                    {estates.map(estate => (
                      <SelectItem key={estate.id} value={estate.id}>
                        <div className="flex items-center gap-2">
                          <span>{estate.name}</span>
                          <span className="text-xs text-muted-foreground">({estate.metastore_name})</span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex gap-2 flex-none">
              <Input
                placeholder={t('labels.filterCatalogs')}
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="h-9 flex-1"
              />
              <Button
                variant="outline"
                size="icon"
                className="h-9 w-9 flex-shrink-0"
                onClick={handleRefresh}
                disabled={isLoading}
                title={t('tooltips.refresh')}
              >
                <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
              </Button>
            </div>
            <div className="flex-1 min-h-0 overflow-auto border rounded-md bg-muted/20">
              {isLoading ? (
                <div className="flex items-center justify-center h-full min-h-[200px]">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-4">
                  <div className="text-destructive text-sm mb-3">{error}</div>
                  <Button size="sm" variant="outline" onClick={() => fetchCatalogs()}>
                    {t('actions.retry')}
                  </Button>
                </div>
              ) : (
                <div className="min-w-max text-sm [&_button]:!py-0.5 [&_button]:!my-0 [&_ul]:!space-y-0 [&_ul]:!gap-0 [&_li]:!my-0 [&_li]:!py-0">
                  <TreeView
                    data={renderTree(sourceItems, true)}
                    className="p-1 !space-y-0 !gap-0"
                    onSelectChange={(item) => handleItemSelect(item as unknown as CatalogItem)}
                  />
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Draggable Divider - Only visible on hover */}
        {rightPanelMode !== 'hidden' && (
          <div
            className={cn(
              "w-1 bg-transparent hover:bg-border cursor-col-resize transition-colors flex-shrink-0 -mx-2",
              isDragging && "bg-primary"
            )}
            onMouseDown={handleMouseDown}
            title={t('tooltips.dragToResize')}
          />
        )}

        {/* Variable Right Panel */}
        {rightPanelMode !== 'hidden' && (
          <>
            {/* Operations Panel: Transfer Arrows + Target Tree */}
            {rightPanelMode === 'dual-tree' && canPerformWriteActions && (
              <>
                <div className="flex flex-col justify-center gap-2">
                  <Button
                    onClick={() => handleOperation('copy')}
                    variant="outline"
                    size="icon"
                    className="h-10 w-10 hover:bg-primary hover:text-primary-foreground transition-colors"
                    title={t('tooltips.copyToTarget')}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                  <Button
                    onClick={() => handleOperation('move')}
                    variant="outline"
                    size="icon"
                    className="h-10 w-10 hover:bg-primary hover:text-primary-foreground transition-colors"
                    title={t('tooltips.moveToTarget')}
                  >
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                  <Button
                    onClick={() => handleOperation('move')}
                    variant="outline"
                    size="icon"
                    className="h-10 w-10 hover:bg-primary hover:text-primary-foreground transition-colors"
                    title={t('tooltips.moveFromTarget')}
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </Button>
                </div>

                <Card className="flex-1 flex flex-col h-full min-w-0 shadow-sm border-border/50">
                  <CardHeader className="flex-none pb-3 border-b">
                    <CardTitle className="text-lg font-semibold">{t('target')}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 flex flex-col h-full min-h-0 p-4 space-y-3">
                    {estates.length > 1 && (
                      <div className="space-y-2 flex-none">
                        <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t('labels.metastore')}</Label>
                        <Select
                          value={selectedTargetEstate}
                          onValueChange={setSelectedTargetEstate}
                        >
                          <SelectTrigger className="h-9">
                            <SelectValue placeholder="Select Estate" />
                          </SelectTrigger>
                          <SelectContent>
                            {estates.map(estate => (
                              <SelectItem key={estate.id} value={estate.id}>
                                <div className="flex items-center gap-2">
                                  <span>{estate.name}</span>
                                  <span className="text-xs text-muted-foreground">({estate.metastore_name})</span>
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                    <div className="flex gap-2 flex-none">
                      <Input
                        placeholder={t('labels.filterCatalogs')}
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        className="h-9 flex-1"
                      />
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-9 w-9 flex-shrink-0"
                        onClick={handleRefresh}
                        disabled={isLoading}
                        title={t('tooltips.refresh')}
                      >
                        <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
                      </Button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-auto border rounded-md bg-muted/20">
                      {isLoading ? (
                        <div className="flex items-center justify-center h-full min-h-[200px]">
                          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                      ) : error ? (
                        <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-4">
                          <div className="text-destructive text-sm mb-3">{error}</div>
                          <Button size="sm" variant="outline" onClick={() => fetchCatalogs()}>
                            Retry
                          </Button>
                        </div>
                      ) : (
                        <div className="min-w-max text-sm [&_button]:!py-0.5 [&_button]:!my-0 [&_ul]:!space-y-0 [&_ul]:!gap-0 [&_li]:!my-0 [&_li]:!py-0">
                          <TreeView
                            data={renderTree(targetItems, false)}
                            className="p-1 !space-y-0 !gap-0"
                            onSelectChange={(item) => handleItemSelect(item as unknown as CatalogItem)}
                          />
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </>
            )}

            {/* Ask Ontos Panel */}
            {rightPanelMode === 'ask' && (
              <Card className="flex-1 flex flex-col h-full min-w-0 shadow-sm border-border/50">
                <CardHeader className="flex-none pb-3 border-b">
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2 text-lg font-semibold">
                      <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                        <Sparkles className="w-3 h-3 text-white" />
                      </div>
                      {t('askPanel.title')}
                    </CardTitle>
                    {askMessages.length > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleNewAskSession}
                        className="h-7 text-xs"
                      >
                        {t('actions.newChat')}
                      </Button>
                    )}
                  </div>
                  {getSelectedNodeDetails() && (
                    <div className="text-xs text-muted-foreground mt-1 flex items-center gap-2">
                      <span>{t('askPanel.askingAbout')} <span className="font-medium">{getSelectedNodeDetails()?.name}</span></span>
                      <Badge variant="outline" className="text-xs">
                        {getSelectedNodeDetails()?.type}
                      </Badge>
                    </div>
                  )}
                </CardHeader>
                <CardContent className="flex-1 overflow-hidden p-0 flex flex-col">
                  {/* Messages Area */}
                  <ScrollArea className="flex-1 p-4">
                    {askMessages.length === 0 ? (
                      <div className="flex flex-col items-center justify-center h-full text-center space-y-4 py-8">
                        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-violet-500/20 to-purple-600/20 flex items-center justify-center">
                          <Sparkles className="w-6 h-6 text-violet-500" />
                        </div>
                        <div className="space-y-2">
                          <h3 className="text-sm font-medium">{t('askPanel.askAboutItem')}</h3>
                          <p className="text-xs text-muted-foreground max-w-[200px]">
                            {getSelectedNodeDetails() 
                              ? t('askPanel.askQuestionsAbout', { name: getSelectedNodeDetails()?.name })
                              : t('askPanel.selectItemFirst')}
                          </p>
                        </div>
                        {getSelectedNodeDetails() && (
                          <div className="flex flex-wrap gap-1.5 justify-center">
                            {[t('askPanel.exampleQuestions.columns'), t('askPanel.exampleQuestions.owner'), t('askPanel.exampleQuestions.usage')].map((q, i) => (
                              <Button
                                key={i}
                                variant="outline"
                                size="sm"
                                className="text-xs h-7"
                                onClick={() => setAskInput(q)}
                              >
                                {q}
                              </Button>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {askMessages.map((msg, idx) => (
                          <div key={idx} className={`group flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                            <div className={`
                              flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center
                              ${msg.role === 'user' 
                                ? 'bg-sky-500 dark:bg-sky-600 text-white' 
                                : 'bg-gradient-to-br from-violet-500 to-purple-600 text-white'
                              }
                            `}>
                              {msg.role === 'user' 
                                ? <span className="text-[10px] font-medium">U</span>
                                : <Sparkles className="w-3 h-3" />
                              }
                            </div>
                            <div className={`
                              flex-1 max-w-[85%] rounded-lg px-3 py-2 text-sm relative
                              ${msg.role === 'user' 
                                ? 'bg-sky-100 dark:bg-sky-900/50 text-sky-900 dark:text-sky-100' 
                                : 'bg-muted'
                              }
                            `}>
                              {msg.role === 'user' ? (
                                <p className="whitespace-pre-wrap">{msg.content}</p>
                              ) : (
                                <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {msg.content}
                                  </ReactMarkdown>
                                </div>
                              )}
                              {/* Hover actions for user messages */}
                              {msg.role === 'user' && msg.content && (
                                <div className="absolute -left-1 top-1/2 -translate-y-1/2 -translate-x-full flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 text-muted-foreground hover:text-foreground"
                                    onClick={() => handleAskCopyToInput(msg.content)}
                                    title={t('askPanel.copyToInput')}
                                  >
                                    <Pencil className="w-3 h-3" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 text-muted-foreground hover:text-foreground"
                                    onClick={() => handleAskRerun(msg.content)}
                                    title={t('askPanel.rerun')}
                                  >
                                    <RefreshCw className="w-3 h-3" />
                                  </Button>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                        {askLoading && (
                          <div className="flex gap-2">
                            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                              <Sparkles className="w-3 h-3 text-white" />
                            </div>
                            <div className="bg-muted rounded-lg px-3 py-2 flex items-center gap-2">
                              <Loader2 className="w-3 h-3 animate-spin" />
                              <span className="text-xs text-muted-foreground">{t('askPanel.thinking')}</span>
                            </div>
                          </div>
                        )}
                        <div ref={askMessagesEndRef} />
                      </div>
                    )}
                  </ScrollArea>
                  
                  {/* Input Area */}
                  <div className="p-3 border-t">
                    <div className="flex gap-2">
                      <Textarea
                        ref={askInputRef}
                        value={askInput}
                        onChange={(e) => setAskInput(e.target.value)}
                        onKeyDown={handleAskKeyDown}
                        placeholder={getSelectedNodeDetails() 
                          ? t('askPanel.askAboutPlaceholder', { name: getSelectedNodeDetails()?.name })
                          : t('askPanel.selectItemPlaceholder')
                        }
                        className="min-h-[36px] max-h-24 resize-none text-sm"
                        disabled={askLoading || !getSelectedNodeDetails()}
                      />
                      <Button
                        onClick={handleAskSend}
                        disabled={!askInput.trim() || askLoading || !getSelectedNodeDetails()}
                        size="icon"
                        className="h-9 w-9 shrink-0"
                      >
                        {askLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Send className="w-4 h-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Info Panel */}
            {rightPanelMode === 'info' && (
              <Card className="flex-1 flex flex-col h-full min-w-0 shadow-sm border-border/50">
                <CardHeader className="flex-none pb-3 border-b">
                  <CardTitle className="text-lg font-semibold">{t('objectInformation')}</CardTitle>
                </CardHeader>
                <CardContent className="flex-1 overflow-auto p-4">
                  {selectedObjectInfo ? (
                    <div className="space-y-4">
                      {/* Basic Information Card */}
                      <Card>
                        <CardHeader className="pb-3">
                          <CardTitle className="text-sm font-medium flex items-center gap-2">
                            <Info className="h-4 w-4" />
                            {t('basicInformation')}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {(() => {
                            const node = getSelectedNodeDetails();
                            return node ? (
                              <div className="space-y-3">
                                <div className="grid grid-cols-3 gap-2 items-center">
                                  <span className="text-sm text-muted-foreground">{t('labels.name')}</span>
                                  <span className="text-sm font-medium col-span-2">{node.name}</span>
                                </div>
                                <Separator />
                                <div className="grid grid-cols-3 gap-2 items-center">
                                  <span className="text-sm text-muted-foreground">{t('labels.type')}</span>
                                  <div className="col-span-2">
                                    <Badge variant="outline" className="font-mono">{node.type}</Badge>
                                  </div>
                                </div>
                                <Separator />
                                <div className="grid grid-cols-3 gap-2">
                                  <span className="text-sm text-muted-foreground">{t('labels.fullPath')}</span>
                                  <code className="text-xs bg-muted p-2 rounded border break-all col-span-2 font-mono">{node.id}</code>
                                </div>
                                {node.type === 'table' && (
                                  <>
                                    <Separator />
                                    <div className="flex items-center justify-between">
                                      <span className="text-sm text-muted-foreground">{t('labels.actions')}</span>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => handleViewDataset(node.id)}
                                        className="h-8"
                                      >
                                        <Eye className="h-3 w-3 mr-1" />
                                        {t('actions.viewData')}
                                      </Button>
                                    </div>
                                  </>
                                )}
                              </div>
                            ) : (
                              <p className="text-sm text-muted-foreground">{t('messages.loadingDetails')}</p>
                            );
                          })()}
                        </CardContent>
                      </Card>

                      {/* Entity Metadata Panel - Notes, Links, Documents */}
                      {getSelectedNodeDetails() && (
                        <EntityMetadataPanel
                          entityId={getSelectedNodeDetails()?.id || ''}
                          entityType={'data_product' as any}
                        />
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <Info className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50" />
                        <p className="text-sm text-muted-foreground">{t('messages.selectObjectToViewInfo')}</p>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Comments Panel */}
            {rightPanelMode === 'comments' && (
              <Card className="flex-1 flex flex-col h-full min-w-0 shadow-sm border-border/50">
                <CardHeader className="flex-none pb-3 border-b">
                  <CardTitle className="flex items-center gap-2 text-lg font-semibold">
                    <MessageSquare className="h-5 w-5" />
                    {t('commentsAndActivity')}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex-1 overflow-hidden p-4">
                  {selectedObjectInfo && getSelectedNodeDetails()?.id ? (
                    <CommentTimeline
                      entityType="catalog-object"
                      entityId={getSelectedNodeDetails()?.id || ''}
                      showHeader={false}
                      showFilters={true}
                      className="h-full"
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <MessageSquare className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50" />
                        <p className="text-sm text-muted-foreground">{t('messages.selectObjectToViewComments')}</p>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>

      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{t('messages.datasetView', { name: selectedDataset })}</DialogTitle>
          </DialogHeader>
          {loadingData ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="animate-spin h-8 w-8 text-blue-500" />
            </div>
          ) : datasetContent ? (
            <div className="mt-4 flex-1 overflow-auto h-full">
              <DataTable
                data={datasetContent.data}
                columns={datasetContent.schema.map(col => ({
                  accessorKey: col.name,
                  header: `${col.name} (${col.type})`,
                }))}
              />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('messages.noDataAvailable')}</p>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('messages.confirmOperation')}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            {selectedItems.length > 0
              ? t('messages.selectedItems', { items: selectedItems.map(item => item.name).join(', ') })
              : t('messages.noItemsSelected')}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>{t('actions.cancel')}</Button>
            <Button onClick={() => setIsDialogOpen(false)}>{t('actions.confirm')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default CatalogCommander; 