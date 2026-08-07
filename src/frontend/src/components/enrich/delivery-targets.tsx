import { useTranslation } from 'react-i18next';
import { Info, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

// ---------------------------------------------------------------------------
// Deliver lane — target rows.
//
// Grounded in the real backend:
//   - Tags: LIVE. Written to Unity Catalog governed tags by the `uc_tag_sync`
//     job (src/backend/src/workflows/uc_tag_sync/). Prefix `x_ontos_`, runs on
//     a 4h schedule + Manual. Overwrite semantics: Ontos-managed tags are
//     updated in place; manual tags are left untouched (per the job's design).
//   - Column descriptions: PLANNED. No sync job ships for this today. dbxmetagen
//     can draft the text (external assist), but Ontos does not write column
//     comments yet.
//   - UC Glossary: COMING (roadmap). Depends on UC's native business-glossary
//     GA; no Ontos writer exists.
//
// NOT claimed anywhere: tag-drift detection. Ontos tracks its own coverage
// (links written vs pending), NOT whether a synced tag was later changed on the
// platform. The Tags info tooltip states this explicitly.
//
// The "N of M synced · K pending · last run …" readout is a PLACEHOLDER until a
// coverage/last-run read-model exists.
// TODO(cb-v2): needs a delivery coverage read-model — {synced, pending,
//   lastRunAt} per target, sourced from the uc_tag_sync job's last run. No
//   endpoint returns this today.
// ---------------------------------------------------------------------------

export type TargetStatus = 'live' | 'planned' | 'coming';

export interface DeliveryTarget {
  id: string;
  name: string;
  status: TargetStatus;
  /** One-line description of what the target writes. */
  description: string;
  /** Advanced-only provenance note (e.g. "via uc_tag_sync"). */
  via?: string;
  /** External assist note (e.g. dbxmetagen). */
  assist?: string;
  /** Coverage readout — PLACEHOLDER metrics. Omit when nothing synced. */
  coverage?: { synced: number; total: number; pending: number; lastRun?: string };
  /** Extra tooltip (e.g. the tag-drift clarification). */
  note?: string;
  /** Whether Configure/Sync actions are enabled for this target. */
  actionable?: boolean;
  onConfigure?: () => void;
  onSync?: () => void;
}

const STATUS_LABEL: Record<TargetStatus, string> = {
  live: 'Live',
  planned: 'Planned',
  coming: 'Coming',
};

const STATUS_CLASS: Record<TargetStatus, string> = {
  live: 'border-emerald-300 bg-emerald-100/60 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200',
  planned:
    'border-amber-300 bg-amber-100/60 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200',
  coming: 'border-border bg-secondary text-muted-foreground',
};

interface Props {
  targets: DeliveryTarget[];
  /** Advanced view reveals provenance ("via uc_tag_sync") + drift tooltip. */
  advanced?: boolean;
  canWrite?: boolean;
}

export default function DeliveryTargets({ targets, advanced = false, canWrite = true }: Props) {
  const { t } = useTranslation(['concepts', 'common']);

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      {targets.map((target) => {
        const synced = !!target.coverage;
        return (
          <div
            key={target.id}
            className={`flex items-center gap-3 border-b px-4 py-3 last:border-b-0 ${
              target.status !== 'live' ? 'bg-muted/40' : ''
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">{target.name}</span>
                <Badge variant="outline" className={STATUS_CLASS[target.status]}>
                  {t(`enrich.deliver.status.${target.status}`, STATUS_LABEL[target.status])}
                </Badge>
                {target.assist && (
                  <span className="inline-flex items-center gap-1 rounded bg-sky-100/60 px-1.5 py-0.5 text-[11px] font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                    <Sparkles className="h-3 w-3" />
                    {target.assist}
                  </span>
                )}
                {target.note && advanced && (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button type="button" aria-label="about" className="text-muted-foreground">
                          <Info className="h-3.5 w-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[280px]">{target.note}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {target.description}
                {advanced && target.via && (
                  <span className="opacity-80"> · {target.via}</span>
                )}
              </p>
              <p className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${synced ? 'bg-emerald-500' : 'bg-border'}`}
                />
                {synced && target.coverage ? (
                  t(
                    'enrich.deliver.coverage',
                    '{{synced}} of {{total}} synced · {{pending}} pending{{run}}',
                    {
                      synced: target.coverage.synced,
                      total: target.coverage.total,
                      pending: target.coverage.pending,
                      run: target.coverage.lastRun ? ` · last run ${target.coverage.lastRun}` : '',
                    },
                  )
                ) : (
                  t('enrich.deliver.notSynced', 'Not synced yet')
                )}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!target.actionable || !canWrite}
                onClick={target.onConfigure}
              >
                {t('enrich.deliver.configure', 'Configure')}
              </Button>
              {target.status === 'live' && (
                <Button
                  size="sm"
                  disabled={!target.actionable || !canWrite}
                  onClick={target.onSync}
                >
                  {t('enrich.deliver.syncNow', 'Sync now')}
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
