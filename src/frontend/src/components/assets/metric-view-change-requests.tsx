import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, GitPullRequest } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import { FeatureAccessLevel } from '@/types/settings';
import type {
    MetricViewChangeRequest, MetricViewChangeRequestStatus,
} from '@/types/metric-view-change-request';
import ProposeMetricViewChangeDialog from './propose-metric-view-change-dialog';
import { useChangeRequestText } from './metric-view-change-request-text';

const PREFIX = 'detail.metricView.changeRequests';

const STATUS_VARIANT: Record<MetricViewChangeRequestStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    draft: 'outline',
    in_review: 'secondary',
    approved: 'secondary',
    delivered: 'default',
    rejected: 'destructive',
    failed: 'destructive',
    cancelled: 'outline',
};

function formatDate(value: string | null | undefined, language: string): string {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(language);
}

function RequestItem({ request, isRequester, canWrite, onAction }: {
    request: MetricViewChangeRequest;
    isRequester: boolean;
    canWrite: boolean;
    onAction: (request: MetricViewChangeRequest, action: 'submit' | 'cancel') => void;
}) {
    const { t, i18n } = useTranslation('assets');
    const text = useChangeRequestText();
    const lang = i18n.language;
    const modes = (request.delivery_mode || '').split(',').filter(Boolean)
        .map((m) => t(`${PREFIX}.deliveryModes.${m}`, { defaultValue: m })).join(', ');
    return (
        <li className="space-y-1 rounded-md border p-3 text-sm" data-testid="mv-change-request">
            <div className="flex flex-wrap items-center gap-2">
                <Badge variant={STATUS_VARIANT[request.status] ?? 'outline'}>
                    {t(`${PREFIX}.status.${request.status}`)}
                </Badge>
                <span className="text-muted-foreground">
                    {t(`${PREFIX}.requestedBy`, {
                        user: request.requested_by,
                        date: formatDate(request.created_at, lang),
                    })}
                </span>
                <code className="text-xs text-muted-foreground"
                    title={request.proposed_digest}>
                    {request.proposed_digest.slice(0, 12)}
                </code>
            </div>
            {request.justification && <p>{request.justification}</p>}
            {request.status === 'in_review' && (
                <p className="text-muted-foreground">{t(`${PREFIX}.inReview`)}</p>
            )}
            {request.decided_by && request.status !== 'cancelled' && (
                <p className="text-muted-foreground">
                    {t(`${PREFIX}.decidedBy`, {
                        user: request.decided_by, date: formatDate(request.decided_at, lang),
                    })}
                    {request.decision_message ? ` — ${request.decision_message}` : ''}
                </p>
            )}
            {request.status === 'delivered' && (
                <p className="text-muted-foreground">
                    {request.applied_at
                        ? t(`${PREFIX}.applied`, { date: formatDate(request.applied_at, lang) })
                        : t(`${PREFIX}.delivered`, { modes })}
                </p>
            )}
            {request.error && (
                <p className="text-destructive" role="alert">
                    {text(request.error.code, request.error.message, request.error.params)}
                </p>
            )}
            {request.warnings.length > 0 && (
                <ul className="space-y-0.5">
                    {request.warnings.map((w, i) => (
                        <li key={`${w.code}-${i}`} className="flex items-start gap-1 text-amber-700">
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                            {text(w.code, w.message, w.params)}
                        </li>
                    ))}
                </ul>
            )}
            {request.ddl && ['approved', 'delivered', 'failed'].includes(request.status) && (
                <details>
                    <summary className="cursor-pointer text-muted-foreground">
                        {t(`${PREFIX}.statement`)}
                    </summary>
                    <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
                        {request.ddl}
                    </pre>
                </details>
            )}
            {canWrite && isRequester && ['draft', 'in_review'].includes(request.status) && (
                <div className="flex gap-2 pt-1">
                    {request.status === 'draft' && (
                        <Button size="sm" onClick={() => onAction(request, 'submit')}>
                            {t(`${PREFIX}.submit`)}
                        </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => onAction(request, 'cancel')}>
                        {t(`${PREFIX}.cancel`)}
                    </Button>
                </div>
            )}
        </li>
    );
}

/**
 * The definition change requests of a metric view (#1124 phase 3): their
 * status, pre-check warnings and delivery, and a "Propose change" dialog. A
 * request is approved through the workflow approval its approvers get in
 * their notifications.
 */
export default function MetricViewChangeRequests({ assetId, currentDefinition }: {
    assetId: string;
    currentDefinition: string;
}) {
    const { t } = useTranslation('assets');
    const { get, post } = useApi();
    const { hasPermission } = usePermissions();
    const userInfo = useUserStore((s) => s.userInfo);
    const text = useChangeRequestText();
    const canWrite = hasPermission('assets', FeatureAccessLevel.READ_WRITE);
    const [requests, setRequests] = useState<MetricViewChangeRequest[] | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);
    const [dialogOpen, setDialogOpen] = useState(false);
    const me = (userInfo?.email || '').toLowerCase();
    const base = `/api/assets/${assetId}/metric-view/change-requests`;

    const load = useCallback(async () => {
        const res = await get<MetricViewChangeRequest[]>(base);
        if (res.error || !Array.isArray(res.data)) {
            setLoadFailed(true);
            return;
        }
        setLoadFailed(false);
        setRequests(res.data);
    }, [base, get]);

    useEffect(() => { load(); }, [load]);

    const onAction = async (request: MetricViewChangeRequest, action: 'submit' | 'cancel') => {
        setActionError(null);
        const res = await post(`${base}/${request.id}/${action}`, {});
        if (res.error) {
            setActionError(text(res.errorCode, res.error, res.errorParams));
        }
        await load();
    };

    return (
        <section className="mt-4 space-y-2" aria-labelledby="mv-change-requests-title">
            <div className="flex items-center justify-between">
                <h4 id="mv-change-requests-title" className="flex items-center gap-1 text-sm font-medium">
                    <GitPullRequest className="h-4 w-4" aria-hidden />
                    {t(`${PREFIX}.title`)}
                </h4>
                {canWrite && (
                    <Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>
                        {t(`${PREFIX}.propose`)}
                    </Button>
                )}
            </div>
            {actionError && <p className="text-sm text-destructive" role="alert">{actionError}</p>}
            {loadFailed && (
                <p className="text-sm text-muted-foreground">{t(`${PREFIX}.loadError`)}</p>
            )}
            {requests && requests.length === 0 && (
                <p className="text-sm text-muted-foreground">{t(`${PREFIX}.empty`)}</p>
            )}
            {requests && requests.length > 0 && (
                <ul className="space-y-2">
                    {requests.map((r) => (
                        <RequestItem
                            key={r.id}
                            request={r}
                            isRequester={Boolean(me) && r.requested_by.toLowerCase() === me}
                            canWrite={canWrite}
                            onAction={onAction}
                        />
                    ))}
                </ul>
            )}
            <ProposeMetricViewChangeDialog
                assetId={assetId}
                open={dialogOpen}
                onOpenChange={setDialogOpen}
                currentDefinition={currentDefinition}
                onSaved={load}
            />
        </section>
    );
}
