/**
 * Unified picker for selecting a Data Contract or Data Product reference.
 *
 * Replaces every ad-hoc `<Select>` of contracts/products in the app. The
 * picker exposes two scopes (PRD #442):
 *
 *   - `entity`  — pin a specific version of an entity. Returned shape:
 *                 `{scope:'entity', entityKind, entityId, displayVersion?}`.
 *                 This is the safe back-compat default — existing storage
 *                 layers only need to persist `entityId`.
 *
 *   - `family`  — follow the family's latest visible version. Returned
 *                 shape: `{scope:'family', entityKind, familyId, familyName?}`.
 *                 Storage layers must persist `familyId` and resolve it via
 *                 the `/families/{familyId}/latest` endpoint at read time.
 *
 * Behavior is shaped by the `allowedScopes` prop:
 *   - Passing `['entity']` hides the scope toggle entirely and the picker
 *     behaves like a fancy combobox with versions on each row.
 *   - Passing `['entity','family']` shows the Entity ▾ / Latest ▾ toggle
 *     and renders an inline VersionSelector under the combobox when the
 *     user is in Entity mode.
 *
 * The picker fetches the *collapsed* list endpoint (one row per family)
 * by default and the per-family versions endpoint only when the user
 * opens the inline sub-picker, so cost scales with interaction depth
 * rather than catalog size.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ChevronsUpDown, Check, GitBranch, Pin, History } from 'lucide-react'
import { cn } from '@/lib/utils'
import VersionSelector, { type EntityVersionRow } from '@/components/common/version-selector'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EntityKind = 'contract' | 'product'

export type ScopeValue =
  | {
      scope: 'entity'
      entityKind: EntityKind
      entityId: string
      // Used purely for display restoration when the parent rehydrates
      // a saved value. The component itself does not rely on it.
      displayName?: string
      displayVersion?: string
    }
  | {
      scope: 'family'
      entityKind: EntityKind
      familyId: string
      displayName?: string
    }

type EntityVersionPickerProps = {
  entityKind: EntityKind
  value: ScopeValue | null
  onChange: (next: ScopeValue) => void
  allowedScopes?: Array<'entity' | 'family'>
  // Filter the candidate set to rows with these statuses. When omitted,
  // the picker shows whatever the backend returns for the caller (the
  // backend already applies role-aware visibility, so no client-side
  // filter is needed for the family-collapse case).
  statusFilter?: string[]
  placeholder?: string
  disabled?: boolean
  className?: string
  // Optional empty-state CTA, used by call sites that want an inline
  // "Create new contract" affordance under the dropdown.
  emptyAction?: React.ReactNode
}

// ---------------------------------------------------------------------------
// Row type (what the collapsed list endpoint returns)
// ---------------------------------------------------------------------------

type FamilyRow = {
  id: string
  name?: string
  version?: string
  status?: string
  versionFamilyId?: string
  // Both naming styles are accepted because /data-contracts and
  // /data-products use slightly different aliases today.
  version_count?: number
  versionCount?: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EntityVersionPicker({
  entityKind,
  value,
  onChange,
  allowedScopes = ['entity'],
  statusFilter,
  placeholder,
  disabled,
  className,
  emptyAction,
}: EntityVersionPickerProps) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<FamilyRow[]>([])
  const [loading, setLoading] = useState(false)
  const [scope, setScope] = useState<'entity' | 'family'>(value?.scope ?? allowedScopes[0])

  // Track the family the user has selected in entity mode so the sub-
  // picker only needs to fetch versions when one is actually chosen.
  const [pinnedFamilyAnchorId, setPinnedFamilyAnchorId] = useState<string | undefined>(
    value && value.scope === 'entity' ? value.entityId : undefined,
  )

  const apiBase = entityKind === 'contract' ? '/api/data-contracts' : '/api/data-products'

  useEffect(() => {
    let cancelled = false
    const fetchRows = async () => {
      setLoading(true)
      try {
        // When a statusFilter is set we need to consider ALL versions,
        // not just the family rep. Otherwise a family whose rep was
        // promoted to draft (under the elevated-rank rule) would
        // disappear from a status-restricted picker, even though it
        // has a perfectly valid published version available — see the
        // POS Transaction Stream regression hit during the smoke test.
        const wantsHistory = !!statusFilter?.length
        const url = wantsHistory ? `${apiBase}?include_history=true` : apiBase
        const res = await fetch(url)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data: FamilyRow[] = await res.json()
        if (cancelled) return
        let filtered = statusFilter
          ? data.filter((r) => statusFilter.includes((r.status || '').toLowerCase()))
          : data
        // Collapse client-side: one row per family, preferring the
        // newest matching version. Family counts are computed BEFORE
        // collapse so the badge still tells the user "this family has
        // 3 versions" even when only the published one is selectable.
        if (wantsHistory) {
          const counts = new Map<string, number>()
          for (const r of filtered) {
            const fid = r.versionFamilyId || r.id
            counts.set(fid, (counts.get(fid) || 0) + 1)
          }
          const picked = new Map<string, FamilyRow>()
          for (const r of filtered) {
            const fid = r.versionFamilyId || r.id
            const cur = picked.get(fid)
            // Lexicographic version compare is good enough here — every
            // version in the same family is semver-y by convention.
            if (!cur || (r.version || '') > (cur.version || '')) {
              picked.set(fid, r)
            }
          }
          filtered = Array.from(picked.values()).map((r) => ({
            ...r,
            versionCount: counts.get(r.versionFamilyId || r.id),
          }))
        }
        setRows(filtered)
      } catch (e) {
        console.warn(`[EntityVersionPicker] fetch failed for ${apiBase}`, e)
        if (!cancelled) setRows([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchRows()
    return () => {
      cancelled = true
    }
  }, [apiBase, statusFilter?.join('|')])

  // Resolve the currently-selected row for trigger display.
  const selectedRow = useMemo(() => {
    if (!value) return null
    if (value.scope === 'family') {
      return rows.find((r) => (r.versionFamilyId || r.id) === value.familyId) || null
    }
    // Entity mode: the entityId points to a specific version. The
    // collapsed list only has the family rep, so fall back to displayName
    // / displayVersion captured at selection time when available.
    return rows.find((r) => r.id === value.entityId) || null
  }, [value, rows])

  const triggerLabel = useMemo(() => {
    if (!value) return placeholder || `Select ${entityKind}…`
    if (value.scope === 'family') {
      const name = selectedRow?.name || value.displayName || value.familyId
      return `${name} (latest)`
    }
    const name = selectedRow?.name || value.displayName || value.entityId
    const version = selectedRow?.version || value.displayVersion
    return version ? `${name} · v${version}` : name
  }, [value, selectedRow, entityKind, placeholder])

  const showScopeToggle = allowedScopes.length > 1

  const handlePickFamily = (row: FamilyRow) => {
    const familyId = row.versionFamilyId || row.id
    if (scope === 'family') {
      onChange({
        scope: 'family',
        entityKind,
        familyId,
        displayName: row.name,
      })
      setOpen(false)
      return
    }
    // Entity mode: anchor on this family so the inline VersionSelector
    // can offer a per-version pin. Default the entity to the family's
    // representative (the row already in `rows`), but the user can refine
    // via the sub-picker before closing.
    setPinnedFamilyAnchorId(row.id)
    onChange({
      scope: 'entity',
      entityKind,
      entityId: row.id,
      displayName: row.name,
      displayVersion: row.version,
    })
  }

  const handlePickPinnedVersion = (versionRow: EntityVersionRow) => {
    onChange({
      scope: 'entity',
      entityKind,
      entityId: versionRow.id,
      displayName: versionRow.name,
      displayVersion: versionRow.version,
    })
    setOpen(false)
  }

  return (
    <div className={cn('space-y-2', className)}>
      {showScopeToggle && (
        <div className="inline-flex items-center rounded-md border border-border p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setScope('entity')}
            className={cn(
              'inline-flex items-center gap-1 rounded px-2 py-1 transition-colors',
              scope === 'entity'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            aria-pressed={scope === 'entity'}
            title="Pin a specific version"
          >
            <Pin className="h-3 w-3" />
            Pin version
          </button>
          <button
            type="button"
            onClick={() => setScope('family')}
            className={cn(
              'inline-flex items-center gap-1 rounded px-2 py-1 transition-colors',
              scope === 'family'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            aria-pressed={scope === 'family'}
            title="Always follow the family's latest visible version"
          >
            <GitBranch className="h-3 w-3" />
            Follow latest
          </button>
        </div>
      )}

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className="w-full justify-between font-normal"
          >
            <span className="truncate">{triggerLabel}</span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command>
            <CommandInput placeholder={`Search ${entityKind}s…`} />
            <CommandList>
              {loading ? (
                <CommandEmpty>Loading…</CommandEmpty>
              ) : (
                <>
                  <CommandEmpty>
                    No matching {entityKind}s.
                    {emptyAction && <div className="mt-2">{emptyAction}</div>}
                  </CommandEmpty>
                  <CommandGroup>
                    {rows.map((row) => {
                      const familyId = row.versionFamilyId || row.id
                      const versionCount = row.versionCount ?? row.version_count
                      const isSelected =
                        value?.scope === 'family'
                          ? value.familyId === familyId
                          : value?.entityId === row.id
                      return (
                        <CommandItem
                          key={familyId}
                          // Make name+version searchable, not just name —
                          // disambiguates same-named families per #69.
                          value={`${row.name || ''} ${row.version || ''}`}
                          onSelect={() => handlePickFamily(row)}
                          className="flex items-center gap-2"
                        >
                          <Check
                            className={cn(
                              'h-3.5 w-3.5',
                              isSelected ? 'opacity-100' : 'opacity-0',
                            )}
                          />
                          <span className="flex-1 truncate">{row.name || '(unnamed)'}</span>
                          {row.version && (
                            <Badge variant="secondary" className="text-[10px]">
                              v{row.version}
                            </Badge>
                          )}
                          {row.status && (
                            <Badge variant="outline" className="text-[10px]">
                              {row.status}
                            </Badge>
                          )}
                          {versionCount && versionCount > 1 && (
                            <span className="inline-flex items-center gap-0.5 rounded border border-border bg-muted/40 px-1 py-0.5 text-[10px] text-muted-foreground">
                              <History className="h-3 w-3" />
                              {versionCount}
                            </span>
                          )}
                        </CommandItem>
                      )
                    })}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Inline version sub-picker — only shown in Entity mode, and only
          once the user has anchored on a family. */}
      {scope === 'entity' && value?.scope === 'entity' && pinnedFamilyAnchorId && (
        <VersionSelector
          entityKind={entityKind}
          currentEntityId={pinnedFamilyAnchorId}
          currentVersion={value.displayVersion}
          onVersionChange={(_id, row) => row && handlePickPinnedVersion(row)}
          triggerClassName="w-full"
        />
      )}
    </div>
  )
}

export default EntityVersionPicker
