import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { EntitySemanticLink } from '@/types/semantic-link'
import { Shapes } from 'lucide-react'

type Props = {
  links: EntitySemanticLink[]
  onRemove?: (linkId: string) => void
  trailing?: React.ReactNode
}

const isBadLabel = (label?: string) => !!label && (/^https?:\/\//i.test(label) || /^urn:/i.test(label))
const iriTail = (iri: string) => (iri.split(/[\/#]/).pop() || iri)
const displayLabel = (iri: string, label?: string) => isBadLabel(label) ? iriTail(iri) : (label || iriTail(iri))

export default function LinkedConceptChips({ links, onRemove, trailing }: Props) {
  const { t } = useTranslation(['semantic-models', 'common'])
  const [resolved, setResolved] = useState<Record<string, string>>({})

  useEffect(() => {
    let cancelled = false
    const fetchLabels = async () => {
      const irisToResolve = (links || [])
        .map(l => l.iri)
        .filter(iri => iri && !resolved[iri])
      if (irisToResolve.length === 0) return

      await Promise.all(irisToResolve.map(async iri => {
        try {
          // Try exact search by IRI
          const r1 = await fetch(`/api/semantic-models/concepts?q=${encodeURIComponent(iri)}&limit=5`)
          if (r1.ok) {
            const data = await r1.json()
            const exact = Array.isArray(data) ? data.find((d: any) => (d.value === iri || d.iri === iri) && d.label) : undefined
            if (exact && !cancelled) {
              setResolved(prev => ({ ...prev, [iri]: (exact.label as string) }))
              return
            }
          }
          // Fallback: try by iri tail
          const tail = iriTail(iri)
          const r2 = await fetch(`/api/semantic-models/concepts?q=${encodeURIComponent(tail)}&limit=10`)
          if (r2.ok) {
            const data2 = await r2.json()
            const exact2 = Array.isArray(data2) ? data2.find((d: any) => (d.value === iri || d.iri === iri) && d.label) : undefined
            if (exact2 && !cancelled) {
              setResolved(prev => ({ ...prev, [iri]: exact2.label as string }))
            } else if (Array.isArray(data2)) {
              // If not exact, pick the first entry that mentions the tail
              const candidate = data2.find((d: any) => typeof d.label === 'string' && d.label.toLowerCase().includes(tail.toLowerCase()))
              if (candidate && candidate.label && !cancelled) {
                setResolved(prev => ({ ...prev, [iri]: candidate.label as string }))
              }
            }
          }
        } catch (_) {
          // ignore and keep fallback
        }
      }))
    }
    fetchLabels()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links])
  if (!links || links.length === 0) {
    return (
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm text-muted-foreground">{t('semantic-models:linkedConcepts.empty')}</span>
        {trailing}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {links.map((l) => (
        <span key={l.id} className="inline-flex items-center gap-1 border rounded px-2 py-1 text-sm max-w-[420px] truncate">
          <Shapes className="h-3 w-3" />
          <a
            href={`/concepts/search?tab=kg&path=${encodeURIComponent(l.iri)}`}
            className="hover:underline truncate"
            title={l.iri}
          >
            {resolved[l.iri] || displayLabel(l.iri, l.label)}
          </a>
          {onRemove && (
            <button
              aria-label={t('semantic-models:linkedConcepts.removeAria')}
              className="ml-1 text-muted-foreground hover:text-foreground"
              onClick={(e) => { e.preventDefault(); onRemove(l.id); }}
            >
              ×
            </button>
          )}
        </span>
      ))}
      {trailing}
    </div>
  )
}


