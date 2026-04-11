/**
 * Knowledge graph using react-force-graph-2d.
 * Canvas-rendered with d3-force physics, zoom/pan, hover tooltips, domain auto-coloring.
 * Supports click-to-expand: clicking a concept node fetches and reveals its children.
 *
 * Replaces the previous Cytoscape-based implementation with a lighter, more
 * performant canvas renderer that handles 500+ nodes smoothly.
 */
import React, { useRef, useCallback, useState, useMemo, useEffect } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import type { OntologyConcept } from '@/types/ontology';
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
  ZoomIn, ZoomOut, Maximize, RotateCcw, Expand, Tag, ChevronDown, X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

// Domain colors — extended palette for multi-source ontologies
const DOMAIN_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899',
  '#06b6d4', '#84cc16', '#f97316', '#6366f1', '#14b8a6', '#e11d48',
  '#0ea5e9', '#22c55e', '#eab308', '#a855f7', '#d946ef', '#f43f5e',
  '#0891b2', '#65a30d', '#ea580c', '#7c3aed', '#db2777', '#dc2626',
  '#2563eb',
];

// Threshold for switching from badges to dropdown
const ROOT_BADGE_THRESHOLD = 10;

// ---- Predicate edge styles (W3C RDF vocabulary) ----

interface PredicateStyle {
  color: string;
  darkColor: string;
  width: number;
  dash?: number[];
  label: string;
}

const PREDICATE_STYLES: Record<string, PredicateStyle> = {
  'skos:broader':        { color: '#3b82f6', darkColor: '#60a5fa', width: 1.5, label: 'skos:broader' },
  'skos:narrower':       { color: '#3b82f6', darkColor: '#60a5fa', width: 1.5, label: 'skos:narrower' },
  'rdfs:subClassOf':     { color: '#10b981', darkColor: '#34d399', width: 1.5, label: 'rdfs:subClassOf' },
  'rdfs:subPropertyOf':  { color: '#f59e0b', darkColor: '#fbbf24', width: 1.0, label: 'rdfs:subPropertyOf' },
  'owl:equivalentClass': { color: '#8b5cf6', darkColor: '#a78bfa', width: 1.0, dash: [4, 2], label: 'owl:equivalentClass' },
  'rdf:type':            { color: '#64748b', darkColor: '#94a3b8', width: 0.8, dash: [2, 2], label: 'rdf:type' },
  'skos:related':        { color: '#ec4899', darkColor: '#f472b6', width: 1.0, dash: [6, 3], label: 'skos:related' },
  'semantic':            { color: '#3b82f6', darkColor: '#60a5fa', width: 1.5, label: 'Semantic Link' },
  'ontology':            { color: '#cbd5e1', darkColor: '#475569', width: 0.5, label: 'Hierarchy' },
};

// ---- Types ----

interface ForceGraphNode {
  id: string;
  label: string;
  group: 'concept' | 'product' | 'property' | 'scheme';
  color: string;
  conceptData?: OntologyConcept;
  parentExpansion?: string;
  notation?: string;
  // d3-force adds these at runtime
  x?: number;
  y?: number;
}

interface ForceGraphLink {
  source: string | ForceGraphNode;
  target: string | ForceGraphNode;
  type: string; // Predicate label (e.g. "skos:broader") or fallback "ontology"/"semantic"
}

interface ForceGraphData {
  nodes: ForceGraphNode[];
  links: ForceGraphLink[];
}

// ---- Root Node Filter (reused from previous implementation) ----

interface RootNodeFilterProps {
  rootNodes: OntologyConcept[];
  rootColors: Map<string, string>;
  hiddenRoots: Set<string>;
  onToggleRoot: (iri: string) => void;
  getRootDescendants: (rootIri: string) => Set<string>;
}

const RootNodeFilter: React.FC<RootNodeFilterProps> = ({
  rootNodes,
  rootColors,
  hiddenRoots,
  onToggleRoot,
  getRootDescendants,
}) => {
  const visibleCount = rootNodes.filter(r => !hiddenRoots.has(r.iri)).length;
  const totalCount = rootNodes.length;

  const handleShowAll = () => {
    rootNodes.forEach(root => {
      if (hiddenRoots.has(root.iri)) onToggleRoot(root.iri);
    });
  };

  const handleHideAll = () => {
    rootNodes.forEach(root => {
      if (!hiddenRoots.has(root.iri)) onToggleRoot(root.iri);
    });
  };

  if (rootNodes.length <= ROOT_BADGE_THRESHOLD) {
    return (
      <div className="flex flex-wrap gap-2 text-xs">
        {rootNodes.map(root => {
          const color = rootColors.get(root.iri) || '#64748b';
          const label = root.label || root.iri.split(/[/#]/).pop() || 'Unknown';
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
                backgroundColor: isHidden ? undefined : `${color}15`,
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
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleShowAll}>
                Show All
              </Button>
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleHideAll}>
                Hide All
              </Button>
            </div>
          </div>
          <ScrollArea className="h-[300px]">
            <div className="p-2 space-y-1">
              {rootNodes.map(root => {
                const color = rootColors.get(root.iri) || '#64748b';
                const label = root.label || root.iri.split(/[/#]/).pop() || 'Unknown';
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

// ---- Exported Props (unchanged from previous API) ----

export interface KnowledgeGraphProps {
  concepts: OntologyConcept[];
  hiddenRoots: Set<string>;
  onToggleRoot: (rootIri: string) => void;
  onNodeClick: (concept: OntologyConcept) => void;
  onNodeRightClick?: (concept: OntologyConcept, event: MouseEvent) => void;
  onBackgroundRightClick?: (event: MouseEvent) => void;
  /** Source concept IRI for link draw mode — highlights the source and changes click behavior */
  linkDrawSource?: string | null;
  /** Called when a target node is clicked while in link draw mode */
  onLinkDraw?: (source: OntologyConcept, target: OntologyConcept) => void;
  /** Called when link draw mode is cancelled (Escape or background click) */
  onLinkDrawCancel?: () => void;
  showRootBadges?: boolean;
}

interface GraphData {
  graphData: ForceGraphData;
  rootNodes: OntologyConcept[];
  rootColors: Map<string, string>;
  getRootDescendants: (rootIri: string) => Set<string>;
}

// ---- Main Component ----

export const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({
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
}) => {
  const fgRef = useRef<ForceGraphMethods>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredNode, setHoveredNode] = useState<ForceGraphNode | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [localGraphData, setLocalGraphData] = useState<ForceGraphData | null>(null);
  const [showLabels, setShowLabels] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 900, height: 600 });

  // Detect dark mode
  useEffect(() => {
    const check = () => setIsDarkMode(document.documentElement.classList.contains('dark'));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // Track container size
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        setDimensions({ width, height });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Transform OntologyConcept[] → force graph data
  const computed = useMemo((): GraphData => {
    const visibleConcepts = concepts.filter(
      c => c.concept_type === 'class' || c.concept_type === 'concept' || c.concept_type === 'property' || c.concept_type === 'scheme'
    );
    const conceptMap = new Map(visibleConcepts.map(c => [c.iri, c]));

    // Root detection
    const rootNodes = visibleConcepts.filter(c => {
      if (!c.parent_concepts || c.parent_concepts.length === 0) return true;
      return c.parent_concepts.every(p => !conceptMap.has(p));
    });

    const rootColors = new Map<string, string>();
    rootNodes.forEach((root, i) => {
      rootColors.set(root.iri, DOMAIN_COLORS[i % DOMAIN_COLORS.length]);
    });

    // Assign each node to its root
    const nodeToRoot = new Map<string, string>();
    const findRoot = (iri: string, visited = new Set<string>()): string | null => {
      if (visited.has(iri)) return null;
      visited.add(iri);
      const concept = conceptMap.get(iri);
      if (!concept) return null;
      if (!concept.parent_concepts?.length || concept.parent_concepts.every(p => !conceptMap.has(p))) return iri;
      for (const p of concept.parent_concepts) {
        const r = findRoot(p, visited);
        if (r) return r;
      }
      return null;
    };
    visibleConcepts.forEach(c => {
      const r = findRoot(c.iri);
      if (r) nodeToRoot.set(c.iri, r);
    });

    const getRootDescendants = (rootIri: string): Set<string> => {
      const desc = new Set<string>([rootIri]);
      const queue = [rootIri];
      while (queue.length > 0) {
        const cur = queue.shift()!;
        const c = conceptMap.get(cur);
        if (c?.child_concepts) {
          c.child_concepts.forEach(ch => {
            if (!desc.has(ch) && conceptMap.has(ch)) {
              desc.add(ch);
              queue.push(ch);
            }
          });
        }
      }
      return desc;
    };

    // Filter by hidden roots
    const visibleIris = new Set<string>();
    rootNodes.forEach(root => {
      if (!hiddenRoots.has(root.iri)) {
        getRootDescendants(root.iri).forEach(iri => visibleIris.add(iri));
      }
    });

    const filtered = visibleConcepts.filter(c => visibleIris.has(c.iri));

    // Build force graph nodes
    const nodes: ForceGraphNode[] = filtered.map(c => {
      const rootIri = nodeToRoot.get(c.iri) || c.iri;
      const color = rootColors.get(rootIri) || '#64748b';
      return {
        id: c.iri,
        label: c.label || c.iri.split(/[/#]/).pop() || 'Unknown',
        group: c.concept_type === 'property' ? 'property' : c.concept_type === 'scheme' ? 'scheme' : 'concept',
        color,
        conceptData: c,
        notation: c.notation,
      };
    });

    // Build force graph links
    const filteredSet = new Set(filtered.map(c => c.iri));
    const links: ForceGraphLink[] = [];
    filtered.forEach(c => {
      // Build typed child lookup for predicate-aware edges
      const typedChildMap = new Map<string, string>();
      if (c.typed_children?.length) {
        c.typed_children.forEach(tc => typedChildMap.set(tc.iri, tc.predicate_label));
      }
      c.child_concepts.forEach(childIri => {
        if (filteredSet.has(childIri)) {
          links.push({
            source: c.iri,
            target: childIri,
            type: typedChildMap.get(childIri) || 'ontology',
          });
        }
      });
      // Add skos:related edges (bidirectional in SKOS, but we only draw once)
      if (c.typed_related?.length) {
        c.typed_related.forEach(tr => {
          if (filteredSet.has(tr.iri) && c.iri < tr.iri) { // avoid duplicates
            links.push({
              source: c.iri,
              target: tr.iri,
              type: tr.predicate_label || 'skos:related',
            });
          }
        });
      }
    });

    return { graphData: { nodes, links }, rootNodes, rootColors, getRootDescendants };
  }, [concepts, hiddenRoots]);

  // Merge base data with expand/collapse state
  const displayData = localGraphData ?? computed.graphData;

  // Handle node click — link draw mode intercept, expand/collapse, or select
  const handleNodeClick = useCallback(async (node: ForceGraphNode) => {
    // Link draw mode: clicking a target node completes the link.
    // Block all normal click behavior (expand/collapse/select) while active.
    if (linkDrawSource) {
      if (onLinkDraw && node.conceptData && node.id !== linkDrawSource) {
        const sourceNode = displayData.nodes.find(n => n.id === linkDrawSource);
        if (sourceNode?.conceptData) {
          onLinkDraw(sourceNode.conceptData, node.conceptData);
        }
      }
      return;
    }

    // Always fire the selection callback first, regardless of expand/collapse outcome
    if (node.conceptData) {
      onNodeClick(node.conceptData);
    }

    const iri = node.id;
    const isExpanded = expandedNodes.has(iri);

    if (isExpanded) {
      // Collapse: remove children added via this node
      setLocalGraphData(prev => {
        const current = prev ?? computed.graphData;
        const keptNodes = current.nodes.filter(n => n.parentExpansion !== iri);
        const keptIds = new Set(keptNodes.map(n => n.id));
        const keptLinks = current.links.filter(l => {
          const sid = typeof l.source === 'object' ? (l.source as ForceGraphNode).id : l.source;
          const tid = typeof l.target === 'object' ? (l.target as ForceGraphNode).id : l.target;
          return keptIds.has(sid) && keptIds.has(tid);
        });
        return { nodes: keptNodes, links: keptLinks };
      });
      setExpandedNodes(prev => {
        const next = new Set(prev);
        next.delete(iri);
        return next;
      });
    } else {
      // Expand: fetch children from API
      try {
        const res = await fetch(`/api/semantic-models/concepts/${encodeURIComponent(iri)}`);
        if (!res.ok) return;
        const concept = await res.json();
        const childIris: string[] = concept?.child_concepts ?? [];
        if (!childIris.length) return;

        // Fetch each child concept for labels
        const childPromises = childIris.slice(0, 20).map(async (childIri: string) => {
          try {
            const r = await fetch(`/api/semantic-models/concepts/${encodeURIComponent(childIri)}`);
            if (!r.ok) return null;
            return await r.json();
          } catch { return null; }
        });
        const children = (await Promise.all(childPromises)).filter(Boolean);
        if (!children.length) return;

        setLocalGraphData(prev => {
          const current = prev ?? computed.graphData;
          const existingIds = new Set(current.nodes.map(n => n.id));
          const newNodes: ForceGraphNode[] = children
            .filter((c: OntologyConcept) => !existingIds.has(c.iri))
            .map((c: OntologyConcept) => ({
              id: c.iri,
              label: c.label || c.iri.split(/[/#]/).pop() || 'Unknown',
              group: 'concept' as const,
              color: node.color,
              conceptData: c,
              parentExpansion: iri,
              x: (node.x ?? 0) + (Math.random() - 0.5) * 60,
              y: (node.y ?? 0) + (Math.random() - 0.5) * 60,
            }));
          const newLinks: ForceGraphLink[] = newNodes.map(n => ({
            source: iri,
            target: n.id,
            type: 'ontology' as const,
          }));
          return {
            nodes: [...current.nodes, ...newNodes],
            links: [...current.links, ...newLinks],
          };
        });
        setExpandedNodes(prev => new Set([...prev, iri]));
      } catch {
        // silently ignore fetch errors
      }
    }
  }, [expandedNodes, computed.graphData, onNodeClick, linkDrawSource, onLinkDraw, displayData.nodes]);

  const handleNodeHover = useCallback((node: ForceGraphNode | null) => {
    setHoveredNode(node ?? null);
  }, []);

  const handleNodeRightClick = useCallback((node: ForceGraphNode, event: MouseEvent) => {
    event.preventDefault();
    if (node.conceptData && onNodeRightClick) {
      onNodeRightClick(node.conceptData, event);
    }
  }, [onNodeRightClick]);

  const handleBackgroundRightClick = useCallback((event: MouseEvent) => {
    event.preventDefault();
    onBackgroundRightClick?.(event);
  }, [onBackgroundRightClick]);

  // Cancel link draw mode on Escape
  useEffect(() => {
    if (!linkDrawSource || !onLinkDrawCancel) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onLinkDrawCancel();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [linkDrawSource, onLinkDrawCancel]);

  // Custom canvas rendering
  const nodeCanvasObject = useCallback((node: ForceGraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isProperty = node.group === 'property';
    const isScheme = node.group === 'scheme';
    const isExpanded = expandedNodes.has(node.id);
    const isHovered = hoveredNode?.id === node.id;
    const size = isScheme ? 8 : isProperty ? 4 : 6;
    const fontSize = Math.max(10 / globalScale, 3);
    const textColor = isDarkMode ? '#e2e8f0' : '#1e293b';

    if (!node.x || !node.y) return;

    ctx.beginPath();
    if (isScheme) {
      // Hexagon shape for ConceptScheme nodes
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 6;
        const px = node.x + size * Math.cos(angle);
        const py = node.y + size * Math.sin(angle);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
    } else if (isProperty) {
      // Diamond shape for properties
      ctx.moveTo(node.x, node.y - size);
      ctx.lineTo(node.x + size, node.y);
      ctx.lineTo(node.x, node.y + size);
      ctx.lineTo(node.x - size, node.y);
      ctx.closePath();
    } else {
      ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
    }

    ctx.fillStyle = node.color;
    ctx.fill();

    // Link draw source — pulsing glow ring
    const isLinkSource = linkDrawSource === node.id;
    if (isLinkSource) {
      ctx.save();
      ctx.strokeStyle = isDarkMode ? '#f472b6' : '#ec4899';
      ctx.lineWidth = 3 / globalScale;
      ctx.setLineDash([4 / globalScale, 2 / globalScale]);
      ctx.stroke();
      ctx.restore();
    } else if (isExpanded || isHovered) {
      // Expanded or hover ring
      ctx.strokeStyle = isDarkMode ? '#60a5fa' : '#3b82f6';
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    }

    // Label (with notation subtitle for hovered/scheme nodes)
    if (showLabels || isHovered || isExpanded) {
      ctx.font = `${isHovered ? 600 : 400} ${fontSize}px Inter, -apple-system, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = textColor;
      ctx.fillText(node.label, node.x, node.y + size + 2);
      // Show notation code as subtitle when hovered
      if (node.notation && isHovered) {
        ctx.font = `300 ${fontSize * 0.8}px Inter, -apple-system, sans-serif`;
        ctx.fillStyle = isDarkMode ? '#94a3b8' : '#64748b';
        ctx.fillText(node.notation, node.x, node.y + size + 2 + fontSize * 1.2);
      }
    }
  }, [hoveredNode, expandedNodes, isDarkMode, showLabels, linkDrawSource]);

  // Custom link rendering — styled by W3C predicate type
  const linkCanvasObject = useCallback((link: ForceGraphLink, ctx: CanvasRenderingContext2D) => {
    const source = link.source as ForceGraphNode;
    const target = link.target as ForceGraphNode;
    if (!source.x || !source.y || !target.x || !target.y) return;

    const style = PREDICATE_STYLES[link.type] || PREDICATE_STYLES['ontology'];
    ctx.save();
    if (style.dash) ctx.setLineDash(style.dash);
    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = isDarkMode ? style.darkColor : style.color;
    ctx.lineWidth = style.width;
    ctx.globalAlpha = link.type === 'ontology' ? 0.3 : 0.6;
    ctx.stroke();
    ctx.restore();
  }, [isDarkMode]);

  const bgColor = isDarkMode ? '#0f172a' : '#f8fafc';
  const conceptCount = displayData.nodes.filter(n => n.group !== 'product').length;

  // Controls
  const handleZoomIn = () => fgRef.current?.zoom(((fgRef.current as any).zoom?.() ?? 1) * 1.3, 300);
  const handleZoomOut = () => fgRef.current?.zoom(((fgRef.current as any).zoom?.() ?? 1) / 1.3, 300);
  const handleFit = () => fgRef.current?.zoomToFit(400, 60);
  const handleReset = () => {
    fgRef.current?.zoomToFit(400, 60);
    // Reheat simulation
    fgRef.current?.d3ReheatSimulation();
  };

  const renderGraph = (w: number, h: number, ref?: React.MutableRefObject<ForceGraphMethods | undefined>) => (
    <ForceGraph2D
      ref={ref as any}
      graphData={displayData}
      width={w}
      height={h}
      nodeCanvasObject={nodeCanvasObject as any}
      linkCanvasObject={linkCanvasObject as any}
      onNodeClick={handleNodeClick as any}
      onNodeHover={handleNodeHover as any}
      onNodeRightClick={handleNodeRightClick as any}
      onBackgroundRightClick={handleBackgroundRightClick as any}
      enableZoomInteraction={true}
      enablePanInteraction={true}
      enableNodeDrag={true}
      cooldownTicks={120}
      warmupTicks={50}
      d3AlphaDecay={0.05}
      d3VelocityDecay={0.4}
      backgroundColor={bgColor}
    />
  );

  return (
    <div className="h-full flex flex-col border rounded-lg bg-background overflow-hidden">
      {/* Legend / Root Filter */}
      {showRootBadges && (
        <div className="px-6 py-3 border-b bg-muted/30">
          <RootNodeFilter
            rootNodes={computed.rootNodes}
            rootColors={computed.rootColors}
            hiddenRoots={hiddenRoots}
            onToggleRoot={onToggleRoot}
            getRootDescendants={computed.getRootDescendants}
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="px-4 py-2 border-b flex items-center justify-between bg-muted/20">
        <div className="flex items-center gap-2">
          <Button
            variant={showLabels ? "secondary" : "ghost"}
            size="icon"
            className="h-8 w-8"
            onClick={() => setShowLabels(prev => !prev)}
            title={showLabels ? "Hide labels" : "Show labels"}
          >
            <Tag className="h-4 w-4" />
          </Button>
          <Badge variant="secondary" className="text-xs">
            {conceptCount} concepts
          </Badge>

          {/* Legend — node shapes + W3C predicate edge styles */}
          <div className="hidden sm:flex items-center gap-3 ml-4 text-[11px] flex-wrap">
            {/* Node shapes */}
            <div className="flex items-center gap-2.5 text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <svg width="10" height="10" className="flex-shrink-0"><circle cx="5" cy="5" r="4" fill="#3b82f6"/></svg>
                Concept
              </span>
              <span className="flex items-center gap-1.5">
                <svg width="10" height="10" className="flex-shrink-0"><polygon points="5,1 9,5 5,9 1,5" fill="#f59e0b"/></svg>
                Property
              </span>
              <span className="flex items-center gap-1.5" title="skos:ConceptScheme">
                <svg width="11" height="10" className="flex-shrink-0"><polygon points="5.5,0.5 10,3 10,7 5.5,9.5 1,7 1,3" fill="#8b5cf6"/></svg>
                Scheme
              </span>
            </div>

            <div className="h-4 w-px bg-border" />

            {/* Edge predicate styles */}
            <div className="flex items-center gap-2.5 font-mono text-muted-foreground">
              {Object.entries(PREDICATE_STYLES)
                .filter(([key]) => !['ontology', 'semantic', 'skos:narrower'].includes(key))
                .map(([key, s]) => (
                  <span key={key} className="flex items-center gap-1.5" title={key}>
                    <svg width="16" height="4" className="flex-shrink-0">
                      <line x1="0" y1="2" x2="16" y2="2"
                        stroke={isDarkMode ? s.darkColor : s.color}
                        strokeWidth={Math.max(s.width, 1.5)}
                        strokeDasharray={s.dash ? s.dash.join(',') : undefined}
                      />
                    </svg>
                    <span>{key}</span>
                  </span>
                ))}
            </div>
          </div>
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

      {/* Graph canvas */}
      <div ref={containerRef} className="flex-1 relative" style={{ minHeight: 0 }}>
        {renderGraph(dimensions.width, dimensions.height, fgRef)}

        {/* Link draw mode indicator */}
        {linkDrawSource && (
          <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full border bg-pink-50 dark:bg-pink-950/50 border-pink-200 dark:border-pink-800 text-sm shadow-sm">
            <div className="w-2 h-2 rounded-full bg-pink-500 animate-pulse" />
            <span className="text-pink-700 dark:text-pink-300">Click a target node to create link</span>
            <button
              className="ml-1 text-pink-400 hover:text-pink-600 dark:hover:text-pink-200"
              onClick={onLinkDrawCancel}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Hover tooltip */}
        {hoveredNode && (
          <div className="absolute top-2 right-2 z-10 max-w-[280px] rounded-xl border bg-popover/95 backdrop-blur-sm p-3 text-sm shadow-lg">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border text-muted-foreground bg-muted/50">
                {hoveredNode.group === 'scheme' ? 'skos:ConceptScheme'
                  : hoveredNode.group === 'property' ? 'owl:Property'
                  : hoveredNode.conceptData?.concept_type === 'class' ? 'owl:Class'
                  : 'skos:Concept'}
              </span>
              {hoveredNode.notation && (
                <span className="font-mono text-[10px] text-muted-foreground">{hoveredNode.notation}</span>
              )}
            </div>
            <div className="font-semibold">{hoveredNode.label}</div>
            {hoveredNode.conceptData?.comment && (
              <div className="text-xs text-muted-foreground mt-1.5 line-clamp-3 leading-relaxed">
                {hoveredNode.conceptData.comment}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Fullscreen Dialog */}
      <Dialog open={isFullscreen} onOpenChange={setIsFullscreen}>
        <DialogContent className="max-w-[95vw] w-[95vw] h-[95vh] max-h-[95vh] p-0 flex flex-col">
          <DialogHeader className="px-6 py-4 border-b flex-shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <DialogTitle className="text-xl font-semibold">Knowledge Graph</DialogTitle>
                <DialogDescription className="sr-only">
                  Fullscreen view of the knowledge graph visualization
                </DialogDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant={showLabels ? "secondary" : "ghost"}
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setShowLabels(prev => !prev)}
                  title={showLabels ? "Hide labels" : "Show labels"}
                >
                  <Tag className="h-4 w-4" />
                </Button>
                <Badge variant="secondary" className="text-xs">
                  {conceptCount} concepts
                </Badge>
              </div>
            </div>
          </DialogHeader>

          {showRootBadges && (
            <div className="px-6 py-3 border-b bg-muted/30 flex-shrink-0">
              <RootNodeFilter
                rootNodes={computed.rootNodes}
                rootColors={computed.rootColors}
                hiddenRoots={hiddenRoots}
                onToggleRoot={onToggleRoot}
                getRootDescendants={computed.getRootDescendants}
              />
            </div>
          )}

          <div className="flex-1 relative">
            {isFullscreen && renderGraph(
              window.innerWidth * 0.95 - 2,
              window.innerHeight * 0.95 - 160,
            )}
          </div>

          <div className="px-4 py-2 border-t flex items-center justify-between bg-muted/20 flex-shrink-0">
            <div className="text-sm text-muted-foreground">
              Click nodes to expand/collapse. Scroll to zoom, drag to pan.
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
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleReset} title="Reset">
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
