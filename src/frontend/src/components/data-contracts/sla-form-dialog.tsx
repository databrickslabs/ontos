import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import type { SLARequirements } from '@/types/data-contract'

type SLAFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (sla: SLARequirements) => Promise<void>
  initial?: SLARequirements
}

export default function SLAFormDialog({ isOpen, onOpenChange, onSubmit, initial }: SLAFormProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { toast } = useToast()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [uptimeTarget, setUptimeTarget] = useState('')
  const [maxDowntimeMinutes, setMaxDowntimeMinutes] = useState('')
  const [queryResponseTimeMs, setQueryResponseTimeMs] = useState('')
  const [dataFreshnessMinutes, setDataFreshnessMinutes] = useState('')

  useEffect(() => {
    if (isOpen && initial) {
      setUptimeTarget(initial.uptimeTarget?.toString() || '')
      setMaxDowntimeMinutes(initial.maxDowntimeMinutes?.toString() || '')
      setQueryResponseTimeMs(initial.queryResponseTimeMs?.toString() || '')
      setDataFreshnessMinutes(initial.dataFreshnessMinutes?.toString() || '')
    } else if (isOpen && !initial) {
      setUptimeTarget('')
      setMaxDowntimeMinutes('')
      setQueryResponseTimeMs('')
      setDataFreshnessMinutes('')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    setIsSubmitting(true)
    try {
      const sla: SLARequirements = {
        uptimeTarget: uptimeTarget ? parseFloat(uptimeTarget) : undefined,
        maxDowntimeMinutes: maxDowntimeMinutes ? parseInt(maxDowntimeMinutes, 10) : undefined,
        queryResponseTimeMs: queryResponseTimeMs ? parseInt(queryResponseTimeMs, 10) : undefined,
        dataFreshnessMinutes: dataFreshnessMinutes ? parseInt(dataFreshnessMinutes, 10) : undefined,
      }

      await onSubmit(sla)
      onOpenChange(false)
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:sla.saveError', 'Failed to save SLA requirements'),
        variant: 'destructive',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('data-contracts:sla.editTitle', 'Edit SLA Requirements')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:sla.description', 'Define service level agreement requirements for this contract.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="uptimeTarget">{t('data-contracts:sla.uptimeTargetLabel', 'Uptime Target (%)')}</Label>
            <Input
              id="uptimeTarget"
              type="number"
              step="0.01"
              min="0"
              max="100"
              value={uptimeTarget}
              onChange={(e) => setUptimeTarget(e.target.value)}
              placeholder={t('data-contracts:sla.uptimeTargetPlaceholder', 'e.g., 99.9')}
            />
            <p className="text-xs text-muted-foreground">{t('data-contracts:sla.uptimeTargetHelp', 'Expected uptime percentage (0-100)')}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="maxDowntimeMinutes">{t('data-contracts:sla.maxDowntimeLabel', 'Max Downtime (minutes)')}</Label>
            <Input
              id="maxDowntimeMinutes"
              type="number"
              min="0"
              value={maxDowntimeMinutes}
              onChange={(e) => setMaxDowntimeMinutes(e.target.value)}
              placeholder={t('data-contracts:sla.maxDowntimePlaceholder', 'e.g., 60')}
            />
            <p className="text-xs text-muted-foreground">{t('data-contracts:sla.maxDowntimeHelp', 'Maximum acceptable downtime per month')}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="queryResponseTimeMs">{t('data-contracts:sla.queryResponseTimeLabel', 'Query Response Time (ms)')}</Label>
            <Input
              id="queryResponseTimeMs"
              type="number"
              min="0"
              value={queryResponseTimeMs}
              onChange={(e) => setQueryResponseTimeMs(e.target.value)}
              placeholder={t('data-contracts:sla.queryResponseTimePlaceholder', 'e.g., 1000')}
            />
            <p className="text-xs text-muted-foreground">{t('data-contracts:sla.queryResponseTimeHelp', 'Maximum query response time in milliseconds')}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="dataFreshnessMinutes">{t('data-contracts:sla.dataFreshnessLabel', 'Data Freshness (minutes)')}</Label>
            <Input
              id="dataFreshnessMinutes"
              type="number"
              min="0"
              value={dataFreshnessMinutes}
              onChange={(e) => setDataFreshnessMinutes(e.target.value)}
              placeholder={t('data-contracts:sla.dataFreshnessPlaceholder', 'e.g., 15')}
            />
            <p className="text-xs text-muted-foreground">{t('data-contracts:sla.dataFreshnessHelp', 'How fresh the data should be (in minutes)')}</p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : t('data-contracts:sla.saveButton', 'Save SLA')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
