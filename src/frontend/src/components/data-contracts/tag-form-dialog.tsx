import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'

type ContractTag = {
  id?: string
  name: string
}

type TagFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (tag: ContractTag) => Promise<void>
  initial?: ContractTag
}

export default function TagFormDialog({ isOpen, onOpenChange, onSubmit, initial }: TagFormProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { toast } = useToast()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [name, setName] = useState('')

  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '')
    } else if (isOpen && !initial) {
      setName('')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: t('data-contracts:tag.validationError', 'Validation Error'), description: t('data-contracts:tag.nameRequired', 'Tag name is required'), variant: 'destructive' })
      return
    }

    // Validate tag name format (alphanumeric, hyphens, underscores only)
    if (!/^[a-zA-Z0-9_-]+$/.test(name.trim())) {
      toast({
        title: t('data-contracts:tag.validationError', 'Validation Error'),
        description: t('data-contracts:tag.nameFormatError', 'Tag name can only contain letters, numbers, hyphens, and underscores'),
        variant: 'destructive'
      })
      return
    }

    setIsSubmitting(true)
    try {
      const tag: ContractTag = {
        name: name.trim(),
      }

      await onSubmit(tag)
      onOpenChange(false)
      toast({
        title: t('common:toast.success'),
        description: initial ? t('data-contracts:tag.updateSuccess', 'Tag updated successfully') : t('data-contracts:tag.createSuccess', 'Tag created successfully')
      })
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:tag.saveError', 'Failed to save tag'),
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
          <DialogTitle>{initial ? t('data-contracts:tag.editTitle', 'Edit Tag') : t('data-contracts:tag.addTitle', 'Add Tag')}</DialogTitle>
          <DialogDescription>
            {initial ? t('data-contracts:tag.editDescription', 'Update the tag name') : t('data-contracts:tag.addDescription', 'Add a new tag to this data contract (ODCS compliant)')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              {t('data-contracts:tag.nameLabel', 'Tag Name')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-contracts:tag.namePlaceholder', 'e.g., pii, sensitive, production')}
              maxLength={255}
              autoFocus
            />
            <p className="text-sm text-muted-foreground">
              {t('data-contracts:tag.nameHelp', 'Use letters, numbers, hyphens, and underscores only')}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.update') : t('common:actions.add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
