import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import type { QualityRule } from '@/types/data-contract'

type QualityRuleFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (rule: QualityRule) => Promise<void>
  initial?: QualityRule
}

const QUALITY_DIMENSIONS = ['accuracy', 'completeness', 'conformity', 'consistency', 'coverage', 'timeliness', 'uniqueness']
const QUALITY_TYPES = ['text', 'library', 'sql', 'custom']
const QUALITY_SEVERITIES = ['info', 'warning', 'error']
const BUSINESS_IMPACTS = ['operational', 'regulatory']
const QUALITY_LEVELS = ['contract', 'object', 'property']

export default function QualityRuleFormDialog({ isOpen, onOpenChange, onSubmit, initial }: QualityRuleFormProps) {
  const { t } = useTranslation(['data-contracts', 'common'])
  const { toast } = useToast()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [level, setLevel] = useState('object')
  const [dimension, setDimension] = useState('completeness')
  const [businessImpact, setBusinessImpact] = useState('operational')
  const [severity, setSeverity] = useState('warning')
  const [type, setType] = useState('library')
  const [query, setQuery] = useState('')
  const [rule, setRule] = useState('')

  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '')
      setDescription(initial.description || '')
      setLevel(initial.level || 'object')
      setDimension(initial.dimension || 'completeness')
      setBusinessImpact(initial.businessImpact || 'operational')
      setSeverity(initial.severity || 'warning')
      setType(initial.type || 'library')
      setQuery(initial.query || '')
      setRule(initial.rule || '')
    } else if (isOpen && !initial) {
      setName('')
      setDescription('')
      setLevel('object')
      setDimension('completeness')
      setBusinessImpact('operational')
      setSeverity('warning')
      setType('library')
      setQuery('')
      setRule('')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: t('data-contracts:quality.validationError', 'Validation Error'), description: t('data-contracts:quality.nameRequired', 'Rule name is required'), variant: 'destructive' })
      return
    }

    setIsSubmitting(true)
    try {
      const qualityRule: QualityRule = {
        name: name.trim(),
        description: description.trim() || undefined,
        level,
        dimension,
        businessImpact,
        severity,
        type,
        query: query.trim() || undefined,
        rule: rule.trim() || undefined,
      }

      await onSubmit(qualityRule)
      onOpenChange(false)
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-contracts:quality.saveError', 'Failed to save quality rule'),
        variant: 'destructive',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? t('data-contracts:quality.editTitle', 'Edit Quality Rule') : t('data-contracts:quality.addTitle', 'Add Quality Rule')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:quality.description', 'Define a data quality check for this contract.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              {t('data-contracts:quality.nameLabel', 'Rule Name')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-contracts:quality.namePlaceholder', 'e.g., Check for null values')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-contracts:quality.descriptionPlaceholder', 'Describe what this rule checks')}
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="level">{t('data-contracts:quality.levelLabel', 'Level')}</Label>
              <Select value={level} onValueChange={setLevel}>
                <SelectTrigger id="level">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {QUALITY_LEVELS.map((lvl) => (
                    <SelectItem key={lvl} value={lvl}>
                      {lvl}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="dimension">{t('data-contracts:quality.dimensionLabel', 'Dimension')}</Label>
              <Select value={dimension} onValueChange={setDimension}>
                <SelectTrigger id="dimension">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {QUALITY_DIMENSIONS.map((dim) => (
                    <SelectItem key={dim} value={dim}>
                      {dim}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="severity">{t('data-contracts:quality.severityLabel', 'Severity')}</Label>
              <Select value={severity} onValueChange={setSeverity}>
                <SelectTrigger id="severity">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {QUALITY_SEVERITIES.map((sev) => (
                    <SelectItem key={sev} value={sev}>
                      {sev}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="businessImpact">{t('data-contracts:quality.businessImpactLabel', 'Business Impact')}</Label>
              <Select value={businessImpact} onValueChange={setBusinessImpact}>
                <SelectTrigger id="businessImpact">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BUSINESS_IMPACTS.map((impact) => (
                    <SelectItem key={impact} value={impact}>
                      {impact}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="type">{t('data-contracts:quality.typeLabel', 'Type')}</Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger id="type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {QUALITY_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {type === 'sql' && (
            <div className="space-y-2">
              <Label htmlFor="query">{t('data-contracts:quality.sqlQueryLabel', 'SQL Query')}</Label>
              <Textarea
                id="query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('data-contracts:quality.sqlQueryPlaceholder', 'SELECT COUNT(*) FROM table WHERE...')}
                rows={4}
                className="font-mono text-sm"
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="rule">{t('data-contracts:quality.ruleExpressionLabel', 'Rule Expression')}</Label>
            <Textarea
              id="rule"
              value={rule}
              onChange={(e) => setRule(e.target.value)}
              placeholder={t('data-contracts:quality.ruleExpressionPlaceholder', 'e.g., col_name is not null')}
              rows={2}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.saveChanges') : t('data-contracts:quality.addButton', 'Add Rule')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
