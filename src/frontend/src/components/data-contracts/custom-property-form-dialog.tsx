import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

interface CustomPropertyFormDialogProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  initial?: { property: string; value: string }
  existingKeys?: string[]
  onSubmit: (data: { property: string; value: string }) => Promise<void>
}

type ValueType = 'string' | 'number' | 'boolean' | 'json'

export default function CustomPropertyFormDialog({
  isOpen,
  onOpenChange,
  initial,
  existingKeys = [],
  onSubmit,
}: CustomPropertyFormDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const [property, setProperty] = useState('')
  const [value, setValue] = useState('')
  const [valueType, setValueType] = useState<ValueType>('string')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isEditing = !!initial

  useEffect(() => {
    if (isOpen) {
      if (initial) {
        setProperty(initial.property)
        setValue(initial.value)
        // Detect value type
        if (initial.value.startsWith('[') || initial.value.startsWith('{')) {
          setValueType('json')
        } else if (initial.value === 'true' || initial.value === 'false') {
          setValueType('boolean')
        } else if (!isNaN(Number(initial.value)) && initial.value !== '') {
          setValueType('number')
        } else {
          setValueType('string')
        }
      } else {
        setProperty('')
        setValue('')
        setValueType('string')
      }
      setError(null)
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    setError(null)

    if (!property.trim()) {
      setError(t('data-contracts:customProperty.validation.nameRequired', 'Property name is required'))
      return
    }

    // Check for duplicate key when adding new
    if (!isEditing && existingKeys.includes(property.trim())) {
      setError(t('data-contracts:customProperty.validation.duplicate', 'A property with this name already exists'))
      return
    }

    // Validate JSON if type is json
    if (valueType === 'json') {
      try {
        JSON.parse(value)
      } catch {
        setError(t('data-contracts:customProperty.validation.invalidJson', 'Invalid JSON format'))
        return
      }
    }

    setIsSubmitting(true)
    try {
      await onSubmit({
        property: property.trim(),
        value: value,
      })
      onOpenChange(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('data-contracts:customProperty.validation.saveFailed', 'Failed to save'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const formatJson = () => {
    if (valueType === 'json') {
      try {
        const parsed = JSON.parse(value)
        setValue(JSON.stringify(parsed, null, 2))
      } catch {
        // Ignore formatting errors
      }
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? t('data-contracts:customProperty.editTitle', 'Edit Custom Property') : t('data-contracts:customProperty.addTitle', 'Add Custom Property')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="property">{t('data-contracts:customProperty.fields.propertyName', 'Property Name')}</Label>
            <Input
              id="property"
              value={property}
              onChange={(e) => setProperty(e.target.value)}
              placeholder={t('data-contracts:customProperty.fields.propertyNamePlaceholder', 'e.g., mdmEntityType')}
              disabled={isEditing}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="valueType">{t('data-contracts:customProperty.fields.valueType', 'Value Type')}</Label>
            <Select value={valueType} onValueChange={(v) => setValueType(v as ValueType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="string">{t('data-contracts:customProperty.valueTypes.string', 'String')}</SelectItem>
                <SelectItem value="number">{t('data-contracts:customProperty.valueTypes.number', 'Number')}</SelectItem>
                <SelectItem value="boolean">{t('data-contracts:customProperty.valueTypes.boolean', 'Boolean')}</SelectItem>
                <SelectItem value="json">{t('data-contracts:customProperty.valueTypes.json', 'JSON (Array/Object)')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="value">{t('data-contracts:customProperty.fields.value', 'Value')}</Label>
              {valueType === 'json' && (
                <Button type="button" variant="ghost" size="sm" onClick={formatJson}>
                  {t('data-contracts:customProperty.formatJson', 'Format JSON')}
                </Button>
              )}
            </div>
            {valueType === 'boolean' ? (
              <Select value={value} onValueChange={setValue}>
                <SelectTrigger>
                  <SelectValue placeholder={t('data-contracts:customProperty.fields.selectValuePlaceholder', 'Select value')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">true</SelectItem>
                  <SelectItem value="false">false</SelectItem>
                </SelectContent>
              </Select>
            ) : valueType === 'json' ? (
              <Textarea
                id="value"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={t('data-contracts:customProperty.fields.jsonPlaceholder', '[{"name": "rule1", "type": "exact"}]')}
                className="font-mono text-sm min-h-[150px]"
              />
            ) : (
              <Input
                id="value"
                type={valueType === 'number' ? 'number' : 'text'}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={valueType === 'number' ? '0.8' : t('data-contracts:customProperty.fields.valuePlaceholder', 'Enter value')}
              />
            )}
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving', 'Saving...') : isEditing ? t('common:actions.update', 'Update') : t('common:actions.add', 'Add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

