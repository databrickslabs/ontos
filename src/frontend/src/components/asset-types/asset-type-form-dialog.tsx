import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { AssetTypeRead, AssetTypeCategory, AssetTypeStatus } from '@/types/asset';

const CATEGORIES: AssetTypeCategory[] = ['data', 'analytics', 'integration', 'system', 'custom'];
const STATUSES: AssetTypeStatus[] = ['active', 'deprecated'];

const formSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  category: z.string().optional(),
  icon: z.string().optional(),
  status: z.enum(['active', 'deprecated']),
});

type FormData = z.infer<typeof formSchema>;

interface AssetTypeFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  assetType?: AssetTypeRead | null;
  onSubmitSuccess: () => void;
}

export function AssetTypeFormDialog({
  isOpen, onOpenChange, assetType, onSubmitSuccess,
}: AssetTypeFormDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { post: apiPost, put: apiPut } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['asset-types', 'common']);

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: { name: '', description: '', category: 'none', icon: '', status: 'active' },
  });

  useEffect(() => {
    if (isOpen) {
      if (assetType) {
        form.reset({
          name: assetType.name,
          description: assetType.description || '',
          category: assetType.category || 'none',
          icon: assetType.icon || '',
          // A retired type is not edited here (Settings disables Edit for it, #970).
          status: assetType.status === 'deprecated' ? 'deprecated' : 'active',
        });
      } else {
        form.reset({ name: '', description: '', category: 'none', icon: '', status: 'active' });
      }
    }
  }, [isOpen, assetType, form]);

  const handleSubmit = async (data: FormData) => {
    setIsSubmitting(true);
    try {
      const payload = {
        name: data.name,
        description: data.description || undefined,
        category: data.category === 'none' ? undefined : data.category,
        icon: data.icon || undefined,
        status: data.status,
      };

      const response = assetType
        ? await apiPut<AssetTypeRead>(`/api/asset-types/${assetType.id}`, payload)
        : await apiPost<AssetTypeRead>('/api/asset-types', payload);

      if (response.error) throw new Error(response.error);

      toast({
        title: assetType ? t('form.toasts.updated') : t('form.toasts.created'),
        description: assetType
          ? t('form.toasts.updatedDescription', { name: data.name })
          : t('form.toasts.createdDescription', { name: data.name }),
      });

      onSubmitSuccess();
      onOpenChange(false);
    } catch (error) {
      toast({
        variant: 'destructive',
        title: assetType ? t('form.toasts.updateFailed') : t('form.toasts.createFailed'),
        description: error instanceof Error ? error.message : 'An error occurred',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{assetType ? t('form.editTitle') : t('form.createTitle')}</DialogTitle>
          <DialogDescription>
            {assetType ? t('form.editDescription') : t('form.createDescription')}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('table.name')}</FormLabel>
                  <FormControl>
                    <Input placeholder={t('form.placeholders.name')} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('table.description')}</FormLabel>
                  <FormControl>
                    <Textarea placeholder={t('form.placeholders.description')} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="category"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('table.category')}</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder={t('form.placeholders.category')} />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">{t('form.noCategory')}</SelectItem>
                      {CATEGORIES.map((cat) => (
                        <SelectItem key={cat} value={cat}>{t(`categories.${cat}`)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="icon"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('form.labels.icon')}</FormLabel>
                  <FormControl>
                    <Input placeholder={t('form.placeholders.icon')} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('table.status')}</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {STATUSES.map((s) => (
                        <SelectItem key={s} value={s}>{t(`statuses.${s}`)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
                {t('common:actions.cancel')}
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {assetType ? t('form.update') : t('form.create')}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
