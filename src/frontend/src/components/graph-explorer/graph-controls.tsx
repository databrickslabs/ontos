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
  nodeSize,
  onNodeSizeChange,
  onResetView,
  graphData,
  stats,
}: GraphControlsProps) {
  const nodeTypes = getUniqueNodeTypes(graphData);
  const relationshipTypes = getUniqueRelationshipTypes(graphData);

  const handleNodeTypeToggle = (type: string) => {
    if (selectedNodeTypes.includes(type)) {
      onNodeTypeChange(selectedNodeTypes.filter((t) => t !== type));
    } else {
      onNodeTypeChange([...selectedNodeTypes, type]);
    }
  };

  const handleRelationshipTypeToggle = (type: string) => {
    if (selectedRelationshipTypes.includes(type)) {
      onRelationshipTypeChange(selectedRelationshipTypes.filter((t) => t !== type));
    } else {
      onRelationshipTypeChange([...selectedRelationshipTypes, type]);
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>Graph Controls</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Graph Statistics */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/30 p-3">
            <div className="text-xs text-muted-foreground">Total Nodes</div>
            <div className="text-2xl font-bold text-blue-700 dark:text-blue-400">
              {stats.totalNodes}
            </div>
          </div>
          <div className="rounded-lg bg-purple-50 dark:bg-purple-950/30 p-3">
            <div className="text-xs text-muted-foreground">Total Edges</div>
            <div className="text-2xl font-bold text-purple-700 dark:text-purple-400">
              {stats.totalEdges}
            </div>
          </div>
          <div className="rounded-lg bg-green-50 dark:bg-green-950/30 p-3">
            <div className="text-xs text-muted-foreground">New Nodes</div>
            <div className="text-2xl font-bold text-green-700 dark:text-green-400">
              {stats.newNodes}
            </div>
          </div>
          <div className="rounded-lg bg-orange-50 dark:bg-orange-950/30 p-3">
            <div className="text-xs text-muted-foreground">New Edges</div>
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
              Show Proposed
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
              Node Labels
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
              Edge Labels
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
              <Label htmlFor="edge-length">Edge Length</Label>
              <span className="text-sm text-muted-foreground">{edgeLength}</span>
            </div>
            <input
              id="edge-length"
              type="range"
              min="30"
              max="200"
              value={edgeLength}
              onChange={(e) => onEdgeLengthChange(Number(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
              style={{
                background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${
                  ((edgeLength - 30) / (200 - 30)) * 100
                }%, rgb(229 231 235) ${((edgeLength - 30) / (200 - 30)) * 100}%, rgb(229 231 235) 100%)`,
              }}
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="node-size">Node Size</Label>
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
          <Label>Node Types</Label>
          <ScrollArea className="h-32">
            <div className="flex flex-wrap gap-2">
              {nodeTypes.map((type) => {
                const isSelected = selectedNodeTypes.includes(type);
                const color = getColorForType(type);
                return (
                  <Badge
                    key={type}
                    variant={isSelected ? 'default' : 'outline'}
                    className={cn(
                      'cursor-pointer transition-colors',
                      isSelected && 'border-2',
                      !isSelected && 'hover:bg-accent'
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
          <Label>Relationship Types</Label>
          <ScrollArea className="h-32">
            <div className="flex flex-wrap gap-2">
              {relationshipTypes.map((type) => {
                const isSelected = selectedRelationshipTypes.includes(type);
                const color = getColorForType(type);
                return (
                  <Badge
                    key={type}
                    variant={isSelected ? 'default' : 'outline'}
                    className={cn(
                      'cursor-pointer transition-colors',
                      isSelected && 'border-2',
                      !isSelected && 'hover:bg-accent'
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
          <Label>Type Colors</Label>
          <ScrollArea className="h-24">
            <div className="space-y-1.5">
              {nodeTypes.slice(0, 10).map((type) => {
                const color = getColorForType(type);
                return (
                  <div key={type} className="flex items-center gap-2 text-sm">
                    <div
                      className="h-4 w-4 rounded-full border"
                      style={{ backgroundColor: color }}
                    />
                    <span className="text-muted-foreground">{type}</span>
                  </div>
                );
              })}
              {nodeTypes.length > 10 && (
                <div className="text-xs text-muted-foreground">
                  +{nodeTypes.length - 10} more types
                </div>
              )}
            </div>
          </ScrollArea>
        </div>

        <Separator />

        {/* Reset View Button */}
        <Button onClick={onResetView} variant="outline" className="w-full">
          <RefreshCw className="mr-2 h-4 w-4" />
          Reset View
        </Button>
      </CardContent>
    </Card>
  );
}
