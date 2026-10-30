import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Archive,
  CheckCircle,
  CopyPlus,
  Loader2,
  Rocket,
  Send,
  ShieldCheck,
  Undo2,
  ArchiveX,
  ArrowRightCircle,
} from 'lucide-react';
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

// ---------------------------------------------------------------------------
// RequestConceptActionDialog: the concept detail page's single "Request"
// entry point (mirrors the data-contract / data-product request dialogs).
// The user picks an action, the body explains what will happen, and the
// primary button follows the selection. It consolidates:
//   * the lifecycle step(s) valid from the current status (Request Review for
//     a draft; approve / request changes / publish / certify / deprecate /
//     archive afterwards), and
//   * "New Version" (opens the PublishVersionDialog in the parent).
//
// The dialog is presentational: the parent decides WHICH transitions the user
// may run and owns every side effect (approval wizard, comment dialogs, API
// calls). It renders nothing when there is nothing to offer.
// ---------------------------------------------------------------------------

export interface ConceptTransitionItem {
  /** Target status, e.g. 'under_review'. */
  status: string;
  /** by-iri action verb, e.g. 'submit-review', 'approve'. */
  action: string;
  labelKey: string;
  defaultLabel: string;
}

export interface ConceptNewVersionOption {
  disabled: boolean;
  /** Why it is disabled; shown as helper text in the dialog. */
  disabledReason?: string;
  onSelect: () => void;
}

export interface RequestConceptActionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conceptLabel?: string;
  currentStatus?: string;
  transitions: ConceptTransitionItem[];
  /** Omit to hide "New Version" entirely (no permission / not versionable). */
  newVersion?: ConceptNewVersionOption | null;
  onTransition: (status: string, action: string) => void;
  busy?: boolean;
}

const NEW_VERSION_KEY = '__new_version__';

interface OptionConfig {
  key: string;
  label: string;
  icon: ReactNode;
  description: string;
  confirmLabel: string;
  disabled: boolean;
  disabledReason?: string;
  run: () => void;
}

const transitionKey = (item: ConceptTransitionItem) => `${item.action || ''}::${item.status}`;

export function RequestConceptActionDialog({
  open,
  onOpenChange,
  conceptLabel,
  currentStatus,
  transitions,
  newVersion,
  onTransition,
  busy = false,
}: RequestConceptActionDialogProps): JSX.Element | null {
  const { t } = useTranslation(['semantic-models', 'common']);

  const options = useMemo<OptionConfig[]>(() => {
    const iconCls = 'h-5 w-5';
    const describe = (item: ConceptTransitionItem): Pick<OptionConfig, 'icon' | 'description'> => {
      const action = (item.action || '').toLowerCase();
      const status = (item.status || '').toLowerCase();
      if (action === 'submit-review') {
        return {
          icon: <Send className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.submitReview',
            'Submit this concept for review. The reviewer is chosen in the next step.',
          ),
        };
      }
      if (action === 'approve') {
        return {
          icon: <CheckCircle className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.approve',
            'Approve this concept so it can be published.',
          ),
        };
      }
      if (action === 'reject' || action === 'request-changes' || status === 'draft') {
        return {
          icon: <Undo2 className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.requestChanges',
            'Send this concept back to draft. You can add a comment in the next step.',
          ),
        };
      }
      if (action === 'publish' || status === 'published') {
        return {
          icon: <Rocket className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.publish',
            'Publish this concept so others can find and use it.',
          ),
        };
      }
      if (action === 'certify' || status === 'certified') {
        return {
          icon: <ShieldCheck className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.certify',
            'Mark this concept as certified, a trusted reference.',
          ),
        };
      }
      if (action === 'deprecate' || status === 'deprecated') {
        return {
          icon: <ArchiveX className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.deprecate',
            'Deprecate this concept. It stays visible but is flagged as no longer recommended.',
          ),
        };
      }
      if (action === 'archive' || status === 'archived') {
        return {
          icon: <Archive className={iconCls} />,
          description: t(
            'semantic-models:lifecycle.requestDialog.describe.archive',
            'Archive this concept. It is retired and hidden from normal use.',
          ),
        };
      }
      return {
        icon: <ArrowRightCircle className={iconCls} />,
        description: t('semantic-models:lifecycle.requestDialog.describe.generic', {
          defaultValue: 'Move this concept to the {{status}} status.',
          status: item.status,
        }),
      };
    };

    const list: OptionConfig[] = transitions.map((item) => {
      const label =
        item.action === 'submit-review'
          ? t('semantic-models:lifecycle.requestReview', 'Request Review')
          : t(item.labelKey, item.defaultLabel);
      return {
        key: transitionKey(item),
        label,
        confirmLabel: label,
        disabled: false,
        run: () => onTransition(item.status, item.action),
        ...describe(item),
      };
    });

    if (newVersion) {
      list.push({
        key: NEW_VERSION_KEY,
        label: t('semantic-models:versionHistory.newVersion', 'New Version'),
        confirmLabel: t('semantic-models:lifecycle.requestDialog.createNewVersion', 'Create New Version'),
        icon: <CopyPlus className={iconCls} />,
        description: t(
          'semantic-models:lifecycle.requestDialog.describe.newVersion',
          'Save a new version of this concept. The IRI stays the same.',
        ),
        disabled: newVersion.disabled,
        disabledReason: newVersion.disabledReason,
        run: () => newVersion.onSelect(),
      });
    }
    return list;
  }, [transitions, newVersion, onTransition, t]);

  const firstEnabledKey = options.find((o) => !o.disabled)?.key ?? options[0]?.key ?? '';
  const [selectedKey, setSelectedKey] = useState<string>(firstEnabledKey);

  // Reset the selection every time the dialog opens.
  useEffect(() => {
    if (open) setSelectedKey(firstEnabledKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (options.length === 0) return null;

  const selected = options.find((o) => o.key === selectedKey) ?? options.find((o) => o.key === firstEnabledKey);
  const confirmDisabled = busy || !selected || selected.disabled;

  const handleConfirm = () => {
    if (!selected || confirmDisabled) return;
    onOpenChange(false);
    selected.run();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t('semantic-models:lifecycle.requestDialog.title', 'Request Action')}</DialogTitle>
          <DialogDescription>
            {conceptLabel
              ? t('semantic-models:lifecycle.requestDialog.descriptionWithLabel', {
                  defaultValue: 'Choose what you want to do with the concept "{{label}}".',
                  label: conceptLabel,
                })
              : t('semantic-models:lifecycle.requestDialog.description', 'Choose what you want to do with this concept.')}
            {currentStatus && (
              <>
                {' '}
                {t('semantic-models:lifecycle.requestDialog.currentStatus', {
                  defaultValue: 'Current status: {{status}}.',
                  status: t(`semantic-models:lifecycle.status.${currentStatus.toLowerCase()}`, currentStatus),
                })}
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="request-concept-action">
              {t('semantic-models:lifecycle.requestDialog.pickerLabel', 'What do you want to request?')}
            </Label>
            <Select value={selected?.key} onValueChange={setSelectedKey}>
              <SelectTrigger
                id="request-concept-action"
                aria-label={t('semantic-models:lifecycle.requestDialog.pickerLabel', 'What do you want to request?')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {options.map((o) => (
                  <SelectItem key={o.key} value={o.key}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selected && (
            <div className="flex items-start gap-3 rounded-md border p-3" data-testid="request-concept-action-body">
              <div className="mt-0.5 text-muted-foreground">{selected.icon}</div>
              <div className="space-y-1">
                <p className="text-sm font-medium">{selected.label}</p>
                <p className="text-sm text-muted-foreground">{selected.description}</p>
                {selected.disabled && selected.disabledReason && (
                  <p className="text-sm text-amber-600 dark:text-amber-500">{selected.disabledReason}</p>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleConfirm} disabled={confirmDisabled}>
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {selected?.confirmLabel ?? t('semantic-models:lifecycle.request', 'Request')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default RequestConceptActionDialog;
