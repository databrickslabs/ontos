import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ChevronDown,
  ChevronRight,
  Columns2,
  Database,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  Globe,
  Link2,
  Loader2,
  Package,
  Plus,
  Shapes,
  Table,
  Trash2,
} from 'lucide-react'
import { useApi } from '@/hooks/use-api'
import { useToast } from '@/hooks/use-toast'
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store'

interface SemanticLink {
  id: string
  entity_id: string
  entity_type: string
  iri: string
  label?: string
  // Optional chain hint: when an asset link resolves *through* a data
  // contract or data product, the backend may point it at that parent so we
  // can render it as a nested child row. Absent for direct concept->asset
  // links, which stay at the top level.
  parent_entity_id?: string
}

interface EnrichedSemanticLink extends SemanticLink {
  entity_name?: string
}

interface LinkedObjectsPanelProps {
  conceptIri: string
  conceptLabel: string
  canAssign: boolean
  onChanged?: () => void
  // When set, the linked-objects list scrolls internally past this row
  // count instead of growing the page (rows are ~32px high).
  maxVisibleRows?: number
}

const ENTITY_ICONS: Record<string, typeof FileText> = {
  data_contract: FileText,
  data_product: Package,
  asset: Database,
  data_domain: Globe,
  uc_catalog: Folder,
  uc_schema: FolderOpen,
  uc_table: Table,
  uc_column: Columns2,
  data_contract_schema: Shapes,
  data_contract_property: Columns2,
}

// Same colour vocabulary as NodeLinksPanel relationshipColors so the badges
// look at home next to the ontology relations panel above.
const ENTITY_TYPE_COLORS: Record<string, string> = {
  data_product: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  data_contract: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  asset: 'bg-rose-500/10 text-rose-600 border-rose-500/30',
  data_domain: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/30',
  uc_catalog: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  uc_schema: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  uc_table: 'bg-orange-500/10 text-orange-600 border-orange-500/30',
  uc_column: 'bg-orange-500/10 text-orange-600 border-orange-500/30',
  data_contract_schema: 'bg-violet-500/10 text-violet-600 border-violet-500/30',
  data_contract_property: 'bg-purple-500/10 text-purple-600 border-purple-500/30',
}

const iconFor = (entityType: string) => ENTITY_ICONS[entityType] ?? FileText

const formatEntityType = (entityType: string) =>
  entityType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export default function LinkedObjectsPanel({
  conceptIri,
  conceptLabel,
  canAssign,
  onChanged,
  maxVisibleRows,
}: LinkedObjectsPanelProps) {
  const ROW_HEIGHT_PX = 32
  const listMaxHeight = maxVisibleRows
    ? { maxHeight: ROW_HEIGHT_PX * maxVisibleRows }
    : undefined
  const { get, post, delete: deleteLink } = useApi()
  const { toast } = useToast()
  const navigate = useNavigate()
  const { t } = useTranslation(['search', 'common', 'semantic-models'])
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce)

  const [links, setLinks] = useState<EnrichedSemanticLink[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [open, setOpen] = useState(true)

  // Assign dialog state
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)
  const [selectedEntityType, setSelectedEntityType] = useState('')
  const [selectedEntityId, setSelectedEntityId] = useState('')
  const [availableEntities, setAvailableEntities] = useState<any[]>([])

  // Single-link removal confirm dialog: holds the link awaiting confirmation.
  const [linkPendingRemoval, setLinkPendingRemoval] = useState<EnrichedSemanticLink | null>(null)
  const [isRemoving, setIsRemoving] = useState(false)

  const enrichLinks = useCallback(
    async (raw: SemanticLink[]): Promise<EnrichedSemanticLink[]> => {
      const enriched: EnrichedSemanticLink[] = []
      for (const link of raw) {
        try {
          let endpoint = ''
          let entityName: string | undefined = link.entity_id

          switch (link.entity_type) {
            case 'data_product':
              endpoint = `/api/data-products/${link.entity_id}`
              break
            case 'data_contract':
              endpoint = `/api/data-contracts/${link.entity_id}`
              break
            case 'asset':
              endpoint = `/api/assets/${link.entity_id}`
              break
            case 'data_domain':
              endpoint = `/api/data-domains/${link.entity_id}`
              break
            case 'data_contract_schema': {
              const [contractId, schemaName] = String(link.entity_id).split('#')
              if (contractId) {
                const contractRes = await get<any>(`/api/data-contracts/${contractId}`)
                const title =
                  contractRes.data?.name || contractRes.data?.info?.title || contractId
                entityName = `${title}#${schemaName || ''}`.trim()
              }
              enriched.push({ ...link, entity_name: entityName })
              continue
            }
            case 'data_contract_property': {
              const [contractId, schemaName, propertyName] = String(link.entity_id).split('#')
              if (contractId) {
                const contractRes = await get<any>(`/api/data-contracts/${contractId}`)
                const title =
                  contractRes.data?.name || contractRes.data?.info?.title || contractId
                entityName = `${title}#${schemaName || ''}.${propertyName || ''}`.trim()
              }
              enriched.push({ ...link, entity_name: entityName })
              continue
            }
            case 'uc_catalog':
            case 'uc_schema':
            case 'uc_table':
            case 'uc_column':
              // entity_id is already the human-readable full name
              enriched.push({ ...link, entity_name: link.entity_id })
              continue
            default:
              enriched.push({ ...link, entity_name: link.entity_id })
              continue
          }

          if (endpoint) {
            const entityRes = await get<any>(endpoint)
            if (entityRes.data && !entityRes.error) {
              entityName =
                entityRes.data.name ||
                entityRes.data.info?.title ||
                entityRes.data.title ||
                link.entity_id
            }
          }
          enriched.push({ ...link, entity_name: entityName })
        } catch (error) {
          console.error('LinkedObjectsPanel: failed to enrich link', link, error)
          enriched.push({ ...link, entity_name: link.entity_id })
        }
      }
      return enriched
    },
    [get]
  )

  const fetchLinks = useCallback(async () => {
    if (!conceptIri) {
      setLinks([])
      return
    }
    setIsLoading(true)
    try {
      // Query-param form (``?iri=``) is required: IRIs containing ``//`` (e.g.
      // ``https://...#Invoice``) get their ``%2F%2F`` collapsed by the Apps
      // proxy on the path form, which 301s to a mangled path and returns [].
      const res = await get<SemanticLink[]>(
        `/api/semantic-links/by-iri?iri=${encodeURIComponent(conceptIri)}`
      )
      const raw = res.data || []
      const enriched = await enrichLinks(raw)
      setLinks(enriched)
    } catch (error) {
      console.error('LinkedObjectsPanel: failed to load links', error)
      setLinks([])
    } finally {
      setIsLoading(false)
    }
  }, [conceptIri, get, enrichLinks])

  useEffect(() => {
    fetchLinks()
  }, [fetchLinks])

  const loadEntitiesForType = useCallback(
    async (entityType: string) => {
      try {
        if (entityType === 'asset') {
          // /api/assets returns a PaginatedAssetSummary { items, total, ... }
          const res = await get<{ items: any[] }>('/api/assets?limit=500')
          setAvailableEntities(res.data?.items || [])
          return
        }

        let endpoint = ''
        switch (entityType) {
          case 'data_product':
            endpoint = '/api/data-products'
            break
          case 'data_contract':
            endpoint = '/api/data-contracts'
            break
          default:
            setAvailableEntities([])
            return
        }
        const res = await get<any[]>(endpoint)
        setAvailableEntities(res.data || [])
      } catch (error) {
        console.error('LinkedObjectsPanel: failed to load entities for', entityType, error)
        setAvailableEntities([])
      }
    },
    [get]
  )

  const handleEntityTypeChange = (entityType: string) => {
    setSelectedEntityType(entityType)
    setSelectedEntityId('')
    loadEntitiesForType(entityType)
  }

  const getEntityTypeLabel = (entityType: string): string => {
    switch (entityType) {
      case 'data_product':
        return t('search:concepts.assignDialog.dataProduct')
      case 'data_contract':
        return t('search:concepts.assignDialog.dataContract')
      case 'asset':
        return t('search:concepts.assignDialog.asset', { defaultValue: 'Asset' })
      case 'data_domain':
        return t('search:concepts.assignDialog.dataDomain')
      case 'uc_catalog':
        return t('search:concepts.assignDialog.ucCatalog')
      case 'uc_schema':
        return t('search:concepts.assignDialog.ucSchema')
      case 'uc_table':
        return t('search:concepts.assignDialog.ucTable')
      default:
        return formatEntityType(entityType)
    }
  }

  const navigateToEntity = (link: EnrichedSemanticLink) => {
    switch (link.entity_type) {
      case 'data_product':
        // A link's entity_id is the product's real id (the "Link asset" action
        // stores the resolved id). Navigate straight to its detail page.
        navigate(`/data-products/${link.entity_id}`)
        return
      case 'data_contract':
        navigate(`/data-contracts/${link.entity_id}`)
        return
      case 'data_contract_schema':
      case 'data_contract_property': {
        // entity_id is {contractId}#{schema}[#{property}] — navigate to the
        // parent contract (the schema/property live inside it).
        const contractId = String(link.entity_id).split('#')[0]
        navigate(`/data-contracts/${contractId}`)
        return
      }
      case 'asset':
        navigate(`/assets/${link.entity_id}`)
        return
      case 'data_domain':
        navigate(`/settings/data-domains/${link.entity_id}`)
        return
      case 'uc_catalog':
      case 'uc_schema':
      case 'uc_table':
      case 'uc_column': {
        // Deep-link into catalog-commander. The route accepts a ?table=<fqn>
        // param (see navigateToTable in catalog-commander.tsx) that expands the
        // catalog/schema and pre-selects the table. It needs a full
        // catalog.schema.table FQN (>=3 parts); for a column FQN
        // (catalog.schema.table.column) we pass just the table portion so the
        // parent table is selected. Catalog/schema-level links have no table to
        // pre-select, so they open the browser root.
        const fqn = String(link.entity_id)
        const parts = fqn.split('.')
        let tableParam: string | null = null
        if (link.entity_type === 'uc_table' && parts.length >= 3) {
          tableParam = fqn
        } else if (link.entity_type === 'uc_column' && parts.length >= 4) {
          tableParam = parts.slice(0, 3).join('.')
        }
        navigate(
          tableParam
            ? `/catalog-commander?table=${encodeURIComponent(tableParam)}`
            : '/catalog-commander',
        )
        const ucLabel =
          link.entity_type === 'uc_catalog'
            ? t('search:concepts.linkedUCCatalog')
            : link.entity_type === 'uc_schema'
              ? t('search:concepts.linkedUCSchema')
              : link.entity_type === 'uc_column'
                ? t('search:concepts.linkedUCColumn')
                : t('search:concepts.linkedUCTable')
        toast({ title: ucLabel, description: link.entity_name || link.entity_id })
        return
      }
      default:
        toast({
          title: t('common:toast.error'),
          description: t('search:concepts.messages.navigationError', {
            entityType: link.entity_type,
          }),
          variant: 'destructive',
        })
    }
  }

  const completeAssignment = async (
    entityType: string,
    _entityId: string,
    successDescriptionId: string
  ) => {
    bumpKnowledgeGraphRefresh('semantic-link-mutated')
    onChanged?.()
    await fetchLinks()
    toast({
      title: t('common:toast.success'),
      description: t('search:concepts.messages.linkedSuccess', {
        label: conceptLabel,
        entityType: getEntityTypeLabel(entityType),
        entityId: successDescriptionId,
      }),
    })
  }

  const handleAssignToObject = async () => {
    if (!conceptIri || !selectedEntityType || !selectedEntityId) {
      toast({
        title: t('common:toast.error'),
        description: t('search:concepts.messages.assignError'),
        variant: 'destructive',
      })
      return
    }
    try {
      const res = await post('/api/semantic-links/', {
        entity_id: selectedEntityId,
        entity_type: selectedEntityType,
        iri: conceptIri,
      })
      if (res.error) throw new Error(res.error)

      setAssignDialogOpen(false)
      const finishedType = selectedEntityType
      const finishedId = selectedEntityId
      setSelectedEntityType('')
      setSelectedEntityId('')
      await completeAssignment(finishedType, finishedId, finishedId)
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('search:concepts.messages.assignFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleRemoveLink = async () => {
    const link = linkPendingRemoval
    if (!link) return
    setIsRemoving(true)
    try {
      const res = await deleteLink(`/api/semantic-links/${link.id}`)
      if (res.error) throw new Error(res.error)

      setLinkPendingRemoval(null)
      bumpKnowledgeGraphRefresh('semantic-link-mutated')
      onChanged?.()
      await fetchLinks()
      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:linkedObjects.removed', {
          label: link.entity_name || link.entity_id,
          defaultValue: 'Removed link to "{{label}}".',
        }),
      })
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description:
          error?.message ||
          t('semantic-models:linkedObjects.removeFailed', {
            defaultValue: 'Failed to remove link.',
          }),
        variant: 'destructive',
      })
    } finally {
      setIsRemoving(false)
    }
  }

  // One flat list, but assets that resolve *through* a linked contract or
  // product are nested as indented child rows under that parent (chain:
  // concept -> contract/product -> asset). Links without a resolvable parent
  // stay at the top level (direct concept -> asset). Data fetching is
  // untouched; this only reorders/indents what fetchLinks already produced.
  const orderedLinks = (() => {
    const byId = new Map(links.map((l) => [l.entity_id, l]))
    const children = new Map<string, EnrichedSemanticLink[]>()
    const roots: EnrichedSemanticLink[] = []
    for (const link of links) {
      const parentId = link.parent_entity_id
      if (parentId && byId.has(parentId) && parentId !== link.entity_id) {
        const bucket = children.get(parentId) ?? []
        bucket.push(link)
        children.set(parentId, bucket)
      } else {
        roots.push(link)
      }
    }
    const out: Array<{ link: EnrichedSemanticLink; depth: number }> = []
    for (const root of roots) {
      out.push({ link: root, depth: 0 })
      for (const child of children.get(root.entity_id) ?? []) {
        out.push({ link: child, depth: 1 })
      }
    }
    return out
  })()

  // Aligned columns: [icon] name … [type pill] [Open] [remove]. The name cell
  // flexes; the trailing cells keep a fixed footprint so every row lines up.
  const renderLinkRow = (link: EnrichedSemanticLink, depth = 0) => {
    const Icon = iconFor(link.entity_type)
    const typeLabel = getEntityTypeLabel(link.entity_type)
    const colour = ENTITY_TYPE_COLORS[link.entity_type] || ''
    return (
      <div
        key={link.id}
        data-testid={`linked-object-${link.id}`}
        data-depth={depth}
        className={`flex items-center gap-2 py-1.5 px-2 rounded hover:bg-muted/50 group ${
          depth > 0 ? 'ml-4 border-l pl-3' : ''
        }`}
      >
        <Icon className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
        <button
          type="button"
          className="text-sm text-primary hover:underline text-left truncate flex-1 min-w-0"
          onClick={() => navigateToEntity(link)}
          title={`${typeLabel}: ${link.entity_name || link.entity_id} • ${link.iri}`}
        >
          {link.entity_name || link.entity_id}
        </button>
        <Badge
          variant="outline"
          className={`text-xs flex-shrink-0 ${colour}`}
        >
          {typeLabel}
        </Badge>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground flex-shrink-0 w-14 justify-end"
          onClick={() => navigateToEntity(link)}
          aria-label={t('semantic-models:linkedObjects.open', {
            defaultValue: 'Open',
          })}
        >
          {t('semantic-models:linkedObjects.open', { defaultValue: 'Open' })}
          <ExternalLink className="h-3 w-3" />
        </button>
        {canAssign ? (
          <Button
            variant="ghost"
            size="icon"
            data-testid={`linked-object-remove-${link.id}`}
            aria-label={t('semantic-models:linkedObjects.removeAria', {
              defaultValue: 'Remove linked entity',
            })}
            className="h-6 w-6 opacity-0 group-hover:opacity-100 flex-shrink-0"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              setLinkPendingRemoval(link)
            }}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        ) : (
          <span className="w-6 flex-shrink-0" aria-hidden="true" />
        )}
      </div>
    )
  }

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
            <Link2 className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">
              {t('semantic-models:linkedObjects.title', {
                defaultValue: 'Linked Entities',
              })}
            </span>
            <Badge variant="secondary" className="text-xs">
              {links.length}
            </Badge>
          </div>

          {canAssign && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7"
              data-testid="linked-objects-assign-button"
              onClick={(e) => {
                e.stopPropagation()
                setAssignDialogOpen(true)
              }}
            >
              <Plus className="h-3 w-3 mr-1" />
              {t('common:actions.add')}
            </Button>
          )}
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div
            className={`border-t px-2 py-1 ${maxVisibleRows ? 'overflow-y-auto' : ''}`}
            style={listMaxHeight}
            data-testid="linked-objects-list"
          >
            {isLoading && links.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-2 px-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t('semantic-models:linkedObjects.loading', {
                  defaultValue: 'Loading linked entities...',
                })}
              </div>
            ) : links.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2 px-2">
                {t('semantic-models:linkedObjects.empty', {
                  defaultValue: 'No entities linked to this concept.',
                })}
              </p>
            ) : (
              orderedLinks.map(({ link, depth }) => renderLinkRow(link, depth))
            )}
          </div>
        </CollapsibleContent>
      </div>

      {/* Assign dialog */}
      <Dialog open={assignDialogOpen} onOpenChange={setAssignDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('search:concepts.assignDialog.title')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm">
              <p className="font-medium">{conceptLabel}</p>
              <p className="text-muted-foreground font-mono text-xs break-all">{conceptIri}</p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t('search:concepts.assignDialog.entityType')}
              </label>
              <Select value={selectedEntityType} onValueChange={handleEntityTypeChange}>
                <SelectTrigger>
                  <SelectValue
                    placeholder={t('search:concepts.assignDialog.selectEntityType')}
                  />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="data_product">
                    {t('search:concepts.assignDialog.dataProduct')}
                  </SelectItem>
                  <SelectItem value="data_contract">
                    {t('search:concepts.assignDialog.dataContract')}
                  </SelectItem>
                  <SelectItem value="asset">
                    {t('search:concepts.assignDialog.asset', { defaultValue: 'Asset' })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {selectedEntityType && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {getEntityTypeLabel(selectedEntityType)}
                </label>
                <Select value={selectedEntityId} onValueChange={setSelectedEntityId}>
                  <SelectTrigger>
                    <SelectValue
                      placeholder={t('search:concepts.assignDialog.selectEntity', {
                        entityType: getEntityTypeLabel(selectedEntityType),
                      })}
                    />
                  </SelectTrigger>
                  <SelectContent className="max-h-72 overflow-y-auto">
                    {availableEntities.map((entity) => {
                      const label =
                        entity.name || entity.info?.title || entity.title || entity.id
                      const subLabel =
                        selectedEntityType === 'asset' && entity.asset_type_name
                          ? entity.asset_type_name
                          : null
                      return (
                        <SelectItem key={entity.id} value={entity.id}>
                          <span className="flex items-center gap-2">
                            <span>{label}</span>
                            {subLabel && (
                              <span className="text-xs text-muted-foreground">
                                · {subLabel}
                              </span>
                            )}
                          </span>
                        </SelectItem>
                      )
                    })}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex justify-end space-x-2 pt-4">
              <Button variant="outline" onClick={() => setAssignDialogOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                onClick={handleAssignToObject}
                disabled={!selectedEntityType || !selectedEntityId}
                data-testid="linked-objects-assign-confirm"
              >
                {t('common:actions.assign')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Remove-link confirm dialog */}
      <AlertDialog
        open={linkPendingRemoval !== null}
        onOpenChange={(open) => {
          if (!open) setLinkPendingRemoval(null)
        }}
      >
        <AlertDialogContent data-testid="linked-object-remove-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('semantic-models:linkedObjects.removeConfirmTitle', {
                defaultValue: 'Remove this link?',
              })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('semantic-models:linkedObjects.removeConfirmBody', {
                label: linkPendingRemoval?.entity_name || linkPendingRemoval?.entity_id,
                defaultValue:
                  'This unlinks "{{label}}" from this concept. It does not delete the entity itself.',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRemoving}>
              {t('common:actions.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              data-testid="linked-object-remove-confirm-button"
              disabled={isRemoving}
              onClick={(e) => {
                // Keep the dialog mounted until the request resolves so we can
                // surface an error toast without it closing underneath us.
                e.preventDefault()
                handleRemoveLink()
              }}
            >
              {t('common:actions.remove', { defaultValue: 'Remove' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Collapsible>
  )
}
