import { useState, useEffect } from 'react'
import { GitBranch, ArrowUp, ArrowDown, Calendar, User } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { VersionLineageSkeleton } from '@/components/common/list-view-skeleton'

type ContractSummary = {
  id: string
  name: string
  version: string
  status: string
  changeSummary?: string
  createdAt: string
  createdBy?: string
}

type VersionHistory = {
  current: ContractSummary
  parent: ContractSummary | null
  children: ContractSummary[]
  siblings: ContractSummary[]
}

type VersionHistoryPanelProps = {
  contractId: string
  onNavigateToVersion?: (contractId: string) => void
}

export default function VersionHistoryPanel({
  contractId,
  onNavigateToVersion,
}: VersionHistoryPanelProps) {
  const { toast } = useToast()
  const [history, setHistory] = useState<VersionHistory | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    fetchVersionHistory()
  }, [contractId])

  const fetchVersionHistory = async () => {
    setIsLoading(true)
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/version-history`)
      if (response.ok) {
        const data = await response.json()
        setHistory(data)
      } else {
        console.error('Failed to fetch version history')
        setHistory(null)
      }
    } catch (error) {
      console.error('Error fetching version history:', error)
      toast({
        title: 'Error',
        description: 'Failed to load version history',
        variant: 'destructive',
      })
      setHistory(null)
    } finally {
      setIsLoading(false)
    }
  }

  const getStatusBadgeVariant = (status: string) => {
    switch (status?.toLowerCase()) {
      case 'published':
        return 'default'
      case 'draft':
        return 'secondary'
      case 'deprecated':
        return 'outline'
      default:
        return 'secondary'
    }
  }

  const renderVersionCard = (version: ContractSummary, label: string, icon: React.ReactNode) => (
    <div className="border rounded-lg p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-medium text-muted-foreground">{label}</span>
        </div>
        <Badge variant={getStatusBadgeVariant(version.status)}>{version.status}</Badge>
      </div>
      <div className="space-y-1">
        <div className="font-semibold">
          {version.name} <span className="text-muted-foreground">v{version.version}</span>
        </div>
        {version.changeSummary && (
          <p className="text-sm text-muted-foreground line-clamp-2">{version.changeSummary}</p>
        )}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Calendar className="h-3 w-3" />
            {new Date(version.createdAt).toLocaleDateString()}
          </div>
          {version.createdBy && (
            <div className="flex items-center gap-1">
              <User className="h-3 w-3" />
              {version.createdBy}
            </div>
          )}
        </div>
      </div>
      {onNavigateToVersion && version.id !== contractId && (
        <Button
          variant="outline"
          size="sm"
          className="w-full mt-2"
          onClick={() => onNavigateToVersion(version.id)}
        >
          View Version
        </Button>
      )}
    </div>
  )

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            Version History
          </CardTitle>
          <CardDescription>Loading version lineage...</CardDescription>
        </CardHeader>
        <CardContent>
          <VersionLineageSkeleton versions={2} />
        </CardContent>
      </Card>
    )
  }

  if (!history) {
    return null
  }

  const hasParent = history.parent !== null
  const hasChildren = history.children.length > 0
  const hasSiblings = history.siblings.length > 0

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitBranch className="h-5 w-5" />
          Version History
        </CardTitle>
        <CardDescription>Version lineage and relationships</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Parent Version */}
        {hasParent && (
          <div className="space-y-2">
            {renderVersionCard(
              history.parent!,
              'Parent Version',
              <ArrowUp className="h-4 w-4 text-blue-500" />
            )}
            <div className="flex justify-center">
              <div className="w-0.5 h-8 bg-border" />
            </div>
          </div>
        )}

        {/* Current Version */}
        <div className="bg-accent/50 border-2 border-primary rounded-lg p-4 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-primary">Current Version</span>
            </div>
            <Badge variant={getStatusBadgeVariant(history.current.status)}>
              {history.current.status}
            </Badge>
          </div>
          <div className="space-y-1">
            <div className="font-semibold">
              {history.current.name}{' '}
              <span className="text-muted-foreground">v{history.current.version}</span>
            </div>
            {history.current.changeSummary && (
              <p className="text-sm text-muted-foreground">{history.current.changeSummary}</p>
            )}
            <div className="flex items-center gap-4 text-xs text-muted-foreground">
              <div className="flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                {new Date(history.current.createdAt).toLocaleDateString()}
              </div>
              {history.current.createdBy && (
                <div className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  {history.current.createdBy}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Siblings */}
        {hasSiblings && (
          <div className="space-y-2">
            <div className="text-sm font-medium text-muted-foreground px-2">
              Sibling Versions ({history.siblings.length})
            </div>
            <div className="space-y-2">
              {history.siblings.map((sibling) => (
                <div key={sibling.id} className="pl-4 border-l-2">
                  {renderVersionCard(
                    sibling,
                    'Sibling',
                    <GitBranch className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Children Versions */}
        {hasChildren && (
          <div className="space-y-2">
            <div className="flex justify-center">
              <div className="w-0.5 h-8 bg-border" />
            </div>
            <div className="text-sm font-medium text-muted-foreground px-2">
              Child Versions ({history.children.length})
            </div>
            <div className="space-y-2">
              {history.children.map((child) => (
                <div key={child.id}>
                  {renderVersionCard(
                    child,
                    'Child Version',
                    <ArrowDown className="h-4 w-4 text-green-500" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {!hasParent && !hasChildren && !hasSiblings && (
          <div className="text-center text-sm text-muted-foreground py-4">
            This is the only version of this contract
          </div>
        )}
      </CardContent>
    </Card>
  )
}
