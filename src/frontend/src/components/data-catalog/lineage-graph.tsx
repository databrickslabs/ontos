/**
 * Lineage Graph Component
 * 
 * Interactive DAG visualization for table/column lineage.
 * Uses a simple custom implementation for now.
 * Can be upgraded to @xyflow/react for more advanced features.
 */

import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Table as TableIcon,
  Eye,
  ExternalLink,
  Loader2,
  AlertCircle,
  Database,
  FileSpreadsheet,
  Workflow
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import type { LineageGraph as LineageGraphType, LineageNode, AssetType, LineageDirection } from '@/types/data-catalog';

// =============================================================================
// Types
// =============================================================================

interface LineageGraphProps {
  graph: LineageGraphType | null;
  isLoading?: boolean;
  error?: string | null;
  direction: LineageDirection;
  onDirectionChange: (direction: LineageDirection) => void;
  onRefresh?: () => void;
}

// =============================================================================
// Helpers
// =============================================================================

const getNodeIcon = (type: AssetType) => {
  switch (type) {
    case 'table':
      return <TableIcon className="h-4 w-4" />;
    case 'view':
      return <Eye className="h-4 w-4" />;
    case 'external':
      return <ExternalLink className="h-4 w-4" />;
    case 'notebook':
      return <FileSpreadsheet className="h-4 w-4" />;
    case 'job':
      return <Workflow className="h-4 w-4" />;
    default:
      return <Database className="h-4 w-4" />;
  }
};

const getNodeColor = (type: AssetType, isRoot: boolean) => {
  if (isRoot) return 'bg-primary text-primary-foreground border-primary';
  
  switch (type) {
    case 'table':
      return 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800';
    case 'view':
      return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800';
    case 'external':
      return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-800';
    case 'notebook':
      return 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800';
    case 'job':
      return 'bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950 dark:text-yellow-300 dark:border-yellow-800';
    default:
      return 'bg-muted text-muted-foreground border-border';
  }
};

// =============================================================================
// Node Component
// =============================================================================

interface LineageNodeCardProps {
  node: LineageNode;
  onClick?: () => void;
}

const LineageNodeCard: React.FC<LineageNodeCardProps> = ({ node, onClick }) => {
  const colorClass = getNodeColor(node.type, node.is_root);
  
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={`
            flex items-center gap-2 px-3 py-2 rounded-lg border-2 cursor-pointer
            transition-all hover:shadow-md hover:scale-105
            ${colorClass}
          `}
          onClick={onClick}
        >
          {getNodeIcon(node.type)}
          <div className="flex flex-col min-w-0">
            <span className="text-sm font-medium truncate max-w-[150px]">
              {node.name}
            </span>
            {node.catalog && node.schema && (
              <span className="text-xs opacity-70 truncate max-w-[150px]">
                {node.catalog}.{node.schema}
              </span>
            )}
          </div>
          {node.is_root && (
            <Badge variant="secondary" className="ml-1 text-xs">Root</Badge>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <div className="space-y-1">
          <p className="font-medium">{node.id}</p>
          <p className="text-xs text-muted-foreground">Type: {node.type}</p>
          {node.owner && <p className="text-xs">Owner: {node.owner}</p>}
          {node.comment && <p className="text-xs">{node.comment}</p>}
          {node.external_system && <p className="text-xs">System: {node.external_system}</p>}
        </div>
      </TooltipContent>
    </Tooltip>
  );
};

// =============================================================================
// Level-based Layout
// =============================================================================

interface LevelLayoutProps {
  graph: LineageGraphType;
  onNodeClick: (node: LineageNode) => void;
}

const LevelLayout: React.FC<LevelLayoutProps> = ({ graph, onNodeClick }) => {
  // Group nodes by depth
  const nodesByDepth = useMemo(() => {
    const grouped: Map<number, LineageNode[]> = new Map();
    
    graph.nodes.forEach(node => {
      const depth = node.depth;
      if (!grouped.has(depth)) {
        grouped.set(depth, []);
      }
      grouped.get(depth)!.push(node);
    });
    
    // Sort depths
    const sortedDepths = Array.from(grouped.keys()).sort((a, b) => a - b);
    return sortedDepths.map(depth => ({
      depth,
      nodes: grouped.get(depth)!
    }));
  }, [graph.nodes]);

  // Find root node
  const rootNode = graph.nodes.find(n => n.is_root);
  if (!rootNode) return null;

  // Split into upstream and downstream
  const upstreamLevels = nodesByDepth.filter(l => l.depth < 0).reverse();
  const rootLevel = nodesByDepth.find(l => l.depth === 0);
  const downstreamLevels = nodesByDepth.filter(l => l.depth > 0);

  return (
    <div className="flex items-center gap-8 p-6 min-w-max">
      {/* Upstream nodes */}
      {upstreamLevels.map((level, _levelIdx) => (
        <React.Fragment key={`up-${level.depth}`}>
          <div className="flex flex-col gap-3">
            {level.nodes.map(node => (
              <LineageNodeCard 
                key={node.id} 
                node={node} 
                onClick={() => onNodeClick(node)}
              />
            ))}
          </div>
          <ArrowRight className="h-6 w-6 text-muted-foreground flex-shrink-0" />
        </React.Fragment>
      ))}
      
      {/* Root node */}
      {rootLevel && (
        <div className="flex flex-col gap-3">
          {rootLevel.nodes.map(node => (
            <LineageNodeCard 
              key={node.id} 
              node={node} 
              onClick={() => onNodeClick(node)}
            />
          ))}
        </div>
      )}
      
      {/* Downstream nodes */}
      {downstreamLevels.map((level, _levelIdx) => (
        <React.Fragment key={`down-${level.depth}`}>
          <ArrowRight className="h-6 w-6 text-muted-foreground flex-shrink-0" />
          <div className="flex flex-col gap-3">
            {level.nodes.map(node => (
              <LineageNodeCard 
                key={node.id} 
                node={node} 
                onClick={() => onNodeClick(node)}
              />
            ))}
          </div>
        </React.Fragment>
      ))}
    </div>
  );
};

// =============================================================================
// Main Component
// =============================================================================

const LineageGraphComponent: React.FC<LineageGraphProps> = ({
  graph,
  isLoading = false,
  error = null,
  direction,
  onDirectionChange,
  onRefresh
}) => {
  const { t } = useTranslation(['data-catalog', 'common']);
  const navigate = useNavigate();

  const handleNodeClick = (node: LineageNode) => {
    // Navigate to table details if it's a UC table/view
    if ((node.type === 'table' || node.type === 'view') && node.catalog && node.schema) {
      navigate(`/data-catalog/${encodeURIComponent(node.id)}`);
    }
  };

  // Stats
  const stats = useMemo(() => {
    if (!graph) return null;
    return {
      upstream: graph.upstream_count,
      downstream: graph.downstream_count,
      external: graph.external_count,
      total: graph.nodes.length - 1 // Exclude root
    };
  }, [graph]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <AlertCircle className="h-8 w-8 mb-2" />
        <p>{error}</p>
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <Workflow className="h-12 w-12 mb-4 opacity-50" />
        <p>{t('data-catalog:lineage.noLineage', 'No lineage information available')}</p>
        <p className="text-sm mt-1">
          {t('data-catalog:lineage.noLineageHint', 'This table may not have any upstream or downstream dependencies')}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Select value={direction} onValueChange={(v) => onDirectionChange(v as LineageDirection)}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="both">{t('data-catalog:lineage.both', 'Both Directions')}</SelectItem>
              <SelectItem value="upstream">{t('data-catalog:lineage.upstream', 'Upstream Only')}</SelectItem>
              <SelectItem value="downstream">{t('data-catalog:lineage.downstream', 'Downstream Only')}</SelectItem>
            </SelectContent>
          </Select>
          
          {onRefresh && (
            <Button variant="outline" size="sm" onClick={onRefresh}>
              {t('common:refresh', 'Refresh')}
            </Button>
          )}
        </div>
        
        {/* Stats */}
        {stats && (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <Badge variant="outline">
              ↑ {stats.upstream} upstream
            </Badge>
            <Badge variant="outline">
              ↓ {stats.downstream} downstream
            </Badge>
            {stats.external > 0 && (
              <Badge variant="outline">
                🔗 {stats.external} external
              </Badge>
            )}
          </div>
        )}
      </div>

      {/* Graph */}
      <Card>
        <CardContent className="p-0">
          <ScrollArea className="h-80">
            <LevelLayout graph={graph} onNodeClick={handleNodeClick} />
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="font-medium">{t('data-catalog:lineage.legend', 'Legend')}:</span>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-blue-200 dark:bg-blue-800" />
          <span>Table</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-green-200 dark:bg-green-800" />
          <span>View</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-orange-200 dark:bg-orange-800" />
          <span>External</span>
        </div>
      </div>
    </div>
  );
};

export default LineageGraphComponent;

