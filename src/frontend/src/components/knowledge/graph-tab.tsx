import React from 'react';
import type { OntologyConcept } from '@/types/ontology';
import { KnowledgeGraph } from '@/components/semantic-models/knowledge-graph';

interface GraphTabProps {
  concepts: OntologyConcept[];
  hiddenRoots: Set<string>;
  onToggleRoot: (rootIri: string) => void;
  onNodeClick: (concept: OntologyConcept) => void;
  showRootBadges?: boolean;
  selectedLanguage?: string;
}

export const GraphTab: React.FC<GraphTabProps> = ({
  concepts,
  hiddenRoots,
  onToggleRoot,
  onNodeClick,
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
          showRootBadges={showRootBadges}
          selectedLanguage={selectedLanguage}
        />
      </div>
    </div>
  );
};
