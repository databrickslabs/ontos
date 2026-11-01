import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import type { MetricViewChangeRequestDetail } from '@/types/metric-view-change-request';
import { useChangeRequestText } from './metric-view-change-request-text';

interface Props {
    assetId: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The current definition, the editor's starting text. */
    currentDefinition: string;
    /** Called after a draft was saved (and submitted, when asked). */
    onSaved: () => void;
}

interface FormError {
    code?: string | null;
    message?: string | null;
    params?: Record<string, unknown> | null;
}

/**
 * Propose a new definition for a metric view: a YAML editor, a justification,
 * and "save as draft" or "save and submit for review". The YAML is checked by
 * the server; its parse error (with line and column) and the pre-check errors
 * are shown under the editor in the user's language.
 */
export default function ProposeMetricViewChangeDialog({
    assetId, open, onOpenChange, currentDefinition, onSaved,
}: Props) {
    const { t } = useTranslation('assets');
    const { post } = useApi();
    const text = useChangeRequestText();
    const [definition, setDefinition] = useState(currentDefinition);
    const [justification, setJustification] = useState('');
    const [error, setError] = useState<FormError | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (open) {
            setDefinition(currentDefinition);
            setJustification('');
            setError(null);
        }
    }, [open, currentDefinition]);

    const base = `/api/assets/${assetId}/metric-view/change-requests`;

    const save = async (andSubmit: boolean) => {
        setSaving(true);
        setError(null);
        try {
            const created = await post<MetricViewChangeRequestDetail>(base, {
                definition,
                justification: justification.trim() || null,
            });
            if (created.error || !created.data?.id) {
                setError({
                    code: created.errorCode, message: created.error, params: created.errorParams,
                });
                return;
            }
            if (andSubmit) {
                const submitted = await post(`${base}/${created.data.id}/submit`, {});
                if (submitted.error) {
                    // The draft is kept: it is in the list, and can be submitted later
                    onSaved();
                    setError({
                        code: submitted.errorCode, message: submitted.error,
                        params: submitted.errorParams,
                    });
                    return;
                }
            }
            onSaved();
            onOpenChange(false);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>{t('detail.metricView.changeRequests.dialog.title')}</DialogTitle>
                    <DialogDescription>
                        {t('detail.metricView.changeRequests.dialog.description')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    <div className="space-y-1">
                        <Label htmlFor="mv-change-definition">
                            {t('detail.metricView.changeRequests.dialog.definition')}
                        </Label>
                        <Textarea
                            id="mv-change-definition"
                            value={definition}
                            onChange={(e) => setDefinition(e.target.value)}
                            className="min-h-[320px] font-mono text-xs"
                            spellCheck={false}
                            aria-invalid={Boolean(error)}
                            aria-describedby={error ? 'mv-change-error' : undefined}
                        />
                        {error && (
                            <p id="mv-change-error" role="alert" className="text-sm text-destructive">
                                {text(error.code, error.message, error.params)}
                            </p>
                        )}
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="mv-change-justification">
                            {t('detail.metricView.changeRequests.dialog.justification')}
                        </Label>
                        <Textarea
                            id="mv-change-justification"
                            value={justification}
                            onChange={(e) => setJustification(e.target.value)}
                            placeholder={t(
                                'detail.metricView.changeRequests.dialog.justificationPlaceholder',
                            )}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" disabled={saving} onClick={() => save(false)}>
                        {t('detail.metricView.changeRequests.dialog.saveDraft')}
                    </Button>
                    <Button disabled={saving || !definition.trim()} onClick={() => save(true)}>
                        {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                        {t('detail.metricView.changeRequests.dialog.saveAndSubmit')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
