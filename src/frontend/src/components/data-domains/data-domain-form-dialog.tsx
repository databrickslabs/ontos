import React from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Loader2 } from 'lucide-react';

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataDomain, DataDomainCreate, DataDomainUpdate } from '@/types/data-domain';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import TagSelector from '@/components/ui/tag-selector';

interface DataDomainFormDialogProps {
  domain?: DataDomain | null;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmitSuccess: (domain: DataDomain) => void;
  trigger?: React.ReactNode;
  allDomains: DataDomain[];
}

const NO_PARENT_VALUE = "__NO_PARENT_SELECTED__"; // Constant for "No Parent" option

const buildSchema = (t: TFunction) => z.object({
  name: z.string().min(2, { message: t('data-domains:form.validation.nameMin') }).max(100),
  description: z.string().max(500, { message: t('data-domains:form.validation.descriptionMax') }).optional().nullable(),
  tags: z.array(z.any()).optional(),
  parent_id: z.string().uuid().optional().nullable().or(z.literal(NO_PARENT_VALUE)), // Allow NO_PARENT_VALUE
});

type DataDomainFormValues = z.infer<ReturnType<typeof buildSchema>>;

export function DataDomainFormDialog({
  domain,
  isOpen,
  onOpenChange,
  onSubmitSuccess,
  trigger,
  allDomains,
}: DataDomainFormDialogProps) {
  const { t } = useTranslation(['data-domains', 'common']);
  const api = useApi();
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = React.useState(false);

  const formSchema = React.useMemo(() => buildSchema(t), [t]);

  const form = useForm<DataDomainFormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: domain?.name || "",
      description: domain?.description || "",
      tags: domain?.tags || [],
      parent_id: domain?.parent_id ?? NO_PARENT_VALUE, // Use NO_PARENT_VALUE for null/undefined
    },
  });

  React.useEffect(() => {
    if (isOpen) {
      form.reset({
        name: domain?.name || "",
        description: domain?.description || "",
        tags: domain?.tags || [],
        parent_id: domain?.parent_id ?? NO_PARENT_VALUE, // Use NO_PARENT_VALUE for null/undefined
      });
    }
  }, [isOpen, domain, form, allDomains]);

  const handleCloseAttempt = () => {
    // Check if form has been modified
    if (form.formState.isDirty && !isSubmitting) {
      setShowDiscardConfirm(true);
    } else {
      onOpenChange(false);
    }
  };

  const handleConfirmDiscard = () => {
    setShowDiscardConfirm(false);
    onOpenChange(false);
  };

  const handleFormSubmit = async (values: DataDomainFormValues) => {
    setIsSubmitting(true);
    let result;

    const processedValues: DataDomainCreate | DataDomainUpdate = {
      name: values.name,
      description: values.description,
      tags: values.tags || [],
      parent_id: values.parent_id === NO_PARENT_VALUE ? null : values.parent_id, // Convert back to null for API
    };

    if (domain?.id) {
      result = await api.put<DataDomain>(`/api/data-domains/${domain.id}`, processedValues as DataDomainUpdate);
    } else {
      result = await api.post<DataDomain>('/api/data-domains', processedValues as DataDomainCreate);
    }

    if (result.error) {
      throw new Error(result.error);
    }
    if (!result.data) {
       throw new Error('No data returned from API.');
    }

    toast({ title: domain ? t('form.toasts.updated') : t('form.toasts.created'), description: t('form.toasts.saveSuccess', { name: result.data.name }) });
    onSubmitSuccess(result.data);
    onOpenChange(false);

    try {
    } catch (error: any) {
      toast({ variant: "destructive", title: t('form.toasts.saveError'), description: error.message || t('common:errors.unknownError') });
    } finally {
      setIsSubmitting(false);
    }
  };

  const dialogTitle = domain ? t('form.editTitle') : t('form.createTitle');
  const dialogDescription = domain
    ? t('form.editDescription')
    : t('form.createDescription');
  const submitButtonText = domain ? t('common:actions.saveChanges') : t('form.createSubmit');

  const parentDomainOptions = allDomains.filter(d => d.id !== domain?.id);

  const dialogContent = (
    <DialogContent 
      className="sm:max-w-[525px]"
      onEscapeKeyDown={(e) => {
        // Prevent closing on Escape key
        e.preventDefault();
        handleCloseAttempt();
      }}
    >
      <DialogHeader>
        <DialogTitle>{dialogTitle}</DialogTitle>
        <DialogDescription>{dialogDescription}</DialogDescription>
      </DialogHeader>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(handleFormSubmit)} className="space-y-4 py-2">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('form.nameLabel')}</FormLabel>
                <FormControl>
                  <Input placeholder={t('form.namePlaceholder')} {...field} />
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
                <FormLabel>{t('form.descriptionLabel')}</FormLabel>
                <FormControl>
                  <Textarea
                    placeholder={t('form.descriptionPlaceholder')}
                    className="resize-none"
                    {...field}
                    value={field.value ?? ''}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="tags"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('form.tagsLabel')}</FormLabel>
                <FormControl>
                  <TagSelector
                    value={field.value || []}
                    onChange={field.onChange}
                    placeholder={t('form.tagsPlaceholder')}
                    allowCreate={true}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="parent_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('form.parentLabel')}</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  value={field.value ?? NO_PARENT_VALUE}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder={t('form.parentPlaceholder')} />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value={NO_PARENT_VALUE}>{t('form.noParent')}</SelectItem>
                    {parentDomainOptions.map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleCloseAttempt} disabled={isSubmitting}>
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={isSubmitting || !form.formState.isValid}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} 
              {submitButtonText}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogContent>
  );

  if (trigger) {
    return (
      <>
        <Dialog open={isOpen} onOpenChange={handleCloseAttempt}>
          <DialogTrigger asChild>{trigger}</DialogTrigger>
          {dialogContent}
        </Dialog>

        <AlertDialog open={showDiscardConfirm} onOpenChange={setShowDiscardConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('common:confirmations.discardChanges')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('form.discardDescription')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('form.continueEditing')}</AlertDialogCancel>
              <AlertDialogAction onClick={handleConfirmDiscard}>{t('form.discardChanges')}</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </>
    );
  }

  return (
    <>
      <Dialog open={isOpen} onOpenChange={handleCloseAttempt}>
        {dialogContent}
      </Dialog>

      <AlertDialog open={showDiscardConfirm} onOpenChange={setShowDiscardConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('common:confirmations.discardChanges')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('form.discardDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('form.continueEditing')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmDiscard}>{t('form.discardChanges')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
} 