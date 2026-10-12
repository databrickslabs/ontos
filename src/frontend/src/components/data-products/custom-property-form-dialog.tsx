import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import type { CustomProperty } from '@/types/data-product';

type CustomPropertyFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (property: CustomProperty) => Promise<void>;
  initial?: CustomProperty;
};

export default function CustomPropertyFormDialog({ isOpen, onOpenChange, onSubmit, initial }: CustomPropertyFormProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [property, setProperty] = useState('');
  const [value, setValue] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setProperty(initial.property || '');
      setValue(typeof initial.value === 'string' ? initial.value : JSON.stringify(initial.value));
      setDescription(initial.description || '');
    } else if (isOpen && !initial) {
      setProperty('');
      setValue('');
      setDescription('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!property.trim()) {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:customProperty.validationNameRequired'), variant: 'destructive' });
      return;
    }

    if (!value.trim()) {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:customProperty.validationValueRequired'), variant: 'destructive' });
      return;
    }

    // Validate camelCase naming
    if (!/^[a-z][a-zA-Z0-9]*$/.test(property.trim())) {
      toast({
        title: t('data-products:messages.validationTitle'),
        description: t('data-products:customProperty.validationCamelCase'),
        variant: 'destructive'
      });
      return;
    }

    setIsSubmitting(true);
    try {
      // Try to parse value as JSON, otherwise keep as string
      let parsedValue: any = value.trim();
      try {
        parsedValue = JSON.parse(value.trim());
      } catch {
        // Keep as string if not valid JSON
      }

      const customProperty: CustomProperty = {
        property: property.trim(),
        value: parsedValue,
        description: description.trim() || undefined,
      };

      await onSubmit(customProperty);
      onOpenChange(false);
      toast({
        title: t('common:toast.success'),
        description: initial ? t('data-products:customProperty.successUpdated') : t('data-products:customProperty.successAdded'),
      });
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-products:customProperty.saveError'),
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? t('data-products:customProperty.editTitle') : t('data-products:customProperty.addTitle')}</DialogTitle>
          <DialogDescription>
            {t('data-products:customProperty.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="property">
              {t('data-products:customProperty.propertyNameLabel')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="property"
              value={property}
              onChange={(e) => setProperty(e.target.value)}
              placeholder={t('data-products:customProperty.propertyNamePlaceholder')}
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              {t('data-products:customProperty.propertyNameHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="value">
              {t('data-products:customProperty.propertyValueLabel')} <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="value"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={t('data-products:customProperty.propertyValuePlaceholder')}
              rows={3}
            />
            <p className="text-xs text-muted-foreground">
              {t('data-products:customProperty.propertyValueHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-products:customProperty.descriptionPlaceholder')}
              rows={2}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.saveChanges') : t('data-products:customProperty.addButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
