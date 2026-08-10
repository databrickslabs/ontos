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
import { useConceptMode, ConceptModeSwitch } from '@/components/concepts/mode-switch';

import CoverageMatrix, { type CoverageRow } from '@/components/enrich/coverage-matrix';
import ReviewSuggestionsDialog, {
  type PlaceholderSuggestion,
} from '@/components/enrich/review-suggestions-dialog';
import DeliveryTargets, { type DeliveryTarget } from '@/components/enrich/delivery-targets';
import DeliveryModes from '@/components/enrich/delivery-modes';

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
  // Term-mapping governs concept-to-asset enrichment writes.
  const canWrite = hasPermission('term-mapping', FeatureAccessLevel.READ_WRITE);

  const [platform, setPlatform] = useState<Platform>('uc');
  const [mode] = useConceptMode();
  const advanced = mode === 'advanced';
  const [reviewScheme, setReviewScheme] = useState<CoverageRow | null>(null);

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
        // PLACEHOLDER coverage — see delivery-targets.tsx TODO(cb-v2).
        coverage: { synced: 82, total: 100, pending: 18, lastRun: '3 hours ago' },
        note: t(
          'enrich.deliver.tags.note',
          'Planned: live tag-drift detection. Today Ontos tracks its own coverage (links written vs pending), not whether a synced tag was later changed on the platform.',
        ),
        actionable: platform === 'uc',
        // The uc_tag_sync trigger from Ontos is not wired yet — show the actions
        // disabled with a reason rather than clickable no-ops.
        // TODO(cb-v2): wire Configure (tag template/trigger) + Sync now
        // (run uc_tag_sync job) and drop comingSoon.
        comingSoon: true,
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
    [t, platform],
  );

  return (
    <div className="max-w-[1180px] space-y-6">
      {/* Subtitle + Simple/Advanced switch (title is in section tab) */}
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          {t('enrich.subtitle', 'Map your concepts to assets, then deliver governed metadata onto the platform.')}
        </p>
        <ConceptModeSwitch tipLeft />
      </div>

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
            {advanced && (
              <div className="inline-flex items-center gap-1 rounded-lg bg-muted p-1" aria-label="Match engine">
                <button type="button" className="rounded-md bg-background px-2.5 py-1 text-xs font-medium shadow">
                  {t('enrich.map.engine.heuristic', 'Heuristic')}
                </button>
                <button type="button" className="rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  {t('enrich.map.engine.llm', 'LLM judge')}
                </button>
              </div>
            )}
            {/* Suggest matches is not wired to the suggester run yet. Show it
                disabled with a clear reason rather than an inert button.
                TODO(cb-v2): trigger the term-mapping suggester and route results
                to the shared Review Board. */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span tabIndex={0}>
                    <Button variant="outline" size="sm" disabled>
                      {t('enrich.map.suggest', 'Suggest matches')}
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-[260px]">
                  {t(
                    'enrich.map.suggestSoon',
                    'Coming soon: runs the match suggester and sends candidates to the Review Board.',
                  )}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
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
    </div>
  );
}
