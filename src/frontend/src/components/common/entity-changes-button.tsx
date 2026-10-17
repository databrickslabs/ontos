import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { GitCompare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import EntityDiffDialog, { pickBaseVersion } from './entity-diff-dialog'
import { fetchEntityVersions, type EntityKind, type EntityVersionRow } from './version-selector'

/**
 * "View changes" for review surfaces (workflow approvals, asset reviews):
 * opens the version diff of the entity under review against the version it
 * was derived from (its parent, else the previous version in the family).
 * Renders nothing for non-versioned entity types or a family of one.
 */

const ENTITY_KINDS: Record<string, EntityKind> = {
  data_contract: 'contract',
  data_product: 'product',
}

export function entityKindFor(entityType?: string | null): EntityKind | null {
  return (entityType && ENTITY_KINDS[entityType.toLowerCase()]) || null
}

type EntityChangesButtonProps = {
  entityType?: string | null
  entityId?: string | null
  className?: string
}

export default function EntityChangesButton({ entityType, entityId, className }: EntityChangesButtonProps) {
  const { t } = useTranslation('common')
  const kind = entityKindFor(entityType)
  const [versions, setVersions] = useState<EntityVersionRow[]>([])
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    setVersions([]) // don't offer a stale family while the new one loads
    if (!kind || !entityId) return
    let cancelled = false
    fetchEntityVersions(kind, entityId)
      .then((rows) => {
        if (!cancelled) setVersions(rows)
      })
      .catch(() => {
        // Unresolvable ref / network error: no button.
      })
    return () => {
      cancelled = true
    }
  }, [kind, entityId])

  const baseId = kind && entityId ? pickBaseVersion(versions, entityId) : null
  if (!kind || !entityId || !baseId) return null

  return (
    <>
      <Button type="button" variant="outline" size="sm" className={className} onClick={() => setIsOpen(true)}>
        <GitCompare className="mr-2 h-4 w-4" />
        {t('entityDiff.viewChanges')}
      </Button>
      {isOpen && (
        <EntityDiffDialog
          open
          onOpenChange={setIsOpen}
          entityKind={kind}
          versions={versions}
          baseId={baseId}
          targetId={entityId}
        />
      )}
    </>
  )
}
