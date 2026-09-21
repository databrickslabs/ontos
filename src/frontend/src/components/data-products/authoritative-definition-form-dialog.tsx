import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import type { AuthoritativeDefinition } from '@/types/data-product';

type AuthoritativeDefinitionFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (definition: AuthoritativeDefinition) => Promise<void>;
  initial?: AuthoritativeDefinition;
};

const DEFINITION_TYPES = [
  'businessDefinition',
  'transformationImplementation',
  'videoTutorial',
  'tutorial',
  'implementation',
];

export default function AuthoritativeDefinitionFormDialog({
  isOpen,
  onOpenChange,
  onSubmit,
  initial,
}: AuthoritativeDefinitionFormProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [type, setType] = useState('businessDefinition');
  const [url, setUrl] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setType(initial.type || 'businessDefinition');
      setUrl(initial.url || '');
      setDescription(initial.description || '');
    } else if (isOpen && !initial) {
      setType('businessDefinition');
      setUrl('');
      setDescription('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!type.trim()) {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:authoritativeDefinitionForm.validationTypeRequired'), variant: 'destructive' });
      return;
    }

    if (!url.trim()) {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:authoritativeDefinitionForm.validationUrlRequired'), variant: 'destructive' });
      return;
    }

    // URL validation
    try {
      new URL(url.trim());
    } catch {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:authoritativeDefinitionForm.validationUrlInvalid'), variant: 'destructive' });
      return;
    }

    setIsSubmitting(true);
    try {
      const definition: AuthoritativeDefinition = {
        type: type.trim(),
        url: url.trim(),
        description: description.trim() || undefined,
      };

      await onSubmit(definition);
      onOpenChange(false);
      toast({
        title: t('common:toast.success'),
        description: initial ? t('data-products:authoritativeDefinitionForm.successUpdated') : t('data-products:authoritativeDefinitionForm.successAdded'),
      });
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-products:authoritativeDefinitionForm.saveError'),
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
          <DialogTitle>{initial ? t('data-products:authoritativeDefinitionForm.editTitle') : t('data-products:authoritativeDefinitionForm.addTitle')}</DialogTitle>
          <DialogDescription>
            {t('data-products:authoritativeDefinitionForm.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="type">
              {t('data-products:authoritativeDefinitionForm.typeLabel')} <span className="text-destructive">*</span>
            </Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger id="type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DEFINITION_TYPES.map((defType) => (
                  <SelectItem key={defType} value={defType}>
                    {defType}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {t('data-products:authoritativeDefinitionForm.typeHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="url">
              {t('data-products:authoritativeDefinitionForm.urlLabel')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('data-products:authoritativeDefinitionForm.urlPlaceholder')}
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              {t('data-products:authoritativeDefinitionForm.urlHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-products:authoritativeDefinitionForm.descriptionPlaceholder')}
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.saveChanges') : t('data-products:authoritativeDefinitionForm.addButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
