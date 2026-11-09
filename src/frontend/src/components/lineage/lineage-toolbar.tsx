/**
 * Toolbar for the column-based lineage view — direction, depth, controls.
 */

import type React from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import {
  ArrowLeft, ArrowRight, ArrowLeftRight, SlidersHorizontal, X, Crosshair, Focus, Layers,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { MODEL_LAYERS } from './constants';
import { EDGE_FILTERS, DEFAULT_VIEW_OPTIONS } from './highlight';
import type { ViewOptions } from './highlight';
import { LINEAGE_DETAILS } from './layout';
import type { LineageDetail } from './layout';

/** "All" runs each chain to its end (backend cap) */
export const DEPTH_ALL = 10;
const DEPTHS = [1, 2, 3, 4, 5, DEPTH_ALL];

export type LineageDirection = 'upstream' | 'downstream' | 'both';

interface LineageToolbarProps {
  direction: LineageDirection;
  onDirectionChange: (d: LineageDirection) => void;
  maxDepth: number;
  onMaxDepthChange: (d: number) => void;
  detail: LineageDetail;
  onDetailChange: (d: LineageDetail) => void;
  nodeCount: number;
  edgeCount: number;
  truncated?: boolean;
  viewOptions: ViewOptions;
  onViewOptionsChange: (o: ViewOptions) => void;
  /** Active path selection, or null */
  selection: { name: string; upstream: number; downstream: number } | null;
  onClearSelection: () => void;
  /** With a selection: show only the path (true) or everything dimmed (false) */
  focusMode: boolean;
  onFocusModeChange: (v: boolean) => void;
}

const DIRECTIONS: { value: LineageDirection; icon: React.ElementType; labelKey: string }[] = [
  { value: 'upstream', icon: ArrowLeft, labelKey: 'data-catalog:lineage.toolbar.upstream' },
  { value: 'both', icon: ArrowLeftRight, labelKey: 'data-catalog:lineage.toolbar.both' },
  { value: 'downstream', icon: ArrowRight, labelKey: 'data-catalog:lineage.toolbar.downstream' },
];

export default function LineageToolbar({
  direction,
  onDirectionChange,
  maxDepth,
  onMaxDepthChange,
  detail,
  onDetailChange,
  nodeCount,
  edgeCount,
  truncated,
  viewOptions,
  onViewOptionsChange,
  selection,
  onClearSelection,
  focusMode,
  onFocusModeChange,
}: LineageToolbarProps) {
  const { t } = useTranslation(['data-catalog', 'common']);
  const hiddenCount =
    MODEL_LAYERS.filter((l) => !viewOptions.layers[l]).length
    + EDGE_FILTERS.filter((f) => !viewOptions.edges[f]).length;
  return (
    <div className="flex items-center gap-3 px-3 py-2 border-b bg-muted/30 rounded-t-md flex-wrap">
      {/* Direction toggle */}
      <div className="flex items-center rounded-md border bg-background p-0.5">
        {DIRECTIONS.map(({ value, icon: Icon, labelKey }) => (
          <Button
            key={value}
            variant="ghost"
            size="sm"
            className={cn(
              'h-7 px-2.5 text-xs rounded-sm',
              direction === value && 'bg-accent text-accent-foreground shadow-sm',
            )}
            onClick={() => onDirectionChange(value)}
          >
            <Icon className="h-3.5 w-3.5 mr-1" />
            {t(labelKey)}
          </Button>
        ))}
      </div>

      {/* Depth: relationship hops from the center, per direction (containment is free) */}
      <div className="flex items-center gap-1.5" title={t('data-catalog:lineage.toolbar.depthHint')}>
        <span className="text-xs text-muted-foreground">{t('data-catalog:lineage.toolbar.depth')}</span>
        <Select
          value={String(maxDepth)}
          onValueChange={(v) => onMaxDepthChange(Number(v))}
        >
          <SelectTrigger className="h-7 w-[4.5rem] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DEPTHS.map((d) => (
              <SelectItem key={d} value={String(d)}>
                {d === DEPTH_ALL ? t('data-catalog:lineage.toolbar.depthAll') : d}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Detail: which rows cards show */}
      <div className="flex items-center rounded-md border bg-background p-0.5" title={t('data-catalog:lineage.toolbar.detailHint')}>
        {LINEAGE_DETAILS.map((d) => (
          <Button
            key={d}
            variant="ghost"
            size="sm"
            className={cn(
              'h-7 px-2.5 text-xs rounded-sm',
              detail === d && 'bg-accent text-accent-foreground shadow-sm',
            )}
            onClick={() => onDetailChange(d)}
          >
            {t(`data-catalog:lineage.toolbar.detailLevels.${d}`)}
          </Button>
        ))}
      </div>

      {/* Entity count */}
      <Badge variant="secondary" className="text-xs font-normal">
        {t('data-catalog:lineage.toolbar.entitiesEdges', { nodes: nodeCount, edges: edgeCount })}
      </Badge>
      {truncated && (
        <Badge
          variant="outline"
          className="text-xs font-normal border-amber-500/50 text-amber-700 dark:text-amber-400"
          title={t('data-catalog:lineage.toolbar.truncatedHint')}
        >
          {t('data-catalog:lineage.toolbar.truncated')}
        </Badge>
      )}

      {/* View options: layers, edge kinds, labels */}
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs">
            <SlidersHorizontal className="h-3.5 w-3.5 mr-1" />
            {t('data-catalog:lineage.toolbar.view')}
            {hiddenCount > 0 && (
              <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[10px]">{hiddenCount}</Badge>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-3 space-y-3">
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {t('data-catalog:lineage.toolbar.layers')}
            </p>
            {MODEL_LAYERS.map((layer) => (
              <label key={layer} className="flex items-center gap-2 text-xs cursor-pointer">
                <Checkbox
                  checked={viewOptions.layers[layer]}
                  onCheckedChange={(c) => onViewOptionsChange({
                    ...viewOptions, layers: { ...viewOptions.layers, [layer]: c === true },
                  })}
                />
                {t(`common:businessLineage.layers.${layer}`)}
              </label>
            ))}
          </div>
          <div className="space-y-1.5 pt-2 border-t">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {t('data-catalog:lineage.toolbar.edges')}
            </p>
            {EDGE_FILTERS.map((f) => (
              <label key={f} className="flex items-center gap-2 text-xs cursor-pointer">
                <Checkbox
                  checked={viewOptions.edges[f]}
                  onCheckedChange={(c) => onViewOptionsChange({
                    ...viewOptions, edges: { ...viewOptions.edges, [f]: c === true },
                  })}
                />
                {t(`data-catalog:lineage.toolbar.edgeFilters.${f}`)}
              </label>
            ))}
          </div>
          <div className="space-y-2 pt-2 border-t">
            <div className="flex items-center justify-between">
              <span className="text-xs">{t('data-catalog:lineage.toolbar.edgeLabels')}</span>
              <Switch
                checked={viewOptions.showLabels}
                onCheckedChange={(c) => onViewOptionsChange({ ...viewOptions, showLabels: c })}
              />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs">{t('data-catalog:lineage.toolbar.minimap')}</span>
              <Switch
                checked={viewOptions.showMinimap}
                onCheckedChange={(c) => onViewOptionsChange({ ...viewOptions, showMinimap: c })}
              />
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full h-7 text-xs"
            onClick={() => onViewOptionsChange(DEFAULT_VIEW_OPTIONS)}
          >
            {t('data-catalog:lineage.toolbar.resetView')}
          </Button>
        </PopoverContent>
      </Popover>

      {/* Path selection summary */}
      {selection ? (
        <Badge variant="outline" className="h-7 gap-1.5 text-xs font-normal border-primary/40 bg-primary/5">
          <Crosshair className="h-3 w-3 text-primary" />
          <span className="max-w-[180px] truncate font-medium">{selection.name}</span>
          <span className="text-muted-foreground">
            {t('data-catalog:lineage.toolbar.pathCounts', { up: selection.upstream, down: selection.downstream })}
          </span>
          <button
            type="button"
            className="ml-1 flex items-center gap-1 rounded px-1 hover:bg-muted"
            onClick={() => onFocusModeChange(!focusMode)}
            title={focusMode ? t('data-catalog:lineage.toolbar.showContext') : t('data-catalog:lineage.toolbar.focusPath')}
          >
            {focusMode ? <Layers className="h-3 w-3" /> : <Focus className="h-3 w-3" />}
            {focusMode ? t('data-catalog:lineage.toolbar.showContext') : t('data-catalog:lineage.toolbar.focusPath')}
          </button>
          <button
            type="button"
            className="rounded hover:bg-muted p-0.5"
            onClick={onClearSelection}
            aria-label={t('data-catalog:lineage.toolbar.clearSelection')}
            title={t('data-catalog:lineage.toolbar.clearSelection')}
          >
            <X className="h-3 w-3" />
          </button>
        </Badge>
      ) : null}

    </div>
  );
}
