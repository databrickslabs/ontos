import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import VersionSelector, {
  EntityKind,
  EntityVersionRow,
  fetchEntityVersions,
} from './version-selector'

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
  const [versions, setVersions] = useState<EntityVersionRow[]>([])

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
              aria-label="Newer version"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {newerVersion ? `Newer: v${newerVersion.version}` : 'Already on newest'}
          </TooltipContent>
        </Tooltip>

        <VersionSelector
          entityKind={entityKind}
          currentEntityId={currentEntityId}
          currentVersion={currentVersion}
          onVersionChange={onVersionChange}
        />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={!olderVersion}
              onClick={() => olderVersion && onVersionChange(olderVersion.id)}
              aria-label="Older version"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {olderVersion ? `Older: v${olderVersion.version}` : 'Already on oldest'}
          </TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  )
}
