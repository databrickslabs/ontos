import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import type { LinkWarning } from '@/types/metric-view-consistency';
import { iriLabel } from './consistency-parts';

/** The params of a warning as the strings its translation interpolates. */
function warningParams(warning: LinkWarning): Record<string, string | number> {
    const list = (key: string, label = (x: string) => x) => {
        const values = warning.params[key];
        return Array.isArray(values) ? values.map((v) => label(String(v))).join(', ') : '';
    };
    return {
        count: Number(warning.params.count ?? 0),
        measures: list('measures'),
        concepts: list('concepts', iriLabel),
    };
}

/**
 * The warnings a new measure-to-concept link raised (`/consistency/link-check`).
 * Non-blocking: the link was created; the user can review and dismiss them.
 * Unknown codes fall back to the server's English message.
 */
export default function MetricViewLinkWarnings({ name, warnings, onDismiss }: {
    name: string;
    warnings: LinkWarning[];
    onDismiss: () => void;
}) {
    const { t } = useTranslation('metric-views');
    return (
        <Alert data-testid="metric-view-link-warnings">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle className="flex items-center justify-between gap-2">
                {t('linkWarning.title', { name })}
                <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    aria-label={t('linkWarning.dismiss')}
                    onClick={onDismiss}
                >
                    <X className="h-4 w-4" />
                </Button>
            </AlertTitle>
            <AlertDescription className="space-y-1">
                <ul className="list-disc pl-4 text-sm">
                    {warnings.map((w) => (
                        <li key={w.code}>
                            {t(`linkWarning.${w.code}`, {
                                ...warningParams(w), defaultValue: w.message,
                            })}
                        </li>
                    ))}
                </ul>
                <p className="text-xs text-muted-foreground">{t('linkWarning.hint')}</p>
            </AlertDescription>
        </Alert>
    );
}
