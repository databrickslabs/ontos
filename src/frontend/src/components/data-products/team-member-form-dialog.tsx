import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { PrincipalPicker } from '@/components/common/principal-picker';
import type { TeamMember } from '@/types/data-product';

type TeamMemberFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (member: TeamMember) => Promise<void>;
  initial?: TeamMember;
};

export default function TeamMemberFormDialog({ isOpen, onOpenChange, onSubmit, initial }: TeamMemberFormProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [role, setRole] = useState('');
  const [dateIn, setDateIn] = useState('');
  const [dateOut, setDateOut] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setUsername(initial.username || '');
      setName(initial.name || '');
      setDescription(initial.description || '');
      setRole(initial.role || '');
      setDateIn(initial.dateIn || '');
      setDateOut(initial.dateOut || '');
    } else if (isOpen && !initial) {
      setUsername('');
      setName('');
      setDescription('');
      setRole('');
      setDateIn('');
      setDateOut('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!username.trim()) {
      toast({ title: t('data-products:messages.validationTitle'), description: t('data-products:teamMemberForm.validationUsernameRequired'), variant: 'destructive' });
      return;
    }

    setIsSubmitting(true);
    try {
      const member: TeamMember = {
        username: username.trim(),
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        role: role.trim() || undefined,
        dateIn: dateIn || undefined,
        dateOut: dateOut || undefined,
      };

      await onSubmit(member);
      onOpenChange(false);
      toast({
        title: t('common:toast.success'),
        description: initial ? t('data-products:teamMemberForm.successUpdated') : t('data-products:teamMemberForm.successAdded'),
      });
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error?.message || t('data-products:teamMemberForm.saveError'),
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
          <DialogTitle>{initial ? t('data-products:teamMemberForm.editTitle') : t('data-products:teamMemberForm.addTitle')}</DialogTitle>
          <DialogDescription>
            {t('data-products:teamMemberForm.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="username">
              {t('data-products:teamMemberForm.usernameLabel')} <span className="text-destructive">*</span>
            </Label>
            <PrincipalPicker
              id="username"
              accepts={['user']}
              value={username || null}
              onChange={(next) => setUsername(next ?? '')}
              placeholder={t('data-products:teamMemberForm.usernamePlaceholder')}
              aria-label={t('data-products:teamMemberForm.usernameLabel')}
            />
            <p className="text-xs text-muted-foreground">
              {t('data-products:teamMemberForm.usernameHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="name">{t('data-products:teamMemberForm.fullNameLabel')}</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-products:teamMemberForm.fullNamePlaceholder')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">{t('data-products:teamMemberForm.roleLabel')}</Label>
            <Input
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder={t('data-products:teamMemberForm.rolePlaceholder')}
            />
            <p className="text-xs text-muted-foreground">
              {t('data-products:teamMemberForm.roleHint')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-products:teamMemberForm.descriptionPlaceholder')}
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="dateIn">{t('data-products:teamMemberForm.dateJoinedLabel')}</Label>
              <Input
                id="dateIn"
                type="date"
                value={dateIn}
                onChange={(e) => setDateIn(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="dateOut">{t('data-products:teamMemberForm.dateLeftLabel')}</Label>
              <Input
                id="dateOut"
                type="date"
                value={dateOut}
                onChange={(e) => setDateOut(e.target.value)}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t('common:actions.saving') : initial ? t('common:actions.saveChanges') : t('data-products:teamMemberForm.addButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
