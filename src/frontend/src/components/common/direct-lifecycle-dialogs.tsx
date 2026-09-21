import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { CertificationLevel } from '@/types/lifecycle';
import { PUBLICATION_SCOPE_LABELS, type PublicationScope } from '@/types/lifecycle';

const PUBLICATION_SCOPES: PublicationScope[] = ['none', 'domain', 'organization', 'external'];

interface DirectCertifyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  certificationLevels: CertificationLevel[];
  selectedLevelOrder: number | null;
  onSelectedLevelOrderChange: (order: number | null) => void;
  isSubmitting: boolean;
  onConfirm: () => void;
}

export function DirectCertifyDialog({
  open,
  onOpenChange,
  title,
  description,
  certificationLevels,
  selectedLevelOrder,
  onSelectedLevelOrderChange,
  isSubmitting,
  onConfirm,
}: DirectCertifyDialogProps) {
  const { t } = useTranslation('common');
  const sorted = [...certificationLevels].sort((a, b) => a.level_order - b.level_order);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title || t('common:lifecycleDialogs.certifyTitle')}</DialogTitle>
          <DialogDescription>{description || t('common:lifecycleDialogs.certifyDescription')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label>{t('common:lifecycleDialogs.certificationLevel')}</Label>
          <Select
            value={selectedLevelOrder != null ? String(selectedLevelOrder) : ''}
            onValueChange={(v) => onSelectedLevelOrderChange(v ? parseInt(v, 10) : null)}
          >
            <SelectTrigger>
              <SelectValue placeholder={t('common:lifecycleDialogs.selectLevel')} />
            </SelectTrigger>
            <SelectContent>
              {sorted.map((lvl) => (
                <SelectItem key={lvl.id} value={String(lvl.level_order)}>
                  {lvl.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isSubmitting || selectedLevelOrder == null || sorted.length === 0}
          >
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('common:actions.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface DirectPublishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  selectedScope: PublicationScope;
  onSelectedScopeChange: (scope: PublicationScope) => void;
  isSubmitting: boolean;
  onConfirm: () => void;
}

export function DirectPublishDialog({
  open,
  onOpenChange,
  title,
  description,
  selectedScope,
  onSelectedScopeChange,
  isSubmitting,
  onConfirm,
}: DirectPublishDialogProps) {
  const { t } = useTranslation('common');
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title || t('common:lifecycleDialogs.publishTitle')}</DialogTitle>
          <DialogDescription>{description || t('common:lifecycleDialogs.publishDescription')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label>{t('common:lifecycleDialogs.publicationScope')}</Label>
          <Select value={selectedScope} onValueChange={(v) => onSelectedScopeChange(v as PublicationScope)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PUBLICATION_SCOPES.map((s) => (
                <SelectItem key={s} value={s}>
                  {PUBLICATION_SCOPE_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={onConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('common:actions.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
