import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, GitCompare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import VersionSelector, {
  EntityKind,
  EntityVersionRow,
  fetchEntityVersions,
} from './version-selector'
import EntityDiffDialog, { orderPair } from './entity-diff-dialog'

/**
 * Combines a previous / next chevron pair with the shared `VersionSelector`
 * dropdown so the detail views for both contracts and products get a
 * single, consistent navigation control across the family.
 *
 * Versions are returned newest-first by the API. "Newer" therefore moves
 * up the list (lower index) and "Older" moves down (higher index).
 */

type VersionNavigatorProps = {
  entityKind: EntityKind
  currentEntityId: string
  currentVersion?: string
  onVersionChange: (entityId: string) => void
}

export default function VersionNavigator({
  entityKind,
  currentEntityId,
  currentVersion,
  onVersionChange,
}: VersionNavigatorProps) {
  const { t } = useTranslation('common')
  const [versions, setVersions] = useState<EntityVersionRow[]>([])
  // [base, target] of the open diff dialog (oldest → newest), or null.
  const [comparePair, setComparePair] = useState<[string, string] | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchEntityVersions(entityKind, currentEntityId).then((rows) => {
      if (!cancelled) setVersions(rows)
    })
    return () => {
      cancelled = true
    }
  }, [entityKind, currentEntityId])

  // Family-of-one: hide the whole nav block.
  if (versions.length <= 1) return null

  const currentIndex = versions.findIndex((v) => v.id === currentEntityId)
  const newerVersion = currentIndex > 0 ? versions[currentIndex - 1] : null
  const olderVersion =
    currentIndex >= 0 && currentIndex < versions.length - 1
      ? versions[currentIndex + 1]
      : null

  return (
    <TooltipProvider>
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={!newerVersion}
              onClick={() => newerVersion && onVersionChange(newerVersion.id)}
              aria-label={t('common:versionNavigator.newerVersion')}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {newerVersion
              ? t('common:versionNavigator.newerTooltip', { version: newerVersion.version })
              : t('common:versionNavigator.alreadyNewest')}
          </TooltipContent>
        </Tooltip>

        <VersionSelector
          entityKind={entityKind}
          currentEntityId={currentEntityId}
          currentVersion={currentVersion}
          onVersionChange={onVersionChange}
          onCompare={(row) => setComparePair(orderPair(versions, row.id, currentEntityId))}
        />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={!olderVersion}
              onClick={() => olderVersion && onVersionChange(olderVersion.id)}
              aria-label={t('common:versionNavigator.olderVersion')}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {olderVersion
              ? t('common:versionNavigator.olderTooltip', { version: olderVersion.version })
              : t('common:versionNavigator.alreadyOldest')}
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={!(olderVersion ?? newerVersion)}
              onClick={() => {
                // Default pair: the previous (older) version → this one; on
                // the oldest version, compare it with the next newer one.
                const other = olderVersion ?? newerVersion
                if (other) setComparePair(orderPair(versions, other.id, currentEntityId))
              }}
              aria-label={t('common:entityDiff.compare')}
            >
              <GitCompare className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {olderVersion
              ? t('common:entityDiff.compareWithPrevious', { version: olderVersion.version })
              : t('common:entityDiff.compare')}
          </TooltipContent>
        </Tooltip>
      </div>

      {comparePair && (
        <EntityDiffDialog
          open
          onOpenChange={(open) => !open && setComparePair(null)}
          entityKind={entityKind}
          versions={versions}
          baseId={comparePair[0]}
          targetId={comparePair[1]}
        />
      )}
    </TooltipProvider>
  )
}
