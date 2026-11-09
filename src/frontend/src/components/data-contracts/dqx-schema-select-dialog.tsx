import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Sparkles, AlertCircle } from 'lucide-react'
import type { DataContract } from '@/types/data-contract'

interface DqxSchemaSelectDialogProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  contract: DataContract | null
  onConfirm: (selectedSchemaNames: string[]) => Promise<void>
}

export default function DqxSchemaSelectDialog({
  isOpen,
  onOpenChange,
  contract,
  onConfirm
}: DqxSchemaSelectDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const [selectedSchemas, setSelectedSchemas] = useState<Set<string>>(new Set())
  const [isSubmitting, setIsSubmitting] = useState(false)

  const schemas = contract?.schema || []

  const handleToggle = (schemaName: string) => {
    const newSet = new Set(selectedSchemas)
    if (newSet.has(schemaName)) {
      newSet.delete(schemaName)
    } else {
      newSet.add(schemaName)
    }
    setSelectedSchemas(newSet)
  }

  const handleSelectAll = () => {
    if (selectedSchemas.size === schemas.length) {
      setSelectedSchemas(new Set())
    } else {
      setSelectedSchemas(new Set(schemas.map(s => s.name)))
    }
  }

  const handleConfirm = async () => {
    if (selectedSchemas.size === 0) return

    setIsSubmitting(true)
    try {
      await onConfirm(Array.from(selectedSchemas))
      onOpenChange(false)
      setSelectedSchemas(new Set())
    } catch (error) {
      console.error('Failed to start profiling:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = () => {
    setSelectedSchemas(new Set())
    onOpenChange(false)
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {t('data-contracts:dqx.title', 'Profile Schemas with DQX')}
          </DialogTitle>
          <DialogDescription>
            {t('data-contracts:dqx.description', 'Select schemas to profile using Databricks DQX. The profiler will analyze your data and generate quality check suggestions.')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          {schemas.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                {t('data-contracts:dqx.noSchemas', 'No schemas defined in this contract. Add schemas first before profiling.')}
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <div className="flex items-center justify-between border-b pb-2">
                <Label className="font-semibold">{t('data-contracts:dqx.availableSchemas', 'Available Schemas')}</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleSelectAll}
                >
                  {selectedSchemas.size === schemas.length ? t('data-contracts:dqx.deselectAll', 'Deselect All') : t('data-contracts:dqx.selectAll', 'Select All')}
                </Button>
              </div>

              <div className="space-y-3">
                {schemas.map((schema) => {
                  const isSelected = selectedSchemas.has(schema.name)
                  const columnCount = schema.propertyCount ?? schema.properties?.length ?? 0

                  return (
                    <div
                      key={schema.name}
                      className={`flex items-start gap-3 p-3 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer ${
                        isSelected ? 'border-primary bg-primary/5' : ''
                      }`}
                      onClick={() => handleToggle(schema.name)}
                    >
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => handleToggle(schema.name)}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <div className="flex-1">
                        <div className="font-medium">{schema.name}</div>
                        {schema.physicalName && (
                          <div className="text-sm text-muted-foreground mt-0.5">
                            {schema.physicalName}
                          </div>
                        )}
                        <div className="text-xs text-muted-foreground mt-1">
                          {t('data-contracts:dqx.columnCount', { count: columnCount, defaultValue: '{{count}} columns' })}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={selectedSchemas.size === 0 || isSubmitting}
          >
            {isSubmitting ? t('data-contracts:dqx.starting', 'Starting...') : t('data-contracts:dqx.profileButton', { count: selectedSchemas.size, defaultValue: 'Profile {{count}} Schemas' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
