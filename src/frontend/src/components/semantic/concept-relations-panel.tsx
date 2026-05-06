import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Link as LinkIcon,
  Loader2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { useApi } from '@/hooks/use-api'

interface NeighborItem {
  direction: 'outgoing' | 'incoming' | 'predicate'
  predicate: string
  display: string
  displayType: 'resource' | 'property' | 'literal'
  stepIri?: string | null
  stepIsResource?: boolean
}

interface ConceptRelationsPanelProps {
  conceptIri: string
  onNavigate: (iri: string) => void
  // When set, the relations list scrolls internally past this row count
  // instead of growing the page (rows are ~32px high).
  maxVisibleRows?: number
  // Optional cap on how many neighbours to fetch from the backend.
  fetchLimit?: number
}

// Predicates whose values are already surfaced elsewhere on the page
// (title, type pill, definition, synonyms, examples). Hiding them keeps
// the relations panel focused on actual semantic relationships.
const PREDICATES_TO_HIDE = new Set<string>([
  'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  'http://www.w3.org/2000/01/rdf-schema#label',
  'http://www.w3.org/2000/01/rdf-schema#comment',
  'http://www.w3.org/2004/02/skos/core#prefLabel',
  'http://www.w3.org/2004/02/skos/core#altLabel',
  'http://www.w3.org/2004/02/skos/core#hiddenLabel',
  'http://www.w3.org/2004/02/skos/core#definition',
  'http://www.w3.org/2004/02/skos/core#example',
  'http://www.w3.org/2004/02/skos/core#notation',
])

// Friendly colour scheme by relationship family. Falls back to neutral.
const PREDICATE_COLORS: Array<[RegExp, string]> = [
  [/subClassOf$|broader$|broaderTransitive$|subPropertyOf$|broadMatch$/i,
    'bg-indigo-500/10 text-indigo-600 border-indigo-500/30'],
  [/narrower$|narrowerTransitive$|narrowMatch$/i,
    'bg-green-500/10 text-green-600 border-green-500/30'],
  [/related$|relatedMatch$|seeAlso$/i,
    'bg-orange-500/10 text-orange-600 border-orange-500/30'],
  [/domain$/i, 'bg-violet-500/10 text-violet-600 border-violet-500/30'],
  [/range$/i, 'bg-pink-500/10 text-pink-600 border-pink-500/30'],
  [/sameAs$|equivalentClass$|equivalentProperty$|exactMatch$|closeMatch$/i,
    'bg-cyan-500/10 text-cyan-600 border-cyan-500/30'],
  [/disjointWith$|complementOf$/i,
    'bg-red-500/10 text-red-600 border-red-500/30'],
  [/inverseOf$/i, 'bg-amber-500/10 text-amber-600 border-amber-500/30'],
  [/isDefinedBy$/i, 'bg-slate-500/10 text-slate-600 border-slate-500/30'],
]

const localName = (iri: string): string => {
  if (!iri) return ''
  const fragment = iri.split('#').pop()
  if (fragment && fragment !== iri) return fragment
  const path = iri.split('/').pop()
  return path || iri
}

const colourFor = (predicate: string): string => {
  for (const [re, cls] of PREDICATE_COLORS) {
    if (re.test(predicate)) return cls
  }
  return ''
}

interface NormalizedRelation {
  key: string
  direction: 'outgoing' | 'incoming'
  predicate: string
  predicateShort: string
  targetLabel: string
  targetIri?: string | null
  isResource: boolean
}

export default function ConceptRelationsPanel({
  conceptIri,
  onNavigate,
  maxVisibleRows,
  fetchLimit = 500,
}: ConceptRelationsPanelProps) {
  const { get } = useApi()
  const { t } = useTranslation(['semantic-models', 'common'])

  const [neighbors, setNeighbors] = useState<NeighborItem[] | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [open, setOpen] = useState(true)

  const ROW_HEIGHT_PX = 32
  const listMaxHeight = maxVisibleRows
    ? { maxHeight: ROW_HEIGHT_PX * maxVisibleRows }
    : undefined

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!conceptIri) {
        setNeighbors([])
        return
      }
      setIsLoading(true)
      try {
        const url = `/api/semantic-models/neighbors?iri=${encodeURIComponent(
          conceptIri,
        )}&limit=${fetchLimit}`
        const res = await get<NeighborItem[]>(url)
        if (cancelled) return
        setNeighbors(res.data || [])
      } catch (err) {
        console.error('ConceptRelationsPanel: failed to load neighbors', err)
        if (!cancelled) setNeighbors([])
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [conceptIri, fetchLimit, get])

  // Normalise + dedupe + sort. Outgoing first, then incoming, then by
  // predicate local name for stable scanning.
  const relations = useMemo<NormalizedRelation[]>(() => {
    if (!neighbors) return []
    const seen = new Set<string>()
    const out: NormalizedRelation[] = []
    for (const n of neighbors) {
      // Predicate-direction items only appear when the IRI itself IS used as
      // a predicate. They are already covered by the inverse triples on the
      // other side, so we ignore them here to avoid double-counting.
      if (n.direction === 'predicate') continue
      if (PREDICATES_TO_HIDE.has(n.predicate)) continue
      // A literal whose predicate we hid still shouldn't appear; literals
      // we keep are domain-specific annotations (e.g. dc:identifier).

      const targetIri = n.stepIri || (n.displayType !== 'literal' ? n.display : null)
      const targetLabel =
        n.displayType === 'literal'
          ? n.display
          : localName(n.display) || n.display

      const key = `${n.direction}|${n.predicate}|${n.display}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        key,
        direction: n.direction,
        predicate: n.predicate,
        predicateShort: localName(n.predicate) || n.predicate,
        targetLabel,
        targetIri,
        isResource: !!n.stepIsResource,
      })
    }
    out.sort((a, b) => {
      if (a.direction !== b.direction) {
        return a.direction === 'outgoing' ? -1 : 1
      }
      if (a.predicateShort !== b.predicateShort) {
        return a.predicateShort.localeCompare(b.predicateShort)
      }
      return a.targetLabel.localeCompare(b.targetLabel)
    })
    return out
  }, [neighbors])

  const counts = useMemo(() => {
    let outgoing = 0
    let incoming = 0
    for (const r of relations) {
      if (r.direction === 'outgoing') outgoing += 1
      else incoming += 1
    }
    return { outgoing, incoming, total: relations.length }
  }, [relations])

  const renderRow = useCallback(
    (r: NormalizedRelation) => {
      const colour = colourFor(r.predicate)
      const DirIcon = r.direction === 'outgoing' ? ArrowRight : ArrowLeft
      const dirTooltip =
        r.direction === 'outgoing'
          ? t('semantic-models:relations.outgoingTooltip', {
              defaultValue: 'This concept → target',
            })
          : t('semantic-models:relations.incomingTooltip', {
              defaultValue: 'Source → this concept',
            })
      return (
        <div
          key={r.key}
          data-testid={`relation-${r.direction}-${r.predicateShort}-${r.targetLabel}`}
          className="flex items-center gap-2 py-1 px-2 rounded hover:bg-muted/50"
        >
          <Badge
            variant="outline"
            className={`text-[10px] font-mono ${colour}`}
            title={r.predicate}
          >
            {r.predicateShort}
          </Badge>
          <DirIcon
            className="h-3 w-3 text-muted-foreground shrink-0"
            aria-label={dirTooltip}
          />
          {r.isResource && r.targetIri ? (
            <button
              type="button"
              className="text-sm text-primary hover:underline text-left truncate"
              onClick={() => onNavigate(r.targetIri!)}
              title={r.targetIri}
            >
              {r.targetLabel}
            </button>
          ) : (
            <span
              className="text-sm text-muted-foreground truncate"
              title={r.targetLabel}
            >
              {r.targetLabel}
            </span>
          )}
        </div>
      )
    },
    [onNavigate, t],
  )

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="border rounded-lg">
        <CollapsibleTrigger className="flex items-center justify-between w-full p-3 hover:bg-muted/50">
          <div className="flex items-center gap-2">
            {open ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            <LinkIcon className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">
              {t('semantic-models:relations.title', {
                defaultValue: 'Relations',
              })}
            </span>
            <Badge variant="secondary" className="text-xs">
              {counts.total}
            </Badge>
            {counts.total > 0 && (
              <span className="text-[11px] text-muted-foreground inline-flex items-center gap-2 ml-1">
                <span className="inline-flex items-center gap-1">
                  <ArrowRight className="h-3 w-3" />
                  {counts.outgoing}
                </span>
                <span className="inline-flex items-center gap-1">
                  <ArrowLeft className="h-3 w-3" />
                  {counts.incoming}
                </span>
              </span>
            )}
          </div>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div
            className={`border-t px-2 py-1 ${maxVisibleRows ? 'overflow-y-auto' : ''}`}
            style={listMaxHeight}
            data-testid="concept-relations-list"
          >
            {isLoading && relations.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-2 px-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t('semantic-models:relations.loading', {
                  defaultValue: 'Loading relations...',
                })}
              </div>
            ) : relations.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2 px-2">
                {t('semantic-models:relations.empty', {
                  defaultValue: 'No relations found.',
                })}
              </p>
            ) : (
              relations.map(renderRow)
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
