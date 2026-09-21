import { useState, useEffect } from 'react'
import { ArrowUpCircle, AlertCircle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import {
  SUPPORTED_ODCS_VERSIONS,
  LATEST_ODCS_VERSION,
  odcsUpgradeTargets,
} from '@/lib/odcs-lifecycle'

type UpgradeVersionDialogProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  contractId: string
  contractName: string
  currentApiVersion: string
  /** Called with the new draft contract's id after a successful upgrade. */
  onSuccess: (newContractId: string) => void
}

type VersionBump = 'major' | 'minor' | 'patch'

export default function UpgradeVersionDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  currentApiVersion,
  onSuccess,
}: UpgradeVersionDialogProps) {
  const { toast } = useToast()
  const [supported, setSupported] = useState<string[]>([...SUPPORTED_ODCS_VERSIONS])
  const [targetVersion, setTargetVersion] = useState('')
  const [versionBump, setVersionBump] = useState<VersionBump>('minor')
  const [changeSummary, setChangeSummary] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  // On open, load the authoritative supported-versions list (falling back to the
  // constant) and initialize the form. All state updates happen inside the async
  // callback so they are not applied synchronously within the effect.
  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    const init = async () => {
      let list: string[] = [...SUPPORTED_ODCS_VERSIONS]
      try {
        const res = await fetch('/api/data-contracts/meta/odcs-versions')
        if (res.ok) {
          const data = await res.json()
          if (Array.isArray(data?.supported)) list = data.supported
        }
      } catch {
        // keep fallback
      }
      if (cancelled) return
      const nextTargets = odcsUpgradeTargets(currentApiVersion, list)
      const preferred = nextTargets.includes(LATEST_ODCS_VERSION)
        ? LATEST_ODCS_VERSION
        : nextTargets[0]
      setSupported(list)
      setTargetVersion(preferred || '')
      setChangeSummary('')
      setVersionBump('minor')
      setError('')
    }
    void init()
    return () => {
      cancelled = true
    }
  }, [isOpen, currentApiVersion])

  const targets = odcsUpgradeTargets(currentApiVersion, supported)

  const handleSubmit = async () => {
    if (!targetVersion) {
      setError('Select a target ODCS version')
      return
    }
    setError('')
    setIsSubmitting(true)
    try {
      const res = await fetch(`/api/data-contracts/${contractId}/upgrade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          targetApiVersion: targetVersion,
          versionBump,
          changeSummary: changeSummary.trim() || undefined,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        toast({
          title: 'Contract Upgraded',
          description: `Created a new draft (${data.version}) on ODCS ${targetVersion}.`,
        })
        onOpenChange(false)
        onSuccess(data.id)
      } else {
        const errorData = await res.json().catch(() => ({}))
        setError(errorData.detail || 'Failed to upgrade contract')
      }
    } catch (err) {
      console.error('Error upgrading contract:', err)
      setError('Failed to upgrade contract')
    } finally {
      setIsSubmitting(false)
    }
  }

  const noTargets = targets.length === 0

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ArrowUpCircle className="h-5 w-5" />
            Upgrade ODCS Version
          </DialogTitle>
          <DialogDescription>
            Create a new draft version of <span className="font-medium">{contractName}</span> on a
            newer ODCS standard. The draft goes through the usual review process; nothing is changed
            in place.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="flex items-center justify-between rounded-lg bg-muted p-4">
            <div className="text-center">
              <p className="text-xs text-muted-foreground">Current</p>
              <p className="text-lg font-semibold">{currentApiVersion || 'unknown'}</p>
            </div>
            <div className="text-2xl text-muted-foreground">→</div>
            <div className="text-center">
              <p className="text-xs text-muted-foreground">Target</p>
              <p className="text-lg font-semibold text-primary">{targetVersion || '—'}</p>
            </div>
          </div>

          {noTargets ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Already up to date</AlertTitle>
              <AlertDescription>
                This contract is already on the latest supported ODCS version.
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="targetVersion">Target ODCS version</Label>
                <Select value={targetVersion} onValueChange={setTargetVersion}>
                  <SelectTrigger id="targetVersion">
                    <SelectValue placeholder="Select version" />
                  </SelectTrigger>
                  <SelectContent>
                    {targets.map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                        {v === LATEST_ODCS_VERSION ? ' (latest)' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Version bump</Label>
                <RadioGroup
                  value={versionBump}
                  onValueChange={(value) => setVersionBump(value as VersionBump)}
                  className="flex gap-4"
                >
                  {(['major', 'minor', 'patch'] as VersionBump[]).map((b) => (
                    <div key={b} className="flex items-center space-x-2">
                      <RadioGroupItem value={b} id={`bump-${b}`} />
                      <Label htmlFor={`bump-${b}`} className="cursor-pointer capitalize">
                        {b}
                      </Label>
                    </div>
                  ))}
                </RadioGroup>
              </div>

              <div className="space-y-2">
                <Label htmlFor="upgradeChangeSummary">Change summary (optional)</Label>
                <Textarea
                  id="upgradeChangeSummary"
                  placeholder={`Upgrade to ODCS ${targetVersion || ''}...`}
                  value={changeSummary}
                  onChange={(e) => setChangeSummary(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
              </div>
            </>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting || noTargets || !targetVersion}>
            {isSubmitting ? 'Upgrading...' : 'Create Upgraded Draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
