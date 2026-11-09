/**
 * Background band for a model-layer lane (Business, Delivery, …) with its title.
 * Rendered behind cards; not interactive.
 */

import { memo } from 'react';
import type { NodeProps } from 'reactflow';

export interface LaneBandData {
  label: string;
  width: number;
  height: number;
  /** Alternate shading so adjacent lanes stay distinguishable */
  shaded: boolean;
}

const LineageLaneBand = memo(({ data }: NodeProps<LaneBandData>) => (
  <div
    className={`rounded-xl border border-dashed border-border/60 ${data.shaded ? 'bg-muted/40 dark:bg-muted/20' : 'bg-muted/15 dark:bg-muted/10'}`}
    style={{ width: data.width, height: data.height, pointerEvents: 'none' }}
  >
    <div className="px-4 pt-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground/80">
      {data.label}
    </div>
  </div>
));

LineageLaneBand.displayName = 'LineageLaneBand';

export default LineageLaneBand;
