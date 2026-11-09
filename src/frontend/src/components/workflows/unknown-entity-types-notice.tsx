/**
 * Stored trigger entity types this version doesn't know (a removed type such
 * as `dataset`), from `trigger.unknown_entity_types` (#1151). They match no
 * event, so they are shown apart from the supported types, never as "any
 * entity", and the backend refuses a save that still lists them: the user
 * removes them here.
 */
import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export interface UnknownEntityTypesNoticeProps {
  values: string[];
  onRemove: (value: string) => void;
  /** The last unknown type was removed from a trigger that had only those: pick a known one */
  needsKnownType?: boolean;
}

export function UnknownEntityTypesNotice({
  values, onRemove, needsKnownType = false,
}: UnknownEntityTypesNoticeProps) {
  const { t } = useTranslation(['workflows']);
  if (values.length === 0) {
    if (!needsKnownType) return null;
    return (
      <p
        className={'flex items-start gap-2 rounded-md border border-destructive/50 p-2 '
          + 'text-xs text-destructive'}
        data-testid="entity-type-required"
        role="alert"
      >
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {t('workflows:triggerEntityChecks.pickKnownType')}
      </p>
    );
  }
  return (
    <div
      className="space-y-2 rounded-md border border-destructive/50 p-2"
      data-testid="unknown-entity-types"
    >
      <p className="flex items-start gap-2 text-xs text-destructive">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {t('workflows:triggerEntityChecks.unknownNotice', { count: values.length })}
      </p>
      <div className="flex flex-wrap gap-1">
        {values.map((value) => (
          <Badge key={value} variant="destructive" className="gap-1 pr-1">
            {t('workflows:triggerEntityChecks.unknownBadge', { type: value })}
            <button
              type="button"
              className="rounded-sm hover:bg-destructive-foreground/20"
              aria-label={t('workflows:triggerEntityChecks.removeUnknown', { type: value })}
              onClick={() => onRemove(value)}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
      </div>
    </div>
  );
}
