import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Plus, Minus, RefreshCw, Wrench } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { SkeletonBlock } from '@/components/common/list-view-skeleton'
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
  const { t } = useTranslation(['data-contracts', 'common'])
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
          title: t('common:states.error'),
          description: t('data-contracts:diff.analyzeError', 'Failed to analyze contract changes'),
          variant: 'destructive',
        })
      }
    } catch (error) {
      console.error('Error analyzing changes:', error)
      toast({
        title: t('common:states.error'),
        description: t('data-contracts:diff.analyzeError', 'Failed to analyze contract changes'),
        variant: 'destructive',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const getVersionBumpBadge = (versionBump: string) => {
    switch (versionBump) {
      case 'major':
        return <Badge variant="destructive">{t('data-contracts:diff.bumpMajor', 'MAJOR')} {versionBump.toUpperCase()}</Badge>
      case 'minor':
        return <Badge variant="default">{t('data-contracts:diff.bumpMinor', 'MINOR')} {versionBump.toUpperCase()}</Badge>
      case 'patch':
        return <Badge variant="secondary">{t('data-contracts:diff.bumpPatch', 'PATCH')} {versionBump.toUpperCase()}</Badge>
      default:
        return <Badge variant="outline">{t('data-contracts:diff.noChange', 'NO CHANGE')}</Badge>
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
        return <Badge variant="destructive">{t('data-contracts:diff.severityCritical', 'Critical')}</Badge>
      case 'moderate':
        return <Badge variant="default">{t('data-contracts:diff.severityModerate', 'Moderate')}</Badge>
      case 'minor':
        return <Badge variant="secondary">{t('data-contracts:diff.severityMinor', 'Minor')}</Badge>
      default:
        return <Badge variant="outline">{severity}</Badge>
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('data-contracts:diff.analyzingChanges', 'Analyzing Changes...')}</CardTitle>
          <CardDescription>{t('data-contracts:diff.comparingVersions', 'Comparing contract versions')}</CardDescription>
        </CardHeader>
        <CardContent>
          <SkeletonBlock height="h-32" />
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
              {t('data-contracts:diff.changeAnalysis', 'Change Analysis')}
            </CardTitle>
            <CardDescription>{t('data-contracts:diff.changeAnalysisDesc', 'Detected changes and recommended version bump')}</CardDescription>
          </div>
          {getVersionBumpBadge(analysis.version_bump)}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary */}
        {hasBreakingChanges && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>{t('data-contracts:diff.breakingDetected', 'Breaking Changes Detected')}</AlertTitle>
            <AlertDescription>
              {t('data-contracts:diff.breakingDesc', 'This update contains breaking changes that require a MAJOR version bump. Consumers will need to update their integrations.')}
            </AlertDescription>
          </Alert>
        )}

        {/* Detailed Changes */}
        <Tabs defaultValue="summary" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="summary">{t('data-contracts:diff.tabSummary', 'Summary')}</TabsTrigger>
            <TabsTrigger value="breaking">
              {t('data-contracts:diff.tabBreaking', 'Breaking ({{count}})', { count: analysis.breaking_changes.length })}
            </TabsTrigger>
            <TabsTrigger value="features">{t('data-contracts:diff.tabFeatures', 'Features ({{count}})', { count: analysis.new_features.length })}</TabsTrigger>
            <TabsTrigger value="fixes">{t('data-contracts:diff.tabFixes', 'Fixes ({{count}})', { count: analysis.fixes.length })}</TabsTrigger>
          </TabsList>

          <TabsContent value="summary" className="space-y-4">
            <div className="prose prose-sm max-w-none">
              <div className="whitespace-pre-wrap text-sm">{analysis.summary}</div>
            </div>

            {/* Schema Changes Overview */}
            {analysis.schema_changes.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-sm font-semibold">{t('data-contracts:diff.schemaChanges', 'Schema Changes ({{count}})', { count: analysis.schema_changes.length })}</h4>
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
                      {t('data-contracts:diff.moreChanges', '... and {{count}} more changes', { count: analysis.schema_changes.length - 5 })}
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
                {t('data-contracts:diff.noBreaking', 'No breaking changes detected')}
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
                {t('data-contracts:diff.noFeatures', 'No new features detected')}
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
              <p className="text-sm text-muted-foreground text-center py-4">{t('data-contracts:diff.noFixes', 'No fixes detected')}</p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
