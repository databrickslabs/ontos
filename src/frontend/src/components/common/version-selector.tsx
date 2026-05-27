import { useState, useEffect } from 'react'
import { ChevronDown, History } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/hooks/use-toast'

/**
 * Shared version selector for any entity kind that participates in the
 * unified version-family model (PRD #442). Each version row returned by
 * the backend carries `versionFamilyId`, lineage edges, and visibility
 * metadata, so the same dropdown UI serves contracts AND products without
 * one-off copies.
 */

export type EntityVersionRow = {
  id: string
  name?: string
  version?: string
  status?: string
  versionFamilyId?: string
  parentContractId?: string
  parentProductId?: string
  baseName?: string
  changeSummary?: string
  draftOwnerId?: string
  publicationScope?: string
  createdAt?: string
  updatedAt?: string
}

export type EntityKind = 'contract' | 'product'

type VersionSelectorProps = {
  entityKind: EntityKind
  currentEntityId: string
  currentVersion?: string
  // The 2nd arg gives callers access to the full row (status, change
  // summary, etc.) without re-fetching. Optional for back-compat — old
  // callers that take only the id still type-check.
  onVersionChange: (entityId: string, row?: EntityVersionRow) => void
  /**
   * Optional: an alternative endpoint, useful for tests or for a future
   * "family-by-id" route. When omitted, the component derives the URL
   * from `entityKind` + `currentEntityId`.
   */
  endpointOverride?: string
  // Lets parents override the trigger button look — used by the
  // EntityVersionPicker to make its inline sub-picker stretch full-width.
  triggerClassName?: string
}

function endpointFor(kind: EntityKind, id: string): string {
  if (kind === 'product') return `/api/data-products/${id}/versions`
  return `/api/data-contracts/${id}/versions`
}

function statusBadgeVariant(status?: string) {
  switch (status?.toLowerCase()) {
    case 'active':
    case 'published':
      return 'default' as const
    case 'draft':
      return 'secondary' as const
    case 'deprecated':
    case 'retired':
      return 'outline' as const
    default:
      return 'secondary' as const
  }
}

export default function VersionSelector({
  entityKind,
  currentEntityId,
  currentVersion,
  onVersionChange,
  endpointOverride,
  triggerClassName,
}: VersionSelectorProps) {
  const { toast } = useToast()
  const [versions, setVersions] = useState<EntityVersionRow[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const url = endpointOverride ?? endpointFor(entityKind, currentEntityId)

    const fetchVersions = async () => {
      setIsLoading(true)
      try {
        const response = await fetch(url)
        if (!response.ok) {
          if (!cancelled) setVersions([])
          return
        }
        const data = await response.json()
        if (!cancelled) setVersions(Array.isArray(data) ? data : [])
      } catch (err) {
        console.error('Error fetching versions:', err)
        if (!cancelled) {
          toast({
            title: 'Error',
            description: `Failed to load ${entityKind} versions`,
            variant: 'destructive',
          })
          setVersions([])
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    fetchVersions()
    return () => {
      cancelled = true
    }
  }, [entityKind, currentEntityId, endpointOverride, toast])

  if (versions.length <= 1) {
    // Family-of-one: nothing to switch between. Render nothing so the
    // surrounding toolbar doesn't show a pointless dropdown.
    return null
  }

  const handleSelect = (id: string) => {
    if (id !== currentEntityId) {
      const row = versions.find((v) => v.id === id)
      onVersionChange(id, row)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={isLoading} className={triggerClassName}>
          <History className="h-4 w-4 mr-2" />
          {currentVersion || 'Version'}
          <ChevronDown className="h-4 w-4 ml-2" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[340px]">
        <DropdownMenuLabel>
          Available Versions ({versions.length})
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {versions.map((v) => (
          <DropdownMenuItem
            key={v.id}
            onClick={() => handleSelect(v.id)}
            className={v.id === currentEntityId ? 'bg-accent' : ''}
          >
            <div className="flex flex-col gap-1 w-full">
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {v.version || 'Unknown'}
                  {v.id === currentEntityId && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      (current)
                    </span>
                  )}
                </span>
                <div className="flex items-center gap-1">
                  {v.draftOwnerId && (
                    <Badge
                      variant="outline"
                      className="text-xs bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200"
                    >
                      Personal
                    </Badge>
                  )}
                  {v.status && (
                    <Badge
                      variant={statusBadgeVariant(v.status)}
                      className="text-xs"
                    >
                      {v.status}
                    </Badge>
                  )}
                </div>
              </div>
              {v.changeSummary && (
                <span className="text-xs text-muted-foreground line-clamp-2">
                  {v.changeSummary}
                </span>
              )}
              {v.createdAt && (
                <span className="text-xs text-muted-foreground">
                  {new Date(v.createdAt).toLocaleDateString()}
                </span>
              )}
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// Re-export a small helper that the navigator uses to fetch the same
// versions list (kept here so both pieces stay in sync).
export async function fetchEntityVersions(
  kind: EntityKind,
  id: string,
): Promise<EntityVersionRow[]> {
  const res = await fetch(endpointFor(kind, id))
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? data : []
}
