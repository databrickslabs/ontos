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
import { Switch } from '@/components/ui/switch';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { BusinessRoleRead, BusinessRoleCategory, BusinessRoleStatus } from '@/types/business-role';

const CATEGORIES: BusinessRoleCategory[] = ['governance', 'technical', 'business', 'operational'];
const STATUSES: BusinessRoleStatus[] = ['active', 'deprecated'];

const formSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  category: z.string().optional(),
  status: z.enum(['active', 'deprecated']),
  is_approver: z.boolean(),
});

type FormData = z.infer<typeof formSchema>;

interface BusinessRoleFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  role?: BusinessRoleRead | null;
  onSubmitSuccess: () => void;
}

export function BusinessRoleFormDialog({
  isOpen, onOpenChange, role, onSubmitSuccess,
}: BusinessRoleFormDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [workflowUsage, setWorkflowUsage] = useState<{ count: number; used_in_workflows: { id: string; name: string }[] }>({ count: 0, used_in_workflows: [] });
  const { get, post: apiPost, put: apiPut } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['business-roles', 'common']);

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: { name: '', description: '', category: 'none', status: 'active', is_approver: false },
  });

  useEffect(() => {
    if (isOpen) {
      if (role) {
        form.reset({
          name: role.name,
          description: role.description || '',
          category: role.category || 'none',
          status: role.status,
          is_approver: role.is_approver ?? false,
        });
        // Check if this role is used in any workflows
        if (role.is_approver) {
          get<{ count: number; used_in_workflows: { id: string; name: string }[] }>(
            `/api/business-roles/${role.id}/workflow-usage`
          ).then((res) => {
            if (res.data) setWorkflowUsage(res.data);
          }).catch(() => setWorkflowUsage({ count: 0, used_in_workflows: [] }));
        } else {
          setWorkflowUsage({ count: 0, used_in_workflows: [] });
        }
      } else {
        form.reset({ name: '', description: '', category: 'none', status: 'active', is_approver: false });
        setWorkflowUsage({ count: 0, used_in_workflows: [] });
      }
    }
  }, [isOpen, role, form]);

  const handleSubmit = async (data: FormData) => {
    setIsSubmitting(true);
    try {
      const payload = {
        name: data.name,
        description: data.description || undefined,
        category: data.category === 'none' ? undefined : data.category,
        status: data.status,
        is_approver: data.is_approver,
      };

      const response = role
        ? await apiPut<BusinessRoleRead>(`/api/business-roles/${role.id}`, payload)
        : await apiPost<BusinessRoleRead>('/api/business-roles', payload);

      if (response.error) throw new Error(response.error);

      toast({
        title: role ? t('form.toasts.updated') : t('form.toasts.created'),
        description: role
          ? t('form.toasts.updatedDescription', { name: data.name })
          : t('form.toasts.createdDescription', { name: data.name }),
      });

      onSubmitSuccess();
      onOpenChange(false);
    } catch (error) {
      toast({
        variant: 'destructive',
        title: role ? t('form.toasts.updateFailed') : t('form.toasts.createFailed'),
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
          <DialogTitle>{role ? t('form.editTitle') : t('form.createTitle')}</DialogTitle>
          <DialogDescription>
            {role ? t('form.editDescription') : t('form.createDescription')}
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

            <FormField
              control={form.control}
              name="is_approver"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <FormLabel>{t('form.isApprover')}</FormLabel>
                    <p className="text-xs text-muted-foreground">
                      {t('form.isApproverDescription')}
                    </p>
                    {workflowUsage.count > 0 && field.value && (
                      <p className="text-xs text-amber-600">
                        {t('form.isApproverInUse', { count: workflowUsage.count, workflows: workflowUsage.used_in_workflows.map(w => w.name).join(', ') })}
                      </p>
                    )}
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={workflowUsage.count > 0 && field.value}
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
                {t('common:actions.cancel')}
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {role ? t('form.update') : t('form.create')}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
