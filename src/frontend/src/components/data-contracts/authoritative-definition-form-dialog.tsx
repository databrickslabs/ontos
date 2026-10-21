import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from 'react-i18next'

type AuthoritativeDefinition = {
  id?: string
  url: string
  type: string
}

type AuthoritativeDefinitionFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (definition: AuthoritativeDefinition) => Promise<void>
  initial?: AuthoritativeDefinition
  level: 'contract' | 'schema' | 'property'
}

export default function AuthoritativeDefinitionFormDialog({
  isOpen,
  onOpenChange,
  onSubmit,
  initial,
  level
}: AuthoritativeDefinitionFormProps) {
  const { toast } = useToast()
  const { t } = useTranslation(['data-contracts', 'common'])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [url, setUrl] = useState('')
  const [type, setType] = useState('')

  useEffect(() => {
    if (isOpen && initial) {
      setUrl(initial.url || '')
      setType(initial.type || '')
    } else if (isOpen && !initial) {
      setUrl('')
      setType('')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    if (!url.trim()) {
      toast({ title: t('data-contracts:authoritativeDefinition.toast.validationError', 'Validation Error'), description: t('data-contracts:authoritativeDefinition.toast.urlRequired', 'URL is required'), variant: 'destructive' })
      return
    }
    if (!type.trim()) {
      toast({ title: t('data-contracts:authoritativeDefinition.toast.validationError', 'Validation Error'), description: t('data-contracts:authoritativeDefinition.toast.typeRequired', 'Type is required'), variant: 'destructive' })
      return
    }

    // URL validation
    try {
      new URL(url.trim())
    } catch {
      toast({ title: t('data-contracts:authoritativeDefinition.toast.validationError', 'Validation Error'), description: t('data-contracts:authoritativeDefinition.toast.invalidUrl', 'Please enter a valid URL'), variant: 'destructive' })
      return
    }

    setIsSubmitting(true)
    try {
      const definition: AuthoritativeDefinition = {
        url: url.trim(),
        type: type.trim(),
      }

      await onSubmit(definition)
      onOpenChange(false)
      toast({
        title: t('common:toast.success', 'Success'),
        description: initial ? t('data-contracts:authoritativeDefinition.toast.updated', 'Authoritative definition updated') : t('data-contracts:authoritativeDefinition.toast.created', 'Authoritative definition created')
      })
    } catch (error: any) {
      toast({
        title: t('common:toast.error', 'Error'),
        description: error?.message || t('data-contracts:authoritativeDefinition.toast.saveError', 'Failed to save authoritative definition'),
        variant: 'destructive',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const levelLabels = {
    contract: t('data-contracts:authoritativeDefinition.levels.contract', 'Contract'),
    schema: t('data-contracts:authoritativeDefinition.levels.schema', 'Schema'),
    property: t('data-contracts:authoritativeDefinition.levels.property', 'Property')
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{initial ? t('data-contracts:authoritativeDefinition.editTitle', 'Edit Authoritative Definition') : t('data-contracts:authoritativeDefinition.addTitle', 'Add Authoritative Definition')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:authoritativeDefinition.description', '{{level}}-level authoritative source (ODCS compliant)', { level: levelLabels[level] })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="url">
              {t('data-contracts:authoritativeDefinition.fields.url', 'URL')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('data-contracts:authoritativeDefinition.fields.urlPlaceholder', 'https://glossary.example.com/term/123')}
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:authoritativeDefinition.fields.urlHelp', 'Full URL to the authoritative source')}
            </p>
          </div>

          {/* Type */}
          <div className="space-y-2">
            <Label htmlFor="type">
              {t('common:labels.type', 'Type')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="type"
              value={type}
              onChange={(e) => setType(e.target.value)}
              placeholder={t('data-contracts:authoritativeDefinition.fields.typePlaceholder', 'e.g., glossary, standard, documentation')}
              maxLength={255}
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:authoritativeDefinition.fields.typeHelp', 'Type of authoritative source')}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving', 'Saving...') : initial ? t('common:actions.update', 'Update') : t('common:actions.add', 'Add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
