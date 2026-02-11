import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { RefreshCw, Eye, Tag } from 'lucide-react';
import {
  getUniqueNodeTypes,
  getUniqueRelationshipTypes,
  getColorForType,
  type GraphData,
} from '@/types/graph-explorer';
import { cn } from '@/lib/utils';

interface GraphControlsProps {
  showProposed: boolean;
  onToggleProposed: (show: boolean) => void;
  selectedNodeTypes: string[];
  onNodeTypeChange: (types: string[]) => void;
  selectedRelationshipTypes: string[];
  onRelationshipTypeChange: (types: string[]) => void;
  showNodeLabels: boolean;
  onToggleNodeLabels: (show: boolean) => void;
  showEdgeLabels: boolean;
  onToggleEdgeLabels: (show: boolean) => void;
  edgeLength: number;
  onEdgeLengthChange: (length: number) => void;
  edgeOpacity?: number;
  onEdgeOpacityChange?: (opacity: number) => void;
  nodeSize: number;
  onNodeSizeChange: (size: number) => void;
  onResetView: () => void;
  graphData: GraphData;
  stats: { totalNodes: number; totalEdges: number; newNodes: number; newEdges: number };
}

export default function GraphControls({
  showProposed,
  onToggleProposed,
  selectedNodeTypes,
  onNodeTypeChange,
  selectedRelationshipTypes,
  onRelationshipTypeChange,
  showNodeLabels,
  onToggleNodeLabels,
  showEdgeLabels,
  onToggleEdgeLabels,
  edgeLength,
  onEdgeLengthChange,
  edgeOpacity,
  onEdgeOpacityChange,
  nodeSize,
  onNodeSizeChange,
  onResetView,
  graphData,
  stats,
}: GraphControlsProps) {
  const { t } = useTranslation('graph-explorer');
  const nodeTypes = useMemo(() => getUniqueNodeTypes(graphData), [graphData]);
  const relationshipTypes = useMemo(() => getUniqueRelationshipTypes(graphData), [graphData]);

  // Color map for node type legend
  const isDarkMode = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
  const nodeTypeColors = useMemo(() => {
    const colorMap = new Map<string, string>();
    nodeTypes.forEach((type) => {
      colorMap.set(type, getColorForType(type, isDarkMode));
    });
    return colorMap;
  }, [nodeTypes, isDarkMode]);

  // "Show all" = empty array. Clicking a type when showing all deselects it
  // (shows all except it). Select All resets to empty array.
  const handleNodeTypeToggle = (type: string) => {
    if (selectedNodeTypes.length === 0) {
      // "Show all" mode — deselect this one (show all except it)
      onNodeTypeChange(nodeTypes.filter((t) => t !== type));
    } else if (selectedNodeTypes.includes(type)) {
      onNodeTypeChange(selectedNodeTypes.filter((t) => t !== type));
    } else {
      onNodeTypeChange([...selectedNodeTypes, type]);
    }
  };

  const handleRelationshipTypeToggle = (type: string) => {
    if (selectedRelationshipTypes.length === 0) {
      onRelationshipTypeChange(relationshipTypes.filter((t) => t !== type));
    } else if (selectedRelationshipTypes.includes(type)) {
      onRelationshipTypeChange(selectedRelationshipTypes.filter((t) => t !== type));
    } else {
      onRelationshipTypeChange([...selectedRelationshipTypes, type]);
    }
  };

  const allNodesSelected = selectedNodeTypes.length === 0;
  const allRelsSelected = selectedRelationshipTypes.length === 0;

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>{t('controls.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Graph Statistics */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/30 p-3">
            <div className="text-xs text-muted-foreground">{t('controls.totalNodes')}</div>
            <div className="text-2xl font-bold text-blue-700 dark:text-blue-400">
              {stats.totalNodes}
            </div>
          </div>
          <div className="rounded-lg bg-purple-50 dark:bg-purple-950/30 p-3">
            <div className="text-xs text-muted-foreground">{t('controls.totalEdges')}</div>
            <div className="text-2xl font-bold text-purple-700 dark:text-purple-400">
              {stats.totalEdges}
            </div>
          </div>
          <div className="rounded-lg bg-green-50 dark:bg-green-950/30 p-3">
            <div className="text-xs text-muted-foreground">{t('controls.newNodes')}</div>
            <div className="text-2xl font-bold text-green-700 dark:text-green-400">
              {stats.newNodes}
            </div>
          </div>
          <div className="rounded-lg bg-orange-50 dark:bg-orange-950/30 p-3">
            <div className="text-xs text-muted-foreground">{t('controls.newEdges')}</div>
            <div className="text-2xl font-bold text-orange-700 dark:text-orange-400">
              {stats.newEdges}
            </div>
          </div>
        </div>

        <Separator />

        {/* Visibility Toggles */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="show-proposed" className="flex items-center gap-2">
              <Eye className="h-4 w-4" />
              {t('controls.showProposed')}
            </Label>
            <Switch
              id="show-proposed"
              checked={showProposed}
              onCheckedChange={onToggleProposed}
            />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="show-node-labels" className="flex items-center gap-2">
              <Tag className="h-4 w-4" />
              {t('controls.nodeLabels')}
            </Label>
            <Switch
              id="show-node-labels"
              checked={showNodeLabels}
              onCheckedChange={onToggleNodeLabels}
            />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="show-edge-labels" className="flex items-center gap-2">
              <Tag className="h-4 w-4" />
              {t('controls.edgeLabels')}
            </Label>
            <Switch
              id="show-edge-labels"
              checked={showEdgeLabels}
              onCheckedChange={onToggleEdgeLabels}
            />
          </div>
        </div>

        <Separator />

        {/* Layout Sliders */}
        <div className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="edge-length">{t('controls.edgeLength')}</Label>
              <span className="text-sm text-muted-foreground">{edgeLength}</span>
            </div>
            <input
              id="edge-length"
              type="range"
              min="30"
              max="1000"
              value={edgeLength}
              onChange={(e) => onEdgeLengthChange(Number(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
              style={{
                background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${
                  ((edgeLength - 30) / (1000 - 30)) * 100
                }%, rgb(229 231 235) ${((edgeLength - 30) / (1000 - 30)) * 100}%, rgb(229 231 235) 100%)`,
              }}
            />
          </div>

          {/* Edge Opacity Slider */}
          {edgeOpacity != null && onEdgeOpacityChange && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="edge-opacity">{t('controls.edgeOpacity', { defaultValue: 'Edge Opacity' })}</Label>
                <span className="text-sm text-muted-foreground">{Math.round(edgeOpacity * 100)}%</span>
              </div>
              <input
                id="edge-opacity"
                type="range"
                min="0.05"
                max="1"
                step="0.05"
                value={edgeOpacity}
                onChange={(e) => onEdgeOpacityChange(Number(e.target.value))}
                className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
                style={{
                  background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${
                    ((edgeOpacity - 0.05) / (1 - 0.05)) * 100
                  }%, rgb(229 231 235) ${((edgeOpacity - 0.05) / (1 - 0.05)) * 100}%, rgb(229 231 235) 100%)`,
                }}
              />
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="node-size">{t('controls.nodeSize')}</Label>
              <span className="text-sm text-muted-foreground">{nodeSize}</span>
            </div>
            <input
              id="node-size"
              type="range"
              min="3"
              max="15"
              value={nodeSize}
              onChange={(e) => onNodeSizeChange(Number(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
              style={{
                background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${
                  ((nodeSize - 3) / (15 - 3)) * 100
                }%, rgb(229 231 235) ${((nodeSize - 3) / (15 - 3)) * 100}%, rgb(229 231 235) 100%)`,
              }}
            />
          </div>
        </div>

        <Separator />

        {/* Node Type Filter */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{t('controls.nodeTypes')}</Label>
            {!allNodesSelected && (
              <Button variant="ghost" size="sm" onClick={() => onNodeTypeChange([])}>
                Select All
              </Button>
            )}
          </div>
          <ScrollArea className="h-32">
            <div className="flex flex-wrap gap-2">
              {nodeTypes.map((type) => {
                const isSelected = selectedNodeTypes.length === 0 || selectedNodeTypes.includes(type);
                const color = nodeTypeColors.get(type) || getColorForType(type, isDarkMode);
                return (
                  <Badge
                    key={type}
                    variant={isSelected ? 'default' : 'outline'}
                    className={cn(
                      'cursor-pointer transition-colors',
                      isSelected && 'border-2',
                      !isSelected && 'hover:bg-accent',
                    )}
                    style={
                      isSelected
                        ? {
                            backgroundColor: color,
                            borderColor: color,
                            color: 'white',
                          }
                        : { borderColor: color }
                    }
                    onClick={() => handleNodeTypeToggle(type)}
                  >
                    {type}
                  </Badge>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        <Separator />

        {/* Relationship Type Filter */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{t('controls.relationshipTypes')}</Label>
            {!allRelsSelected && (
              <Button variant="ghost" size="sm" onClick={() => onRelationshipTypeChange([])}>
                Select All
              </Button>
            )}
          </div>
          <ScrollArea className="h-32">
            <div className="flex flex-wrap gap-2">
              {relationshipTypes.map((type) => {
                const isSelected =
                  selectedRelationshipTypes.length === 0 || selectedRelationshipTypes.includes(type);
                const color = getColorForType(type, isDarkMode);
                return (
                  <Badge
                    key={type}
                    variant={isSelected ? 'default' : 'outline'}
                    className={cn(
                      'cursor-pointer transition-colors',
                      isSelected && 'border-2',
                      !isSelected && 'hover:bg-accent',
                    )}
                    style={
                      isSelected
                        ? {
                            backgroundColor: color,
                            borderColor: color,
                            color: 'white',
                          }
                        : {}
                    }
                    onClick={() => handleRelationshipTypeToggle(type)}
                  >
                    {type}
                  </Badge>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        <Separator />

        {/* Legend */}
        <div className="space-y-2">
          <Label>{t('controls.typeColors')}</Label>
          <ScrollArea className="h-28">
            <div className="space-y-1.5">
              {/* Show only selected types (or all if none selected) */}
              {(selectedNodeTypes.length === 0 ? nodeTypes : selectedNodeTypes).map((type) => {
                const color = nodeTypeColors.get(type) || getColorForType(type, isDarkMode);
                return (
                  <div key={type} className="flex items-center gap-2 text-sm">
                    <div
                      className="h-4 w-4 rounded-full border flex-shrink-0"
                      style={{ backgroundColor: color, boxShadow: `0 2px 6px ${color}40` }}
                    />
                    <span className="text-muted-foreground">{type}</span>
                  </div>
                );
              })}
              {nodeTypes.length > 10 && selectedNodeTypes.length === 0 && (
                <div className="text-xs text-muted-foreground">
                  {t('controls.moreTypes', { count: nodeTypes.length - 10 })}
                </div>
              )}

              {/* Proposed indicator */}
              {showProposed && (
                <>
                  <Separator className="my-1" />
                  <div className="flex items-center gap-2 text-sm">
                    <div className="h-4 w-4 rounded-full border-2 border-green-500 bg-green-500/20 flex-shrink-0" />
                    <span className="text-muted-foreground font-medium">Proposed New</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <div className="h-4 w-4 rounded-full border-2 border-amber-500 border-dashed bg-amber-500/20 flex-shrink-0" />
                    <span className="text-muted-foreground font-medium">Modified</span>
                  </div>
                </>
              )}
            </div>
          </ScrollArea>
        </div>

        <Separator />

        {/* Reset View Button */}
        <Button onClick={onResetView} variant="outline" className="w-full">
          <RefreshCw className="mr-2 h-4 w-4" />
          {t('actions.resetView')}
        </Button>
      </CardContent>
    </Card>
  );
}
