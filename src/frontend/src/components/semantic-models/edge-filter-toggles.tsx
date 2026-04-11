/**
 * EdgeFilterToggles — pill toggle buttons for filtering edge types in graph views.
 * Active types shown with primary fill, inactive with muted fill.
 */
import React from 'react';
import { cn } from '@/lib/utils';

interface EdgeType {
  type: string;
  count?: number;
}

interface EdgeFilterTogglesProps {
  edgeTypes: EdgeType[];
  visible: Set<string>;
  onToggle: (type: string) => void;
}

export const EdgeFilterToggles: React.FC<EdgeFilterTogglesProps> = ({
  edgeTypes,
  visible,
  onToggle,
}) => {
  return (
    <div
      className="flex flex-wrap gap-2 mt-3"
      data-testid="edge-filter-toggles"
    >
      {edgeTypes.map(({ type, count }) => {
        const isActive = visible.has(type);
        return (
          <button
            key={type}
            data-testid={`edge-toggle-${type}`}
            data-active={isActive}
            onClick={() => onToggle(type)}
            className={cn(
              "px-3.5 py-1 rounded-full border text-xs font-medium transition-all cursor-pointer",
              isActive
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-muted text-muted-foreground border-border hover:bg-muted/80"
            )}
          >
            {type}
            {count !== undefined && ` (${count})`}
          </button>
        );
      })}
    </div>
  );
};

export default EdgeFilterToggles;
