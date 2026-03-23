import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertCircle, Download, Pencil, Trash2, Loader2, ArrowLeft, FileText, KeyRound, CopyPlus, Plus, Shapes, Columns2, Database, Sparkles, Table2, Package, ChevronLeft, ChevronRight } from 'lucide-react'
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DataTable } from '@/components/ui/data-table'
import { ColumnDef } from '@tanstack/react-table'
import { useToast } from '@/hooks/use-toast'
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel'
import EntityQualityPanel from '@/components/quality/entity-quality-panel'
import { OwnershipPanel } from '@/components/common/ownership-panel'
import { EntityTreePanel } from '@/components/common/entity-tree-panel'
import { CommentSidebar } from '@/components/comments'
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog'
import LinkedConceptChips from '@/components/semantic/linked-concept-chips'
import TagChip from '@/components/ui/tag-chip'
import { useDomains } from '@/hooks/use-domains'
import { usePermissions } from '@/stores/permissions-store'
import { useUserStore } from '@/stores/user-store'
import { FeatureAccessLevel } from '@/types/settings'
import type { EntitySemanticLink } from '@/types/semantic-link'
import type { DataContract, SchemaObject, QualityRule, TeamMember, ServerConfig, SLARequirements } from '@/types/data-contract'
import useBreadcrumbStore from '@/stores/breadcrumb-store'
import RequestContractActionDialog from '@/components/data-contracts/request-contract-action-dialog'
import CreateVersionDialog from '@/components/data-products/create-version-dialog'
import DataContractBasicFormDialog from '@/components/data-contracts/data-contract-basic-form-dialog'
import SchemaFormDialog from '@/components/data-contracts/schema-form-dialog'
import QualityRuleFormDialog from '@/components/data-contracts/quality-rule-form-dialog'
import TeamMemberFormDialog from '@/components/data-contracts/team-member-form-dialog'
import ServerConfigFormDialog from '@/components/data-contracts/server-config-form-dialog'
import SLAFormDialog from '@/components/data-contracts/sla-form-dialog'
import InferFromCatalogDialog from '@/components/data-contracts/infer-from-catalog-dialog'
import type { CatalogSchemaResult } from '@/components/data-contracts/infer-from-catalog-dialog'
import InferFromAssetDialog from '@/components/data-contracts/infer-from-asset-dialog'
import type { InferredSchemaObject } from '@/components/data-contracts/infer-from-asset-dialog'
import CreateFromContractDialog from '@/components/data-products/create-from-contract-dialog'
import DqxSchemaSelectDialog from '@/components/data-contracts/dqx-schema-select-dialog'
import DqxSuggestionsDialog from '@/components/data-contracts/dqx-suggestions-dialog'
import AuthoritativeDefinitionFormDialog from '@/components/data-contracts/authoritative-definition-form-dialog'
import ImportTeamMembersDialog from '@/components/data-contracts/import-team-members-dialog'
import LinkProductToContractDialog from '@/components/data-contracts/link-product-to-contract-dialog'
import LinkDatasetToContractDialog from '@/components/data-contracts/link-dataset-to-contract-dialog'
import VersioningRecommendationDialog from '@/components/common/versioning-recommendation-dialog'
import CustomPropertyFormDialog from '@/components/data-contracts/custom-property-form-dialog'
import CommitDraftDialog from '@/components/data-contracts/commit-draft-dialog'
import VersionSelector from '@/components/data-contracts/version-selector'
import type { DataProduct } from '@/types/data-product'
import type { DataProfilingRun } from '@/types/data-contract'
import type { DatasetListItem } from '@/types/dataset'
import { DATASET_STATUS_LABELS, DATASET_STATUS_COLORS } from '@/types/dataset'
import { useCopilotContext } from '@/hooks/use-copilot-context'

// Status-based editability constants
// Only draft/proposed contracts can be edited in place
const EDITABLE_STATUSES = ['draft', 'proposed']

// View mode for filtering contract details sections
type ViewMode = 'minimal' | 'medium' | 'large'
const VIEW_MODE_STORAGE_KEY = 'data-contract-view-mode'

// Define column structure for schema properties
type SchemaProperty = {
  name: string
  logicalType?: string
  logical_type?: string  // API response uses underscore
  required: boolean
  unique: boolean
  description?: string
}

// Define this as a function to access component state
const createSchemaPropertyColumns = (
  contract: DataContract | null,
  selectedSchemaIndex: number,
  propertyLinks: Record<string, EntitySemanticLink[]>,
): ColumnDef<SchemaProperty>[] => [
  {
    accessorKey: 'name',
    header: 'Column Name',
    cell: ({ row }) => {
      const property = row.original
      const schemaName = contract?.schema?.[selectedSchemaIndex]?.name || ''
      const propertyKey = `${schemaName}#${property.name}`
      const links = propertyLinks[propertyKey] || []

      const getLabel = (iri: string, label?: string) => (label && !/^https?:\/\//.test(label) && !/^urn:/.test(label)) ? label : (iri.split(/[\/#]/).pop() || iri)
      return (
        <div>
          <span className="font-mono font-medium">{property.name}</span>
          {links.length > 0 && (
            <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-2">
              {links.map((link, idx) => {
                const displayLabel = getLabel(link.iri, link.label)
                return (
                  <span key={idx} className="inline-flex items-center gap-1">
                    <Columns2 className="h-3 w-3" />
                    <span
                      className="cursor-pointer hover:underline"
                      onClick={() => window.open(`/data-catalog?concept=${encodeURIComponent(displayLabel)}`, '_blank')}
                      title={link.iri}
                    >
                      {displayLabel}
                    </span>
                  </span>
                )
              })}
            </div>
          )}
        </div>
      )
    },
  },
  {
    accessorKey: 'logicalType',
    header: 'Data Type',
    cell: ({ row }) => {
      const property = row.original
      const logicalType = property.logicalType || (property as any).logical_type
      return (
        <Badge variant="secondary" className="text-xs">
          {logicalType || '-'}
        </Badge>
      )
    },
  },
  {
    accessorKey: 'required',
    header: 'Required',
    cell: ({ row }) => (
      <span className="text-center block">
        {row.getValue('required') ? '✓' : '✗'}
      </span>
    ),
  },
  {
    accessorKey: 'unique',
    header: 'Unique',
    cell: ({ row }) => (
      <span className="text-center block">
        {row.getValue('unique') ? '✓' : '✗'}
      </span>
    ),
  },
  {
    accessorKey: 'description',
    header: 'Description',
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {row.getValue('description') || '-'}
      </span>
    ),
  },
]

const formatDate = (dateString: string | undefined, fallback: string = 'N/A'): string => {
  if (!dateString) return fallback;
  try {
    return new Date(dateString).toLocaleString();
  } catch (e) {
    return 'Invalid Date';
  }
};

const getStatusColor = (status: string | undefined): 'default' | 'secondary' | 'destructive' | 'outline' => {
  const lowerStatus = status?.toLowerCase() || '';
  if (lowerStatus === 'active' || lowerStatus === 'approved' || lowerStatus === 'certified') return 'default';
  if (lowerStatus === 'draft' || lowerStatus === 'proposed') return 'secondary';
  if (lowerStatus === 'retired' || lowerStatus === 'deprecated' || lowerStatus === 'rejected') return 'outline';
  return 'default';
};

export default function DataContractDetails() {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { contractId } = useParams<{ contractId: string }>()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const listPath = pathname.replace(/\/[^/]+$/, '')
  const productBasePath = '/data-products'
  const { toast } = useToast()
  const { getDomainName } = useDomains()
  const { getPermissionLevel } = usePermissions()
  const { userInfo, fetchUserInfo } = useUserStore()

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments)
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle)

  const [contract, setContract] = useState<DataContract | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false)
  const [iriDialogOpen, setIriDialogOpen] = useState(false)
  const [isRequestDialogOpen, setIsRequestDialogOpen] = useState(false)
  const [isVersionDialogOpen, setIsVersionDialogOpen] = useState(false)
  const [isVersioningDialogOpen, setIsVersioningDialogOpen] = useState(false)
  const [versioningAnalysis, setVersioningAnalysis] = useState<any>(null)
  const [versioningUserCanOverride, setVersioningUserCanOverride] = useState(false)
  const [pendingUpdate, setPendingUpdate] = useState<any>(null)
  const [links, setLinks] = useState<EntitySemanticLink[]>([])
  const [selectedSchemaIndex, setSelectedSchemaIndex] = useState(0)
  const [schemaLinks, setSchemaLinks] = useState<Record<string, EntitySemanticLink[]>>({})
  const [propertyLinks] = useState<Record<string, EntitySemanticLink[]>>({})

  // Lazy-loaded schema properties with pagination
  const [schemaProperties, setSchemaProperties] = useState<Record<string, SchemaProperty[]>>({})
  const [schemaPropTotal, setSchemaPropTotal] = useState<Record<string, number>>({})
  const [schemaPropPage, setSchemaPropPage] = useState<Record<string, number>>({})
  const [loadingSchemaProps, setLoadingSchemaProps] = useState(false)
  const PROPS_PAGE_SIZE = 50

  // All properties for the edit dialog (fetched with limit=0, bypasses pagination)
  const [allSchemaProperties, setAllSchemaProperties] = useState<Record<string, SchemaProperty[]>>({})
  const [loadingEditProperties, setLoadingEditProperties] = useState(false)

  // Linked products state
  const [linkedProducts, setLinkedProducts] = useState<DataProduct[]>([])
  const [loadingProducts, setLoadingProducts] = useState(false)
  const [isCreateProductDialogOpen, setIsCreateProductDialogOpen] = useState(false)

  // Linked datasets state
  const [linkedDatasets, setLinkedDatasets] = useState<DatasetListItem[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)

  // Team import state
  const [isImportTeamMembersOpen, setIsImportTeamMembersOpen] = useState(false)

  // Link product dialog state
  const [isLinkProductDialogOpen, setIsLinkProductDialogOpen] = useState(false)

  // Link dataset dialog state
  const [isLinkDatasetDialogOpen, setIsLinkDatasetDialogOpen] = useState(false)

  // Commit draft dialog state
  const [isCommitDraftDialogOpen, setIsCommitDraftDialogOpen] = useState(false)

  // Version navigation state
  type ContractVersionInfo = { id: string; version: string; status: string; createdAt: string }
  const [versions, setVersions] = useState<ContractVersionInfo[]>([])

  // Admin permission check — admins can edit/delete regardless of status
  const contractPermissionLevel = getPermissionLevel('data-contracts')
  const isContractAdmin = contractPermissionLevel === FeatureAccessLevel.ADMIN || contractPermissionLevel === FeatureAccessLevel.FULL

  // Computed properties for status-based editability
  // Admins bypass status restrictions; others need draft/proposed
  const canEditInPlace = isContractAdmin || !!(contract?.status && EDITABLE_STATUSES.includes(contract.status.toLowerCase()))
  // Personal drafts are editable since they have draft status
  const isPersonalDraft = contract?.draftOwnerId != null
  // Contract is read-only if it's not editable and not a personal draft
  const isReadOnly = !canEditInPlace

  // Version navigation helpers
  const currentVersionIndex = versions.findIndex(v => v.id === contractId)
  const prevVersion = currentVersionIndex > 0 ? versions[currentVersionIndex - 1] : null
  const nextVersion = currentVersionIndex >= 0 && currentVersionIndex < versions.length - 1 ? versions[currentVersionIndex + 1] : null

  // View mode state for filtering sections - initialize from localStorage
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    const stored = localStorage.getItem(VIEW_MODE_STORAGE_KEY)
    if (stored && ['minimal', 'medium', 'large'].includes(stored)) {
      return stored as ViewMode
    }
    return 'minimal' // Default, will be updated by getDefaultViewMode effect if needed
  })

  // Authoritative Definitions state (contract-level)
  type AuthoritativeDefinition = { id: string; url: string; type: string }
  const [contractAuthDefs, setContractAuthDefs] = useState<AuthoritativeDefinition[]>([])
  const [editingContractAuthDefIndex, setEditingContractAuthDefIndex] = useState<number | null>(null)

  // Authoritative Definitions state (schema-level) - keyed by schema ID
  const [schemaAuthDefs, setSchemaAuthDefs] = useState<Record<string, AuthoritativeDefinition[]>>({})
  const [editingSchemaAuthDef, setEditingSchemaAuthDef] = useState<{ schemaId: string; index: number } | null>(null)
  const [isSchemaAuthDefFormOpen, setIsSchemaAuthDefFormOpen] = useState(false)
  const [activeSchemaIdForAuthDef, setActiveSchemaIdForAuthDef] = useState<string | null>(null)

  // Authoritative Definitions state (property-level) - keyed by propertyId
  const [propertyAuthDefs, setPropertyAuthDefs] = useState<Record<string, AuthoritativeDefinition[]>>({})
  const [editingPropertyAuthDef, setEditingPropertyAuthDef] = useState<{ schemaId: string; propertyId: string; index: number } | null>(null)
  const [isPropertyAuthDefFormOpen, setIsPropertyAuthDefFormOpen] = useState(false)
  const [_activePropertyForAuthDef, _setActivePropertyForAuthDef] = useState<{ schemaId: string; propertyId: string } | null>(null)

  // Dialog states for CRUD operations
  const [isInferFromCatalogOpen, setIsInferFromCatalogOpen] = useState(false)
  const [isInferFromAssetOpen, setIsInferFromAssetOpen] = useState(false)
  const [isBasicFormOpen, setIsBasicFormOpen] = useState(false)
  const [isSchemaFormOpen, setIsSchemaFormOpen] = useState(false)
  const [isQualityRuleFormOpen, setIsQualityRuleFormOpen] = useState(false)
  const [isTeamMemberFormOpen, setIsTeamMemberFormOpen] = useState(false)
  const [isServerConfigFormOpen, setIsServerConfigFormOpen] = useState(false)
  const [isSLAFormOpen, setIsSLAFormOpen] = useState(false)
  const [isContractAuthDefFormOpen, setIsContractAuthDefFormOpen] = useState(false)
  const [isCustomPropertyFormOpen, setIsCustomPropertyFormOpen] = useState(false)
  const [editingCustomPropertyKey, setEditingCustomPropertyKey] = useState<string | null>(null)

  // Schema inference state
  const [isInferringSchema, setIsInferringSchema] = useState(false)

  // DQX Profiling states
  const [isDqxSchemaSelectOpen, setIsDqxSchemaSelectOpen] = useState(false)
  const [isDqxSuggestionsOpen, setIsDqxSuggestionsOpen] = useState(false)
  const [selectedProfileRunId, setSelectedProfileRunId] = useState<string | null>(null)
  const [latestProfileRun, setLatestProfileRun] = useState<DataProfilingRun | null>(null)
  const [pendingSuggestionsCount, setPendingSuggestionsCount] = useState(0)
  const [isProfilingRunning, setIsProfilingRunning] = useState(false)

  // Editing states
  const [editingSchemaIndex, setEditingSchemaIndex] = useState<number | null>(null)
  const [editingQualityRuleIndex, setEditingQualityRuleIndex] = useState<number | null>(null)
  const [editingTeamMemberIndex, setEditingTeamMemberIndex] = useState<number | null>(null)
  const [editingServerIndex, setEditingServerIndex] = useState<number | null>(null)

  useCopilotContext(
    'Data Contract Details',
    `/data-contracts/${contractId}`,
    contract ? { type: 'data_contract', name: contract.name || 'Unnamed', id: contractId || '' } : null,
  )

  const fetchLinkedProducts = async () => {
    if (!contractId) return
    setLoadingProducts(true)
    try {
      const response = await fetch(`/api/data-products/by-contract/${contractId}`)
      if (response.ok) {
        const data = await response.json()
        setLinkedProducts(Array.isArray(data) ? data : [])
      } else {
        setLinkedProducts([])
      }
    } catch (e) {
      console.warn('Failed to fetch linked products:', e)
      setLinkedProducts([])
    } finally {
      setLoadingProducts(false)
    }
  }

  const fetchLinkedDatasets = async () => {
    if (!contractId) return
    setLoadingDatasets(true)
    try {
      const response = await fetch(`/api/datasets/by-contract/${contractId}`)
      if (response.ok) {
        const data = await response.json()
        setLinkedDatasets(Array.isArray(data) ? data : [])
      } else {
        setLinkedDatasets([])
      }
    } catch (e) {
      console.warn('Failed to fetch linked datasets:', e)
      setLinkedDatasets([])
    } finally {
      setLoadingDatasets(false)
    }
  }

  const fetchVersions = async () => {
    if (!contractId) return
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/versions`)
      if (response.ok) {
        const data = await response.json()
        setVersions(Array.isArray(data) ? data : [])
      } else {
        setVersions([])
      }
    } catch (e) {
      console.warn('Failed to fetch contract versions:', e)
      setVersions([])
    }
  }

  const fetchContractAuthDefs = async () => {
    if (!contractId) return
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/authoritative-definitions`)
      if (response.ok) {
        const data = await response.json()
        setContractAuthDefs(Array.isArray(data) ? data : [])
      } else {
        setContractAuthDefs([])
      }
    } catch (e) {
      console.warn('Failed to fetch contract authoritative definitions:', e)
      setContractAuthDefs([])
    }
  }

  const fetchSchemaAuthDefs = async (schemaId: string) => {
    if (!contractId) return
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/authoritative-definitions`)
      if (response.ok) {
        const data = await response.json()
        setSchemaAuthDefs(prev => ({ ...prev, [schemaId]: Array.isArray(data) ? data : [] }))
      } else {
        setSchemaAuthDefs(prev => ({ ...prev, [schemaId]: [] }))
      }
    } catch (e) {
      console.warn("Failed to fetch schema authoritative definitions for", schemaId, ":", e)
      setSchemaAuthDefs(prev => ({ ...prev, [schemaId]: [] }))
    }
  }

  const fetchSelectedSchemaAuthDefs = () => {
    if (!contract?.schema || contract.schema.length === 0) return
    const schema = contract.schema[selectedSchemaIndex]
    if (!schema) return
    const schemaId = (schema as any).id || schema.name
    if (schemaId && !schemaAuthDefs[schemaId]) {
      fetchSchemaAuthDefs(schemaId)
    }
  }

  const fetchSchemaSemanticLinks = useCallback(async (schemaName: string) => {
    if (!contractId || !schemaName) return
    try {
      const schemaEntityId = `${contractId}#${schemaName}`
      const schemaLinksRes = await fetch(`/api/semantic-links/entity/data_contract_schema/${encodeURIComponent(schemaEntityId)}`)
      if (schemaLinksRes.ok) {
        const data = await schemaLinksRes.json()
        setSchemaLinks(prev => ({ ...prev, [schemaName]: Array.isArray(data) ? data : [] }))
      }
    } catch (e) {
      console.warn('Failed to fetch schema links for', schemaName, ':', e)
    }
  }, [contractId])

  const fetchSchemaProperties = useCallback(async (schemaName: string, page: number = 0) => {
    if (!contractId || !schemaName) return
    setLoadingSchemaProps(true)
    try {
      const skip = page * PROPS_PAGE_SIZE
      const res = await fetch(
        `/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaName)}/properties?skip=${skip}&limit=${PROPS_PAGE_SIZE}`
      )
      if (res.ok) {
        const data = await res.json()
        const items = data.items ?? []
        setSchemaProperties(prev => ({ ...prev, [schemaName]: items }))
        setSchemaPropTotal(prev => ({ ...prev, [schemaName]: data.total ?? 0 }))
        setSchemaPropPage(prev => ({ ...prev, [schemaName]: page }))
      }
    } catch (e) {
      console.warn('Failed to fetch schema properties for', schemaName, ':', e)
    } finally {
      setLoadingSchemaProps(false)
    }
  }, [contractId, fetchSchemaSemanticLinks])

  const fetchAllSchemaProperties = useCallback(async (schemaName: string): Promise<SchemaProperty[]> => {
    if (!contractId || !schemaName) return []
    setLoadingEditProperties(true)
    try {
      const res = await fetch(
        `/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaName)}/properties?skip=0&limit=0`
      )
      if (res.ok) {
        const data = await res.json()
        const items: SchemaProperty[] = data.items ?? []
        setAllSchemaProperties(prev => ({ ...prev, [schemaName]: items }))
        return items
      }
    } catch (e) {
      console.warn('Failed to fetch all schema properties for', schemaName, ':', e)
    } finally {
      setLoadingEditProperties(false)
    }
    return []
  }, [contractId])

  const fetchDetails = async () => {
    if (!contractId) return
    setLoading(true)
    setError(null)
    setDynamicTitle('Loading...')
    try {
      const [contractRes, linksRes] = await Promise.all([
        fetch(`/api/data-contracts/${contractId}`),
        fetch(`/api/semantic-links/entity/data_contract/${contractId}`)
      ])

      if (!contractRes.ok) throw new Error('Failed to load contract')
      const contractData: DataContract = await contractRes.json()
      console.log('[DEBUG] Contract data loaded:', {
        id: contractData.id,
        name: contractData.name,
        owner_team_id: contractData.owner_team_id,
        hasOwnerTeamId: !!contractData.owner_team_id,
        schema: contractData.schema,
        schemaCount: contractData.schema?.length
      })
      setContract(contractData)
      setDynamicTitle(contractData.name)

      if (linksRes.ok) {
        const linksData = await linksRes.json()
        setLinks(Array.isArray(linksData) ? linksData : [])
      } else {
        setLinks([])
      }

      // Schema and property semantic links are now fetched on-demand
      // when the user selects a schema (see fetchSchemaSemanticLinks)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setDynamicTitle('Error')
    } finally {
      setLoading(false)
    }
  }

  // DQX Profiling handlers - defined early to be used in initial useEffect
  const fetchProfileRuns = useCallback(async () => {
    if (!contractId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/profile-runs`)
      if (res.ok) {
        const runs: DataProfilingRun[] = await res.json()
        if (runs.length > 0) {
          const latest = runs[0]
          const wasRunning = isProfilingRunning
          
          setLatestProfileRun(latest)
          setPendingSuggestionsCount(latest.suggestion_counts?.pending || 0)
          
          // Check if profiling is still running
          const isRunning = latest.status === 'running' || latest.status === 'pending'
          setIsProfilingRunning(isRunning)
          
          // Notify when profiling completes
          if (wasRunning && !isRunning && latest.status === 'completed') {
            const suggestionsCount = latest.suggestion_counts?.pending || 0
            if (suggestionsCount > 0) {
              toast({
                title: 'DQX Profiling Complete',
                description: `${suggestionsCount} quality check ${suggestionsCount === 1 ? 'suggestion' : 'suggestions'} available for review.`
              })
            } else {
              toast({
                title: 'DQX Profiling Complete',
                description: 'Profiling completed but no suggestions were generated.'
              })
            }
          } else if (wasRunning && !isRunning && latest.status === 'failed') {
            toast({
              title: 'DQX Profiling Failed',
              description: latest.error_message || 'Profiling failed. Check the job logs for details.',
              variant: 'destructive'
            })
          }
        } else {
          setIsProfilingRunning(false)
        }
      }
    } catch (e) {
      console.warn('Failed to fetch profile runs:', e)
      setIsProfilingRunning(false)
    }
  }, [contractId, isProfilingRunning, toast])

  // Determine default view mode based on user role and ownership
  const getDefaultViewMode = useCallback((): ViewMode => {
    // Check if user is owner or member of owning team
    if (contract?.owner_team_id && userInfo?.groups?.includes(contract.owner_team_id)) {
      return 'large'
    }

    // Check permission level for data-contracts feature
    const permissionLevel = getPermissionLevel('data-contracts')
    if (permissionLevel === FeatureAccessLevel.READ_WRITE ||
        permissionLevel === FeatureAccessLevel.ADMIN ||
        permissionLevel === FeatureAccessLevel.FULL) {
      return 'medium'
    }

    // Default to minimal
    return 'minimal'
  }, [contract?.owner_team_id, userInfo?.groups, getPermissionLevel])

  // Fetch user info on mount if not already loaded
  useEffect(() => {
    if (!userInfo) {
      fetchUserInfo()
    }
  }, [userInfo, fetchUserInfo])

  // Set default view mode only if no stored preference exists
  useEffect(() => {
    const stored = localStorage.getItem(VIEW_MODE_STORAGE_KEY)
    if (!stored) {
      // No stored preference - set based on user's role/permissions
      setViewMode(getDefaultViewMode())
    }
  }, [getDefaultViewMode])

  // Save view mode to localStorage when changed
  useEffect(() => {
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode)
  }, [viewMode])

  useEffect(() => {
    setStaticSegments([{ label: 'Data Contracts', path: listPath }])
    fetchDetails()
    fetchLinkedProducts()
    fetchLinkedDatasets()
    fetchContractAuthDefs()
    fetchProfileRuns()
    fetchVersions()

    return () => {
      setStaticSegments([])
      setDynamicTitle(null)
    }
  }, [contractId, setStaticSegments, setDynamicTitle, fetchProfileRuns])

  // Fetch authoritative definitions for the currently selected schema only
  useEffect(() => {
    fetchSelectedSchemaAuthDefs()
  }, [contract?.schema, selectedSchemaIndex])

  // Lazy-load properties and schema-level semantic links for the currently selected schema
  useEffect(() => {
    if (!contract?.schema || contract.schema.length === 0) return
    const schema = contract.schema[selectedSchemaIndex]
    if (!schema) return
    if (!schemaProperties[schema.name]) {
      fetchSchemaProperties(schema.name, 0)
    }
    if (!schemaLinks[schema.name]) {
      fetchSchemaSemanticLinks(schema.name)
    }
  }, [contract?.schema, selectedSchemaIndex, fetchSchemaProperties, fetchSchemaSemanticLinks])

  // Poll for profiling updates while profiling is running
  useEffect(() => {
    if (!isProfilingRunning || !contractId) return

    console.log('Starting profiling poll interval...')
    const pollInterval = setInterval(() => {
      console.log('Polling for profiling updates...')
      fetchProfileRuns()
    }, 5000) // Poll every 5 seconds

    return () => {
      console.log('Stopping profiling poll interval')
      clearInterval(pollInterval)
    }
  }, [isProfilingRunning, contractId, fetchProfileRuns])

  const handleDelete = async () => {
    if (!contractId) return
    if (!confirm('Delete this contract?')) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Delete failed')
      toast({ title: 'Deleted', description: 'Contract deleted.' })
      navigate(listPath)
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to delete', variant: 'destructive' })
    }
  }

  const handleCloneForEditing = async () => {
    if (!contractId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/clone-for-editing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to create personal draft')
      }
      const data = await res.json()
      toast({
        title: 'Personal Draft Created',
        description: 'You can now edit this draft. It will only be visible to you until committed.',
      })
      // Navigate to the new draft
      navigate(`${listPath}/${data.id}`)
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to clone', variant: 'destructive' })
    }
  }

  const handleDiscardDraft = async () => {
    if (!contractId) return
    if (!confirm('Discard this personal draft? This cannot be undone.')) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/discard`, { method: 'DELETE' })
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to discard draft')
      }
      toast({ title: 'Draft Discarded', description: 'Your personal draft has been deleted.' })
      // Navigate back to contracts list or parent contract
      if (contract?.parentContractId) {
        navigate(`${listPath}/${contract.parentContractId}`)
      } else {
        navigate(listPath)
      }
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to discard', variant: 'destructive' })
    }
  }

  const handleCommitSuccess = () => {
    // Refresh the contract details after successful commit
    fetchDetails()
  }

  const exportOdcs = async () => {
    if (!contractId || !contract) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/odcs/export`)
      if (!res.ok) throw new Error('Export ODCS failed')
      const text = await res.text()
      const contentDisposition = res.headers.get('Content-Disposition') || ''
      const filenameMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
      const suggestedName = filenameMatch?.[1]
      const blob = new Blob([text], { type: 'application/x-yaml; charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = suggestedName || `${contract.name.toLowerCase().replace(/\s+/g, '_')}-odcs.yaml`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast({ title: 'Export failed', description: e instanceof Error ? e.message : 'Unable to export', variant: 'destructive' })
    }
  }

  const addIri = async (iri: string) => {
    if (!contractId) return
    try {
      const res = await fetch(`/api/semantic-links/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_id: contractId,
          entity_type: 'data_contract',
          iri,
        })
      })
      if (!res.ok) throw new Error('Failed to add concept')
      await fetchDetails()
      setIriDialogOpen(false)
      toast({ title: 'Linked', description: 'Business concept linked to data contract.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to link business concept', variant: 'destructive' })
    }
  }

  const removeLink = async (linkId: string) => {
    try {
      const res = await fetch(`/api/semantic-links/${linkId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to remove concept')
      await fetchDetails()
      toast({ title: 'Unlinked', description: 'Business concept unlinked from data contract.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to unlink business concept', variant: 'destructive' })
    }
  }

  const handleCreateNewVersion = () => {
    if (!contractId || !contract) {
      toast({ title: 'Permission Denied or Data Missing', description: 'Cannot create new version.', variant: 'destructive' })
      return
    }
    setIsVersionDialogOpen(true)
  }

  const submitNewVersion = async (newVersionString: string) => {
    if (!contractId) return
    toast({ title: 'Creating New Version', description: `Creating version ${newVersionString}...` })
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/versions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_version: newVersionString.trim() })
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || 'Failed to create new version.')
      }
      const data = await res.json()
      const newId = data?.id
      if (!newId) throw new Error('Invalid response when creating version.')
      toast({ title: 'Success', description: `Version ${newVersionString} created successfully!` })
      setIsVersionDialogOpen(false)
      navigate(`${listPath}/${newId}`)
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Failed to create new version.', variant: 'destructive' })
    }
  }

  // CRUD handlers for main metadata
  const handleUpdateMetadata = async (payload: any) => {
    console.log('[DEBUG] handleUpdateMetadata called with payload.owner_team_id:', payload.owner_team_id)
    console.log('[DEBUG] Full payload:', JSON.stringify(payload, null, 2))
    try {
      const updatePayload = {
        name: payload.name,
        version: payload.version,
        status: payload.status,
        owner_team_id: payload.owner_team_id,
        project_id: payload.project_id,
        tenant: payload.tenant,
        domainId: payload.domainId,
        descriptionUsage: payload.description?.usage,
        descriptionPurpose: payload.description?.purpose,
        descriptionLimitations: payload.description?.limitations,
        tags: payload.tags || [],
      }
      console.log('[DEBUG] Update payload owner_team_id:', updatePayload.owner_team_id)
      console.log('[DEBUG] Sending update request:', JSON.stringify(updatePayload, null, 2))
      
      const res = await fetch(`/api/data-contracts/${contractId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload)
      })
      
      console.log('[DEBUG] Update response status:', res.status)
      
      // Handle version conflict (breaking changes detected)
      if (res.status === 409) {
        const errorData = await res.json()
        console.log('[DEBUG] 409 error data:', errorData)
        
        // Show dialog with breaking changes and options
        if (errorData.detail?.user_can_override) {
          // Admin can force update or create new version
          toast({
            title: 'Breaking Changes Detected',
            description: `${errorData.detail.message}. As an admin, you can force this update or create a new version.`,
            variant: 'destructive',
            duration: 10000
          })
        } else {
          // Non-admin must create new version
          toast({
            title: 'Breaking Changes Detected',
            description: `${errorData.detail.message}. You must create a new version.`,
            variant: 'destructive',
            duration: 10000
          })
        }
        throw new Error(errorData.detail?.message || 'Breaking changes detected')
      }
      
      if (!res.ok) throw new Error('Update failed')
      
      console.log('[DEBUG] Calling fetchDetails()...')
      await fetchDetails()
      
      toast({ title: 'Updated', description: 'Contract metadata updated.' })
    } catch (e) {
      console.error('[DEBUG] Update error:', e)
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to update', variant: 'destructive' })
      throw e
    }
  }

  // Pre-fetch all properties then open the schema edit dialog
  const handleEditSchema = async (schemaIndex: number) => {
    const schemaName = contract?.schema?.[schemaIndex]?.name
    if (!schemaName) return
    await fetchAllSchemaProperties(schemaName)
    setEditingSchemaIndex(schemaIndex)
    setIsSchemaFormOpen(true)
  }

  const clearSchemaCache = () => {
    setSchemaProperties({})
    setSchemaPropTotal({})
    setSchemaPropPage({})
    setAllSchemaProperties({})
    setSchemaLinks({})
    setSchemaAuthDefs({})
  }

  // Schema CRUD handlers
  const handleAddSchema = async (schema: SchemaObject) => {
    if (!contractId) return
    const res = await fetch(`/api/data-contracts/${contractId}/schemas`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(schema),
    })
    if (!res.ok) throw new Error('Failed to add schema')
    clearSchemaCache()
    await fetchDetails()
  }

  const handleUpdateSchema = async (schema: SchemaObject) => {
    if (!contract || editingSchemaIndex === null) return
    const updatedSchemas = [...(contract.schema || [])]
    updatedSchemas[editingSchemaIndex] = schema
    await updateContract({ schema: updatedSchemas })
    clearSchemaCache()
    setEditingSchemaIndex(null)
  }

  // Enrich schema with property-level semantic links from propertyLinks so the Edit Schema dialog loads them.
  // Properties are sourced from allSchemaProperties (fetched with limit=0 before opening the edit dialog)
  // rather than contract.schema[].properties which is always [] due to lazy loading.
  const schemaFormInitial = useMemo(() => {
    if (editingSchemaIndex === null || !contract?.schema?.[editingSchemaIndex]) return undefined
    const baseSchema = contract.schema[editingSchemaIndex]
    const SEMANTIC_ASSIGNMENT_TYPE = 'http://databricks.com/ontology/uc/semanticAssignment'
    const sourceProperties = allSchemaProperties[baseSchema.name] || baseSchema.properties || []
    const enrichedProperties = sourceProperties.map((prop: any) => {
      const propertyKey = `${baseSchema.name}#${prop.name}`
      const links: EntitySemanticLink[] = propertyLinks[propertyKey] || []
      const authoritativeDefinitions = links.length > 0
        ? links.map(l => ({ url: l.iri, type: SEMANTIC_ASSIGNMENT_TYPE }))
        : (prop.authoritativeDefinitions || [])
      const semanticConcepts = links.length > 0
        ? links.map(l => ({ iri: l.iri, label: l.label }))
        : ((prop as any).semanticConcepts || (prop.authoritativeDefinitions || []).map((d: { url: string }) => ({ iri: d.url })))
      return {
        ...prop,
        authoritativeDefinitions: authoritativeDefinitions.length > 0 ? authoritativeDefinitions : undefined,
        semanticConcepts: semanticConcepts.length > 0 ? semanticConcepts : undefined,
      }
    })
    return { ...baseSchema, properties: enrichedProperties }
  }, [contract, editingSchemaIndex, propertyLinks, allSchemaProperties])

  const handleDeleteSchema = async (index: number) => {
    if (!contract || !contractId) return
    if (!confirm('Delete this schema?')) return
    const schemaName = contract.schema?.[index]?.name
    if (!schemaName) return
    const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaName)}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error('Failed to delete schema')
    clearSchemaCache()
    if (selectedSchemaIndex >= (contract.schema?.length || 1) - 1) {
      setSelectedSchemaIndex(Math.max(0, selectedSchemaIndex - 1))
    }
    await fetchDetails()
  }

  // Quality Rule CRUD handlers
  const handleAddQualityRule = async (rule: QualityRule) => {
    if (!contract) return
    const updatedRules = [...(contract.qualityRules || []), rule]
    await updateContract({ qualityRules: updatedRules })
  }

  const handleUpdateQualityRule = async (rule: QualityRule) => {
    if (!contract || editingQualityRuleIndex === null) return
    const updatedRules = [...(contract.qualityRules || [])]
    updatedRules[editingQualityRuleIndex] = rule
    await updateContract({ qualityRules: updatedRules })
    setEditingQualityRuleIndex(null)
  }

  const handleDeleteQualityRule = async (index: number) => {
    if (!contract) return
    if (!confirm('Delete this quality rule?')) return
    const updatedRules = (contract.qualityRules || []).filter((_, i) => i !== index)
    await updateContract({ qualityRules: updatedRules })
  }

  // Team Member CRUD handlers
  const handleAddTeamMember = async (member: TeamMember) => {
    if (!contract) return
    const updatedTeam = [...(contract.team || []), member]
    await updateContract({ team: updatedTeam })
  }

  const handleUpdateTeamMember = async (member: TeamMember) => {
    if (!contract || editingTeamMemberIndex === null) return
    const updatedTeam = [...(contract.team || [])]
    updatedTeam[editingTeamMemberIndex] = member
    await updateContract({ team: updatedTeam })
    setEditingTeamMemberIndex(null)
  }

  const handleDeleteTeamMember = async (index: number) => {
    if (!contract) return
    if (!confirm('Remove this team member?')) return
    const updatedTeam = (contract.team || []).filter((_, i) => i !== index)
    await updateContract({ team: updatedTeam })
  }

  // Server Config CRUD handlers
  const handleAddServer = async (server: ServerConfig) => {
    if (!contract) return
    const currentServers = Array.isArray(contract.servers) ? contract.servers : (contract.servers ? [contract.servers] : [])
    const updatedServers = [...currentServers, server]
    await updateContract({ servers: updatedServers })
  }

  const handleUpdateServer = async (server: ServerConfig) => {
    if (!contract || editingServerIndex === null) return
    const currentServers = Array.isArray(contract.servers) ? contract.servers : (contract.servers ? [contract.servers] : [])
    const updatedServers = [...currentServers]
    updatedServers[editingServerIndex] = server
    await updateContract({ servers: updatedServers })
    setEditingServerIndex(null)
  }

  const handleDeleteServer = async (index: number) => {
    if (!contract) return
    if (!confirm('Delete this server configuration?')) return
    const currentServers = Array.isArray(contract.servers) ? contract.servers : (contract.servers ? [contract.servers] : [])
    const updatedServers = currentServers.filter((_, i) => i !== index)
    await updateContract({ servers: updatedServers })
  }

  // SLA handler
  const handleUpdateSLA = async (sla: SLARequirements) => {
    await updateContract({ sla })
  }

  // Contract-level Authoritative Definition handlers
  const handleAddContractAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/authoritative-definitions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to create authoritative definition')
      await fetchContractAuthDefs()
      toast({ title: 'Added', description: 'Authoritative definition added successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to add', variant: 'destructive' })
      throw e
    }
  }

  const handleUpdateContractAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId || editingContractAuthDefIndex === null) return
    const defId = contractAuthDefs[editingContractAuthDefIndex]?.id
    if (!defId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/authoritative-definitions/${defId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to update authoritative definition')
      await fetchContractAuthDefs()
      setEditingContractAuthDefIndex(null)
      toast({ title: 'Updated', description: 'Authoritative definition updated successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to update', variant: 'destructive' })
      throw e
    }
  }

  const handleDeleteContractAuthDef = async (index: number) => {
    if (!contractId) return
    if (!confirm('Delete this authoritative definition?')) return
    const defId = contractAuthDefs[index]?.id
    if (!defId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/authoritative-definitions/${defId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error('Failed to delete authoritative definition')
      await fetchContractAuthDefs()
      toast({ title: 'Deleted', description: 'Authoritative definition deleted successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to delete', variant: 'destructive' })
    }
  }

  // Custom Property CRUD handlers
  const handleAddCustomProperty = async (data: { property: string; value: string }) => {
    if (!contract) return
    const updatedProps = { ...(contract.customProperties || {}), [data.property]: data.value }
    await updateContract({ customProperties: updatedProps })
    setIsCustomPropertyFormOpen(false)
  }

  const handleUpdateCustomProperty = async (data: { property: string; value: string }) => {
    if (!contract || !editingCustomPropertyKey) return
    const updatedProps = { ...(contract.customProperties || {}) }
    // If key changed, remove old key
    if (editingCustomPropertyKey !== data.property) {
      delete updatedProps[editingCustomPropertyKey]
    }
    updatedProps[data.property] = data.value
    await updateContract({ customProperties: updatedProps })
    setEditingCustomPropertyKey(null)
    setIsCustomPropertyFormOpen(false)
  }

  const handleDeleteCustomProperty = async (key: string) => {
    if (!contract) return
    if (!confirm(`Delete custom property "${key}"?`)) return
    const updatedProps = { ...(contract.customProperties || {}) }
    delete updatedProps[key]
    await updateContract({ customProperties: updatedProps })
  }

  // Schema-level Authoritative Definition handlers
  const handleAddSchemaAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId || !activeSchemaIdForAuthDef) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(activeSchemaIdForAuthDef)}/authoritative-definitions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to create schema authoritative definition')
      await fetchSchemaAuthDefs(activeSchemaIdForAuthDef)
      toast({ title: 'Added', description: 'Schema authoritative definition added successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to add', variant: 'destructive' })
      throw e
    }
  }

  const handleUpdateSchemaAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId || !editingSchemaAuthDef) return
    const { schemaId, index } = editingSchemaAuthDef
    const defs = schemaAuthDefs[schemaId] || []
    const defId = defs[index]?.id
    if (!defId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/authoritative-definitions/${defId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to update schema authoritative definition')
      await fetchSchemaAuthDefs(schemaId)
      setEditingSchemaAuthDef(null)
      toast({ title: 'Updated', description: 'Schema authoritative definition updated successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to update', variant: 'destructive' })
      throw e
    }
  }

  const handleDeleteSchemaAuthDef = async (schemaId: string, index: number) => {
    if (!contractId) return
    if (!confirm('Delete this schema authoritative definition?')) return
    const defs = schemaAuthDefs[schemaId] || []
    const defId = defs[index]?.id
    if (!defId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/authoritative-definitions/${defId}`, {
        method: 'DELETE'
      })
      if (!res.ok) throw new Error('Failed to delete schema authoritative definition')
      await fetchSchemaAuthDefs(schemaId)
      toast({ title: 'Deleted', description: 'Schema authoritative definition deleted successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to delete', variant: 'destructive' })
    }
  }

  // Property-level Authoritative Definition fetch and handlers
  const fetchPropertyAuthDefs = async (schemaId: string, propertyId: string) => {
    if (!contractId) return
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/properties/${encodeURIComponent(propertyId)}/authoritative-definitions`)
      if (response.ok) {
        const data = await response.json()
        setPropertyAuthDefs(prev => ({ ...prev, [propertyId]: Array.isArray(data) ? data : [] }))
      } else {
        setPropertyAuthDefs(prev => ({ ...prev, [propertyId]: [] }))
      }
    } catch (e) {
      console.warn("Failed to fetch property authoritative definitions for", propertyId, ":", e)
      setPropertyAuthDefs(prev => ({ ...prev, [propertyId]: [] }))
    }
  }

  const handleAddPropertyAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId || !_activePropertyForAuthDef) return
    const { schemaId, propertyId } = _activePropertyForAuthDef
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/properties/${encodeURIComponent(propertyId)}/authoritative-definitions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to create property authoritative definition')
      await fetchPropertyAuthDefs(schemaId, propertyId)
      toast({ title: 'Added', description: 'Property authoritative definition added successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to add', variant: 'destructive' })
      throw e
    }
  }

  const handleUpdatePropertyAuthDef = async (definition: { url: string; type: string }) => {
    if (!contractId || !editingPropertyAuthDef) return
    const { schemaId, propertyId, index } = editingPropertyAuthDef
    const defs = propertyAuthDefs[propertyId] || []
    const defId = defs[index]?.id
    if (!defId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/properties/${encodeURIComponent(propertyId)}/authoritative-definitions/${defId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition)
      })
      if (!res.ok) throw new Error('Failed to update property authoritative definition')
      await fetchPropertyAuthDefs(schemaId, propertyId)
      setEditingPropertyAuthDef(null)
      toast({ title: 'Updated', description: 'Property authoritative definition updated successfully.' })
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to update', variant: 'destructive' })
      throw e
    }
  }

  // Available for future use - commented out to prevent unused variable errors
  // const handleDeletePropertyAuthDef = async (schemaId: string, propertyId: string, index: number) => {
  //   if (!contractId) return
  //   if (!confirm('Delete this property authoritative definition?')) return
  //   const defs = propertyAuthDefs[propertyId] || []
  //   const defId = defs[index]?.id
  //   if (!defId) return
  //   try {
  //     const res = await fetch(`/api/data-contracts/${contractId}/schemas/${encodeURIComponent(schemaId)}/properties/${encodeURIComponent(propertyId)}/authoritative-definitions/${defId}`, {
  //       method: 'DELETE'
  //     })
  //     if (!res.ok) throw new Error('Failed to delete property authoritative definition')
  //     await fetchPropertyAuthDefs(schemaId, propertyId)
  //     toast({ title: 'Deleted', description: 'Property authoritative definition deleted successfully.' })
  //   } catch (e) {
  //     toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to delete', variant: 'destructive' })
  //   }
  // }

  // Available for future use - commented out to prevent unused variable errors
  // const handleManagePropertyAuthDefs = (schemaId: string, propertyName: string, propertyId: string) => {
  //   // Fetch property auth defs if not already loaded
  //   if (!propertyAuthDefs[propertyId]) {
  //     fetchPropertyAuthDefs(schemaId, propertyId)
  //   }
  //   setActivePropertyForAuthDef({ schemaId, propertyId })
  //   setEditingPropertyAuthDef(null)
  //   setIsPropertyAuthDefFormOpen(true)
  // }

  // Helper to update contract (read-modify-write pattern)
  const updateContract = async (updates: Partial<any>, showToast: boolean = true, forceUpdate: boolean = false) => {
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' }
      if (forceUpdate) {
        headers['X-Force-Update'] = 'true'
      }
      
      const res = await fetch(`/api/data-contracts/${contractId}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(updates)
      })
      
      // Handle 409 Conflict - versioning required
      if (res.status === 409) {
        const conflictData = await res.json()
        const detail = conflictData.detail
        
        if (detail && typeof detail === 'object' && detail.requires_versioning) {
          // Store the pending update and show versioning dialog
          setPendingUpdate(updates)
          setVersioningAnalysis(detail.change_analysis)
          setVersioningUserCanOverride(detail.user_can_override)
          setIsVersioningDialogOpen(true)
          return // Don't throw, let the dialog handle it
        }
      }
      
      if (!res.ok) throw new Error('Update failed')
      await fetchDetails()
      if (showToast) {
        toast({ title: 'Updated', description: 'Contract updated successfully.' })
      }
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : 'Failed to update', variant: 'destructive' })
      throw e
    }
  }

  // Handlers for versioning dialog
  const handleVersioningUpdateInPlace = async () => {
    if (!pendingUpdate) return
    try {
      await updateContract(pendingUpdate, true, true) // Force update
      setIsVersioningDialogOpen(false)
      setPendingUpdate(null)
      setVersioningAnalysis(null)
    } catch (e) {
      // Error already handled by updateContract
    }
  }

  const handleVersioningCreateNewVersion = async () => {
    if (!contractId) return
    setIsVersioningDialogOpen(false)
    // Open the version creation dialog instead
    setIsVersionDialogOpen(true)
    // The pending update will be discarded - user needs to apply it to the new version
    toast({
      title: 'Create New Version',
      description: 'Creating a new version will clone this contract. Apply your changes to the new version after creation.'
    })
  }

  // Handler for inferring schema from a connected catalog (via schema-importer)
  const handleInferFromCatalog = async (schemas: CatalogSchemaResult[]) => {
    setIsInferringSchema(true)
    try {
      for (const schema of schemas) {
        const newSchema: SchemaObject = {
          name: schema.name,
          physicalName: schema.physicalName,
          description: schema.description || undefined,
          physicalType: schema.physicalType || 'table',
          properties: schema.properties.map(p => ({
            name: p.name,
            physicalType: p.physicalType,
            logicalType: p.logicalType || 'string',
            required: p.required,
            description: p.description,
            partitioned: p.partitioned,
          })),
        }
        await handleAddSchema(newSchema)
      }

      const totalCols = schemas.reduce((sum, s) => sum + s.properties.length, 0)
      toast({
        title: 'Schema inferred successfully',
        description: `Added ${schemas.length} schema${schemas.length > 1 ? 's' : ''} with ${totalCols} total columns`,
      })
      setIsInferFromCatalogOpen(false)
    } catch (e) {
      toast({
        title: 'Failed to infer schema',
        description: e instanceof Error ? e.message : 'Could not infer schema from catalog',
        variant: 'destructive',
      })
    } finally {
      setIsInferringSchema(false)
    }
  }

  // Handler for inferring schema from an existing Ontos asset
  const handleInferFromAsset = async (schemas: InferredSchemaObject[]) => {
    setIsInferringSchema(true)
    try {
      for (const schema of schemas) {
        const newSchema: SchemaObject = {
          name: schema.name,
          physicalName: schema.physicalName,
          description: schema.description || undefined,
          physicalType: schema.physicalType || 'table',
          properties: schema.properties.map(p => ({
            name: p.name,
            physicalType: p.physicalType,
            logicalType: p.logicalType || 'string',
            required: p.required,
            description: p.description,
            partitioned: p.partitioned,
          })),
        }
        await handleAddSchema(newSchema)
      }

      const totalCols = schemas.reduce((sum, s) => sum + s.properties.length, 0)
      toast({
        title: 'Schema inferred successfully',
        description: `Added ${schemas.length} schema${schemas.length > 1 ? 's' : ''} with ${totalCols} total columns from asset`,
      })
    } catch (e) {
      toast({
        title: 'Failed to infer schema',
        description: e instanceof Error ? e.message : 'Could not infer schema from asset',
        variant: 'destructive',
      })
    } finally {
      setIsInferringSchema(false)
    }
  }

  const handleApprove = async () => {
    if (!contractId) return;
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/approve`, { method: 'POST' });
      if (!res.ok) throw new Error(`Approve failed (${res.status})`);
      await fetchDetails();
      toast({ title: 'Approved', description: 'Contract approved.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Approve failed', variant: 'destructive' });
    }
  };

  const handleReject = async () => {
    if (!contractId) return;
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/reject`, { method: 'POST' });
      if (!res.ok) throw new Error(`Reject failed (${res.status})`);
      await fetchDetails();
      toast({ title: 'Rejected', description: 'Contract rejected.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e?.message || 'Reject failed', variant: 'destructive' });
    }
  };

  const handleStartProfiling = async (selectedSchemaNames: string[]) => {
    if (!contractId) return
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema_names: selectedSchemaNames })
      })
      if (!res.ok) {
        const errorText = await res.text()
        throw new Error(errorText || 'Failed to start profiling')
      }
      await res.json()
      toast({ 
        title: 'DQX Profiling Started', 
        description: 'The profiler is analyzing your data. You will be notified when complete.' 
      })
      setIsDqxSchemaSelectOpen(false)
      
      // Immediately mark as running and fetch status
      setIsProfilingRunning(true)
      fetchProfileRuns()
    } catch (e) {
      toast({ 
        title: 'Failed to start profiling', 
        description: e instanceof Error ? e.message : 'Could not start DQX profiling', 
        variant: 'destructive' 
      })
    }
  }

  const handleOpenSuggestions = (runId?: string) => {
    const profileId = runId || latestProfileRun?.id
    if (profileId) {
      setSelectedProfileRunId(profileId)
      setIsDqxSuggestionsOpen(true)
    }
  }

  const handleSuggestionsSuccess = () => {
    fetchDetails()
    fetchProfileRuns()
  }

  const handleImportTeamMembers = async (members: TeamMember[]) => {
    if (!contract) return
    
    try {
      // Append to existing team array
      const updatedTeam = [...(contract.team || []), ...members]
      
      // Store team assignment metadata in customProperties
      const customProps = contract.customProperties || {}
      const now = new Date().toISOString()
      
      await updateContract({
        team: updatedTeam,
        customProperties: {
          ...customProps,
          assignedTeamId: contract.owner_team_id,
          assignedTeamName: contract.owner_team_name,
          assignedTeamDate: now
        }
      }, false)  // Suppress generic toast, show custom one below
      
      toast({
        title: 'Team Members Imported',
        description: `Successfully imported ${members.length} team ${members.length === 1 ? 'member' : 'members'} to the contract.`
      })
    } catch (e) {
      // Error already handled by updateContract
      throw e
    }
  }

  // Helper functions for conditional rendering based on view mode
  const shouldShowSection = (section: string): boolean => {
    switch (viewMode) {
      case 'minimal':
        return ['metadata', 'description', 'schemas'].includes(section)
      case 'medium':
        return !['quality-rules', 'sla', 'access-control', 'custom-properties', 'support', 'authoritative-definitions'].includes(section)
      case 'large':
        return true
      default:
        return false
    }
  }

  // Special case for linked products in minimal mode
  const shouldShowLinkedProducts = (): boolean => {
    if (viewMode === 'minimal') {
      return linkedProducts.length > 0
    }
    return shouldShowSection('linked-products')
  }

  // Special case for linked datasets in minimal mode
  const shouldShowLinkedDatasets = (): boolean => {
    if (viewMode === 'minimal') {
      return linkedDatasets.length > 0
    }
    return shouldShowSection('linked-datasets')
  }

  if (loading) {
    return <DetailViewSkeleton cards={4} actionButtons={4} />
  }
  if (error || !contract) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error || 'Contract not found.'}</AlertDescription>
      </Alert>
    )
  }

  const serversList = Array.isArray(contract.servers) ? contract.servers : (contract.servers ? [contract.servers] : [])

  const renderSchemaPropertiesTable = () => {
    const schemaName = contract?.schema?.[selectedSchemaIndex]?.name || ''
    const props = schemaProperties[schemaName] || []
    const totalProps = schemaPropTotal[schemaName] || 0
    const currentPage = schemaPropPage[schemaName] || 0
    const totalPages = Math.ceil(totalProps / PROPS_PAGE_SIZE)

    if (loadingSchemaProps && props.length === 0) {
      return <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading columns...</div>
    }
    if (props.length === 0 && totalProps === 0) return null
    return (
      <div className="space-y-2">
        <DataTable
          columns={createSchemaPropertyColumns(contract, selectedSchemaIndex, propertyLinks)}
          data={props}
          searchColumn="name"
        />
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-sm text-muted-foreground pt-1">
            <span>Showing {currentPage * PROPS_PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PROPS_PAGE_SIZE, totalProps)} of {totalProps} columns</span>
            <div className="flex gap-1">
              <Button size="sm" variant="outline" disabled={currentPage === 0 || loadingSchemaProps} onClick={() => fetchSchemaProperties(schemaName, currentPage - 1)}>Previous</Button>
              <Button size="sm" variant="outline" disabled={currentPage >= totalPages - 1 || loadingSchemaProps} onClick={() => fetchSchemaProperties(schemaName, currentPage + 1)}>Next</Button>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={() => navigate(listPath)} size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to List
          </Button>

          {/* Version Navigation */}
          {versions.length > 1 && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                disabled={!prevVersion}
                onClick={() => prevVersion && navigate(`${listPath}/${prevVersion.id}`)}
                title={prevVersion ? `Previous version: ${prevVersion.version}` : 'No previous version'}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <VersionSelector
                currentContractId={contractId!}
                currentVersion={contract?.version}
                onVersionChange={(id) => navigate(`${listPath}/${id}`)}
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                disabled={!nextVersion}
                onClick={() => nextVersion && navigate(`${listPath}/${nextVersion.id}`)}
                title={nextVersion ? `Next version: ${nextVersion.version}` : 'No next version'}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}

          {/* View Mode Toggle */}
          <div className="inline-flex items-stretch h-8 gap-px border rounded-md bg-background overflow-hidden">
            <Button
              variant={viewMode === 'minimal' ? 'default' : 'ghost'}
              onClick={() => setViewMode('minimal')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.smallView')}
            >
              S
            </Button>
            <Button
              variant={viewMode === 'medium' ? 'default' : 'ghost'}
              onClick={() => setViewMode('medium')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.mediumView')}
            >
              M
            </Button>
            <Button
              variant={viewMode === 'large' ? 'default' : 'ghost'}
              onClick={() => setViewMode('large')}
              className="h-full w-8 p-0 font-semibold text-xs rounded-none"
              title={t('common:tooltips.largeView')}
            >
              L
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Lifecycle actions */}
          {contract && (['proposed','under_review'].includes((contract.status || '').toLowerCase())) && (
            <>
              <Button size="sm" variant="outline" onClick={handleApprove}>Approve</Button>
              <Button size="sm" variant="destructive" onClick={handleReject}>Reject</Button>
            </>
          )}
          <Button variant="outline" onClick={() => setIsRequestDialogOpen(true)} size="sm"><KeyRound className="mr-2 h-4 w-4" /> Request...</Button>
          <CommentSidebar
            entityType="data_contract"
            entityId={contractId!}
            isOpen={isCommentSidebarOpen}
            onToggle={() => setIsCommentSidebarOpen(!isCommentSidebarOpen)}
            className="h-8"
          />
          {/* Personal draft actions */}
          {isPersonalDraft && (
            <>
              <Button variant="default" onClick={() => setIsCommitDraftDialogOpen(true)} size="sm">
                <CopyPlus className="mr-2 h-4 w-4" /> Commit Changes
              </Button>
              <Button variant="outline" onClick={handleDiscardDraft} size="sm">
                <Trash2 className="mr-2 h-4 w-4" /> Discard Draft
              </Button>
            </>
          )}
          {/* Clone for editing (for active+ contracts) */}
          {!canEditInPlace && !isPersonalDraft && (
            <Button variant="outline" onClick={handleCloneForEditing} size="sm">
              <CopyPlus className="mr-2 h-4 w-4" /> Clone for Editing
            </Button>
          )}
          {/* Create new version (for any contract) */}
          {!isPersonalDraft && (
            <Button variant="outline" onClick={handleCreateNewVersion} size="sm">
              <CopyPlus className="mr-2 h-4 w-4" /> Create New Version
            </Button>
          )}
          {/* Edit metadata only if editable */}
          {canEditInPlace && (
            <Button variant="outline" onClick={() => setIsBasicFormOpen(true)} size="sm">
              <Pencil className="mr-2 h-4 w-4" /> Edit Metadata
            </Button>
          )}
          <Button variant="outline" onClick={exportOdcs} size="sm"><Download className="mr-2 h-4 w-4" /> Export ODCS</Button>
          {canEditInPlace && (
            <Button variant="destructive" onClick={handleDelete} size="sm"><Trash2 className="mr-2 h-4 w-4" /> Delete</Button>
          )}
        </div>
      </div>

      {/* Personal Draft Banner */}
      {isPersonalDraft && (
        <Alert className="bg-amber-50 border-amber-300 dark:bg-amber-950 dark:border-amber-800">
          <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          <AlertDescription className="text-amber-800 dark:text-amber-200">
            <strong>Personal Draft</strong> — Only visible to you. Commit to share with your team.
            {contract?.parentContractId && (
              <span className="ml-2 text-sm">
                Based on{' '}
                <Button variant="link" className="h-auto p-0 text-amber-700 dark:text-amber-300" onClick={() => navigate(`${listPath}/${contract.parentContractId}`)}>
                  v{contract?.version?.replace('-draft', '') || 'parent'}
                </Button>
              </span>
            )}
          </AlertDescription>
        </Alert>
      )}

      {/* Read-Only Banner (for active+ contracts that aren't personal drafts) */}
      {isReadOnly && !isPersonalDraft && (
        <Alert className="bg-blue-50 border-blue-300 dark:bg-blue-950 dark:border-blue-800">
          <AlertCircle className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          <AlertDescription className="text-blue-800 dark:text-blue-200">
            <strong>Read-Only</strong> — This contract is {contract?.status?.toLowerCase()}. Clone to create a new version for editing.
          </AlertDescription>
        </Alert>
      )}

      {/* Core Metadata Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <FileText className="mr-3 h-7 w-7 text-primary" />
            {contract.name}
          </CardTitle>
          <CardDescription className="pt-1">
            {contract.description?.purpose || 'No description provided'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid md:grid-cols-3 gap-x-6 gap-y-2">
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Status:</Label>
              <div className="flex items-center gap-1.5">
                <Badge variant={getStatusColor(contract.status)} className="text-xs">
                  {contract.status || t('common:states.notAvailable')}
                </Badge>
                {contract.published && (
                  <Badge variant="default" className="bg-green-600 text-xs">Published</Badge>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">Version:</Label>
              <Badge variant="outline" className="text-xs">{contract.version || t('common:states.notAvailable')}</Badge>
            </div>
            {/* Hide Domain if empty in minimal mode */}
            {(viewMode !== 'minimal' || contract.domainId || contract.domain) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Domain:</Label>
                {(() => {
                  const domainId = contract.domainId;
                  const domainName = getDomainName(domainId) || contract.domain;
                  return domainName && domainId ? (
                    <span
                      className="text-xs cursor-pointer text-primary hover:underline truncate"
                      onClick={() => navigate(`/data-domains/${domainId}`)}
                    >
                      {domainName}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">{contract.domain || t('common:states.notAssigned')}</span>
                  );
                })()}
              </div>
            )}
            {/* Hide Project if empty in minimal mode */}
            {(viewMode !== 'minimal' || ((contract as any).project_id && contract.project_name)) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Project:</Label>
                {(contract as any).project_id && contract.project_name ? (
                  <span
                    className="text-xs cursor-pointer text-primary hover:underline truncate"
                    onClick={() => navigate(`/projects/${(contract as any).project_id}`)}
                    title={`Project ID: ${(contract as any).project_id}`}
                  >
                    {contract.project_name}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">{t('common:states.notAssigned')}</span>
                )}
              </div>
            )}
            {/* Hide Tenant if empty in minimal mode */}
            {(viewMode !== 'minimal' || contract.tenant) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Tenant:</Label>
                <span className="text-xs text-muted-foreground truncate">{contract.tenant || t('common:states.notAssigned')}</span>
              </div>
            )}
            {/* Hide Owner if empty in minimal mode */}
            {(viewMode !== 'minimal' || (contract.owner_team_id && contract.owner_team_name)) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Owner:</Label>
                {contract.owner_team_id && contract.owner_team_name ? (
                  <span
                    className="text-xs cursor-pointer text-primary hover:underline truncate"
                    onClick={() => navigate(`/teams/${contract.owner_team_id}`)}
                    title={`Team ID: ${contract.owner_team_id}`}
                  >
                    {contract.owner_team_name}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">{t('common:states.notAssigned')}</span>
                )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground min-w-[4rem]">API Ver:</Label>
              {contract.apiVersion ? (
                <Badge variant="outline" className="text-xs">{contract.apiVersion}</Badge>
              ) : (
                <span className="text-xs text-muted-foreground">N/A</span>
              )}
            </div>
            {/* Hide Created if empty in minimal mode */}
            {(viewMode !== 'minimal' || contract.created) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Created:</Label>
                <span className="text-xs text-muted-foreground truncate">{formatDate(contract.created)}</span>
              </div>
            )}
            {/* Hide Updated if empty in minimal mode */}
            {(viewMode !== 'minimal' || contract.updated) && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground min-w-[4rem]">Updated:</Label>
                <span className="text-xs text-muted-foreground truncate">{formatDate(contract.updated)}</span>
              </div>
            )}
          </div>

          <div className="pt-2 border-t">
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="flex-1 min-w-0">
                <Label className="text-xs text-muted-foreground mb-1.5 block">Tags:</Label>
                <div className="flex flex-wrap gap-1">
                  {(contract.tags || []).length > 0 ? (
                    (contract.tags || []).map((tag, index) => (
                      <TagChip key={index} tag={tag} size="sm" />
                    ))
                  ) : (
                    <span className="text-xs text-muted-foreground">No tags</span>
                  )}
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <Label className="text-xs text-muted-foreground mb-1.5 block">Linked Business Concepts:</Label>
                <LinkedConceptChips
                  links={links}
                  onRemove={canEditInPlace ? (id) => removeLink(id) : undefined}
                  trailing={canEditInPlace ? <Button size="sm" variant="outline" onClick={() => setIriDialogOpen(true)} className="h-6 text-xs">Add</Button> : undefined}
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Structured Description (ODCS) */}
      {shouldShowSection('description') && contract.description && (contract.description.purpose || contract.description.usage || contract.description.limitations) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center">
                <FileText className="mr-2 h-5 w-5" />
                Description
              </span>
              {canEditInPlace && (
                <Button size="sm" variant="outline" onClick={() => setIsBasicFormOpen(true)}>
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {contract.description.purpose && (
              <div>
                <Label>Purpose:</Label>
                <p className="text-sm mt-1">{contract.description.purpose}</p>
              </div>
            )}
            {contract.description.limitations && (
              <div>
                <Label>Limitations:</Label>
                <p className="text-sm mt-1">{contract.description.limitations}</p>
              </div>
            )}
            {contract.description.usage && (
              <div>
                <Label>Usage:</Label>
                <p className="text-sm mt-1">{contract.description.usage}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Schemas Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl">Schemas ({contract.schema?.length || 0})</CardTitle>
              <CardDescription>Database schema definitions</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button 
                size="sm" 
                variant="outline" 
                onClick={() => setIsDqxSchemaSelectOpen(true)}
                disabled={!contract.schema || contract.schema.length === 0}
              >
                <Sparkles className="h-4 w-4 mr-1.5" />
                Profile with DQX
              </Button>
              {canEditInPlace && (
                <>
                  <Button size="sm" variant="outline" onClick={() => setIsInferFromCatalogOpen(true)} disabled={isInferringSchema}>
                    {isInferringSchema ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Database className="h-4 w-4 mr-1.5" />}
                    {isInferringSchema ? 'Inferring...' : 'Infer from Catalog'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setIsInferFromAssetOpen(true)} disabled={isInferringSchema}>
                    <Package className="h-4 w-4 mr-1.5" />
                    Infer from Asset
                  </Button>
                  <Button size="sm" onClick={() => { setEditingSchemaIndex(null); setIsSchemaFormOpen(true); }}>
                    <Plus className="h-4 w-4 mr-1.5" />
                    Add Schema
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isProfilingRunning && (
            <Alert className="mb-4">
              <Loader2 className="h-4 w-4 animate-spin" />
              <AlertDescription className="flex items-center justify-between">
                <span>
                  DQX profiling in progress... Results will appear here when complete.
                </span>
              </AlertDescription>
            </Alert>
          )}
          {!isProfilingRunning && pendingSuggestionsCount > 0 && (
            <Alert className="mb-4">
              <Sparkles className="h-4 w-4" />
              <AlertDescription className="flex items-center justify-between">
                <span>
                  {pendingSuggestionsCount} quality check {pendingSuggestionsCount === 1 ? 'suggestion' : 'suggestions'} available from DQX profiling
                </span>
                <Button 
                  size="sm" 
                  variant="outline" 
                  onClick={() => handleOpenSuggestions()}
                >
                  Review Suggestions
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {isInferringSchema && (
            <Alert className="mb-4">
              <Loader2 className="h-4 w-4 animate-spin" />
              <AlertDescription>
                Inferring schema... This may take a moment.
              </AlertDescription>
            </Alert>
          )}
          {!contract.schema || contract.schema.length === 0 ? (
            <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
              <div className="text-muted-foreground mb-2">No schemas defined yet</div>
              <div className="text-sm text-muted-foreground mb-4">
                {canEditInPlace 
                  ? 'Define the structure of your data by adding schemas'
                  : 'This contract has no schemas defined'}
              </div>
              {canEditInPlace && (
                <div className="flex gap-3 justify-center flex-wrap">
                  <Button variant="outline" onClick={() => setIsInferFromCatalogOpen(true)} disabled={isInferringSchema}>
                    {isInferringSchema ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Database className="h-4 w-4 mr-2" />}
                    {isInferringSchema ? 'Inferring Schema...' : 'Infer from Catalog'}
                  </Button>
                  <Button variant="outline" onClick={() => setIsInferFromAssetOpen(true)} disabled={isInferringSchema}>
                    <Package className="h-4 w-4 mr-2" />
                    Infer from Asset
                  </Button>
                  <Button onClick={() => { setEditingSchemaIndex(null); setIsSchemaFormOpen(true); }}>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Schema Manually
                  </Button>
                </div>
              )}
            </div>
          ) : contract.schema.length === 1 ? (
              // Single schema - simple view
              <div className="space-y-4">
                <div className="flex items-center gap-4 justify-between">
                  <div>
                    <Label className="text-base font-semibold">{contract.schema[0].name || 'Table 1'}</Label>
                    {contract.schema[0].name && schemaLinks[contract.schema[0].name] && schemaLinks[contract.schema[0].name].length > 0 && (
                      <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-2">
                        {schemaLinks[contract.schema[0].name].map((link, idx) => (
                          <span key={idx} className="inline-flex items-center gap-1">
                            <Shapes className="h-3 w-3" />
                            <span
                              className="cursor-pointer hover:underline"
                              onClick={() => {
                                const displayLabel = (link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)
                                window.open(`/data-catalog?concept=${encodeURIComponent(displayLabel)}`, '_blank')
                              }}
                              title={link.iri}
                            >
                              {(link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)}
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {contract.schema[0].physicalName && (
                      <a
                        href={`/catalog-commander?table=${encodeURIComponent(contract.schema[0].physicalName)}`}
                        className="flex items-center gap-1.5 text-sm text-primary hover:underline"
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`Open ${contract.schema[0].physicalName} in Catalog Commander`}
                      >
                        <Database className="h-4 w-4" />
                        {contract.schema[0].physicalName}
                      </a>
                    )}
                    {canEditInPlace && (
                      <>
                        <Button size="sm" variant="ghost" disabled={loadingEditProperties} onClick={() => handleEditSchema(0)}>
                          {loadingEditProperties ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pencil className="h-4 w-4" />}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => handleDeleteSchema(0)} className="text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                {renderSchemaPropertiesTable()}

                {/* Schema Authoritative Definitions */}
                {shouldShowSection('authoritative-definitions') && (() => {
                  const schemaId = (contract.schema[0] as any).id || contract.schema[0].name
                  const defs = schemaAuthDefs[schemaId] || []
                  return (
                    <div className="mt-4 pt-4 border-t">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-sm font-semibold">Authoritative Definitions ({defs.length})</h4>
                        {canEditInPlace && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setActiveSchemaIdForAuthDef(schemaId)
                              setEditingSchemaAuthDef(null)
                              setIsSchemaAuthDefFormOpen(true)
                            }}
                          >
                            <Plus className="h-3 w-3 mr-1" />
                            Add
                          </Button>
                        )}
                      </div>
                      {defs.length === 0 ? (
                        <p className="text-xs text-muted-foreground">No authoritative definitions for this schema.</p>
                      ) : (
                        <div className="space-y-2">
                          {defs.map((def, idx) => (
                            <div key={def.id} className="flex items-start justify-between p-2 border rounded text-xs">
                              <div className="space-y-1 flex-1">
                                <Badge variant="secondary" className="text-xs">{def.type}</Badge>
                                <a href={def.url} target="_blank" rel="noreferrer" className="text-primary hover:underline block break-all">
                                  {def.url}
                                </a>
                              </div>
                              {canEditInPlace && (
                                <div className="flex gap-1 ml-2">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => {
                                      setEditingSchemaAuthDef({ schemaId, index: idx })
                                      setIsSchemaAuthDefFormOpen(true)
                                    }}
                                    className="h-6 w-6 p-0"
                                  >
                                    <Pencil className="h-3 w-3" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleDeleteSchemaAuthDef(schemaId, idx)}
                                    className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </div>
            ) : contract.schema.length > 6 ? (
              // Many schemas - use dropdown selector
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <Label>Select Schema:</Label>
                  <Select value={selectedSchemaIndex.toString()} onValueChange={(value) => setSelectedSchemaIndex(parseInt(value))}>
                    <SelectTrigger className="w-80">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-[40vh] overflow-y-auto" position="popper" sideOffset={5}>
                      {contract.schema.map((schemaObj, idx) => (
                        <SelectItem key={idx} value={idx.toString()}>
                          {schemaObj.name || `Table ${idx + 1}`} ({schemaPropTotal[schemaObj.name] ?? schemaObj.propertyCount ?? 0} columns)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-4">
                  <div className="flex items-center gap-4 justify-between">
                    <div>
                      <Label className="text-base font-semibold">{contract.schema[selectedSchemaIndex]?.name || `Table ${selectedSchemaIndex + 1}`}</Label>
                      {contract.schema[selectedSchemaIndex]?.name && schemaLinks[contract.schema[selectedSchemaIndex].name] && schemaLinks[contract.schema[selectedSchemaIndex].name].length > 0 && (
                        <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-2">
                          {schemaLinks[contract.schema[selectedSchemaIndex].name].map((link, idx) => (
                            <span key={idx} className="inline-flex items-center gap-1">
                              <Shapes className="h-3 w-3" />
                              <span
                                className="cursor-pointer hover:underline"
                                onClick={() => {
                                  const displayLabel = (link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)
                                  window.open(`/data-catalog?concept=${encodeURIComponent(displayLabel)}`, '_blank')
                                }}
                                title={link.iri}
                              >
                                {(link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)}
                              </span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {contract.schema[selectedSchemaIndex]?.physicalName && (
                        <a
                          href={`/catalog-commander?table=${encodeURIComponent(contract.schema[selectedSchemaIndex].physicalName)}`}
                          className="flex items-center gap-1.5 text-sm text-primary hover:underline"
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Open ${contract.schema[selectedSchemaIndex].physicalName} in Catalog Commander`}
                        >
                          <Database className="h-4 w-4" />
                          {contract.schema[selectedSchemaIndex].physicalName}
                        </a>
                      )}
                      {canEditInPlace && (
                        <>
                          <Button size="sm" variant="ghost" disabled={loadingEditProperties} onClick={() => handleEditSchema(selectedSchemaIndex)}>
                            {loadingEditProperties ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pencil className="h-4 w-4" />}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => handleDeleteSchema(selectedSchemaIndex)} className="text-destructive hover:text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  {renderSchemaPropertiesTable()}

                  {/* Schema Authoritative Definitions */}
                  {shouldShowSection('authoritative-definitions') && (() => {
                    const schemaId = (contract.schema[selectedSchemaIndex] as any).id || contract.schema[selectedSchemaIndex].name
                    const defs = schemaAuthDefs[schemaId] || []
                    return (
                      <div className="mt-4 pt-4 border-t">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-semibold">Authoritative Definitions ({defs.length})</h4>
                          {canEditInPlace && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setActiveSchemaIdForAuthDef(schemaId)
                                setEditingSchemaAuthDef(null)
                                setIsSchemaAuthDefFormOpen(true)
                              }}
                            >
                              <Plus className="h-3 w-3 mr-1" />
                              Add
                            </Button>
                          )}
                        </div>
                        {defs.length === 0 ? (
                          <p className="text-xs text-muted-foreground">No authoritative definitions for this schema.</p>
                        ) : (
                          <div className="space-y-2">
                            {defs.map((def, idx) => (
                              <div key={def.id} className="flex items-start justify-between p-2 border rounded text-xs">
                                <div className="space-y-1 flex-1">
                                  <Badge variant="secondary" className="text-xs">{def.type}</Badge>
                                  <a href={def.url} target="_blank" rel="noreferrer" className="text-primary hover:underline block break-all">
                                    {def.url}
                                  </a>
                                </div>
                                {canEditInPlace && (
                                  <div className="flex gap-1 ml-2">
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => {
                                        setEditingSchemaAuthDef({ schemaId, index: idx })
                                        setIsSchemaAuthDefFormOpen(true)
                                      }}
                                      className="h-6 w-6 p-0"
                                    >
                                      <Pencil className="h-3 w-3" />
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => handleDeleteSchemaAuthDef(schemaId, idx)}
                                      className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </Button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })()}
                </div>
              </div>
            ) : (
              // Few schemas - use tabs with custom scrollable container
              <div className="space-y-4">
                <div className="w-full overflow-x-auto">
                  <div className="flex border-b border-border">
                    {contract.schema.map((schemaObj, idx) => (
                      <button
                        key={idx}
                        onClick={() => setSelectedSchemaIndex(idx)}
                        className={`flex-shrink-0 px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                          selectedSchemaIndex === idx
                            ? 'border-primary text-primary'
                            : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground'
                        }`}
                      >
                        {schemaObj.name || `Table ${idx + 1}`}
                        <span className="ml-2 text-xs">
                          ({schemaPropTotal[schemaObj.name] ?? schemaObj.propertyCount ?? schemaObj.properties?.length ?? 0})
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-4">
                  <div className="flex items-center gap-4 justify-between">
                    <div>
                      <Label className="text-base font-semibold">{contract.schema[selectedSchemaIndex]?.name || `Table ${selectedSchemaIndex + 1}`}</Label>
                      {contract.schema[selectedSchemaIndex]?.name && schemaLinks[contract.schema[selectedSchemaIndex].name] && schemaLinks[contract.schema[selectedSchemaIndex].name].length > 0 && (
                        <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-2">
                          {schemaLinks[contract.schema[selectedSchemaIndex].name].map((link, idx) => (
                            <span key={idx} className="inline-flex items-center gap-1">
                              <Shapes className="h-3 w-3" />
                              <span
                                className="cursor-pointer hover:underline"
                                onClick={() => {
                                  const displayLabel = (link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)
                                  window.open(`/data-catalog?concept=${encodeURIComponent(displayLabel)}`, '_blank')
                                }}
                                title={link.iri}
                              >
                                {(link.label && !/^https?:\/\//.test(link.label) && !/^urn:/.test(link.label)) ? link.label : (link.iri.split(/[\/#]/).pop() || link.iri)}
                              </span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {contract.schema[selectedSchemaIndex]?.physicalName && (
                        <a
                          href={`/catalog-commander?table=${encodeURIComponent(contract.schema[selectedSchemaIndex].physicalName)}`}
                          className="flex items-center gap-1.5 text-sm text-primary hover:underline"
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Open ${contract.schema[selectedSchemaIndex].physicalName} in Catalog Commander`}
                        >
                          <Database className="h-4 w-4" />
                          {contract.schema[selectedSchemaIndex].physicalName}
                        </a>
                      )}
                      {canEditInPlace && (
                        <>
                          <Button size="sm" variant="ghost" disabled={loadingEditProperties} onClick={() => handleEditSchema(selectedSchemaIndex)}>
                            {loadingEditProperties ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pencil className="h-4 w-4" />}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => handleDeleteSchema(selectedSchemaIndex)} className="text-destructive hover:text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  {renderSchemaPropertiesTable()}

                  {/* Schema Authoritative Definitions */}
                  {shouldShowSection('authoritative-definitions') && (() => {
                    const schemaId = (contract.schema[selectedSchemaIndex] as any).id || contract.schema[selectedSchemaIndex].name
                    const defs = schemaAuthDefs[schemaId] || []
                    return (
                      <div className="mt-4 pt-4 border-t">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-semibold">Authoritative Definitions ({defs.length})</h4>
                          {canEditInPlace && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setActiveSchemaIdForAuthDef(schemaId)
                                setEditingSchemaAuthDef(null)
                                setIsSchemaAuthDefFormOpen(true)
                              }}
                            >
                              <Plus className="h-3 w-3 mr-1" />
                              Add
                            </Button>
                          )}
                        </div>
                        {defs.length === 0 ? (
                          <p className="text-xs text-muted-foreground">No authoritative definitions for this schema.</p>
                        ) : (
                          <div className="space-y-2">
                            {defs.map((def, idx) => (
                              <div key={def.id} className="flex items-start justify-between p-2 border rounded text-xs">
                                <div className="space-y-1 flex-1">
                                  <Badge variant="secondary" className="text-xs">{def.type}</Badge>
                                  <a href={def.url} target="_blank" rel="noreferrer" className="text-primary hover:underline block break-all">
                                    {def.url}
                                  </a>
                                </div>
                                {canEditInPlace && (
                                  <div className="flex gap-1 ml-2">
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => {
                                        setEditingSchemaAuthDef({ schemaId, index: idx })
                                        setIsSchemaAuthDefFormOpen(true)
                                      }}
                                      className="h-6 w-6 p-0"
                                    >
                                      <Pencil className="h-3 w-3" />
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => handleDeleteSchemaAuthDef(schemaId, idx)}
                                      className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </Button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })()}
                </div>
              </div>
            )
          }
        </CardContent>
      </Card>

      {/* Linked Data Products Section */}
      {shouldShowLinkedProducts() && (
        <Card>
          <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl flex items-center gap-2">
                <Package className="h-5 w-5 text-primary" />
                Linked Data Products ({linkedProducts.length})
              </CardTitle>
              <CardDescription>Data Products using this contract for deliverables</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsLinkProductDialogOpen(true)}
                disabled={!contract || !['active', 'approved', 'certified'].includes((contract.status || '').toLowerCase())}
              >
                <Plus className="h-4 w-4 mr-1.5" />
                Link to Existing Product
              </Button>
              <Button
                size="sm"
                onClick={() => setIsCreateProductDialogOpen(true)}
                disabled={!contract || !['active', 'approved', 'certified'].includes((contract.status || '').toLowerCase())}
              >
                <Plus className="h-4 w-4 mr-1.5" />
                Create Data Product
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingProducts ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : linkedProducts.length === 0 ? (
            <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
              <Package className="h-12 w-12 mx-auto text-muted-foreground/50 mb-3" />
              <div className="text-muted-foreground mb-2">No linked data products yet</div>
              <div className="text-sm text-muted-foreground mb-4">
                Create a data product that uses this contract to govern a deliverable
              </div>
              {contract && ['active', 'approved', 'certified'].includes((contract.status || '').toLowerCase()) ? (
                <Button onClick={() => setIsCreateProductDialogOpen(true)}>
                  <Plus className="h-4 w-4 mr-2" />
                  Create Data Product
                </Button>
              ) : (
                <div className="text-sm text-muted-foreground italic">
                  Contract must be in 'active', 'approved', or 'certified' status
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {linkedProducts.map((product) => {
                // Find output ports that use this contract
                const linkedPorts = product.outputPorts?.filter(port => port.contractId === contractId) || [];
                return (
                  <div
                    key={product.id}
                    className="p-4 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                    onClick={() => navigate(`${productBasePath}/${product.id}`)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="font-medium text-base">{product.name || 'Unnamed Product'}</div>
                        {product.description?.purpose && (
                          <p className="text-sm text-muted-foreground mt-1">{product.description.purpose}</p>
                        )}
                        <div className="flex items-center gap-3 mt-2">
                          <Badge variant="outline" className="text-xs">
                            v{product.version}
                          </Badge>
                          <Badge variant="secondary" className="text-xs">
                            {product.status}
                          </Badge>
                        </div>
                        {linkedPorts.length > 0 && (
                          <div className="mt-2 text-xs text-muted-foreground">
                            Deliverable{linkedPorts.length > 1 ? 's' : ''}: {linkedPorts.map(port => `${port.name} (v${port.version})`).join(', ')}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {/* Linked Datasets Section */}
      {shouldShowLinkedDatasets() && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-xl flex items-center gap-2">
                  <Table2 className="h-5 w-5 text-primary" />
                  Linked Datasets ({linkedDatasets.length})
                </CardTitle>
                <CardDescription>Datasets that implement this contract</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setIsLinkDatasetDialogOpen(true)}
                >
                  <Plus className="h-4 w-4 mr-1.5" />
                  Link to Existing Dataset
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loadingDatasets ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : linkedDatasets.length === 0 ? (
              <div className="text-center py-12 border-2 border-dashed border-muted-foreground/25 rounded-lg">
                <Table2 className="h-12 w-12 mx-auto text-muted-foreground/50 mb-3" />
                <div className="text-muted-foreground mb-2">No linked datasets yet</div>
                <div className="text-sm text-muted-foreground">
                  Datasets can be linked to this contract from the Dataset details page
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {linkedDatasets.map((dataset) => (
                  <div
                    key={dataset.id}
                    className="p-4 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                    onClick={() => navigate(`/datasets/${dataset.id}`)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="font-medium text-base">{dataset.name || 'Unnamed Dataset'}</div>
                        {dataset.description && (
                          <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{dataset.description}</p>
                        )}
                        <div className="flex items-center gap-3 mt-2">
                          {dataset.version && (
                            <Badge variant="outline" className="text-xs">
                              v{dataset.version}
                            </Badge>
                          )}
                          <Badge 
                            variant="secondary" 
                            className={`text-xs ${DATASET_STATUS_COLORS[dataset.status] || ''}`}
                          >
                            {DATASET_STATUS_LABELS[dataset.status] || dataset.status}
                          </Badge>
                          {dataset.instance_count !== undefined && dataset.instance_count > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {dataset.instance_count} instance{dataset.instance_count !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                        {dataset.owner_team_name && (
                          <div className="mt-2 text-xs text-muted-foreground">
                            Owner: {dataset.owner_team_name}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Quality Rules Section */}
      {shouldShowSection('quality-rules') && (
        <Card>
          <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl">Quality Rules ({contract.qualityRules?.length || 0})</CardTitle>
              <CardDescription>Data quality checks and validations</CardDescription>
            </div>
            {canEditInPlace && (
              <Button size="sm" onClick={() => { setEditingQualityRuleIndex(null); setIsQualityRuleFormOpen(true); }}>
                <Plus className="h-4 w-4 mr-1.5" />
                Add Rule
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {contract.qualityRules && contract.qualityRules.length > 0 ? (
            <div className="space-y-3">
              {contract.qualityRules.map((rule, idx) => (
                <div key={idx} className="border rounded-lg p-3 flex items-center justify-between">
                  <div>
                    <div className="font-medium">{rule.name}</div>
                    <div className="text-sm text-muted-foreground flex gap-2 mt-1">
                      <Badge variant="outline" className="text-xs">{rule.dimension}</Badge>
                      <Badge variant="secondary" className="text-xs">{rule.severity}</Badge>
                      <span>{rule.type}</span>
                    </div>
                  </div>
                  {canEditInPlace && (
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => { setEditingQualityRuleIndex(idx); setIsQualityRuleFormOpen(true); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => handleDeleteQualityRule(idx)} className="text-destructive hover:text-destructive">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-8">No quality rules defined. Click "Add Rule" to create one.</p>
          )}
        </CardContent>
      </Card>
      )}

      {/* Team & Roles Section */}
      {shouldShowSection('team-members') && (
        <Card>
          <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl">Team Members ({contract.team?.length || 0})</CardTitle>
              <CardDescription>Team responsible for this contract</CardDescription>
            </div>
            <div className="flex gap-2">
              {(() => {
                console.log('[DEBUG] Rendering Team Members buttons:', {
                  owner_team_id: contract.owner_team_id,
                  owner_team_name: contract.owner_team_name,
                  hasOwnerTeamId: !!contract.owner_team_id,
                  shouldShowButton: !!contract.owner_team_id
                })
                return null
              })()}
              {canEditInPlace && contract.owner_team_id && (
                <Button 
                  size="sm" 
                  variant="outline"
                  onClick={() => setIsImportTeamMembersOpen(true)}
                  disabled={!contract.owner_team_name}
                  title={contract.owner_team_name ? `Import members from ${contract.owner_team_name}` : 'No team assigned'}
                >
                  <Plus className="h-4 w-4 mr-1.5" />
                  Import from Team
                </Button>
              )}
              {canEditInPlace && (
                <Button size="sm" onClick={() => { setEditingTeamMemberIndex(null); setIsTeamMemberFormOpen(true); }}>
                  <Plus className="h-4 w-4 mr-1.5" />
                  Add Member
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {contract.team && contract.team.length > 0 ? (
            <div className="space-y-2">
              {contract.team.map((member, idx) => (
                <div key={idx} className="flex items-center justify-between p-3 border rounded-lg">
                  <div className="flex items-center gap-3">
                    <Badge variant="outline">{member.role}</Badge>
                    <span className="text-sm">{member.name || member.username || member.email}</span>
                  </div>
                  {canEditInPlace && (
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => { setEditingTeamMemberIndex(idx); setIsTeamMemberFormOpen(true); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => handleDeleteTeamMember(idx)} className="text-destructive hover:text-destructive">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-8">No team members defined. Click "Add Member" to add one.</p>
          )}
        </CardContent>
      </Card>
      )}

      {/* SLA & Infrastructure Section */}
      {shouldShowSection('sla') && (
        <Card>
          <CardHeader>
          <CardTitle className="text-xl">SLA & Infrastructure</CardTitle>
          <CardDescription>Service level agreements and server configurations</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* SLA Requirements */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <Label className="text-base font-semibold">SLA Requirements</Label>
              {canEditInPlace && (
                <Button size="sm" variant="outline" onClick={() => setIsSLAFormOpen(true)}>
                  <Pencil className="h-4 w-4 mr-1.5" />
                  Edit SLA
                </Button>
              )}
            </div>
            {contract.sla && Object.keys(contract.sla).length > 0 ? (
              <div className="grid grid-cols-2 gap-3 pl-4">
                {contract.sla.uptimeTarget !== undefined && (
                  <div className="space-y-1">
                    <Label className="text-sm">Uptime Target:</Label>
                    <span className="text-sm text-muted-foreground block">{contract.sla.uptimeTarget}%</span>
                  </div>
                )}
                {contract.sla.maxDowntimeMinutes !== undefined && (
                  <div className="space-y-1">
                    <Label className="text-sm">Max Downtime:</Label>
                    <span className="text-sm text-muted-foreground block">{contract.sla.maxDowntimeMinutes} min</span>
                  </div>
                )}
                {contract.sla.queryResponseTimeMs !== undefined && (
                  <div className="space-y-1">
                    <Label className="text-sm">Query Response Time:</Label>
                    <span className="text-sm text-muted-foreground block">{contract.sla.queryResponseTimeMs} ms</span>
                  </div>
                )}
                {contract.sla.dataFreshnessMinutes !== undefined && (
                  <div className="space-y-1">
                    <Label className="text-sm">Data Freshness:</Label>
                    <span className="text-sm text-muted-foreground block">{contract.sla.dataFreshnessMinutes} min</span>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground pl-4">No SLA requirements defined.</p>
            )}
          </div>

          {/* Server Configurations */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <Label className="text-base font-semibold">Server Configurations ({serversList.length})</Label>
              {canEditInPlace && (
                <Button size="sm" onClick={() => { setEditingServerIndex(null); setIsServerConfigFormOpen(true); }}>
                  <Plus className="h-4 w-4 mr-1.5" />
                  Add Server
                </Button>
              )}
            </div>
            {serversList.length > 0 ? (
              <div className="space-y-2 pl-4">
                {serversList.map((server, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 border rounded-lg">
                    <div>
                      <div className="font-medium">{server.server}</div>
                      <div className="text-sm text-muted-foreground flex gap-2 mt-1">
                        <Badge variant="outline" className="text-xs">{server.type}</Badge>
                        <Badge variant="secondary" className="text-xs">{server.environment}</Badge>
                        {server.host && <span>{server.host}</span>}
                      </div>
                    </div>
                    {canEditInPlace && (
                      <div className="flex gap-2">
                        <Button size="sm" variant="ghost" onClick={() => { setEditingServerIndex(idx); setIsServerConfigFormOpen(true); }}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => handleDeleteServer(idx)} className="text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground pl-4">No server configurations defined.</p>
            )}
          </div>
        </CardContent>
      </Card>
      )}

      {/* Access Control (read-only for now, can add edit later) */}
      {shouldShowSection('access-control') && contract.accessControl && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Access Control</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-2 gap-3">
              {contract.accessControl.classification && (
                <div className="space-y-1">
                  <Label>Classification:</Label>
                  <Badge variant="secondary">{contract.accessControl.classification}</Badge>
                </div>
              )}
              <div className="space-y-1">
                <Label>Contains PII:</Label>
                <span className="text-sm">{contract.accessControl.containsPii ? 'Yes' : 'No'}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Custom Properties */}
      {shouldShowSection('custom-properties') && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-xl">Custom Properties ({Object.keys(contract.customProperties || {}).length})</CardTitle>
                <CardDescription>Additional metadata and configuration</CardDescription>
              </div>
              {canEditInPlace && (
                <Button size="sm" onClick={() => { setEditingCustomPropertyKey(null); setIsCustomPropertyFormOpen(true); }}>
                  <Plus className="h-4 w-4 mr-1.5" />
                  Add Property
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {!contract.customProperties || Object.keys(contract.customProperties).length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">No custom properties defined. Click "Add Property" to create one.</p>
            ) : (
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="text-left p-3 font-medium w-48">Property</th>
                      <th className="text-left p-3 font-medium">Value</th>
                      <th className="text-right p-3 font-medium w-24">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(contract.customProperties).map(([key, value]) => {
                      const valueStr = String(value)
                      const isJson = valueStr.startsWith('[') || valueStr.startsWith('{')
                      return (
                        <tr key={key} className="border-t hover:bg-muted/30">
                          <td className="p-3 align-top">
                            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-medium">{key}</code>
                          </td>
                          <td className="p-3 align-top">
                            {isJson ? (
                              <pre className="text-xs bg-muted/50 p-2 rounded overflow-x-auto max-h-32 whitespace-pre-wrap break-all font-mono">
                                {(() => {
                                  try {
                                    return JSON.stringify(JSON.parse(valueStr), null, 2)
                                  } catch {
                                    return valueStr
                                  }
                                })()}
                              </pre>
                            ) : (
                              <span className="text-muted-foreground break-all">{valueStr}</span>
                            )}
                          </td>
                          {canEditInPlace && (
                            <td className="p-3 align-top text-right">
                              <div className="flex justify-end gap-1">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => {
                                    setEditingCustomPropertyKey(key)
                                    setIsCustomPropertyFormOpen(true)
                                  }}
                                  className="h-7 w-7 p-0"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => handleDeleteCustomProperty(key)}
                                  className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </td>
                          )}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Support Channels (read-only for now) */}
      {shouldShowSection('support') && contract.support && Object.keys(contract.support).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Support</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(contract.support).map(([channel, url]) => (
                <div key={channel} className="flex items-center gap-3">
                  <Badge variant="outline" className="text-xs capitalize">{channel}</Badge>
                  {url ? (
                    <a href={url} target="_blank" rel="noreferrer" className="text-sm text-primary hover:underline break-all">{url}</a>
                  ) : (
                    <span className="text-sm text-muted-foreground">N/A</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Authoritative Definitions - Contract Level (ODCS) */}
      {shouldShowSection('authoritative-definitions') && (
        <Card>
          <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl">Authoritative Definitions</CardTitle>
              <CardDescription>ODCS authoritative sources for this contract ({contractAuthDefs.length})</CardDescription>
            </div>
            {canEditInPlace && (
              <Button
                size="sm"
                onClick={() => {
                  setEditingContractAuthDefIndex(null)
                  setIsContractAuthDefFormOpen(true)
                }}
              >
                <Plus className="h-4 w-4 mr-1.5" />
                Add Definition
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {contractAuthDefs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No authoritative definitions defined yet.</p>
          ) : (
            <div className="space-y-3">
              {contractAuthDefs.map((def, idx) => (
                <div key={def.id} className="flex items-start justify-between p-3 border rounded-md">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="text-xs">{def.type}</Badge>
                    </div>
                    <a
                      href={def.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-primary hover:underline break-all block"
                    >
                      {def.url}
                    </a>
                  </div>
                  {canEditInPlace && (
                    <div className="flex gap-1 ml-3">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setEditingContractAuthDefIndex(idx)
                          setIsContractAuthDefFormOpen(true)
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteContractAuthDef(idx)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {/* Ownership Panel */}
      {shouldShowSection('metadata-panel') && contract.id && (
        <OwnershipPanel objectType="data_contract" objectId={contract.id} canAssign={canEditInPlace} className="mb-6" />
      )}

      {/* Entity Relationships Panel */}
      {shouldShowSection('metadata-panel') && contract.id && (
        <EntityTreePanel
          entityType="DataContract"
          entityId={contract.id}
          title="Related Entities"
          canEdit={canEditInPlace}
        />
      )}

      {/* Metadata Panel */}
      {shouldShowSection('metadata-panel') && contract.id && (
        <EntityMetadataPanel entityId={contract.id} entityType="data_contract" />
      )}

      {/* Quality Panel */}
      {contract.id && (
        <EntityQualityPanel entityId={contract.id} entityType="data_contract" />
      )}

      {/* Dialogs */}
      <DataContractBasicFormDialog
        isOpen={isBasicFormOpen}
        onOpenChange={setIsBasicFormOpen}
        initial={{
          name: contract.name,
          version: contract.version,
          status: contract.status,
          owner_team_id: contract.owner_team_id,
          project_id: (contract as any).project_id,
          domain: contract.domainId,
          tenant: contract.tenant,
          descriptionUsage: contract.description?.usage,
          descriptionPurpose: contract.description?.purpose,
          descriptionLimitations: contract.description?.limitations,
          tags: contract.tags || [],
        }}
        onSubmit={handleUpdateMetadata}
      />

      <SchemaFormDialog
        isOpen={isSchemaFormOpen}
        onOpenChange={setIsSchemaFormOpen}
        initial={schemaFormInitial}
        onSubmit={editingSchemaIndex !== null ? handleUpdateSchema : handleAddSchema}
      />

      <QualityRuleFormDialog
        isOpen={isQualityRuleFormOpen}
        onOpenChange={setIsQualityRuleFormOpen}
        initial={editingQualityRuleIndex !== null ? contract.qualityRules?.[editingQualityRuleIndex] : undefined}
        onSubmit={editingQualityRuleIndex !== null ? handleUpdateQualityRule : handleAddQualityRule}
      />

      <TeamMemberFormDialog
        isOpen={isTeamMemberFormOpen}
        onOpenChange={setIsTeamMemberFormOpen}
        initial={editingTeamMemberIndex !== null ? contract.team?.[editingTeamMemberIndex] : undefined}
        onSubmit={editingTeamMemberIndex !== null ? handleUpdateTeamMember : handleAddTeamMember}
      />

      <ServerConfigFormDialog
        isOpen={isServerConfigFormOpen}
        onOpenChange={setIsServerConfigFormOpen}
        initial={editingServerIndex !== null ? serversList[editingServerIndex] : undefined}
        onSubmit={editingServerIndex !== null ? handleUpdateServer : handleAddServer}
      />

      <SLAFormDialog
        isOpen={isSLAFormOpen}
        onOpenChange={setIsSLAFormOpen}
        initial={contract.sla}
        onSubmit={handleUpdateSLA}
      />

      <ConceptSelectDialog
        isOpen={iriDialogOpen}
        onOpenChange={setIriDialogOpen}
        onSelect={addIri}
      />

      {contract && (
        <CreateVersionDialog
          isOpen={isVersionDialogOpen}
          onOpenChange={setIsVersionDialogOpen}
          currentVersion={contract.version}
          productTitle={contract.name}
          onSubmit={submitNewVersion}
        />
      )}

      {contract && (
        <RequestContractActionDialog
          isOpen={isRequestDialogOpen}
          onOpenChange={setIsRequestDialogOpen}
          contractId={contractId!}
          contractName={contract.name}
          contractStatus={contract.status}
          onSuccess={() => fetchDetails()}
          canDirectStatusChange={(() => {
            const permLevel = getPermissionLevel('data-contracts')
            return permLevel === FeatureAccessLevel.READ_WRITE ||
                   permLevel === FeatureAccessLevel.ADMIN ||
                   permLevel === FeatureAccessLevel.FULL
          })()}
        />
      )}

      <InferFromCatalogDialog
        isOpen={isInferFromCatalogOpen}
        onOpenChange={setIsInferFromCatalogOpen}
        onInfer={handleInferFromCatalog}
      />

      <InferFromAssetDialog
        isOpen={isInferFromAssetOpen}
        onOpenChange={setIsInferFromAssetOpen}
        onInfer={handleInferFromAsset}
      />

      {contract && (
        <CreateFromContractDialog
          isOpen={isCreateProductDialogOpen}
          onOpenChange={setIsCreateProductDialogOpen}
          contractId={contractId!}
          contractName={contract.name}
          onSuccess={(productId) => {
            fetchLinkedProducts()
            navigate(`${productBasePath}/${productId}`)
          }}
        />
      )}

      {/* DQX Profiling Dialogs */}
      <DqxSchemaSelectDialog
        isOpen={isDqxSchemaSelectOpen}
        onOpenChange={setIsDqxSchemaSelectOpen}
        contract={contract}
        onConfirm={handleStartProfiling}
      />

      {selectedProfileRunId && (
        <DqxSuggestionsDialog
          isOpen={isDqxSuggestionsOpen}
          onOpenChange={setIsDqxSuggestionsOpen}
          contractId={contractId!}
          contract={contract}
          profileRunId={selectedProfileRunId}
          onSuccess={handleSuggestionsSuccess}
        />
      )}

      <AuthoritativeDefinitionFormDialog
        isOpen={isContractAuthDefFormOpen}
        onOpenChange={setIsContractAuthDefFormOpen}
        initial={editingContractAuthDefIndex !== null ? contractAuthDefs[editingContractAuthDefIndex] : undefined}
        onSubmit={editingContractAuthDefIndex !== null ? handleUpdateContractAuthDef : handleAddContractAuthDef}
        level="contract"
      />

      <AuthoritativeDefinitionFormDialog
        isOpen={isSchemaAuthDefFormOpen}
        onOpenChange={setIsSchemaAuthDefFormOpen}
        initial={editingSchemaAuthDef !== null && activeSchemaIdForAuthDef ? schemaAuthDefs[editingSchemaAuthDef.schemaId]?.[editingSchemaAuthDef.index] : undefined}
        onSubmit={editingSchemaAuthDef !== null ? handleUpdateSchemaAuthDef : handleAddSchemaAuthDef}
        level="schema"
      />

      <AuthoritativeDefinitionFormDialog
        isOpen={isPropertyAuthDefFormOpen}
        onOpenChange={setIsPropertyAuthDefFormOpen}
        initial={editingPropertyAuthDef !== null && _activePropertyForAuthDef ? propertyAuthDefs[editingPropertyAuthDef.propertyId]?.[editingPropertyAuthDef.index] : undefined}
        onSubmit={editingPropertyAuthDef !== null ? handleUpdatePropertyAuthDef : handleAddPropertyAuthDef}
        level="property"
      />

      {/* Import Team Members Dialog */}
      {contract?.owner_team_id && (
        <ImportTeamMembersDialog
          isOpen={isImportTeamMembersOpen}
          onOpenChange={setIsImportTeamMembersOpen}
          entityId={contractId!}
          entityType="contract"
          teamId={contract.owner_team_id}
          teamName={contract.owner_team_name || contract.owner_team_id}
          onImport={handleImportTeamMembers}
        />
      )}

      {/* Link Product to Contract Dialog */}
      <LinkProductToContractDialog
        isOpen={isLinkProductDialogOpen}
        onOpenChange={setIsLinkProductDialogOpen}
        contractId={contractId!}
        contractName={contract?.name || 'this contract'}
        onSuccess={() => {
          fetchLinkedProducts();
          setIsLinkProductDialogOpen(false);
          toast({
            title: 'Contract Linked',
            description: 'Contract successfully linked to product deliverable.'
          });
        }}
      />

      {/* Link Dataset to Contract Dialog */}
      <LinkDatasetToContractDialog
        isOpen={isLinkDatasetDialogOpen}
        onOpenChange={setIsLinkDatasetDialogOpen}
        contractId={contractId!}
        contractName={contract?.name || 'this contract'}
        onSuccess={() => {
          fetchLinkedDatasets();
          toast({
            title: 'Contract Linked',
            description: 'Contract successfully linked to dataset.'
          });
        }}
      />

      <VersioningRecommendationDialog
        isOpen={isVersioningDialogOpen}
        onOpenChange={setIsVersioningDialogOpen}
        analysis={versioningAnalysis}
        userCanOverride={versioningUserCanOverride}
        onUpdateInPlace={handleVersioningUpdateInPlace}
        onCreateNewVersion={handleVersioningCreateNewVersion}
      />

      <CustomPropertyFormDialog
        isOpen={isCustomPropertyFormOpen}
        onOpenChange={setIsCustomPropertyFormOpen}
        initial={editingCustomPropertyKey && contract?.customProperties ? {
          property: editingCustomPropertyKey,
          value: String(contract.customProperties[editingCustomPropertyKey] || '')
        } : undefined}
        existingKeys={Object.keys(contract?.customProperties || {})}
        onSubmit={editingCustomPropertyKey ? handleUpdateCustomProperty : handleAddCustomProperty}
      />

      {/* Commit Draft Dialog */}
      <CommitDraftDialog
        isOpen={isCommitDraftDialogOpen}
        onOpenChange={setIsCommitDraftDialogOpen}
        contractId={contractId!}
        contractName={contract?.name || 'this contract'}
        onSuccess={handleCommitSuccess}
      />
    </div>
  )
}
