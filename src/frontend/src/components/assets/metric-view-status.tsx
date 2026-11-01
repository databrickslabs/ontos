import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, ExternalLink, HelpCircle, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type {
    MetricViewBaseline,
    MetricViewDrift,
    MetricViewRefresh,
} from '@/types/data-asset-review';

/** A date from the API in the user's language; the raw text when it isn't a date. */
function formatDate(value: string | null | undefined, language: string): string {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(language);
}

function DriftBadge({ drift }: { drift: MetricViewDrift }) {
    const { t } = useTranslation('assets');
    const label = t(`detail.metricView.state.drift.${drift.state}`);
    if (drift.state === 'in_sync') {
        return (
            <Badge variant="secondary" className="gap-1">
                <CheckCircle2 className="h-3 w-3 text-green-600" aria-hidden />
                {label}
            </Badge>
        );
    }
    if (drift.state === 'drifted') {
        return (
            <Badge variant="destructive" className="gap-1">
                <AlertTriangle className="h-3 w-3" aria-hidden />
                {label}
            </Badge>
        );
    }
    return (
        <Badge variant="outline" className="gap-1">
            <HelpCircle className="h-3 w-3" aria-hidden />
            {label}
        </Badge>
    );
}

function BaselineText({ baseline, language }: {
    baseline: MetricViewBaseline | null | undefined;
    language: string;
}) {
    const { t } = useTranslation('assets');
    if (!baseline) {
        return <span>{t('detail.metricView.state.baseline.none')}</span>;
    }
    const text = baseline.approved_at
        ? t('detail.metricView.state.baseline.approved', {
            date: formatDate(baseline.approved_at, language),
        })
        : t('detail.metricView.state.baseline.recorded', {
            date: formatDate(baseline.recorded_at, language),
        });
    return (
        <span>
            {text}{' '}
            <code className="text-xs" title={baseline.digest}>
                {t('detail.metricView.state.baseline.digest', {
                    digest: baseline.digest.slice(0, 12),
                })}
            </code>
        </span>
    );
}

function RefreshSection({ refresh, language }: {
    refresh: MetricViewRefresh;
    language: string;
}) {
    const { t } = useTranslation('assets');
    const status = t(`detail.metricView.state.refresh.${refresh.status}`);
    return (
        <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{t('detail.metricView.state.refresh.label')}</span>
                <Badge
                    variant={refresh.status === 'failed' ? 'destructive' : 'secondary'}
                    className="gap-1"
                >
                    {refresh.status === 'running' && (
                        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                    )}
                    {status}
                </Badge>
                {refresh.latest_update_at && (
                    <span className="text-muted-foreground">
                        {t('detail.metricView.state.refresh.lastStarted', {
                            date: formatDate(refresh.latest_update_at, language),
                        })}
                    </span>
                )}
                {refresh.pipeline_url && (
                    <a
                        href={refresh.pipeline_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                        {t('detail.metricView.state.refresh.openPipeline')}
                        <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                )}
            </div>
            <p className="text-muted-foreground">
                {refresh.schedule
                    ? t('detail.metricView.state.refresh.schedule', { schedule: refresh.schedule })
                    : t('detail.metricView.state.refresh.noSchedule')}
            </p>
            {refresh.status === 'unknown' && (
                <p className="text-muted-foreground">
                    {t('detail.metricView.state.refresh.notAvailable')}
                </p>
            )}
            {refresh.status === 'failed' && (
                <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle>{t('detail.metricView.state.refresh.failedTitle')}</AlertTitle>
                    <AlertDescription>
                        {t('detail.metricView.state.refresh.failedHint')}
                    </AlertDescription>
                </Alert>
            )}
        </div>
    );
}

/**
 * A metric view's baseline, its drift state and, when it is materialized, its
 * refresh state, as `GET /api/assets/{id}/metric-view` returns them. Renders
 * nothing when the answer carries none of them (an older backend).
 */
export default function MetricViewStatus({ baseline, drift, refresh }: {
    baseline?: MetricViewBaseline | null;
    drift?: MetricViewDrift | null;
    refresh?: MetricViewRefresh | null;
}) {
    const { t, i18n } = useTranslation('assets');
    if (!drift && !refresh) return null;
    const language = i18n.language;
    return (
        <div
            className="mb-4 space-y-3 rounded-md border p-3 text-sm"
            data-testid="metric-view-status"
        >
            {drift && (
                <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">
                            {t('detail.metricView.state.drift.label')}
                        </span>
                        <DriftBadge drift={drift} />
                        {drift.last_checked_at && (
                            <span className="text-muted-foreground">
                                {t('detail.metricView.state.lastChecked', {
                                    date: formatDate(drift.last_checked_at, language),
                                })}
                            </span>
                        )}
                    </div>
                    <p className="text-muted-foreground">
                        <BaselineText baseline={baseline} language={language} />
                    </p>
                    {drift.state !== 'in_sync' && (
                        <p className="text-muted-foreground">
                            {t(`detail.metricView.state.drift.${drift.state}Hint`)}
                        </p>
                    )}
                </div>
            )}
            {refresh && <RefreshSection refresh={refresh} language={language} />}
        </div>
    );
}
