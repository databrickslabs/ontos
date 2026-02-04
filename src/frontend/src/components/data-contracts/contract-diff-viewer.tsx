import { useState, useEffect } from 'react'
import { AlertTriangle, Plus, Minus, RefreshCw, Wrench } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/hooks/use-toast'

type SchemaChange = {
  change_type: string
  schema_name: string
  field_name?: string
  old_value?: string
  new_value?: string
  severity: string
}

type ChangeAnalysis = {
  change_type: string
  version_bump: string
  summary: string
  breaking_changes: string[]
  new_features: string[]
  fixes: string[]
  schema_changes: SchemaChange[]
  quality_rule_changes: any[]
}

type ContractDiffViewerProps = {
  oldContract: any
  newContract: any
}

export default function ContractDiffViewer({ oldContract, newContract }: ContractDiffViewerProps) {
  const { toast } = useToast()
  const [analysis, setAnalysis] = useState<ChangeAnalysis | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (oldContract && newContract) {
      analyzeChanges()
    }
  }, [oldContract, newContract])

  const analyzeChanges = async () => {
    setIsLoading(true)
    try {
      const response = await fetch('/api/data-contracts/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_contract: oldContract,
          new_contract: newContract,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        setAnalysis(data)
      } else {
        console.error('Failed to analyze changes')
        toast({
          title: 'Error',
          description: 'Failed to analyze contract changes',
          variant: 'destructive',
        })
      }
    } catch (error) {
      console.error('Error analyzing changes:', error)
      toast({
        title: 'Error',
        description: 'Failed to analyze contract changes',
        variant: 'destructive',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const getVersionBumpBadge = (versionBump: string) => {
    switch (versionBump) {
      case 'major':
        return <Badge variant="destructive">MAJOR {versionBump.toUpperCase()}</Badge>
      case 'minor':
        return <Badge variant="default">MINOR {versionBump.toUpperCase()}</Badge>
      case 'patch':
        return <Badge variant="secondary">PATCH {versionBump.toUpperCase()}</Badge>
      default:
        return <Badge variant="outline">NO CHANGE</Badge>
    }
  }

  const getChangeIcon = (changeType: string) => {
    switch (changeType) {
      case 'breaking':
        return <AlertTriangle className="h-5 w-5 text-destructive" />
      case 'feature':
        return <Plus className="h-5 w-5 text-green-600" />
      case 'fix':
        return <Wrench className="h-5 w-5 text-blue-600" />
      default:
        return <RefreshCw className="h-5 w-5 text-muted-foreground" />
    }
  }

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case 'critical':
        return <Badge variant="destructive">Critical</Badge>
      case 'moderate':
        return <Badge variant="default">Moderate</Badge>
      case 'minor':
        return <Badge variant="secondary">Minor</Badge>
      default:
        return <Badge variant="outline">{severity}</Badge>
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Analyzing Changes...</CardTitle>
          <CardDescription>Comparing contract versions</CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!analysis) {
    return null
  }

  const hasBreakingChanges = analysis.breaking_changes.length > 0
  const hasNewFeatures = analysis.new_features.length > 0
  const hasFixes = analysis.fixes.length > 0

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2">
              {getChangeIcon(analysis.change_type)}
              Change Analysis
            </CardTitle>
            <CardDescription>Detected changes and recommended version bump</CardDescription>
          </div>
          {getVersionBumpBadge(analysis.version_bump)}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary */}
        {hasBreakingChanges && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Breaking Changes Detected</AlertTitle>
            <AlertDescription>
              This update contains breaking changes that require a MAJOR version bump. Consumers
              will need to update their integrations.
            </AlertDescription>
          </Alert>
        )}

        {/* Detailed Changes */}
        <Tabs defaultValue="summary" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="breaking">
              Breaking ({analysis.breaking_changes.length})
            </TabsTrigger>
            <TabsTrigger value="features">Features ({analysis.new_features.length})</TabsTrigger>
            <TabsTrigger value="fixes">Fixes ({analysis.fixes.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="summary" className="space-y-4">
            <div className="prose prose-sm max-w-none">
              <div className="whitespace-pre-wrap text-sm">{analysis.summary}</div>
            </div>

            {/* Schema Changes Overview */}
            {analysis.schema_changes.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-sm font-semibold">Schema Changes ({analysis.schema_changes.length})</h4>
                <div className="space-y-2">
                  {analysis.schema_changes.slice(0, 5).map((change, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-sm border-l-2 pl-3 py-1">
                      {getSeverityBadge(change.severity)}
                      <div className="flex-1">
                        <span className="font-medium">{change.schema_name}</span>
                        {change.field_name && (
                          <>
                            <span className="text-muted-foreground"> → </span>
                            <span>{change.field_name}</span>
                          </>
                        )}
                        <div className="text-xs text-muted-foreground">
                          {change.change_type}
                          {change.old_value && change.new_value && (
                            <span>
                              {' '}
                              ({change.old_value} → {change.new_value})
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {analysis.schema_changes.length > 5 && (
                    <p className="text-xs text-muted-foreground">
                      ... and {analysis.schema_changes.length - 5} more changes
                    </p>
                  )}
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="breaking" className="space-y-2">
            {hasBreakingChanges ? (
              <ul className="space-y-2">
                {analysis.breaking_changes.map((change, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm">
                    <Minus className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
                    <span>{change}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                No breaking changes detected
              </p>
            )}
          </TabsContent>

          <TabsContent value="features" className="space-y-2">
            {hasNewFeatures ? (
              <ul className="space-y-2">
                {analysis.new_features.map((feature, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm">
                    <Plus className="h-4 w-4 text-green-600 mt-0.5 flex-shrink-0" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                No new features detected
              </p>
            )}
          </TabsContent>

          <TabsContent value="fixes" className="space-y-2">
            {hasFixes ? (
              <ul className="space-y-2">
                {analysis.fixes.map((fix, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm">
                    <Wrench className="h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0" />
                    <span>{fix}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">No fixes detected</p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
