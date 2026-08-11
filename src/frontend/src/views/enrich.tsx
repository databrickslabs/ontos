import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useConceptMode } from '@/components/concepts/mode-switch';

import CoverageMatrix, { type CoverageRow } from '@/components/enrich/coverage-matrix';
import ReviewSuggestionsDialog, {
  type PlaceholderSuggestion,
} from '@/components/enrich/review-suggestions-dialog';
import DeliveryTargets, { type DeliveryTarget } from '@/components/enrich/delivery-targets';
import DeliveryModes from '@/components/enrich/delivery-modes';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import RunConfigDialog from '@/components/term-mapping/run-config-dialog';
import GenerateReviewDialog from '@/components/term-mapping/generate-review-dialog';
import { useUserStore } from '@/stores/user-store';
import type { Run } from '@/types/term-mapping';

// ---------------------------------------------------------------------------
// Enrich — Concept Builder v2 delivery frame (wireframe: enrich.html).
//
// Two lanes:
//   1. Map    — per-scheme coverage matrix + inline "Review suggested matches".
//   2. Deliver — target rows (Tags live / Column descriptions planned /
//                UC Glossary coming) + Direct/Indirect/Manual mode cards
//                (advanced-only).
//
// WHAT IS REAL vs PLACEHOLDER
//   Real (grounded in code):
//     - Tags target is LIVE, backed by the uc_tag_sync job.
//     - Column descriptions = PLANNED (no writer; dbxmetagen can draft).
//     - UC Glossary = COMING (roadmap; UC native glossary GA).
//     - Delivery modes Direct/Indirect/Manual map to Ontos' real Delivery Mode.
//     - The inline reviewer embeds the SHARED term-mapping suggester.
//   Placeholder (no backend read-model yet, clearly flagged in-UI):
//     - Per-scheme coverage counts (concepts/coverage%/products/contracts/
//       assets/suggested).
//     - Per-target "N of M synced · K pending · last run" readouts.
//     - The sample suggestion rows in the review modal (until a run id per
//       scheme is available to hand the shared reviewer real FQNs).
//   NOT claimed: tag-drift detection (Ontos tracks coverage, not platform-side
//     tag changes).
//
// Simple/Advanced view: mirrors the wireframe's shared mode. The integrator
// owns the global mode store; here we read/write the same localStorage key
// (`ontosConceptMode`) as a low-risk, additive interop so advanced-only detail
// (mode cards, provenance) reveals consistently. No shared store is edited.
// ---------------------------------------------------------------------------

type Platform = 'uc' | 'snowflake' | 'bigquery' | 'powerbi';

const PLATFORM_NOUN: Record<Platform, string> = {
  uc: 'Unity Catalog',
  snowflake: 'Snowflake',
  bigquery: 'BigQuery',
  powerbi: 'Power BI',
};

// PLACEHOLDER coverage rows — see coverage-matrix.tsx TODO(cb-v2).
const PLACEHOLDER_ROWS: CoverageRow[] = [
  {
    id: 'finance',
    name: 'Finance',
    concepts: 45,
    coveragePct: 87,
    products: 3,
    contracts: 5,
    assets: 38,
    suggested: 7,
  },
  {
    id: 'logistics',
    name: 'Logistics',
    concepts: 23,
    coveragePct: 65,
    products: 2,
    contracts: 2,
    assets: 13,
    suggested: 5,
  },
];

// PLACEHOLDER suggestion rows for the inline reviewer (inert until live refs).
const PLACEHOLDER_SUGGESTIONS: Record<string, PlaceholderSuggestion[]> = {
  finance: [
    {
      id: 's1',
      concept: 'Payment Term',
      target: 'finance.gold.dim_payment_terms',
      reason: 'exact label match · 45 rows profiled',
      confidence: 'high',
    },
    {
      id: 's2',
      concept: 'Net Revenue',
      target: 'finance.gold.fct_revenue.net_amt',
      reason: 'column comment + synonym hit',
      confidence: 'high',
    },
    {
      id: 's3',
      concept: 'Cost Center',
      target: 'finance.silver.gl_entries.cc_code',
      reason: 'name similarity 0.71',
      confidence: 'medium',
    },
  ],
  logistics: [
    {
      id: 's4',
      concept: 'Shipment',
      target: 'logistics.gold.fct_shipments',
      reason: 'exact label match',
      confidence: 'high',
    },
  ],
};

function InfoDot({ text }: { text: string }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button" aria-label={text} className="text-muted-foreground hover:text-foreground">
            <Info className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[280px]">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function EnrichView() {
  const { t } = useTranslation(['concepts', 'term-mapping', 'common']);
  const { hasPermission } = usePermissions();
  const currentUser = useUserStore((s) => s.userInfo);
  // Term-mapping governs concept-to-asset enrichment writes.
  const canWrite = hasPermission('term-mapping', FeatureAccessLevel.READ_WRITE);

  const [platform, setPlatform] = useState<Platform>('uc');
  const [mode] = useConceptMode();
  const advanced = mode === 'advanced';
  const [reviewScheme, setReviewScheme] = useState<CoverageRow | null>(null);
  // Suggest matches reuses the full term-mapping run dialog, then the shared
  // review dialog (which spawns the Review Board request and navigates there).
  const [runConfigOpen, setRunConfigOpen] = useState(false);
  const [reviewRun, setReviewRun] = useState<Run | null>(null);

  // Real per-scheme coverage from GET /api/knowledge/coverage. Falls back to the
  // placeholder rows only if the endpoint is unavailable, so the frame is never
  // empty during review.
  const [coverageRows, setCoverageRows] = useState<CoverageRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/knowledge/coverage');
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled || !Array.isArray(data?.schemes)) return;
        const rows: CoverageRow[] = data.schemes.map((s: any) => ({
          id: s.scheme,
          name: s.label || s.scheme,
          concepts: s.concepts ?? 0,
          coveragePct: s.coverage_pct ?? 0,
          products: s.products ?? 0,
          contracts: s.contracts ?? 0,
          assets: s.assets ?? 0,
          suggested: s.suggested ?? 0,
        }));
        setCoverageRows(rows);
      } catch {
        /* endpoint unavailable — keep placeholder rows */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = coverageRows ?? PLACEHOLDER_ROWS;

  // Real tag-delivery stats (eligible links + pending since last sync + last
  // run). Null until loaded / when the endpoint is unavailable.
  interface TagPendingItem {
    entity_id: string;
    entity_type: string;
    iri: string;
    label: string | null;
    created_at: string | null;
  }
  interface TagStats {
    eligible: number;
    pending: number;
    synced: number;
    last_run_state: string | null;
    last_run_at: string | null;
    job_installed: boolean;
    pending_items: TagPendingItem[];
  }
  const [tagStats, setTagStats] = useState<TagStats | null>(null);
  const [pendingOpen, setPendingOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/knowledge/tag-delivery-stats');
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setTagStats(data);
      } catch {
        /* endpoint unavailable — Tags row omits the coverage readout */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const platformNoun = PLATFORM_NOUN[platform];

  const targets = useMemo<DeliveryTarget[]>(
    () => [
      {
        id: 'tags',
        name: t('enrich.deliver.tags.name', 'Tags'),
        status: 'live',
        description: t(
          'enrich.deliver.tags.desc',
          'Key/value governance tags on tables and columns. Drives discovery and access policy.',
        ),
        via: t('enrich.deliver.tags.via', 'via uc_tag_sync'),
        // Real coverage from /api/knowledge/tag-delivery-stats: eligible links,
        // pending = created since last successful sync. Omitted until loaded.
        coverage: tagStats
          ? {
              synced: tagStats.synced,
              total: tagStats.eligible,
              pending: tagStats.pending,
              lastRun: tagStats.last_run_at
                ? new Date(tagStats.last_run_at).toLocaleString()
                : undefined,
            }
          : undefined,
        note: t(
          'enrich.deliver.tags.note',
          'Tag delivery runs through the shared uc_tag_sync job, which also covers other aspects beyond semantic assignment. Configure its scope and schedule in Settings > Jobs.',
        ),
        actionable: platform === 'uc',
        // Shared job — manage scope/schedule in Settings, not from here.
        manageHref: '/settings/jobs',
        // Make the pending count clickable to list the actual pending changes.
        onShowPending:
          tagStats && tagStats.pending > 0 ? () => setPendingOpen(true) : undefined,
      },
      {
        id: 'descriptions',
        name: t('enrich.deliver.desc.name', 'Column descriptions'),
        status: 'planned',
        description: t(
          'enrich.deliver.desc.desc',
          'Plain-language meaning on columns. What Genie and search read to answer accurately.',
        ),
        assist: t('enrich.deliver.desc.assist', 'dbxmetagen can draft these'),
        actionable: false,
      },
      {
        id: 'glossary',
        name: t('enrich.deliver.glossary.name', 'UC Glossary'),
        status: 'coming',
        description: t(
          'enrich.deliver.glossary.desc',
          'The governed business glossary in the platform itself.',
        ),
        note: t(
          'enrich.deliver.glossary.note',
          "Syncs concepts to Unity Catalog's native business glossary, the governed layer Genie Ontology reads from. Arrives at UC Glossary GA.",
        ),
        actionable: false,
      },
    ],
    [t, platform, tagStats],
  );

  return (
    <div className="max-w-[1180px] space-y-6 pt-3">
      {/* Subtitle (title + Simple/Advanced switch live in the section tab row). */}
      <p className="text-sm text-muted-foreground">
        {t('enrich.subtitle', 'Map your concepts to assets, then deliver governed metadata onto the platform.')}
      </p>

      {/* Platform selector */}
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="text-xs font-medium text-muted-foreground">
          {t('enrich.deliverTo', 'Deliver to')}
        </span>
        <Select value={platform} onValueChange={(v) => setPlatform(v as Platform)}>
          <SelectTrigger className="h-9 w-[240px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="uc">Databricks, Unity Catalog</SelectItem>
            <SelectItem value="snowflake">Snowflake</SelectItem>
            <SelectItem value="bigquery">BigQuery</SelectItem>
            <SelectItem value="powerbi">Power BI</SelectItem>
          </SelectContent>
        </Select>
        <InfoDot
          text={t(
            'enrich.platformTip',
            'Delivery platforms come from your configured connections in Settings. Unity Catalog is the default. The delivery targets below adapt to the platform you pick.',
          )}
        />
        <a
          href="/settings/connectors"
          className="ml-auto text-xs text-sky-700 hover:underline dark:text-sky-400"
        >
          {t('enrich.manageConnections', 'Manage connections ↗')}
        </a>
      </div>

      {/* LANE 1 — MAP */}
      <section className="space-y-2">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            1
          </span>
          <h3 className="text-base font-semibold">{t('enrich.map.title', 'Map')}</h3>
          <div className="ml-auto flex items-center gap-2">
            {/* Suggest matches: opens the full run-config dialog (engine, target,
                contexts live there), runs the suggester, and routes candidates
                to the Review Board. Requires write access on term-mapping. */}
            <Button
              variant="outline"
              size="sm"
              disabled={!canWrite}
              onClick={() => setRunConfigOpen(true)}
            >
              {t('enrich.map.suggest', 'Suggest matches')}
            </Button>
          </div>
        </div>
        <p className="ml-8 text-sm text-muted-foreground">
          {t(
            'enrich.map.desc',
            'Link a concept straight to a {{platform}} Asset (the default path, no product or contract needed), then optionally add links to data products and data contracts. All three are independent.',
            { platform: platformNoun },
          )}
        </p>
        <div className="ml-8">
          <CoverageMatrix
            rows={rows}
            platformNoun={platformNoun}
            canWrite={canWrite}
            isLive={coverageRows !== null}
            onReview={(row) => setReviewScheme(row)}
          />
        </div>
      </section>

      {/* LANE 2 — DELIVER */}
      <section className="space-y-2">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            2
          </span>
          <h3 className="text-base font-semibold">{t('enrich.deliver.title', 'Deliver')}</h3>
          <InfoDot
            text={t(
              'enrich.deliver.tip',
              "Deliver writes your governed metadata onto the platform. Downstream tools (Genie, search, agents) read it from there. Tags = policy & discovery. Descriptions = what Genie reads. Glossary = the governed business layer.",
            )}
          />
        </div>
        <p className="ml-8 text-sm text-muted-foreground">
          {t('enrich.deliver.desc', 'Write governed metadata onto the mapped {{platform}} assets.', {
            platform: platformNoun,
          })}
        </p>
        <div className="ml-8 space-y-3">
          {/* Delivery-mode cards are advanced-only per the wireframe. */}
          {advanced && (
            <DeliveryModes activeModes={['direct', 'indirect']} settingsHref="/settings/delivery" />
          )}
          <DeliveryTargets targets={targets} advanced={advanced} canWrite={canWrite} />
        </div>
      </section>

      {/* Inline "Review suggested matches" — modal, no route change. */}
      <ReviewSuggestionsDialog
        open={reviewScheme !== null}
        onOpenChange={(open) => {
          if (!open) setReviewScheme(null);
        }}
        schemeName={reviewScheme?.name ?? ''}
        placeholders={reviewScheme ? PLACEHOLDER_SUGGESTIONS[reviewScheme.id] ?? [] : []}
        driftCount={reviewScheme ? Math.min(3, reviewScheme.suggested) : 0}
        reviewBoardHref="/data-asset-reviews"
      />

      {/* Suggest matches — reuse the full term-mapping run dialog. On a
          completed run, open the shared review dialog which spawns the Review
          Board request and navigates there. */}
      <RunConfigDialog
        isOpen={runConfigOpen}
        onOpenChange={setRunConfigOpen}
        onCreated={(run) => {
          setRunConfigOpen(false);
          setReviewRun(run);
        }}
      />
      <GenerateReviewDialog
        isOpen={reviewRun !== null}
        onOpenChange={(open) => {
          if (!open) setReviewRun(null);
        }}
        run={reviewRun}
        currentUserEmail={currentUser?.email ?? undefined}
      />

      {/* Pending tag changes — the actual list behind the "N pending" count. */}
      <Dialog open={pendingOpen} onOpenChange={setPendingOpen}>
        <DialogContent className="sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle>{t('enrich.deliver.pendingTitle', 'Pending tag changes')}</DialogTitle>
            <DialogDescription>
              {t(
                'enrich.deliver.pendingSubtitle',
                'Concept-to-asset links created since the last successful tag sync. A re-run of uc_tag_sync would deliver these.',
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[420px] overflow-auto divide-y">
            {(tagStats?.pending_items ?? []).length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('enrich.deliver.pendingEmpty', 'Nothing pending.')}
              </p>
            ) : (
              (tagStats?.pending_items ?? []).map((it) => (
                <div key={`${it.entity_type}:${it.entity_id}:${it.iri}`} className="flex items-center gap-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-xs truncate" title={it.entity_id}>{it.entity_id}</div>
                    <div className="text-xs text-muted-foreground truncate" title={it.iri}>
                      {t('enrich.deliver.pendingLinkedTo', 'linked to')} {it.label || it.iri}
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0 text-[10px]">{it.entity_type}</Badge>
                  {it.created_at && (
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {new Date(it.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
