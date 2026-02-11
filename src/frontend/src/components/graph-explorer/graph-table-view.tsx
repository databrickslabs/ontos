/**
 * Table view for graph data.
 *
 * Renders nodes and edges as sortable tables, providing an alternative
 * "spreadsheet" view alongside the force-directed graph canvas.
 */

import React, { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ArrowUpDown, Circle, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { GraphData } from '@/types/graph-explorer';
import { getColorForType } from '@/types/graph-explorer';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SortDirection = 'asc' | 'desc';
type NodeSortField = 'id' | 'label' | 'type';
type EdgeSortField = 'source' | 'target' | 'relationshipType';

export interface GraphTableViewProps {
  data: GraphData;
  onNodeClick?: (nodeId: string) => void;
  onEdgeClick?: (edgeId: string) => void;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  className?: string;
}

// ---------------------------------------------------------------------------
// Sort helper
// ---------------------------------------------------------------------------

function sortBy<T>(items: T[], key: keyof T, direction: SortDirection): T[] {
  return [...items].sort((a, b) => {
    const aVal = String(a[key] ?? '');
    const bVal = String(b[key] ?? '');
    const cmp = aVal.localeCompare(bVal);
    return direction === 'asc' ? cmp : -cmp;
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GraphTableView({
  data,
  onNodeClick,
  onEdgeClick,
  selectedNodeId,
  selectedEdgeId,
  className,
}: GraphTableViewProps) {
  const { t } = useTranslation('graph-explorer');
  const isDarkMode = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

  // Tabs
  const [activeTab, setActiveTab] = useState<'nodes' | 'edges'>('nodes');

  // Sort state
  const [nodeSortField, setNodeSortField] = useState<NodeSortField>('label');
  const [nodeSortDir, setNodeSortDir] = useState<SortDirection>('asc');
  const [edgeSortField, setEdgeSortField] = useState<EdgeSortField>('relationshipType');
  const [edgeSortDir, setEdgeSortDir] = useState<SortDirection>('asc');

  const sortedNodes = useMemo(
    () => sortBy(data.nodes, nodeSortField, nodeSortDir),
    [data.nodes, nodeSortField, nodeSortDir],
  );

  const sortedEdges = useMemo(
    () => sortBy(data.edges, edgeSortField, edgeSortDir),
    [data.edges, edgeSortField, edgeSortDir],
  );

  const toggleNodeSort = (field: NodeSortField) => {
    if (nodeSortField === field) {
      setNodeSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setNodeSortField(field);
      setNodeSortDir('asc');
    }
  };

  const toggleEdgeSort = (field: EdgeSortField) => {
    if (edgeSortField === field) {
      setEdgeSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setEdgeSortField(field);
      setEdgeSortDir('asc');
    }
  };

  // Collect property keys across all nodes for column headers
  const nodePropertyKeys = useMemo(() => {
    const keys = new Set<string>();
    data.nodes.forEach((n) => {
      Object.keys(n.properties).forEach((k) => keys.add(k));
    });
    return [...keys].sort().slice(0, 6); // cap at 6 to prevent overflow
  }, [data.nodes]);

  return (
    <Card className={cn('flex flex-col overflow-hidden', className)}>
      <CardHeader className="pb-2 flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{t('tableView.title')}</CardTitle>
          <div className="flex gap-1">
            <Button
              variant={activeTab === 'nodes' ? 'default' : 'ghost'}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setActiveTab('nodes')}
            >
              {t('tableView.nodes')} ({data.nodes.length})
            </Button>
            <Button
              variant={activeTab === 'edges' ? 'default' : 'ghost'}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setActiveTab('edges')}
            >
              {t('tableView.edges')} ({data.edges.length})
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-auto p-0">
        {activeTab === 'nodes' ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleNodeSort('label')}
                  >
                    {t('tableView.label')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleNodeSort('type')}
                  >
                    {t('tableView.type')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleNodeSort('id')}
                  >
                    {t('tableView.id')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
                {nodePropertyKeys.map((key) => (
                  <TableHead key={key} className="text-xs">
                    {key}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedNodes.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4 + nodePropertyKeys.length} className="text-center text-muted-foreground py-8">
                    {t('tableView.noNodes')}
                  </TableCell>
                </TableRow>
              ) : (
                sortedNodes.map((node) => (
                  <TableRow
                    key={node.id}
                    className={cn(
                      'cursor-pointer hover:bg-muted/50 transition-colors',
                      selectedNodeId === node.id && 'bg-primary/10',
                    )}
                    onClick={() => onNodeClick?.(node.id)}
                  >
                    <TableCell className="w-8 pr-0">
                      <Circle
                        className="h-3 w-3"
                        fill={getColorForType(node.type, isDarkMode)}
                        stroke={getColorForType(node.type, isDarkMode)}
                      />
                    </TableCell>
                    <TableCell className="font-medium text-sm">{node.label}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {node.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground font-mono">
                      {node.id}
                    </TableCell>
                    {nodePropertyKeys.map((key) => (
                      <TableCell key={key} className="text-xs text-muted-foreground max-w-[120px] truncate">
                        {node.properties[key] != null ? String(node.properties[key]) : ''}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleEdgeSort('source')}
                  >
                    {t('tableView.source')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
                <TableHead className="w-8" />
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleEdgeSort('relationshipType')}
                  >
                    {t('tableView.relationship')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
                <TableHead className="w-8" />
                <TableHead>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1 text-xs font-medium -ml-1"
                    onClick={() => toggleEdgeSort('target')}
                  >
                    {t('tableView.target')}
                    <ArrowUpDown className="ml-1 h-3 w-3" />
                  </Button>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedEdges.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    {t('tableView.noEdges')}
                  </TableCell>
                </TableRow>
              ) : (
                sortedEdges.map((edge) => (
                  <TableRow
                    key={edge.id}
                    className={cn(
                      'cursor-pointer hover:bg-muted/50 transition-colors',
                      selectedEdgeId === edge.id && 'bg-primary/10',
                    )}
                    onClick={() => onEdgeClick?.(edge.id)}
                  >
                    <TableCell className="text-sm font-mono">{edge.source}</TableCell>
                    <TableCell className="w-8 text-center">
                      <ArrowRight className="h-3 w-3 text-muted-foreground inline-block" />
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">
                        {edge.relationshipType}
                      </Badge>
                    </TableCell>
                    <TableCell className="w-8 text-center">
                      <ArrowRight className="h-3 w-3 text-muted-foreground inline-block" />
                    </TableCell>
                    <TableCell className="text-sm font-mono">{edge.target}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
