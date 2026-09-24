import { useEffect, useState, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DataTable } from '@/components/ui/data-table'
import { ColumnDef, RowSelectionState } from '@tanstack/react-table'
import { useToast } from '@/hooks/use-toast'
import { CheckCircle2, XCircle, Loader2, Sparkles } from 'lucide-react'
import type { SuggestedQualityCheck, DataContract } from '@/types/data-contract'
import CreateVersionDialog from '@/components/data-products/create-version-dialog'

interface DqxSuggestionsDialogProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  contractId: string
  contract: DataContract | null
  profileRunId: string
  onSuccess: () => void
}

export default function DqxSuggestionsDialog({
  isOpen,
  onOpenChange,
  contractId,
  contract,
  profileRunId,
  onSuccess
}: DqxSuggestionsDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { toast } = useToast()
  const [suggestions, setSuggestions] = useState<SuggestedQualityCheck[]>([])
  const [loading, setLoading] = useState(false)
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [isVersionDialogOpen, setIsVersionDialogOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<'accept' | 'reject' | null>(null)

  // Compute selected IDs from row selection state
  const selectedIds = useMemo(() => {
    return new Set(Object.keys(rowSelection).filter(id => rowSelection[id]))
  }, [rowSelection])

  // Group suggestions by schema
  const suggestionsBySchema = useMemo(() => {
    const grouped: Record<string, SuggestedQualityCheck[]> = {}
    suggestions.filter(s => s.status === 'pending').forEach(suggestion => {
      if (!grouped[suggestion.schema_name]) {
        grouped[suggestion.schema_name] = []
      }
      grouped[suggestion.schema_name].push(suggestion)
    })
    return grouped
  }, [suggestions])

  const schemaNames = Object.keys(suggestionsBySchema)
  const pendingCount = suggestions.filter(s => s.status === 'pending').length

  useEffect(() => {
    if (isOpen && profileRunId) {
      fetchSuggestions()
    }
  }, [isOpen, profileRunId])

  const fetchSuggestions = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/profile-runs/${profileRunId}/suggestions`)
      if (!res.ok) throw new Error('Failed to fetch suggestions')
      const data = await res.json()
      setSuggestions(Array.isArray(data) ? data : [])
    } catch (e) {
      toast({ title: t('common:toast.error'), description: e instanceof Error ? e.message : t('data-contracts:dqx.loadError', 'Failed to load suggestions'), variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  const handleSelectAll = useCallback(() => {
    // Select/deselect all pending suggestions
    const pendingIds = suggestions.filter(s => s.status === 'pending').map(s => s.id)
    const allSelected = pendingIds.length > 0 && pendingIds.every(id => rowSelection[id])

    if (allSelected) {
      setRowSelection({})
    } else {
      const newSelection: RowSelectionState = {}
      pendingIds.forEach(id => { newSelection[id] = true })
      setRowSelection(newSelection)
    }
  }, [suggestions, rowSelection])

  const handleAccept = () => {
    if (selectedIds.size === 0) return

    // Check if version bump is needed
    const needsVersionBump = contract && !['draft'].includes((contract.status || '').toLowerCase())

    if (needsVersionBump) {
      setPendingAction('accept')
      setIsVersionDialogOpen(true)
    } else {
      acceptSuggestions()
    }
  }

  const acceptSuggestions = async (newVersion?: string) => {
    try {
      const payload: any = {
        suggestion_ids: Array.from(selectedIds)
      }

      if (newVersion) {
        payload.bump_version = { new_version: newVersion }
      }

      const res = await fetch(`/api/data-contracts/${contractId}/suggestions/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })

      if (!res.ok) throw new Error('Failed to accept suggestions')

      const data = await res.json()
      toast({
        title: t('common:toast.success'),
        description: t('data-contracts:dqx.acceptedCount', { count: data.accepted_count, defaultValue: 'Accepted {{count}} quality check suggestions' })
      })

      setRowSelection({})
      onSuccess()
      onOpenChange(false)
    } catch (e) {
      toast({ title: t('common:toast.error'), description: e instanceof Error ? e.message : t('data-contracts:dqx.acceptError', 'Failed to accept suggestions'), variant: 'destructive' })
    }
  }

  const handleReject = async () => {
    if (selectedIds.size === 0) return

    if (!confirm(t('data-contracts:dqx.rejectConfirm', { count: selectedIds.size, defaultValue: 'Reject {{count}} suggestions?' }))) return

    try {
      const res = await fetch(`/api/data-contracts/${contractId}/suggestions/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ suggestion_ids: Array.from(selectedIds) })
      })

      if (!res.ok) throw new Error('Failed to reject suggestions')

      const data = await res.json()
      toast({ title: t('data-contracts:dqx.rejected', 'Rejected'), description: t('data-contracts:dqx.rejectedCount', { count: data.rejected_count, defaultValue: 'Rejected {{count}} suggestions' }) })

      setRowSelection({})
      fetchSuggestions()
    } catch (e) {
      toast({ title: t('common:toast.error'), description: e instanceof Error ? e.message : t('data-contracts:dqx.rejectError', 'Failed to reject suggestions'), variant: 'destructive' })
    }
  }

  const submitNewVersion = async (newVersionString: string) => {
    if (pendingAction === 'accept') {
      await acceptSuggestions(newVersionString)
    }
    setPendingAction(null)
  }

  const createColumns = (): ColumnDef<SuggestedQualityCheck>[] => [
    {
      accessorKey: 'property_name',
      header: t('data-contracts:dqx.columns.column', 'Column'),
      cell: ({ row }) => (
        <span className="font-mono text-sm">
          {row.original.property_name || <span className="text-muted-foreground italic">{t('data-contracts:dqx.tableLevel', 'Table-level')}</span>}
        </span>
      )
    },
    {
      accessorKey: 'name',
      header: t('data-contracts:dqx.columns.ruleType', 'Rule Type'),
      cell: ({ row }) => (
        <span className="text-sm">{row.original.name || t('common:states.notAvailable')}</span>
      )
    },
    {
      accessorKey: 'dimension',
      header: t('data-contracts:dqx.columns.dimension', 'Dimension'),
      cell: ({ row }) => (
        row.original.dimension ? (
          <Badge variant="outline" className="text-xs">
            {row.original.dimension}
          </Badge>
        ) : null
      )
    },
    {
      accessorKey: 'severity',
      header: t('data-contracts:dqx.columns.severity', 'Severity'),
      cell: ({ row }) => {
        const severity = row.original.severity
        const variant = severity === 'error' ? 'destructive' : severity === 'warning' ? 'default' : 'secondary'
        return severity ? (
          <Badge variant={variant} className="text-xs">
            {severity}
          </Badge>
        ) : null
      }
    },
    {
      accessorKey: 'rule',
      header: t('data-contracts:dqx.columns.rule', 'Rule'),
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground font-mono max-w-xs truncate block">
          {row.original.rule || row.original.description || '-'}
        </span>
      )
    }
  ]

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-6xl max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              {t('data-contracts:dqx.reviewTitle', 'Review Quality Check Suggestions')}
            </DialogTitle>
            <DialogDescription>
              {t('data-contracts:dqx.reviewDescription', 'Review and accept DQX-generated quality check suggestions for your contract')}
            </DialogDescription>
          </DialogHeader>

          {loading ? (
            <div className="flex justify-center items-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : pendingCount === 0 ? (
            <Alert>
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>
                {t('data-contracts:dqx.noPending', 'No pending suggestions. All suggestions have been reviewed.')}
              </AlertDescription>
            </Alert>
          ) : (
            <div className="flex-1 overflow-hidden flex flex-col">
              <div className="flex items-center justify-between mb-4 pb-3 border-b">
                <div className="flex items-center gap-4">
                  <span className="text-sm font-medium">
                    {t('data-contracts:dqx.pendingCount', { count: pendingCount, defaultValue: '{{count}} pending suggestions' })}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {t('data-contracts:dqx.selectedCount', { count: selectedIds.size, defaultValue: '{{count}} selected' })}
                  </span>
                </div>
                <Button variant="ghost" size="sm" onClick={() => handleSelectAll()}>
                  {selectedIds.size === pendingCount ? t('data-contracts:dqx.deselectAll', 'Deselect All') : t('data-contracts:dqx.selectAll', 'Select All')}
                </Button>
              </div>

              <div className="flex-1 overflow-y-auto">
                {schemaNames.length === 1 ? (
                  // Single schema - simple view
                  <div className="space-y-3">
                    <div className="font-medium text-sm pb-2">
                      {schemaNames[0]}
                    </div>
                    <DataTable
                      columns={createColumns()}
                      data={suggestionsBySchema[schemaNames[0]]}
                      rowSelection={rowSelection}
                      onRowSelectionChange={setRowSelection}
                    />
                  </div>
                ) : (
                  // Multiple schemas - use tabs
                  <Tabs defaultValue={schemaNames[0]} className="w-full">
                    <TabsList className="w-full justify-start overflow-x-auto flex-nowrap">
                      {schemaNames.map(schemaName => (
                        <TabsTrigger key={schemaName} value={schemaName} className="flex-shrink-0">
                          {schemaName}
                          <Badge variant="secondary" className="ml-2 text-xs">
                            {suggestionsBySchema[schemaName].length}
                          </Badge>
                        </TabsTrigger>
                      ))}
                    </TabsList>
                    {schemaNames.map(schemaName => (
                      <TabsContent key={schemaName} value={schemaName} className="mt-4">
                        <DataTable
                          columns={createColumns()}
                          data={suggestionsBySchema[schemaName]}
                          rowSelection={rowSelection}
                          onRowSelectionChange={setRowSelection}
                        />
                      </TabsContent>
                    ))}
                  </Tabs>
                )}
              </div>
            </div>
          )}

          <DialogFooter className="flex items-center justify-between border-t pt-4">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common:actions.close')}
            </Button>
            <div className="flex gap-2">
              <Button
                variant="destructive"
                onClick={handleReject}
                disabled={selectedIds.size === 0 || loading}
              >
                <XCircle className="h-4 w-4 mr-2" />
                {t('data-contracts:dqx.rejectSelected', 'Reject Selected')}
              </Button>
              <Button
                onClick={handleAccept}
                disabled={selectedIds.size === 0 || loading}
              >
                <CheckCircle2 className="h-4 w-4 mr-2" />
                {t('data-contracts:dqx.acceptSelected', 'Accept Selected')}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {contract && (
        <CreateVersionDialog
          isOpen={isVersionDialogOpen}
          onOpenChange={setIsVersionDialogOpen}
          currentVersion={contract.version}
          productTitle={contract.name}
          onSubmit={submitNewVersion}
        />
      )}
    </>
  )
}
