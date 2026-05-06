import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactFlow, {
  Edge,
  Handle,
  MarkerType,
  Node,
  Position,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Card } from '@/components/ui/card'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useApi } from '@/hooks/use-api'
import { OntologyConcept } from '@/types/ontology'

interface NeighborItem {
  direction: 'outgoing' | 'incoming' | 'predicate'
  predicate: string
  display: string
  displayType: 'resource' | 'property' | 'literal'
  stepIri?: string | null
  stepIsResource?: boolean
}

interface ConceptNeighborhoodGraphProps {
  concept: OntologyConcept
  onNavigate: (iri: string) => void
}

const PARENT_PREDICATE_FRAGMENTS = [
  'subClassOf',
  'broader',
  'subPropertyOf',
]

const CHILD_PREDICATE_FRAGMENTS = [
  'subClassOf',
  'narrower',
  'subPropertyOf',
]

const matchesPredicate = (predicate: string, fragments: string[]): boolean => {
  const lower = predicate.toLowerCase()
  return fragments.some((f) => lower.endsWith(f.toLowerCase()))
}

const localName = (iri: string): string => {
  if (!iri) return ''
  const fragment = iri.split('#').pop()
  if (fragment && fragment !== iri) return fragment
  const path = iri.split('/').pop()
  return path || iri
}

interface MiniNodeData {
  label: string
  iri: string
  isCurrent?: boolean
  isPlaceholder?: boolean
  onClick?: (iri: string) => void
  typeBadge?: string
}

const NODE_WIDTH = 170
const NODE_HEIGHT = 56
const HORIZONTAL_SPACING = 24
const VERTICAL_LEVEL_SPACING = 50
const FIXED_PADDING = 16

function MiniNode({ data }: { data: MiniNodeData }) {
  // The default `bg-card` + `text-card-foreground` combo always pairs
  // correctly in both light and dark themes. The "current" node only tints
  // the background (bg-primary/10) so we keep the regular foreground colour
  // there too -- using `text-primary-foreground` would render invisibly on
  // such a faintly-tinted background. Placeholders use `text-foreground`
  // muted via opacity so they read in both modes.
  return (
    <Card
      onClick={() => {
        if (data.isPlaceholder) return
        if (data.iri && data.onClick) data.onClick(data.iri)
      }}
      title={data.iri || data.label}
      className={cn(
        'p-2 flex flex-col items-center justify-center text-center text-xs shadow-sm hover:shadow-md transition-shadow',
        'bg-card text-card-foreground',
        data.isPlaceholder &&
          'cursor-default bg-muted/60 text-muted-foreground border-dashed',
        !data.isPlaceholder && !data.isCurrent && 'cursor-pointer',
        data.isCurrent &&
          'cursor-default bg-primary/10 border-primary text-foreground ring-1 ring-primary/40',
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} id="t-top" style={{ background: 'transparent', border: 'none' }} />
      <Handle type="source" position={Position.Bottom} id="s-bottom" style={{ background: 'transparent', border: 'none' }} />
      <div
        className={cn(
          'font-medium truncate w-full',
          data.isPlaceholder && 'opacity-80',
        )}
      >
        {data.label}
      </div>
      {data.typeBadge && (
        <div
          className={cn(
            'text-[10px] uppercase tracking-wide',
            data.isCurrent ? 'text-primary' : 'text-muted-foreground',
          )}
        >
          {data.typeBadge}
        </div>
      )}
    </Card>
  )
}

const nodeTypes = { mini: MiniNode }

interface NeighborItemForLayout {
  iri: string
  label: string
  typeBadge: string
}

interface LayoutInput {
  current: NeighborItemForLayout
  parents: NeighborItemForLayout[]
  children: NeighborItemForLayout[]
  parentOverflow: number
  childOverflow: number
}

function buildNodesAndEdges(
  layout: LayoutInput,
  onNavigate: (iri: string) => void,
  parentMoreLabel: string,
  childMoreLabel: string,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []

  const parentRowCount = layout.parents.length + (layout.parentOverflow > 0 ? 1 : 0)
  const childRowCount = layout.children.length + (layout.childOverflow > 0 ? 1 : 0)

  const rowWidth = (count: number) =>
    count > 0 ? count * NODE_WIDTH + Math.max(0, count - 1) * HORIZONTAL_SPACING : NODE_WIDTH

  const parentWidth = rowWidth(parentRowCount)
  const childWidth = rowWidth(childRowCount)
  const maxWidth = Math.max(parentWidth, childWidth, NODE_WIDTH)

  const centralX = (maxWidth - NODE_WIDTH) / 2 + FIXED_PADDING
  const parentRowStartX = (maxWidth - parentWidth) / 2 + FIXED_PADDING
  const childRowStartX = (maxWidth - childWidth) / 2 + FIXED_PADDING

  let yCursor = FIXED_PADDING

  // Parents (top row)
  if (parentRowCount > 0) {
    const parentY = yCursor
    layout.parents.forEach((parent, idx) => {
      const x = parentRowStartX + idx * (NODE_WIDTH + HORIZONTAL_SPACING)
      nodes.push({
        id: `parent-${parent.iri}`,
        type: 'mini',
        position: { x, y: parentY },
        data: {
          label: parent.label,
          iri: parent.iri,
          typeBadge: parent.typeBadge,
          onClick: onNavigate,
        },
      })
      edges.push({
        id: `e-parent-${parent.iri}`,
        source: `parent-${parent.iri}`,
        target: 'current',
        sourceHandle: 's-bottom',
        targetHandle: 't-top',
      })
    })
    if (layout.parentOverflow > 0) {
      const overflowX =
        parentRowStartX + layout.parents.length * (NODE_WIDTH + HORIZONTAL_SPACING)
      nodes.push({
        id: 'parent-overflow',
        type: 'mini',
        position: { x: overflowX, y: parentY },
        data: {
          label: parentMoreLabel.replace('{{count}}', String(layout.parentOverflow)),
          iri: '',
          isPlaceholder: true,
        },
      })
    }
    yCursor += NODE_HEIGHT + VERTICAL_LEVEL_SPACING
  }

  // Current (centre)
  const currentY = yCursor
  nodes.push({
    id: 'current',
    type: 'mini',
    position: { x: centralX, y: currentY },
    data: {
      label: layout.current.label,
      iri: layout.current.iri,
      isCurrent: true,
      typeBadge: layout.current.typeBadge,
    },
  })
  yCursor += NODE_HEIGHT + VERTICAL_LEVEL_SPACING

  // Children (bottom row)
  if (childRowCount > 0) {
    const childY = yCursor
    layout.children.forEach((child, idx) => {
      const x = childRowStartX + idx * (NODE_WIDTH + HORIZONTAL_SPACING)
      nodes.push({
        id: `child-${child.iri}`,
        type: 'mini',
        position: { x, y: childY },
        data: {
          label: child.label,
          iri: child.iri,
          typeBadge: child.typeBadge,
          onClick: onNavigate,
        },
      })
      edges.push({
        id: `e-child-${child.iri}`,
        source: 'current',
        target: `child-${child.iri}`,
        sourceHandle: 's-bottom',
        targetHandle: 't-top',
      })
    })
    if (layout.childOverflow > 0) {
      const overflowX =
        childRowStartX + layout.children.length * (NODE_WIDTH + HORIZONTAL_SPACING)
      nodes.push({
        id: 'child-overflow',
        type: 'mini',
        position: { x: overflowX, y: childY },
        data: {
          label: childMoreLabel.replace('{{count}}', String(layout.childOverflow)),
          iri: '',
          isPlaceholder: true,
        },
      })
    }
  }

  return { nodes, edges }
}

const MAX_PER_SIDE = 8

function ConceptNeighborhoodGraphInner({
  concept,
  onNavigate,
}: ConceptNeighborhoodGraphProps) {
  const { get } = useApi()
  const { t } = useTranslation(['semantic-models'])
  const { fitView } = useReactFlow()
  const [neighbors, setNeighbors] = useState<NeighborItem[] | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!concept?.iri) {
        setNeighbors([])
        return
      }
      setIsLoading(true)
      try {
        const url = `/api/semantic-models/neighbors?iri=${encodeURIComponent(
          concept.iri,
        )}&limit=200`
        const res = await get<NeighborItem[]>(url)
        if (cancelled) return
        setNeighbors(res.data || [])
      } catch (error) {
        console.error('ConceptNeighborhoodGraph: failed to load neighbors', error)
        if (!cancelled) setNeighbors([])
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [concept?.iri, get])

  const layout = useMemo<LayoutInput | null>(() => {
    if (!neighbors) return null

    const typeBadgeFor = (c: OntologyConcept): string =>
      c.concept_type === 'property'
        ? t('semantic-models:types.property', { defaultValue: 'Property' })
        : t('semantic-models:types.class', { defaultValue: 'Class' })

    const parentsAll: NeighborItemForLayout[] = []
    const childrenAll: NeighborItemForLayout[] = []
    const seenParents = new Set<string>()
    const seenChildren = new Set<string>()

    for (const n of neighbors) {
      if (!n.stepIri || !n.stepIsResource) continue
      if (n.direction === 'outgoing' && matchesPredicate(n.predicate, PARENT_PREDICATE_FRAGMENTS)) {
        if (n.stepIri === concept.iri) continue
        if (seenParents.has(n.stepIri)) continue
        seenParents.add(n.stepIri)
        parentsAll.push({
          iri: n.stepIri,
          label: localName(n.display) || n.display,
          typeBadge: t('semantic-models:types.class', { defaultValue: 'Class' }),
        })
      } else if (
        n.direction === 'incoming' &&
        matchesPredicate(n.predicate, CHILD_PREDICATE_FRAGMENTS)
      ) {
        if (n.stepIri === concept.iri) continue
        if (seenChildren.has(n.stepIri)) continue
        seenChildren.add(n.stepIri)
        childrenAll.push({
          iri: n.stepIri,
          label: localName(n.display) || n.display,
          typeBadge: t('semantic-models:types.class', { defaultValue: 'Class' }),
        })
      }
    }

    const parents = parentsAll.slice(0, MAX_PER_SIDE)
    const children = childrenAll.slice(0, MAX_PER_SIDE)
    return {
      current: {
        iri: concept.iri,
        label: concept.label || localName(concept.iri) || concept.iri,
        typeBadge: typeBadgeFor(concept),
      },
      parents,
      children,
      parentOverflow: parentsAll.length - parents.length,
      childOverflow: childrenAll.length - children.length,
    }
  }, [neighbors, concept, t])

  const parentMoreLabel = t('semantic-models:neighborhood.moreParents', {
    count: layout?.parentOverflow ?? 0,
    defaultValue: '+{{count}} more',
  })
  const childMoreLabel = t('semantic-models:neighborhood.moreChildren', {
    count: layout?.childOverflow ?? 0,
    defaultValue: '+{{count}} more',
  })

  const { nodes, edges } = useMemo(() => {
    if (!layout) return { nodes: [], edges: [] }
    return buildNodesAndEdges(layout, onNavigate, parentMoreLabel, childMoreLabel)
  }, [layout, onNavigate, parentMoreLabel, childMoreLabel])

  useEffect(() => {
    if (nodes.length === 0) return
    const timer = setTimeout(() => {
      fitView({ padding: 0.1, duration: 200 })
    }, 50)
    return () => clearTimeout(timer)
  }, [nodes, fitView])

  if (isLoading && !layout) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground py-3 gap-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t('semantic-models:neighborhood.loading', {
          defaultValue: 'Loading neighbourhood...',
        })}
      </div>
    )
  }

  if (
    layout &&
    layout.parents.length === 0 &&
    layout.children.length === 0 &&
    layout.parentOverflow === 0 &&
    layout.childOverflow === 0
  ) {
    return (
      <p className="text-sm text-muted-foreground py-2 px-2">
        {t('semantic-models:neighborhood.empty', {
          defaultValue: 'No related concepts.',
        })}
      </p>
    )
  }

  const isDarkMode =
    typeof document !== 'undefined' &&
    document.documentElement.classList.contains('dark')

  const defaultEdgeOptions = {
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 14,
      height: 14,
      color: isDarkMode ? '#94a3b8' : '#64748b',
    },
    style: {
      stroke: isDarkMode ? '#94a3b8' : '#64748b',
      strokeWidth: 1.5,
    },
  }

  return (
    <div
      className="bg-muted/30"
      style={{ height: GRAPH_HEIGHT }}
      data-testid="concept-neighborhood-graph"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnScroll={false}
        panOnDrag={false}
        selectNodesOnDrag={false}
        minZoom={0.2}
        maxZoom={1.5}
      />
    </div>
  )
}

const GRAPH_HEIGHT = 320

export default function ConceptNeighborhoodGraph(
  props: ConceptNeighborhoodGraphProps,
) {
  return (
    <ReactFlowProvider>
      <ConceptNeighborhoodGraphInner {...props} />
    </ReactFlowProvider>
  )
}
