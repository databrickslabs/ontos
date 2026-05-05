import React from 'react';
import type { OntologyConcept } from '@/types/ontology';
import { KnowledgeGraph } from '@/components/semantic-models/knowledge-graph';

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
  return (
    <div className="h-[800px] flex flex-col">
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
