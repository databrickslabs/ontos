import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowRight, GitCompare, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { fetchEntityVersions, type EntityKind, type EntityVersionRow } from './version-selector'

/**
 * Shows how two versions of a versioned entity differ (PRD #1086).
 *
 * The backend renders both versions as their file model (ODCS / ODPS),
 * diffs them structurally and classifies each change as a major / minor /
 * patch bump, so the dialog is a pure view over `EntityDiffResponse`.
 */

export type BumpLabel = 'major' | 'minor' | 'patch' | 'none'

export type EntityDiffChange = {
  path: string
  op: 'added' | 'removed' | 'modified'
  old?: unknown
  new?: unknown
  bump: BumpLabel
  rule_id: string
  message: string
}

export type EntityDiffResponse = {
  entity_type: 'data_contract' | 'data_product'
  base: { id: string; name?: string; version?: string; status?: string }
  target: { id: string; name?: string; version?: string; status?: string }
  changes: EntityDiffChange[]
  counts: Record<BumpLabel, number>
  suggested_bump: BumpLabel
  suggested_version: string
  version_consistent: boolean | null
  unified_diff: string
}

const BUMP_ORDER: BumpLabel[] = ['major', 'minor', 'patch', 'none']

export function diffEndpointFor(kind: EntityKind, baseId: string, targetId: string): string {
  const base = kind === 'product' ? '/api/data-products' : '/api/data-contracts'
  return `${base}/${encodeURIComponent(baseId)}/diff/${encodeURIComponent(targetId)}`
}

export function bumpBadgeClass(bump: BumpLabel): string {
  switch (bump) {
    case 'major':
      return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200 border-red-200 dark:border-red-900'
    case 'minor':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200 border-amber-200 dark:border-amber-900'
    case 'patch':
      return 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200 border-sky-200 dark:border-sky-900'
    default:
      return 'bg-muted text-muted-foreground'
  }
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/**
 * The version a given version should be compared against to show "what
 * changed in it": its lineage parent when visible, else the next older
 * version in the family. Null for a family-of-one / the oldest version.
 */
export function pickBaseVersion(versions: EntityVersionRow[], entityId: string): string | null {
  const index = versions.findIndex((v) => v.id === entityId)
  if (index < 0) return null
  const row = versions[index]
  const parentId = row.parentContractId || row.parentProductId
  if (parentId && versions.some((v) => v.id === parentId)) return parentId
  return versions[index + 1]?.id ?? null
}

/** Order two versions oldest → newest using the newest-first versions list. */
export function orderPair(versions: EntityVersionRow[], a: string, b: string): [string, string] {
  const ia = versions.findIndex((v) => v.id === a)
  const ib = versions.findIndex((v) => v.id === b)
  return ia >= ib ? [a, b] : [b, a]
}

type EntityDiffDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  entityKind: EntityKind
  /**
   * Family versions, newest first (as returned by the /versions endpoint).
   * Fetched from `targetId`'s family when omitted.
   */
  versions?: EntityVersionRow[]
  baseId: string
  targetId: string
}

export default function EntityDiffDialog({
  open,
  onOpenChange,
  entityKind,
  versions: providedVersions,
  baseId: initialBaseId,
  targetId: initialTargetId,
}: EntityDiffDialogProps) {
  const { t } = useTranslation('common')
  const [baseId, setBaseId] = useState(initialBaseId)
  const [targetId, setTargetId] = useState(initialTargetId)
  const [diff, setDiff] = useState<EntityDiffResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedVersions, setFetchedVersions] = useState<EntityVersionRow[]>([])
  const versions = providedVersions ?? fetchedVersions

  useEffect(() => {
    if (!open || providedVersions) return
    let cancelled = false
    fetchEntityVersions(entityKind, initialTargetId)
      .then((rows) => {
        if (!cancelled) setFetchedVersions(rows)
      })
      .catch(() => {
        if (!cancelled) setFetchedVersions([])
      })
    return () => {
      cancelled = true
    }
  }, [open, providedVersions, entityKind, initialTargetId])

  // Re-seed the pair whenever the dialog is (re)opened for a new pair.
  useEffect(() => {
    if (open) {
      setBaseId(initialBaseId)
      setTargetId(initialTargetId)
    }
  }, [open, initialBaseId, initialTargetId])

  useEffect(() => {
    if (!open || !baseId || !targetId || baseId === targetId) {
      setDiff(null)
      setError(null)
      return
    }
    let cancelled = false
    setIsLoading(true)
    setError(null)
    setDiff(null) // don't show the previous pair's bump while the new one loads
    fetch(diffEndpointFor(entityKind, baseId, targetId))
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status))
        return (await res.json()) as EntityDiffResponse
      })
      .then((data) => {
        if (!cancelled) setDiff(data)
      })
      .catch(() => {
        if (!cancelled) {
          setDiff(null)
          setError(t('entityDiff.loadError'))
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, entityKind, baseId, targetId, t])

  const grouped = useMemo(() => {
    const groups: Record<BumpLabel, EntityDiffChange[]> = { major: [], minor: [], patch: [], none: [] }
    for (const change of diff?.changes ?? []) groups[change.bump].push(change)
    return groups
  }, [diff])

  const versionLabel = (v: EntityVersionRow) =>
    `${v.version || t('entityDiff.unknownVersion')}${v.status ? ` · ${v.status}` : ''}`

  const versionPicker = (value: string, onChange: (id: string) => void, label: string) => (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-[220px]" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {versions.map((v) => (
          <SelectItem key={v.id} value={v.id}>
            {versionLabel(v)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitCompare className="h-5 w-5" />
            {t('entityDiff.title')}
          </DialogTitle>
          <DialogDescription>{t('entityDiff.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          {versionPicker(baseId, setBaseId, t('entityDiff.baseVersion'))}
          <ArrowRight className="h-4 w-4 text-muted-foreground" />
          {versionPicker(targetId, setTargetId, t('entityDiff.targetVersion'))}
          {diff && (
            <div className="ml-auto flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">{t('entityDiff.suggestedBump')}</span>
              <Badge variant="outline" className={bumpBadgeClass(diff.suggested_bump)}>
                {t(`entityDiff.bump.${diff.suggested_bump}`)}
              </Badge>
              {diff.suggested_bump !== 'none' && (
                <span className="font-mono">→ {diff.suggested_version}</span>
              )}
            </div>
          )}
        </div>

        {baseId === targetId && (
          <p className="text-sm text-muted-foreground">{t('entityDiff.sameVersion')}</p>
        )}

        {diff?.version_consistent === false && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              {t('entityDiff.versionInconsistent', {
                target: diff.target.version,
                bump: t(`entityDiff.bump.${diff.suggested_bump}`),
                suggested: diff.suggested_version,
              })}
            </AlertDescription>
          </Alert>
        )}

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> {t('entityDiff.loading')}
          </div>
        )}
        {error && !isLoading && <p className="text-sm text-destructive">{error}</p>}

        {diff && !isLoading && (
          <Tabs defaultValue="changes" className="flex-1 min-h-0 flex flex-col">
            <TabsList className="self-start">
              <TabsTrigger value="changes">
                {t('entityDiff.tabs.changes', { count: diff.changes.length })}
              </TabsTrigger>
              <TabsTrigger value="yaml">{t('entityDiff.tabs.yaml')}</TabsTrigger>
            </TabsList>

            <TabsContent value="changes" className="flex-1 min-h-0 overflow-auto">
              {diff.changes.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">{t('entityDiff.noChanges')}</p>
              ) : (
                <div className="space-y-4">
                  {BUMP_ORDER.filter((b) => grouped[b].length > 0).map((bump) => (
                    <section key={bump}>
                      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                        <Badge variant="outline" className={bumpBadgeClass(bump)}>
                          {t(`entityDiff.bump.${bump}`)}
                        </Badge>
                        <span className="text-muted-foreground font-normal">{grouped[bump].length}</span>
                      </h4>
                      <ul className="space-y-1">
                        {grouped[bump].map((c) => (
                          <li key={`${c.op}:${c.path}`} className="rounded border px-3 py-2 text-sm">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium">{c.message}</span>
                              <span className="text-xs text-muted-foreground">{t(`entityDiff.op.${c.op}`)}</span>
                            </div>
                            <code className="block text-xs text-muted-foreground break-all">{c.path}</code>
                            {c.op === 'modified' && (
                              <div className="mt-1 font-mono text-xs break-all">
                                <span className="text-red-700 dark:text-red-300 line-through">{formatValue(c.old)}</span>
                                <span className="mx-2 text-muted-foreground">→</span>
                                <span className="text-green-700 dark:text-green-300">{formatValue(c.new)}</span>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="yaml" className="flex-1 min-h-0 overflow-auto">
              {diff.unified_diff ? (
                <pre className="rounded border bg-muted/30 p-3 text-xs leading-5 overflow-x-auto">
                  {diff.unified_diff.split('\n').map((line, i) => (
                    <div
                      key={i}
                      className={cn(
                        line.startsWith('+') && !line.startsWith('+++') && 'bg-green-100/70 text-green-900 dark:bg-green-950/60 dark:text-green-200',
                        line.startsWith('-') && !line.startsWith('---') && 'bg-red-100/70 text-red-900 dark:bg-red-950/60 dark:text-red-200',
                        line.startsWith('@@') && 'text-sky-700 dark:text-sky-300',
                        (line.startsWith('+++') || line.startsWith('---')) && 'font-semibold',
                      )}
                    >
                      {line || ' '}
                    </div>
                  ))}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground py-6 text-center">{t('entityDiff.noChanges')}</p>
              )}
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  )
}
