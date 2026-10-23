import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface CreateVersionDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  currentVersion: string;
  productTitle: string;
  onSubmit: (newVersion: string) => void; // Callback with the new version string
  /** Accept only an X.Y.Z version (contract versions are cloned, which requires it) */
  requireSemver?: boolean;
}

const SEMVER = /^\d+\.\d+\.\d+$/;

const CreateVersionDialog: React.FC<CreateVersionDialogProps> = ({
  isOpen,
  onOpenChange,
  currentVersion,
  productTitle,
  onSubmit,
  requireSemver = false,
}) => {
  const { t } = useTranslation(['data-products', 'common']);
  const [newVersion, setNewVersion] = useState<string>(currentVersion); // Pre-fill with current
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (event?: React.MouseEvent) => {
    const trimmedVersion = newVersion.trim();
    // A refused version keeps the dialog open (the action button closes it otherwise)
    if (!trimmedVersion) {
      event?.preventDefault();
      setError(t('data-products:createVersion.errors.versionEmpty'));
      return;
    }
    if (requireSemver && !SEMVER.test(trimmedVersion)) {
      event?.preventDefault();
      setError(t('data-products:createVersion.errors.versionFormat', { version: trimmedVersion }));
      return;
    }
    setError(null);
    onSubmit(trimmedVersion);
    onOpenChange(false); // Close dialog on successful submit
  };

  const handleCancel = () => {
    setError(null);
    setNewVersion(currentVersion); // Reset input on cancel
    onOpenChange(false);
  };

  // Reset input when dialog opens/closes externally
  React.useEffect(() => {
    if (isOpen) {
      setNewVersion(currentVersion); // Reset to current when opened
      setError(null);
    }
  }, [isOpen, currentVersion]);


  return (
    <AlertDialog open={isOpen} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('data-products:createVersion.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('data-products:createVersion.description', { productTitle, currentVersion })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="py-4">
          <Label htmlFor="new-version-input" className="mb-2 block">
            {t('data-products:createVersion.versionLabel')}
          </Label>
          <Input
            id="new-version-input"
            value={newVersion}
            onChange={(e) => setNewVersion(e.target.value)}
            placeholder={t(requireSemver
              ? 'data-products:createVersion.versionPlaceholderSemver'
              : 'data-products:createVersion.versionPlaceholder')}
            className={error ? "border-destructive" : ""}
          />
          {error && <p className="text-sm text-destructive mt-1">{error}</p>}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={handleCancel}>{t('common:actions.cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={handleSubmit}>{t('data-products:createVersion.createButton')}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

export default CreateVersionDialog; 