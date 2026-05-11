import React, { useRef, useEffect, useMemo, useCallback, useState } from 'react';
// @ts-expect-error - react-cytoscapejs doesn't have type declarations
import CytoscapeComponent from 'react-cytoscapejs';
import type { Core, ElementDefinition, LayoutOptions } from 'cytoscape';
import type { OntologyConcept } from '@/types/ontology';
import { resolveLabel } from '@/lib/ontology-utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ZoomIn, ZoomOut, Maximize, RotateCcw, Expand, Group, Ungroup, ChevronDown, Tag, Workflow, CircleDot, MoveHorizontal } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

// Domain colors from app.py
const DOMAIN_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD',
  '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9', '#F8B500', '#00CED1',
  '#FF7F50', '#9FE2BF', '#DE3163', '#40E0D0', '#CCCCFF', '#FFB347',
  '#77DD77', '#AEC6CF', '#FDFD96', '#836953', '#C23B22', '#779ECB', '#966FD6',
];

// Threshold for switching from badges to dropdown
const ROOT_BADGE_THRESHOLD = 10;

export type LayoutType = 'circle' | 'cose' | 'grid' | 'breadthfirst' | 'concentric';

// Props for the RootNodeFilter component
interface RootNodeFilterProps {
  rootNodes: OntologyConcept[];
  rootColors: Map<string, string>;
  hiddenRoots: Set<string>;
  onToggleRoot: (iri: string) => void;
  getRootDescendants: (rootIri: string) => Set<string>;
  selectedLanguage: string;
}

// Internal component for filtering root nodes - handles both badge and dropdown modes
const RootNodeFilter: React.FC<RootNodeFilterProps> = ({
  rootNodes,
  rootColors,
  hiddenRoots,
  onToggleRoot,
  getRootDescendants,
  selectedLanguage,
}) => {
  const visibleCount = rootNodes.filter(r => !hiddenRoots.has(r.iri)).length;
  const totalCount = rootNodes.length;

  // Show all roots
  const handleShowAll = () => {
    rootNodes.forEach(root => {
      if (hiddenRoots.has(root.iri)) {
        onToggleRoot(root.iri);
      }
    });
  };

  // Hide all roots
  const handleHideAll = () => {
    rootNodes.forEach(root => {
      if (!hiddenRoots.has(root.iri)) {
        onToggleRoot(root.iri);
      }
    });
  };

  // Badge mode: render clickable badge buttons (when <= threshold)
  if (rootNodes.length <= ROOT_BADGE_THRESHOLD) {
    return (
      <div className="flex flex-wrap gap-2 text-xs">
        {rootNodes.map(root => {
          const color = rootColors.get(root.iri) || '#64748b';
          const label = resolveLabel(root, selectedLanguage);
          const isHidden = hiddenRoots.has(root.iri);
          const descendants = getRootDescendants(root.iri);
          
          return (
            <button
              key={root.iri}
              onClick={() => onToggleRoot(root.iri)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md transition-all",
                "hover:shadow-md hover:scale-105",
                "bg-card border-2",
                isHidden ? "opacity-40 hover:opacity-60" : "opacity-100"
              )}
              style={{
                borderColor: color,
                backgroundColor: isHidden ? undefined : `${color}15`
              }}
              title={`${isHidden ? 'Show' : 'Hide'} ${label} (${descendants.size} concepts)`}
            >
              <div 
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className={cn(
                "font-medium text-foreground",
                isHidden && "line-through"
              )}>
                {label}
              </span>
              <span className="text-muted-foreground">
                ({descendants.size})
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  // Dropdown mode: render a popover with checkboxes (when > threshold)
  return (
    <div className="flex items-center gap-3 text-xs">
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-8 gap-2">
            <span className="font-medium">
              {visibleCount} of {totalCount} sources visible
            </span>
            <ChevronDown className="h-4 w-4 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
            <span className="text-sm font-medium">Filter Sources</span>
            <div className="flex gap-1">
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-7 px-2 text-xs"
                onClick={handleShowAll}
              >
                Show All
              </Button>
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-7 px-2 text-xs"
                onClick={handleHideAll}
              >
                Hide All
              </Button>
            </div>
          </div>
          <ScrollArea className="h-[300px]">
            <div className="p-2 space-y-1">
              {rootNodes.map(root => {
                const color = rootColors.get(root.iri) || '#64748b';
                const label = resolveLabel(root, selectedLanguage);
                const isVisible = !hiddenRoots.has(root.iri);
                const descendants = getRootDescendants(root.iri);
                
                return (
                  <label
                    key={root.iri}
                    className={cn(
                      "flex items-center gap-3 px-2 py-1.5 rounded-md cursor-pointer transition-colors",
                      "hover:bg-muted/50",
                      isVisible ? "opacity-100" : "opacity-60"
                    )}
                  >
                    <Checkbox
                      checked={isVisible}
                      onCheckedChange={() => onToggleRoot(root.iri)}
                    />
                    <div 
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span className={cn(
                      "flex-1 text-sm",
                      !isVisible && "line-through text-muted-foreground"
                    )}>
                      {label}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      ({descendants.size})
                    </span>
                  </label>
                );
              })}
            </div>
          </ScrollArea>
        </PopoverContent>
      </Popover>
      <span className="text-muted-foreground">
        Click legend items to toggle visibility
      </span>
    </div>
  );
};

interface KnowledgeGraphProps {
  concepts: OntologyConcept[];
  hiddenRoots: Set<string>;
  onToggleRoot: (rootIri: string) => void;
  onNodeClick: (concept: OntologyConcept) => void;
  showRootBadges?: boolean;
  selectedLanguage?: string;
}

interface GraphData {
  elements: ElementDefinition[];
  rootNodes: OntologyConcept[];
  rootColors: Map<string, string>;
  getRootDescendants: (rootIri: string) => Set<string>;
}

export const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({
  concepts,
  hiddenRoots,
  onToggleRoot,
  onNodeClick,
  showRootBadges = true,
  selectedLanguage = 'en',
}) => {
  const cyRef = useRef<Core | null>(null);
  const fullscreenCyRef = useRef<Core | null>(null);
  const layoutRef = useRef<{ stop: () => void } | null>(null);
  const initialLayoutDoneRef = useRef(false);
  const fullscreenInitialLayoutDoneRef = useRef(false);
  const [layout, setLayout] = useState<LayoutType>('cose');
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showDomainBoxes, setShowDomainBoxes] = useState(true);
  const [showNodeLabels, setShowNodeLabels] = useState(false);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [nodeSize, setNodeSize] = useState(24);
  const [spacing, setSpacing] = useState(80);
  
  // Handler for toggling domain boxes
  const handleToggleDomainBoxes = useCallback(() => {
    setShowDomainBoxes(prev => !prev);
  }, []);

  // Reset layout done ref when showDomainBoxes changes (component will remount)
  useEffect(() => {
    initialLayoutDoneRef.current = false;
    fullscreenInitialLayoutDoneRef.current = false;
  }, [showDomainBoxes]);

  // Detect dark mode
  useEffect(() => {
    const checkDarkMode = () => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    };
    checkDarkMode();
    
    // Watch for theme changes
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    
    return () => observer.disconnect();
  }, []);

  // Cleanup cytoscape and layouts on unmount
  useEffect(() => {
    return () => {
      // Stop any running layout
      if (layoutRef.current) {
        layoutRef.current.stop();
        layoutRef.current = null;
      }
      // Remove all listeners from cytoscape
      if (cyRef.current) {
        cyRef.current.removeAllListeners();
        cyRef.current = null;
      }
    };
  }, []);

  // Transform concepts to Cytoscape elements
  const graphData = useMemo((): GraphData => {
    // Include classes, concepts, and properties (matching the tree view)
    const visibleConcepts = concepts.filter(
      (c) => c.concept_type === 'class' || c.concept_type === 'concept' || c.concept_type === 'property'
    );

    // Build concept map for fast lookups
    const conceptMap = new Map(visibleConcepts.map(c => [c.iri, c]));

    // Identify root nodes: no parents, OR all parents are outside the visible set
    const rootNodes = visibleConcepts.filter((c) => {
      if (!c.parent_concepts || c.parent_concepts.length === 0) return true;
      return c.parent_concepts.every(parentIri => !conceptMap.has(parentIri));
    });

    // Generate colors for each root
    const rootColors = new Map<string, string>();
    rootNodes.forEach((root, index) => {
      rootColors.set(root.iri, DOMAIN_COLORS[index % DOMAIN_COLORS.length]);
    });

    const nodeToRoot = new Map<string, string>();

    const findRoot = (iri: string, visited = new Set<string>()): string | null => {
      if (visited.has(iri)) return null;
      visited.add(iri);
      
      const concept = conceptMap.get(iri);
      if (!concept) return null;
      
      if (!concept.parent_concepts || concept.parent_concepts.length === 0) {
        return iri;
      }

      // All parents external → this is a root in the visible set
      if (concept.parent_concepts.every(p => !conceptMap.has(p))) {
        return iri;
      }
      
      for (const parentIri of concept.parent_concepts) {
        const root = findRoot(parentIri, visited);
        if (root) return root;
      }
      
      return null;
    };

    visibleConcepts.forEach(concept => {
      const root = findRoot(concept.iri);
      if (root) {
        nodeToRoot.set(concept.iri, root);
      }
    });

    // Get all descendants of a root (including the root itself)
    const getRootDescendants = (rootIri: string): Set<string> => {
      const descendants = new Set<string>([rootIri]);
      const queue = [rootIri];
      
      while (queue.length > 0) {
        const currentIri = queue.shift()!;
        const concept = conceptMap.get(currentIri);
        
        if (concept?.child_concepts) {
          concept.child_concepts.forEach(childIri => {
            if (!descendants.has(childIri) && conceptMap.has(childIri)) {
              descendants.add(childIri);
              queue.push(childIri);
            }
          });
        }
      }
      
      return descendants;
    };

    // Filter nodes based on hidden roots
    const visibleNodeIris = new Set<string>();
    rootNodes.forEach(root => {
      if (!hiddenRoots.has(root.iri)) {
        const descendants = getRootDescendants(root.iri);
        descendants.forEach(iri => visibleNodeIris.add(iri));
      }
    });

    const filteredConcepts = visibleConcepts.filter(c => visibleNodeIris.has(c.iri));

    // Build elements array
    const elements: ElementDefinition[] = [];

    // Add domain compound nodes (parents) if enabled
    if (showDomainBoxes) {
      rootNodes.forEach(root => {
        if (!hiddenRoots.has(root.iri)) {
          elements.push({
            data: {
              id: `domain_${root.iri}`,
              label: resolveLabel(root, selectedLanguage),
              type: 'domain',
              color: rootColors.get(root.iri),
            },
            classes: 'domain-node',
          });
        }
      });
    }

    // Add concept nodes
    filteredConcepts.forEach(concept => {
      const rootIri = nodeToRoot.get(concept.iri) || concept.iri;
      const color = rootColors.get(rootIri) || '#64748b';
      
      const isProperty = concept.concept_type === 'property';
      const nodeData: ElementDefinition = {
        data: {
          id: concept.iri,
          label: resolveLabel(concept, selectedLanguage),
          type: 'concept',
          conceptType: concept.concept_type,
          color: color,
          conceptData: concept,
          sourceContext: concept.source_context,
          childCount: concept.child_concepts?.length || 0,
          parentCount: concept.parent_concepts?.length || 0,
        },
        classes: isProperty ? 'concept-node property-node' : 'concept-node',
      };

      // Add parent reference for compound nodes
      if (showDomainBoxes && !hiddenRoots.has(rootIri)) {
        nodeData.data.parent = `domain_${rootIri}`;
      }

      elements.push(nodeData);
    });

    // Add edges for parent-child relationships
    filteredConcepts.forEach(concept => {
      concept.child_concepts.forEach(childIri => {
        const childExists = filteredConcepts.some(c => c.iri === childIri);
        if (childExists) {
          elements.push({
            data: {
              id: `edge_${concept.iri}_${childIri}`,
              source: concept.iri,
              target: childIri,
              // Generic hierarchy relation; future: derive from RDF predicate when typed edges land.
              label: 'subClassOf',
            },
            classes: 'hierarchy-edge',
          });
        }
      });
    });

    return { elements, rootNodes, rootColors, getRootDescendants };
  }, [concepts, hiddenRoots, showDomainBoxes, selectedLanguage]);

  // Create stylesheet based on dark mode
  // Cytoscape stylesheet - using any[] due to complex type definitions
  const stylesheet = useMemo((): any[] => {
    const textColor = isDarkMode ? '#f1f5f9' : '#1f2937';
    const textOutlineColor = isDarkMode ? 'rgba(0,0,0,0.8)' : 'rgba(255,255,255,0.8)';
    const edgeColor = isDarkMode ? '#71717a' : '#64748b';
    const domainBgOpacity = isDarkMode ? 0.15 : 0.12;
    
    return [
      // Base node styles
      {
        selector: 'node',
        style: {
          'font-family': 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
          'font-size': 11,
          'font-weight': 500,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 8,
          'color': textColor,
          'text-outline-width': 2,
          'text-outline-color': textOutlineColor,
        },
      },
      // Concept nodes
      {
        selector: '.concept-node',
        style: {
          'shape': 'ellipse',
          'width': nodeSize,
          'height': nodeSize,
          'background-color': 'data(color)',
          'border-width': 2,
          'border-color': isDarkMode ? 'rgba(30,30,30,0.8)' : 'rgba(255,255,255,0.9)',
          'label': showNodeLabels ? 'data(label)' : '',
        },
      },
      // Concept node hover
      {
        selector: '.concept-node.hover',
        style: {
          'width': nodeSize * 1.33,
          'height': nodeSize * 1.33,
          'border-width': 3,
          'label': 'data(label)',
          'font-size': 13,
          'font-weight': 600,
          'z-index': 999,
        },
      },
      // Concept node selected
      {
        selector: '.concept-node:selected',
        style: {
          'width': nodeSize * 1.67,
          'height': nodeSize * 1.67,
          'border-width': 4,
          'border-color': '#FFD700',
          'label': 'data(label)',
          'font-size': 14,
          'font-weight': 700,
        },
      },
      // Property nodes (diamond shape to distinguish from class/concept ellipses)
      {
        selector: '.property-node',
        style: {
          'shape': 'diamond',
          'width': nodeSize * 0.83,
          'height': nodeSize * 0.83,
        },
      },
      {
        selector: '.property-node.hover',
        style: {
          'width': nodeSize * 1.17,
          'height': nodeSize * 1.17,
        },
      },
      {
        selector: '.property-node:selected',
        style: {
          'width': nodeSize * 1.5,
          'height': nodeSize * 1.5,
        },
      },
      // Domain compound nodes (no label to avoid redundancy with contained nodes)
      {
        selector: '.domain-node',
        style: {
          'shape': 'round-rectangle',
          'background-color': 'data(color)',
          'background-opacity': domainBgOpacity,
          'border-width': 2,
          'border-color': 'data(color)',
          'border-opacity': 0.4,
          'label': '',
          'padding': 30,
        },
      },
      // Edges
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': edgeColor,
          'target-arrow-color': edgeColor,
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.8,
          'curve-style': 'bezier',
          'opacity': 0.6,
          'label': showEdgeLabels ? 'data(label)' : '',
          'font-size': 9,
          'font-family': 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
          'color': textColor,
          'text-outline-width': 1,
          'text-outline-color': textOutlineColor,
          'text-rotation': 'autorotate',
          'text-background-opacity': 0,
        },
      },
      // Edge hover
      {
        selector: 'edge.hover',
        style: {
          'width': 2.5,
          'opacity': 1,
          'line-color': '#FFD700',
          'target-arrow-color': '#FFD700',
        },
      },
    ];
  }, [isDarkMode, showNodeLabels, showEdgeLabels, nodeSize]);

  // Layout configurations
  const getLayoutConfig = useCallback((layoutName: LayoutType, animate = true): LayoutOptions => {
    const baseConfig = {
      fit: true,
      padding: 60,
      animate: animate,
      animationDuration: animate ? 500 : 0,
    };

    // Scale layout-level spacing knobs from the single user slider (default 80).
    const spacingFactor = (spacing / 80) * 1.5;

    switch (layoutName) {
      case 'circle':
        return {
          name: 'circle',
          ...baseConfig,
          avoidOverlap: true,
          spacingFactor,
        };
      case 'cose':
        return {
          name: 'cose',
          ...baseConfig,
          idealEdgeLength: () => spacing,
          nodeOverlap: 20,
          // Preserves 80 → 400000 ratio so default behavior matches pre-slider.
          nodeRepulsion: () => spacing * 5000,
          edgeElasticity: () => 100,
          nestingFactor: 5,
          gravity: 80,
          numIter: animate ? 1000 : 500,
          initialTemp: 200,
          coolingFactor: 0.95,
          minTemp: 1.0,
          randomize: false,
        };
      case 'grid':
        return {
          name: 'grid',
          ...baseConfig,
          avoidOverlap: true,
          avoidOverlapPadding: Math.max(4, spacing / 8),
          condense: false,
        };
      case 'breadthfirst':
        return {
          name: 'breadthfirst',
          ...baseConfig,
          directed: true,
          spacingFactor,
          avoidOverlap: true,
          maximal: false,
        };
      case 'concentric':
        return {
          name: 'concentric',
          ...baseConfig,
          avoidOverlap: true,
          minNodeSpacing: Math.max(8, spacing / 4),
          concentric: (node: any) => node.degree(),
          levelWidth: () => 2,
        };
      default:
        return { name: 'circle', ...baseConfig };
    }
  }, [spacing]);

  // Wire up event handlers
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Clear existing handlers
    cy.removeAllListeners();

    // Node click handler
    cy.on('tap', 'node.concept-node', (evt) => {
      const nodeData = evt.target.data();
      if (nodeData.conceptData) {
        onNodeClick(nodeData.conceptData);
      }
    });

    // Hover handlers
    cy.on('mouseover', 'node.concept-node', (evt) => {
      evt.target.addClass('hover');
    });

    cy.on('mouseout', 'node.concept-node', (evt) => {
      evt.target.removeClass('hover');
    });

    cy.on('mouseover', 'edge', (evt) => {
      evt.target.addClass('hover');
    });

    cy.on('mouseout', 'edge', (evt) => {
      evt.target.removeClass('hover');
    });

    // Cleanup
    return () => {
      cy.removeAllListeners();
    };
  }, [onNodeClick]);

  // Run layout when layout type changes or when elements change
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    
    // Small delay to ensure cytoscape is fully initialized
    const timeoutId = setTimeout(() => {
      const currentCy = cyRef.current;
      if (!currentCy || currentCy.elements().length === 0) return;

      // Stop any running layout first
      if (layoutRef.current) {
        layoutRef.current.stop();
      }

      const layoutConfig = getLayoutConfig(layout, true);
      const layoutInstance = currentCy.layout(layoutConfig);
      layoutRef.current = layoutInstance;
      layoutInstance.run();
    }, 50);

    // Cleanup: stop layout on unmount or before re-running
    return () => {
      clearTimeout(timeoutId);
      if (layoutRef.current) {
        layoutRef.current.stop();
        layoutRef.current = null;
      }
    };
  }, [layout, getLayoutConfig, graphData.elements.length]);

  // Control handlers
  const handleFit = () => {
    cyRef.current?.fit(undefined, 60);
  };

  const handleZoomIn = () => {
    const cy = cyRef.current;
    if (cy) {
      cy.zoom(cy.zoom() * 1.3);
    }
  };

  const handleZoomOut = () => {
    const cy = cyRef.current;
    if (cy) {
      cy.zoom(cy.zoom() / 1.3);
    }
  };

  const handleReset = () => {
    const cy = cyRef.current;
    if (cy) {
      // Stop any running layout first
      if (layoutRef.current) {
        layoutRef.current.stop();
      }
      const layoutConfig = getLayoutConfig(layout);
      const layoutInstance = cy.layout(layoutConfig);
      layoutRef.current = layoutInstance;
      layoutInstance.run();
    }
  };

  return (
    <div className="h-full flex flex-col border rounded-lg bg-background overflow-hidden">
      {/* Legend with toggleable roots - shown when Group by Source is OFF */}
      {showRootBadges && (
        <div className="px-6 py-3 border-b bg-muted/30">
          <RootNodeFilter
            rootNodes={graphData.rootNodes}
            rootColors={graphData.rootColors}
            hiddenRoots={hiddenRoots}
            onToggleRoot={onToggleRoot}
            getRootDescendants={graphData.getRootDescendants}
            selectedLanguage={selectedLanguage}
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="px-4 py-2 border-b flex items-center justify-between bg-muted/20">
        <div className="flex items-center gap-2">
          <Select value={layout} onValueChange={(v) => setLayout(v as LayoutType)}>
            <SelectTrigger className="w-[160px] h-8">
              <SelectValue placeholder="Layout" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="circle">Circular</SelectItem>
              <SelectItem value="cose">Force-Directed</SelectItem>
              <SelectItem value="grid">Grid</SelectItem>
              <SelectItem value="breadthfirst">Hierarchical</SelectItem>
              <SelectItem value="concentric">Concentric</SelectItem>
            </SelectContent>
          </Select>
          
          <Button
            variant={showDomainBoxes ? "secondary" : "ghost"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={handleToggleDomainBoxes}
            title={showDomainBoxes ? "Hide domain groups" : "Show domain groups"}
          >
            {showDomainBoxes ? <Group className="h-4 w-4" /> : <Ungroup className="h-4 w-4" />}
            <span>Groups</span>
          </Button>

          <Button
            variant={showNodeLabels ? "secondary" : "ghost"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={() => setShowNodeLabels(prev => !prev)}
            title={showNodeLabels ? "Hide node labels" : "Show node labels"}
          >
            <Tag className="h-4 w-4" />
            <span>Node labels</span>
          </Button>

          <Button
            variant={showEdgeLabels ? "secondary" : "ghost"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={() => setShowEdgeLabels(prev => !prev)}
            title={showEdgeLabels ? "Hide edge labels" : "Show edge labels"}
          >
            <Workflow className="h-4 w-4" />
            <span>Edge labels</span>
          </Button>

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 gap-1.5" title="Node size">
                <CircleDot className="h-4 w-4" />
                <span>Size</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-3" align="start">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Node size</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground tabular-nums w-6 text-right">{nodeSize}</span>
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setNodeSize(24)}>
                    Reset
                  </Button>
                </div>
              </div>
              <Slider
                value={[nodeSize]}
                onValueChange={(v) => setNodeSize(v[0])}
                min={12}
                max={48}
                step={2}
                aria-label="Node size"
              />
            </PopoverContent>
          </Popover>

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 gap-1.5" title="Node spacing">
                <MoveHorizontal className="h-4 w-4" />
                <span>Spacing</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-3" align="start">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Spacing</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">{spacing}</span>
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setSpacing(80)}>
                    Reset
                  </Button>
                </div>
              </div>
              <Slider
                value={[spacing]}
                onValueChange={(v) => setSpacing(v[0])}
                min={40}
                max={240}
                step={10}
                aria-label="Node spacing"
              />
              <p className="text-[10px] text-muted-foreground mt-2">
                Re-runs layout. Affects edge length and node repulsion.
              </p>
            </PopoverContent>
          </Popover>

          <Badge variant="secondary" className="text-xs">
            {graphData.elements.filter(e => e.classes?.includes('concept-node')).length} concepts
          </Badge>
        </div>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleZoomOut} title="Zoom Out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleZoomIn} title="Zoom In">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleFit} title="Fit to View">
            <Maximize className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleReset} title="Reset Layout">
            <RotateCcw className="h-4 w-4" />
          </Button>
          <div className="w-px h-6 bg-border mx-1" />
          <Button 
            variant="ghost" 
            size="icon" 
            className="h-8 w-8" 
            onClick={() => setIsFullscreen(true)} 
            title="Open Fullscreen"
          >
            <Expand className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Graph */}
      <div className="flex-1 relative" style={{ minHeight: 0 }}>
        <CytoscapeComponent
          key={`graph-${showDomainBoxes}`}
          cy={(cy: Core) => {
            cyRef.current = cy;
            // Run initial layout only once after mounting
            if (!initialLayoutDoneRef.current) {
              initialLayoutDoneRef.current = true;
              setTimeout(() => {
                if (cyRef.current && cyRef.current.elements().length > 0) {
                  const layoutConfig = getLayoutConfig(layout, true);
                  cyRef.current.layout(layoutConfig).run();
                }
              }, 50);
            }
          }}
          elements={graphData.elements}
          stylesheet={stylesheet}
          layout={{ name: 'preset' }}
          style={{ width: '100%', height: '100%' }}
          minZoom={0.1}
          maxZoom={4}
          wheelSensitivity={0.3}
          boxSelectionEnabled={false}
          autounselectify={false}
          userPanningEnabled={true}
          userZoomingEnabled={true}
        />
      </div>

      {/* Fullscreen Modal */}
      <Dialog open={isFullscreen} onOpenChange={setIsFullscreen}>
        <DialogContent className="max-w-[95vw] w-[95vw] h-[95vh] max-h-[95vh] p-0 flex flex-col">
          <DialogHeader className="px-6 py-4 border-b flex-shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <DialogTitle className="text-xl font-semibold">View Graph</DialogTitle>
                <DialogDescription className="sr-only">
                  Fullscreen view of the concept graph visualization
                </DialogDescription>
              </div>
              <div className="flex items-center gap-2">
                <Select value={layout} onValueChange={(v) => setLayout(v as LayoutType)}>
                  <SelectTrigger className="w-[160px] h-8">
                    <SelectValue placeholder="Layout" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="circle">Circular</SelectItem>
                    <SelectItem value="cose">Force-Directed</SelectItem>
                    <SelectItem value="grid">Grid</SelectItem>
                    <SelectItem value="breadthfirst">Hierarchical</SelectItem>
                    <SelectItem value="concentric">Concentric</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant={showDomainBoxes ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={handleToggleDomainBoxes}
                  title={showDomainBoxes ? "Hide domain groups" : "Show domain groups"}
                >
                  {showDomainBoxes ? <Group className="h-4 w-4" /> : <Ungroup className="h-4 w-4" />}
                  <span>Groups</span>
                </Button>
                <Button
                  variant={showNodeLabels ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={() => setShowNodeLabels(prev => !prev)}
                  title={showNodeLabels ? "Hide node labels" : "Show node labels"}
                >
                  <Tag className="h-4 w-4" />
                  <span>Node labels</span>
                </Button>
                <Button
                  variant={showEdgeLabels ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={() => setShowEdgeLabels(prev => !prev)}
                  title={showEdgeLabels ? "Hide edge labels" : "Show edge labels"}
                >
                  <Workflow className="h-4 w-4" />
                  <span>Edge labels</span>
                </Button>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-8 gap-1.5" title="Node size">
                      <CircleDot className="h-4 w-4" />
                      <span>Size</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-3" align="end">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium">Node size</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground tabular-nums w-6 text-right">{nodeSize}</span>
                        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setNodeSize(24)}>
                          Reset
                        </Button>
                      </div>
                    </div>
                    <Slider
                      value={[nodeSize]}
                      onValueChange={(v) => setNodeSize(v[0])}
                      min={12}
                      max={48}
                      step={2}
                      aria-label="Node size"
                    />
                  </PopoverContent>
                </Popover>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-8 gap-1.5" title="Node spacing">
                      <MoveHorizontal className="h-4 w-4" />
                      <span>Spacing</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-3" align="end">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium">Spacing</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">{spacing}</span>
                        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setSpacing(80)}>
                          Reset
                        </Button>
                      </div>
                    </div>
                    <Slider
                      value={[spacing]}
                      onValueChange={(v) => setSpacing(v[0])}
                      min={40}
                      max={240}
                      step={10}
                      aria-label="Node spacing"
                    />
                    <p className="text-[10px] text-muted-foreground mt-2">
                      Re-runs layout. Affects edge length and node repulsion.
                    </p>
                  </PopoverContent>
                </Popover>
                <Badge variant="secondary" className="text-xs">
                  {graphData.elements.filter(e => e.classes?.includes('concept-node')).length} concepts
                </Badge>
              </div>
            </div>
          </DialogHeader>
          
          {/* Legend in modal - shown when Group by Source is OFF */}
          {showRootBadges && (
            <div className="px-6 py-3 border-b bg-muted/30 flex-shrink-0">
              <RootNodeFilter
                rootNodes={graphData.rootNodes}
                rootColors={graphData.rootColors}
                hiddenRoots={hiddenRoots}
                onToggleRoot={onToggleRoot}
                getRootDescendants={graphData.getRootDescendants}
                selectedLanguage={selectedLanguage}
              />
            </div>
          )}

          {/* Fullscreen Graph */}
          <div className="flex-1 relative">
            {isFullscreen && (
              <CytoscapeComponent
                key={`fullscreen-graph-${showDomainBoxes}`}
                cy={(cy: Core) => {
                  fullscreenCyRef.current = cy;
                  // Run layout only once after mounting in fullscreen
                  if (!fullscreenInitialLayoutDoneRef.current) {
                    fullscreenInitialLayoutDoneRef.current = true;
                    const timeoutId = setTimeout(() => {
                      if (fullscreenCyRef.current && fullscreenCyRef.current.elements().length > 0) {
                        const layoutConfig = getLayoutConfig(layout, true);
                        fullscreenCyRef.current.layout(layoutConfig).run();
                      }
                    }, 150);
                    // Store cleanup
                    cy.scratch('_layoutTimeout', timeoutId);
                  }
                }}
                elements={graphData.elements}
                stylesheet={stylesheet}
                layout={{ name: 'preset' }}
                style={{ width: '100%', height: '100%' }}
                minZoom={0.05}
                maxZoom={5}
                wheelSensitivity={0.3}
                boxSelectionEnabled={false}
                autounselectify={false}
                userPanningEnabled={true}
                userZoomingEnabled={true}
              />
            )}
          </div>

          {/* Fullscreen toolbar */}
          <div className="px-4 py-2 border-t flex items-center justify-between bg-muted/20 flex-shrink-0">
            <div className="text-sm text-muted-foreground">
              Click on nodes to select concepts. Use scroll to zoom, drag to pan.
            </div>
            <div className="flex items-center gap-1">
              <Button 
                variant="ghost" 
                size="icon" 
                className="h-8 w-8" 
                onClick={() => fullscreenCyRef.current?.zoom((fullscreenCyRef.current?.zoom() || 1) / 1.3)} 
                title="Zoom Out"
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="icon" 
                className="h-8 w-8" 
                onClick={() => fullscreenCyRef.current?.zoom((fullscreenCyRef.current?.zoom() || 1) * 1.3)} 
                title="Zoom In"
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="icon" 
                className="h-8 w-8" 
                onClick={() => fullscreenCyRef.current?.fit(undefined, 60)} 
                title="Fit to View"
              >
                <Maximize className="h-4 w-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="icon" 
                className="h-8 w-8" 
                onClick={() => {
                  const cy = fullscreenCyRef.current;
                  if (cy) {
                    const layoutConfig = getLayoutConfig(layout, true);
                    cy.layout(layoutConfig).run();
                  }
                }} 
                title="Reset Layout"
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default KnowledgeGraph;

