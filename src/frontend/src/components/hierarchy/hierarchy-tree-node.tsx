import { useState, useCallback, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronRight, ChevronDown, Loader2, ExternalLink,
  Box, Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain,
  Activity, Server, Shield, BookOpen, Database, FolderOpen, Shapes, Network,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useApi } from '@/hooks/use-api';
import { cn } from '@/lib/utils';
import type { InstanceHierarchyNode } from '@/types/ontology-schema';

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box, Network,
};

const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
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

interface HierarchyTreeNodeProps {
  node: InstanceHierarchyNode;
  depth: number;
  selectedId?: string | null;
  onSelect?: (node: InstanceHierarchyNode) => void;
  isLazy?: boolean;
}

export function HierarchyTreeNode({
  node,
  depth,
  selectedId,
  onSelect,
  isLazy = false,
}: HierarchyTreeNodeProps) {
  const { t } = useTranslation(['data-catalog', 'common']);
  const [expanded, setExpanded] = useState(depth < 1);
  const [children, setChildren] = useState<InstanceHierarchyNode[]>(node.children || []);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(!isLazy || (node.children && node.children.length > 0));

  const navigate = useNavigate();
  const { get: apiGet } = useApi();

  const Icon = getIconComponent(node.icon);
  const hasChildren = node.child_count > 0 || children.length > 0;
  const isSelected = selectedId === node.entity_id;
  const paddingLeft = depth * 16 + 8;

  const loadChildren = useCallback(async () => {
    if (loaded || loading) return;
    setLoading(true);
    try {
      const response = await apiGet<InstanceHierarchyNode>(
        `/api/entity-hierarchy/${node.entity_type}/${node.entity_id}?max_depth=2`
      );
      if (!response.error && response.data) {
        setChildren(response.data.children || []);
      }
    } catch {
      // silently fail
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [apiGet, node.entity_type, node.entity_id, loaded, loading]);

  const handleToggle = useCallback(() => {
    if (!expanded && isLazy && !loaded) {
      loadChildren();
    }
    setExpanded(!expanded);
  }, [expanded, isLazy, loaded, loadChildren]);

  const handleClick = useCallback(() => {
    onSelect?.(node);
  }, [onSelect, node]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      if (!expanded) handleToggle();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      if (expanded) setExpanded(false);
    }
  }, [handleClick, handleToggle, expanded]);

  return (
    <div role="treeitem" aria-expanded={expanded}>
      <div
        className={cn(
          'group flex items-center gap-1.5 py-1 pr-2 rounded-md transition-colors cursor-pointer',
          isSelected ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
        )}
        style={{ paddingLeft }}
      >
        {/* Expand/collapse toggle */}
        <button
          onClick={handleToggle}
          onKeyDown={handleKeyDown}
          className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded hover:bg-muted-foreground/10"
          tabIndex={0}
          aria-label={expanded ? t('data-catalog:hierarchy.collapse') : t('data-catalog:hierarchy.expand')}
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : hasChildren ? (
            expanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
            )
          ) : (
            <span className="w-3.5" />
          )}
        </button>

        {/* Entity icon */}
        <Icon className="h-4 w-4 flex-shrink-0 text-muted-foreground" />

        {/* Name - clickable for selection */}
        <button
          onClick={handleClick}
          className="flex-1 text-left text-sm truncate min-w-0"
        >
          {node.name}
        </button>

        {/* Status badge */}
        {node.status && (
          <Badge
            variant={STATUS_VARIANT[node.status] ?? 'outline'}
            className="text-[10px] flex-shrink-0 h-4 px-1"
          >
            {node.status}
          </Badge>
        )}

        {/* Child count */}
        {node.child_count > 0 && (
          <span className="text-[10px] text-muted-foreground flex-shrink-0">
            {node.child_count}
          </span>
        )}

        {/* Navigate to detail */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => {
                e.stopPropagation();
                navigate(getEntityRoute(node.entity_type, node.entity_id));
              }}
            >
              <ExternalLink className="h-3 w-3" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">{t('data-catalog:hierarchy.viewDetails')}</TooltipContent>
        </Tooltip>
      </div>

      {/* Children */}
      {expanded && (
        <div role="group">
          {children.map((child) => (
            <HierarchyTreeNode
              key={`${child.entity_type}-${child.entity_id}`}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
              isLazy={isLazy}
            />
          ))}
          {loading && (
            <div className="flex items-center gap-2 py-2" style={{ paddingLeft: paddingLeft + 16 }}>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              <span className="text-xs text-muted-foreground">{t('common:states.loading')}</span>
            </div>
          )}
          {!loading && loaded && children.length === 0 && hasChildren && (
            <div className="py-1 text-xs text-muted-foreground italic" style={{ paddingLeft: paddingLeft + 24 }}>
              {t('data-catalog:hierarchy.noChildrenFound')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
