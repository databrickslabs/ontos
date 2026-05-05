import React from 'react';
import { X } from 'lucide-react';
import type { OntologyConcept } from '@/types/ontology';
import { KnowledgeGraph } from '@/components/semantic-models/knowledge-graph';
import { resolveLabel } from '@/lib/ontology-utils';

interface GraphTabProps {
  concepts: OntologyConcept[];
  hiddenRoots: Set<string>;
  onToggleRoot: (rootIri: string) => void;
  onNodeClick: (concept: OntologyConcept) => void;
  onNodeRightClick?: (concept: OntologyConcept, event: MouseEvent) => void;
  onBackgroundRightClick?: (event: MouseEvent) => void;
  linkDrawSource?: string | null;
  onLinkDraw?: (source: OntologyConcept, target: OntologyConcept) => void;
  onLinkDrawCancel?: () => void;
  showRootBadges?: boolean;
  selectedLanguage?: string;
}

export const GraphTab: React.FC<GraphTabProps> = ({
  concepts,
  hiddenRoots,
  onToggleRoot,
  onNodeClick,
  onNodeRightClick,
  onBackgroundRightClick,
  linkDrawSource,
  onLinkDraw,
  onLinkDrawCancel,
  showRootBadges = true,
  selectedLanguage = 'en',
}) => {
  const sourceConcept = linkDrawSource
    ? concepts.find((c) => c.iri === linkDrawSource)
    : null;

  return (
    <div className="h-[800px] flex flex-col relative">
      {/* Link-draw mode banner: shows when user picks "Create Link From..." in the
          context menu. Mirrors the pink dashed-ring source highlight applied by
          knowledge-graph.tsx via the .link-draw-source class. */}
      {sourceConcept && (
        <div
          role="status"
          aria-live="polite"
          className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3 rounded-md border border-pink-300 bg-pink-50 px-4 py-2 text-sm text-pink-900 shadow-sm"
        >
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-pink-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-pink-500" />
          </span>
          <span>
            Click a target node to create link from{' '}
            <strong>{resolveLabel(sourceConcept, selectedLanguage)}</strong>
          </span>
          <button
            type="button"
            onClick={onLinkDrawCancel}
            aria-label="Cancel link draw"
            className="ml-1 rounded p-0.5 text-pink-700 hover:bg-pink-100 hover:text-pink-900"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {/* Graph */}
      <div className="flex-1 min-h-0">
        <KnowledgeGraph
          concepts={concepts}
          hiddenRoots={hiddenRoots}
          onToggleRoot={onToggleRoot}
          onNodeClick={onNodeClick}
          onNodeRightClick={onNodeRightClick}
          onBackgroundRightClick={onBackgroundRightClick}
          linkDrawSource={linkDrawSource}
          onLinkDraw={onLinkDraw}
          onLinkDrawCancel={onLinkDrawCancel}
          showRootBadges={showRootBadges}
          selectedLanguage={selectedLanguage}
        />
      </div>
    </div>
  );
};
