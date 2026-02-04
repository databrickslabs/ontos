import { useState, useEffect } from 'react'
import { GitCommit, AlertCircle, CheckCircle2, Info, AlertTriangle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'
import type { DiffFromParentResponse } from '@/types/data-contract'

type CommitDraftDialogProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  contractId: string
  contractName: string
  onSuccess: () => void
}

export default function CommitDraftDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName: _contractName,
  onSuccess,
}: CommitDraftDialogProps) {
  const { toast } = useToast()
  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [diffData, setDiffData] = useState<DiffFromParentResponse | null>(null)
  const [error, setError] = useState('')

  const [versionBumpType, setVersionBumpType] = useState<'major' | 'minor' | 'patch' | 'custom'>('patch')
  const [customVersion, setCustomVersion] = useState('')
  const [changeSummary, setChangeSummary] = useState('')

  // Fetch diff data when dialog opens
  useEffect(() => {
    if (isOpen && contractId) {
      fetchDiffData()
    }
  }, [isOpen, contractId])

  const fetchDiffData = async () => {
    setIsLoading(true)
    setError('')
    try {
      const response = await fetch(`/api/data-contracts/${contractId}/diff-from-parent`)
      if (response.ok) {
        const data = await response.json()
        setDiffData(data)
        // Set default version bump type based on suggestion
        if (data.suggested_bump) {
          setVersionBumpType(data.suggested_bump)
        }
        // Pre-populate change summary from analysis
        if (data.analysis?.summary) {
          setChangeSummary(data.analysis.summary)
        }
      } else {
        const errorData = await response.json().catch(() => ({}))
        setError(errorData.detail || 'Failed to load diff data')
      }
    } catch (err) {
      console.error('Error fetching diff:', err)
      setError('Failed to load diff data')
    } finally {
      setIsLoading(false)
    }
  }

  const calculateNewVersion = () => {
    if (versionBumpType === 'custom') {
      return customVersion
    }
    if (!diffData?.parent_version) {
      return '1.0.0'
    }

    const parts = diffData.parent_version.split('.').map(Number)
    if (parts.length !== 3 || parts.some(isNaN)) {
      return '1.0.0'
    }

    const [major, minor, patch] = parts
    switch (versionBumpType) {
      case 'major':
        return `${major + 1}.0.0`
      case 'minor':
        return `${major}.${minor + 1}.0`
      case 'patch':
        return `${major}.${minor}.${patch + 1}`
      default:
        return diffData.parent_version
    }
  }

  const validateVersion = (version: string): boolean => {
    return /^\d+\.\d+\.\d+$/.test(version)
  }

  const handleSubmit = async () => {
    const newVersion = calculateNewVersion()

    if (!validateVersion(newVersion)) {
      setError('Version must be in format X.Y.Z (e.g., 1.1.0)')
      return
    }

    if (!changeSummary.trim()) {
      setError('Please provide a change summary')
      return
    }

    setError('')
    setIsSubmitting(true)

    try {
      const response = await fetch(`/api/data-contracts/${contractId}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          new_version: newVersion,
          change_summary: changeSummary.trim(),
        }),
      })

      if (response.ok) {
        toast({
          title: 'Draft Committed',
          description: `Version ${newVersion} is now visible to your team.`,
        })
        onSuccess()
        onOpenChange(false)
      } else {
        const errorData = await response.json().catch(() => ({}))
        setError(errorData.detail || 'Failed to commit draft')
      }
    } catch (err) {
      console.error('Error committing draft:', err)
      setError('Failed to commit draft')
    } finally {
      setIsSubmitting(false)
    }
  }

  const newVersion = calculateNewVersion()
  const analysis = diffData?.analysis

  const hasBreakingChanges = analysis?.breaking_changes && analysis.breaking_changes.length > 0
  const hasNewFeatures = analysis?.new_features && analysis.new_features.length > 0
  const hasFixes = analysis?.fixes && analysis.fixes.length > 0

  const getVersionBumpBadge = (bump: string) => {
    switch (bump) {
      case 'major':
        return <Badge variant="destructive">MAJOR</Badge>
      case 'minor':
        return <Badge className="bg-blue-500">MINOR</Badge>
      case 'patch':
        return <Badge variant="secondary">PATCH</Badge>
      default:
        return <Badge variant="outline">{bump.toUpperCase()}</Badge>
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitCommit className="h-5 w-5" />
            Commit Personal Draft
          </DialogTitle>
          <DialogDescription>
            Review your changes and commit to make this version visible to your team.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        ) : error && !diffData ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : diffData ? (
          <div className="space-y-6 py-4">
            {/* Version Display */}
            <div className="flex items-center justify-between p-4 bg-muted rounded-lg">
              <div className="text-center">
                <p className="text-sm text-muted-foreground">Parent Version</p>
                <p className="text-2xl font-bold">{diffData.parent_version}</p>
                <Badge variant="outline" className="mt-1">{diffData.parent_status}</Badge>
              </div>
              <div className="text-4xl text-muted-foreground">→</div>
              <div className="text-center">
                <p className="text-sm text-muted-foreground">New Version</p>
                <p className="text-2xl font-bold text-primary">{newVersion}</p>
                <Badge className="mt-1">draft</Badge>
              </div>
            </div>

            {/* Suggested Version Bump */}
            {diffData.suggested_bump && (
              <Alert>
                <Info className="h-4 w-4" />
                <AlertTitle className="flex items-center gap-2">
                  Suggested: {getVersionBumpBadge(diffData.suggested_bump)}
                </AlertTitle>
                <AlertDescription>
                  Based on the changes detected, we recommend a {diffData.suggested_bump} version bump.
                </AlertDescription>
              </Alert>
            )}

            {/* Breaking Changes Warning */}
            {hasBreakingChanges && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Breaking Changes Detected</AlertTitle>
                <AlertDescription>
                  This version contains changes that may impact existing consumers.
                  Consider a major version bump.
                </AlertDescription>
              </Alert>
            )}

            {/* Change Analysis Tabs */}
            {analysis && (hasBreakingChanges || hasNewFeatures || hasFixes) && (
              <Tabs defaultValue="summary" className="w-full">
                <TabsList className="grid w-full grid-cols-4">
                  <TabsTrigger value="summary">Summary</TabsTrigger>
                  {hasBreakingChanges && (
                    <TabsTrigger value="breaking" className="text-red-600 dark:text-red-400">
                      Breaking ({analysis.breaking_changes.length})
                    </TabsTrigger>
                  )}
                  {hasNewFeatures && (
                    <TabsTrigger value="features" className="text-blue-600 dark:text-blue-400">
                      Features ({analysis.new_features.length})
                    </TabsTrigger>
                  )}
                  {hasFixes && (
                    <TabsTrigger value="fixes">
                      Fixes ({analysis.fixes.length})
                    </TabsTrigger>
                  )}
                </TabsList>

                <TabsContent value="summary" className="mt-4">
                  <Card>
                    <CardContent className="pt-4">
                      <pre className="whitespace-pre-wrap text-sm">{analysis.summary}</pre>
                    </CardContent>
                  </Card>
                </TabsContent>

                {hasBreakingChanges && (
                  <TabsContent value="breaking" className="mt-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <AlertCircle className="h-4 w-4 text-red-600" />
                          Breaking Changes
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {analysis.breaking_changes.map((change, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm">
                              <span className="text-red-600 dark:text-red-400 mt-0.5">•</span>
                              <span>{change}</span>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  </TabsContent>
                )}

                {hasNewFeatures && (
                  <TabsContent value="features" className="mt-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                          New Features
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {analysis.new_features.map((feature, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm">
                              <span className="text-blue-600 dark:text-blue-400 mt-0.5">•</span>
                              <span>{feature}</span>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  </TabsContent>
                )}

                {hasFixes && (
                  <TabsContent value="fixes" className="mt-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <Info className="h-4 w-4" />
                          Improvements & Fixes
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {analysis.fixes.map((fix, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm">
                              <span className="text-gray-600 mt-0.5">•</span>
                              <span>{fix}</span>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  </TabsContent>
                )}
              </Tabs>
            )}

            {/* Version Bump Selection */}
            <div className="space-y-3">
              <Label>Version Bump Type</Label>
              <RadioGroup
                value={versionBumpType}
                onValueChange={(value) => setVersionBumpType(value as 'major' | 'minor' | 'patch' | 'custom')}
              >
                <div className="flex items-start space-x-3 rounded-md border p-3">
                  <RadioGroupItem value="major" id="major" />
                  <div className="flex-1">
                    <Label htmlFor="major" className="font-medium cursor-pointer">
                      Major (Breaking Changes)
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Incompatible changes that break existing integrations
                    </p>
                  </div>
                </div>

                <div className="flex items-start space-x-3 rounded-md border p-3">
                  <RadioGroupItem value="minor" id="minor" />
                  <div className="flex-1">
                    <Label htmlFor="minor" className="font-medium cursor-pointer">
                      Minor (New Features)
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Backward-compatible new features or improvements
                    </p>
                  </div>
                </div>

                <div className="flex items-start space-x-3 rounded-md border p-3">
                  <RadioGroupItem value="patch" id="patch" />
                  <div className="flex-1">
                    <Label htmlFor="patch" className="font-medium cursor-pointer">
                      Patch (Bug Fixes)
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Backward-compatible bug fixes or minor improvements
                    </p>
                  </div>
                </div>

                <div className="flex items-start space-x-3 rounded-md border p-3">
                  <RadioGroupItem value="custom" id="custom" />
                  <div className="flex-1 space-y-2">
                    <Label htmlFor="custom" className="font-medium cursor-pointer">
                      Custom Version
                    </Label>
                    <Input
                      placeholder="e.g., 2.0.0"
                      value={customVersion}
                      onChange={(e) => setCustomVersion(e.target.value)}
                      disabled={versionBumpType !== 'custom'}
                      className="h-8"
                    />
                  </div>
                </div>
              </RadioGroup>
            </div>

            {/* Change Summary */}
            <div className="space-y-2">
              <Label htmlFor="changeSummary">
                Change Summary <span className="text-destructive">*</span>
              </Label>
              <Textarea
                id="changeSummary"
                placeholder="Describe what changed in this version..."
                value={changeSummary}
                onChange={(e) => setChangeSummary(e.target.value)}
                rows={4}
                className="resize-none"
              />
              <p className="text-xs text-muted-foreground">
                This summary will help your team understand what changed.
              </p>
            </div>

            {/* Error Display */}
            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Error</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isLoading || isSubmitting || !diffData}>
            {isSubmitting ? 'Committing...' : `Commit Version ${newVersion}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

