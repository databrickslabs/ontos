import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/hooks/use-toast'
import { ArrowLeftRight, Plus, Trash2, Edit2, Clock, CheckCircle2, XCircle } from 'lucide-react'
import { ColumnDef } from "@tanstack/react-table"
import useBreadcrumbStore from '@/stores/breadcrumb-store'
import { DataTable } from '@/components/ui/data-table'
import { ListViewSkeleton } from '@/components/common/list-view-skeleton'

interface EntitlementsSyncConfig {
  id: string
  name: string
  connection: string
  schedule: string
  enabled: boolean
  catalogs: string[]
  lastSync?: {
    status: 'success' | 'error' | 'running'
    timestamp?: string
    error?: string
  }
}

export default function EntitlementsSync() {
  const { t } = useTranslation(['entitlements', 'common'])
  const [configs, setConfigs] = useState<EntitlementsSyncConfig[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<EntitlementsSyncConfig | null>(null)
  const [connections, setConnections] = useState<{ id: string; name: string }[]>([])
  const [catalogs, setCatalogs] = useState<string[]>([])
  const { toast } = useToast()

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments)
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle)

  useEffect(() => {
    fetchConfigs()
    setStaticSegments([])
    setDynamicTitle(t('entitlements:sync.title'))

    return () => {
      setStaticSegments([])
      setDynamicTitle(null)
    }
  }, [setStaticSegments, setDynamicTitle])

  // Load connections and catalogs when dialog opens
  useEffect(() => {
    if (isDialogOpen) {
      fetchConnections()
      fetchCatalogs()
    }
  }, [isDialogOpen])

  const fetchConfigs = async () => {
    try {
      const response = await fetch('/api/entitlements-sync/configs')
      if (!response.ok) throw new Error('Failed to load configurations')
      const data = await response.json()
      setConfigs(data)
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:sync.errors.loadConfigsFailed'),
        variant: 'destructive',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const fetchConnections = async () => {
    try {
      const response = await fetch('/api/entitlements-sync/connections')
      if (!response.ok) throw new Error('Failed to load connections')
      const data = await response.json()
      setConnections(data)
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:sync.errors.loadConnectionsFailed'),
        variant: 'destructive',
      })
    }
  }

  const fetchCatalogs = async () => {
    try {
      const response = await fetch('/api/entitlements-sync/catalogs')
      if (!response.ok) throw new Error('Failed to load catalogs')
      const data = await response.json()
      setCatalogs(data)
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:sync.errors.loadCatalogsFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const formData = new FormData(e.target as HTMLFormElement)
    const config: Partial<EntitlementsSyncConfig> = {
      name: formData.get('name') as string,
      connection: formData.get('connection') as string,
      schedule: formData.get('schedule') as string,
      enabled: formData.get('enabled') === 'on',
      catalogs: formData.getAll('catalogs') as string[],
    }

    try {
      const url = editingConfig
        ? `/api/entitlements-sync/configs/${editingConfig.id}`
        : '/api/entitlements-sync/configs'
      const method = editingConfig ? 'PUT' : 'POST'

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })

      if (!response.ok) throw new Error('Failed to save configuration')

      toast({
        title: t('common:toast.success'),
        description: editingConfig ? t('entitlements:sync.configUpdated') : t('entitlements:sync.configCreated'),
      })

      setIsDialogOpen(false)
      setEditingConfig(null)
      fetchConfigs()
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:sync.errors.saveConfigFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('entitlements:sync.confirmDelete'))) return

    try {
      const response = await fetch(`/api/entitlements-sync/configs/${id}`, {
        method: 'DELETE',
      })

      if (!response.ok) throw new Error('Failed to delete configuration')

      toast({
        title: t('common:toast.success'),
        description: t('entitlements:sync.configDeleted'),
      })

      fetchConfigs()
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:sync.errors.deleteConfigFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleEdit = (config: EntitlementsSyncConfig) => {
    setEditingConfig(config)
    setIsDialogOpen(true)
  }

  const columns: ColumnDef<EntitlementsSyncConfig>[] = [
    {
      accessorKey: "name",
      header: t('common:labels.name'),
      cell: ({ row }) => <div className="font-medium">{row.getValue("name")}</div>,
    },
    {
      accessorKey: "connection",
      header: t('common:labels.connection'),
      cell: ({ row }) => <div>{row.getValue("connection")}</div>,
    },
    {
      accessorKey: "schedule",
      header: t('common:labels.schedule'),
      cell: ({ row }) => <div>{row.getValue("schedule")}</div>,
    },
    {
      accessorKey: "enabled",
      header: t('common:labels.status'),
      cell: ({ row }) => (
        <div className="flex items-center">
          {row.getValue("enabled") ? (
            <span className="flex items-center text-green-600">
              <CheckCircle2 className="w-4 h-4 mr-1" />
              {t('common:labels.enabled')}
            </span>
          ) : (
            <span className="flex items-center text-gray-500">
              <XCircle className="w-4 h-4 mr-1" />
              {t('common:labels.disabled')}
            </span>
          )}
        </div>
      ),
    },
    {
      accessorKey: "lastSync",
      header: t('common:labels.lastSync'),
      cell: ({ row }) => {
        const lastSync = row.getValue("lastSync") as any;
        return (
          <div className="flex items-center">
            {lastSync?.status === 'running' && (
              <Clock className="w-4 h-4 mr-1 text-blue-600" />
            )}
            {lastSync?.status === 'success' && (
              <CheckCircle2 className="w-4 h-4 mr-1 text-green-600" />
            )}
            {lastSync?.status === 'error' && (
              <XCircle className="w-4 h-4 mr-1 text-red-600" />
            )}
            {lastSync?.timestamp || t('entitlements:sync.never')}
          </div>
        );
      },
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const config = row.original;
        return (
          <div className="flex space-x-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => handleEdit(config)}
            >
              <Edit2 className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => handleDelete(config.id)}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <ArrowLeftRight className="w-8 h-8" /> {t('entitlements:sync.title')}
      </h1>
      <div className="flex justify-between items-center mb-8">
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              {t('entitlements:sync.newConfig')}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {editingConfig ? t('entitlements:sync.editConfig') : t('entitlements:sync.newConfig')}
              </DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t('common:labels.name')}</Label>
                <Input
                  id="name"
                  name="name"
                  defaultValue={editingConfig?.name}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="connection">{t('common:labels.connection')}</Label>
                <Select name="connection" defaultValue={editingConfig?.connection}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('common:placeholders.selectConnection')} />
                  </SelectTrigger>
                  <SelectContent>
                    {connections.map((conn) => (
                      <SelectItem key={conn.id} value={conn.id}>
                        {conn.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="schedule">{t('entitlements:sync.scheduleCron')}</Label>
                <Input
                  id="schedule"
                  name="schedule"
                  defaultValue={editingConfig?.schedule}
                  placeholder={t('common:placeholders.enterCronExpression')}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="catalogs">{t('entitlements:sync.catalogs')}</Label>
                <Select name="catalogs" defaultValue={editingConfig?.catalogs[0]}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('common:placeholders.selectCatalogs')} />
                  </SelectTrigger>
                  <SelectContent>
                    {catalogs.map((catalog) => (
                      <SelectItem key={catalog} value={catalog}>
                        {catalog}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center space-x-2">
                <Switch
                  id="enabled"
                  name="enabled"
                  defaultChecked={editingConfig?.enabled}
                />
                <Label htmlFor="enabled">{t('common:labels.enabled')}</Label>
              </div>
              <div className="flex justify-end space-x-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setIsDialogOpen(false)
                    setEditingConfig(null)
                  }}
                >
                  {t('common:actions.cancel')}
                </Button>
                <Button type="submit">{t('common:actions.save')}</Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading && configs.length === 0 ? (
        <ListViewSkeleton columns={5} rows={5} toolbarButtons={1} />
      ) : (
        <DataTable
          columns={columns}
          data={configs}
          searchColumn="name"
          storageKey="entitlements-sync-sort"
          isLoading={isLoading}
        />
      )}
    </div>
  )
} 