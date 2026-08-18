import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
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
import RunResultDialog from '@/components/enrich/run-result-dialog';
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

function readableName(s: string): string {
  // Extract the last segment after /, #, or .
  const lastSlash = s.lastIndexOf('/');
  const lastHash = s.lastIndexOf('#');
  const lastDot = s.lastIndexOf('.');
  const lastIdx = Math.max(lastSlash, lastHash, lastDot);
  return lastIdx >= 0 ? s.substring(lastIdx + 1) : s;
}

export default function EnrichView() {
  const { t } = useTranslation(['concepts', 'term-mapping', 'common']);
  const navigate = useNavigate();

  // Navigate to the physical asset a pending tag will land on. Mirrors the
  // linked-objects-panel routing: registered Ontos asset -> Asset Explorer;
  // raw UC object -> catalog-commander deep-link.
  const goToPendingAsset = (it: {
    entity_type: string;
    entity_id: string;
  }) => {
    if (it.entity_type === 'asset') {
      navigate(`/assets/${it.entity_id}`);
      return;
    }
    const parts = String(it.entity_id).split('.');
    let tableParam: string | null = null;
    if (it.entity_type === 'uc_table' && parts.length >= 3) tableParam = it.entity_id;
    else if (it.entity_type === 'uc_column' && parts.length >= 4) tableParam = parts.slice(0, 3).join('.');
    navigate(tableParam ? `/catalog-commander?table=${encodeURIComponent(tableParam)}` : '/catalog-commander');
  };
  const { hasPermission } = usePermissions();
  const currentUser = useUserStore((s) => s.userInfo);
  // Term-mapping governs concept-to-asset enrichment writes.
  const canWrite = hasPermission('term-mapping', FeatureAccessLevel.READ_WRITE);

  const [platform, setPlatform] = useState<Platform>('uc');
  const [mode] = useConceptMode();
  const advanced = mode === 'advanced';
  const [reviewScheme, setReviewScheme] = useState<CoverageRow | null>(null);
  // Live pending suggestions for the scheme being reviewed, fetched from
  // GET /api/knowledge/coverage/{scheme}/pending-suggestions. When present the
  // ReviewSuggestionsDialog runs its live accept-and-apply path; empty/undefined
  // falls back to the inert placeholder rows.
  interface SchemePendingSuggestion {
    id: string;
    run_id: string;
    source_entity_type: string;
    source_entity_id: string;
    source_label: string | null;
    target_concept_iri: string;
    target_concept_label: string | null;
    confidence: number;
    reason: string;
  }
  const [reviewSuggestions, setReviewSuggestions] = useState<SchemePendingSuggestion[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  // Suggest matches reuses the full term-mapping run dialog. On a completed run
  // we land on a RESULT SUMMARY (not the delegate form): from there the primary
  // action reviews the matches in place; requesting a Review-Board handoff is a
  // secondary, opt-in action. reviewRun drives that opt-in delegate dialog.
  const [runConfigOpen, setRunConfigOpen] = useState(false);
  const [reviewRun, setReviewRun] = useState<Run | null>(null);
  // Result of the just-completed run: the run + its live suggestion refs for the
  // in-place reviewer. Null when no run summary is showing.
  const [runResult, setRunResult] = useState<
    { run: Run; refs: { fqn: string }[] } | null
  >(null);
  const [runResultLoading, setRunResultLoading] = useState(false);

  // Real per-scheme coverage from GET /api/knowledge/coverage. Falls back to the
  // placeholder rows only if the endpoint is unavailable, so the frame is never
  // empty during review.
  const [coverageRows, setCoverageRows] = useState<CoverageRow[] | null>(null);
  const fetchCoverage = useCallback(async () => {
    try {
      const res = await fetch('/api/knowledge/coverage');
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data?.schemes)) return;
      const rows: CoverageRow[] = data.schemes.map((s: any) => ({
        id: s.scheme,
        name: s.label || s.scheme,
        concepts: s.concepts ?? 0,
        coveragePct: s.coverage_pct ?? 0,
        products: s.products ?? 0,
        contracts: s.contracts ?? 0,
        assets: s.assets ?? 0,
        suggested: s.suggested ?? 0,
        lastRun: s.last_run_at ?? null,
      }));
      setCoverageRows(rows);
    } catch {
      /* endpoint unavailable — keep placeholder rows */
    }
  }, []);
  useEffect(() => {
    void fetchCoverage();
  }, [fetchCoverage]);

  // Per-scheme "Last run" now lives as a column in the coverage matrix (driven
  // by coverage.last_run_at), so the separate recent-runs list was removed.

  const rows = coverageRows ?? PLACEHOLDER_ROWS;

  // Real tag-delivery stats (eligible links + pending since last sync + last
  // run). Null until loaded / when the endpoint is unavailable.
  interface TagPendingItem {
    entity_id: string;
    entity_type: string;
    iri: string;
    label: string | null;
    created_at: string | null;
    scheme?: string | null;
    scheme_label?: string | null;
    asset_name?: string | null;
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
  const fetchTagStats = useCallback(async () => {
    try {
      const res = await fetch('/api/knowledge/tag-delivery-stats');
      if (!res.ok) return;
      const data = await res.json();
      setTagStats(data);
    } catch {
      /* endpoint unavailable — Tags row omits the coverage readout */
    }
  }, []);
  useEffect(() => {
    void fetchTagStats();
  }, [fetchTagStats]);

  // Load a scheme's live pending suggestions when the Review dialog opens.
  const openReview = useCallback(async (row: CoverageRow) => {
    setReviewScheme(row);
    setReviewSuggestions([]);
    setReviewLoading(true);
    try {
      const res = await fetch(
        `/api/knowledge/coverage/${encodeURIComponent(row.id)}/pending-suggestions`,
      );
      const data = res.ok ? await res.json() : [];
      setReviewSuggestions(Array.isArray(data) ? data : []);
    } catch {
      setReviewSuggestions([]);
    } finally {
      setReviewLoading(false);
    }
  }, []);

  // Accept every pending suggestion for the reviewed scheme, then materialise
  // the links, then refresh coverage + tag stats so the table, the Deliver tag
  // counter, and the Last-run column update without a manual page refresh.
  const acceptAndApplyReview = useCallback(async () => {
    // Group suggestion ids by run (they usually share one run, but be safe).
    const byRun = new Map<string, string[]>();
    for (const s of reviewSuggestions) {
      const arr = byRun.get(s.run_id) ?? [];
      arr.push(s.id);
      byRun.set(s.run_id, arr);
    }
    for (const [runId, ids] of byRun.entries()) {
      const decisionsRes = await fetch(
        `/api/term-mappings/runs/${runId}/decisions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            decisions: ids.map((id) => ({ id, decision: 'accept' })),
          }),
        },
      );
      if (!decisionsRes.ok) {
        throw new Error(`decisions failed for run ${runId}: ${decisionsRes.status}`);
      }
      const applyRes = await fetch(`/api/term-mappings/runs/${runId}/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!applyRes.ok) {
        throw new Error(`apply failed for run ${runId}: ${applyRes.status}`);
      }
    }
    // Refresh the surfaces that reflect the applied links.
    await Promise.all([fetchCoverage(), fetchTagStats()]);
  }, [reviewSuggestions, fetchCoverage, fetchTagStats]);

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
        coverage: tagStats && tagStats.job_installed
          ? {
              synced: tagStats.synced,
              total: tagStats.eligible,
              pending: tagStats.pending,
              lastRun: tagStats.last_run_at
                ? new Date(tagStats.last_run_at).toLocaleString()
                : undefined,
            }
          : undefined,
        note: tagStats && !tagStats.job_installed
          ? t(
              'enrich.deliver.tags.notConfigured',
              'Tag delivery is not configured. The uc_tag_sync job needs to be installed in Settings > Jobs to activate this.',
            )
          : t(
              'enrich.deliver.tags.note',
              'Tag delivery runs through the shared uc_tag_sync job, which also covers other aspects beyond semantic assignment. Configure its scope and schedule in Settings > Jobs.',
            ),
        actionable: platform === 'uc' && (!tagStats || tagStats.job_installed),
        // Shared job — manage scope/schedule in Settings, not from here.
        manageHref: '/settings/jobs',
        // Make the pending count clickable to list the actual pending changes.
        onShowPending:
          tagStats && tagStats.pending > 0 && tagStats.job_installed ? () => setPendingOpen(true) : undefined,
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
    [t, platform, tagStats?.job_installed, tagStats?.synced, tagStats?.eligible, tagStats?.pending, tagStats?.last_run_at],
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
            onReview={(row) => void openReview(row)}
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
          if (!open) {
            setReviewScheme(null);
            setReviewSuggestions([]);
          }
        }}
        schemeName={reviewScheme?.name ?? ''}
        liveSuggestions={reviewSuggestions.map((s) => ({
          id: s.id,
          runId: s.run_id,
          concept: s.target_concept_label || readableName(s.target_concept_iri),
          target: s.source_label || s.source_entity_id,
          reason: s.reason,
          confidence: s.confidence,
        }))}
        loading={reviewLoading}
        canWrite={canWrite}
        onAcceptAndApplyAll={acceptAndApplyReview}
        placeholders={reviewScheme ? PLACEHOLDER_SUGGESTIONS[reviewScheme.id] ?? [] : []}
        driftCount={reviewScheme ? Math.min(3, reviewScheme.suggested) : 0}
        reviewBoardHref="/data-asset-reviews"
      />

      {/* Suggest matches — reuse the full term-mapping run dialog. On a
          completed run we land on a RESULT SUMMARY (RunResultDialog): the user
          sees what was found and chooses to review the matches in place. The
          Review-Board handoff (GenerateReviewDialog) is a secondary opt-in from
          there, not the forced next step. */}
      <RunConfigDialog
        isOpen={runConfigOpen}
        onOpenChange={setRunConfigOpen}
        onCreated={async (run) => {
          setRunConfigOpen(false);
          // Refresh the coverage matrix so the per-scheme suggested count, the
          // Review button, and the Last run column reflect the new run.
          void fetchCoverage();
          // Fetch the run's suggestions so the in-place reviewer has live refs.
          setRunResultLoading(true);
          setRunResult({ run, refs: [] });
          try {
            const res = await fetch(
              `/api/term-mappings/runs/${run.id}/suggestions?status=pending`,
            );
            const data = res.ok ? await res.json() : [];
            const refs = (Array.isArray(data) ? data : []).map((s: { id: string }) => ({
              fqn: `term-mapping://${run.id}/${s.id}`,
            }));
            setRunResult({ run, refs });
          } catch {
            setRunResult({ run, refs: [] });
          } finally {
            setRunResultLoading(false);
          }
        }}
      />
      <RunResultDialog
        open={runResult !== null}
        onOpenChange={(open) => {
          if (!open) setRunResult(null);
        }}
        run={runResult?.run ?? null}
        suggestionRefs={runResult?.refs ?? []}
        loading={runResultLoading}
        onRequestReview={() => {
          const r = runResult?.run ?? null;
          setRunResult(null);
          setReviewRun(r);
        }}
      />
      {/* Delegate-to-reviewer handoff — opt-in, spawns a Review-Board request. */}
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
                  <div className="min-w-0 flex-1 space-y-0.5">
                    {/* Concept (linkable) + its scheme (linkable). No raw urn shown. */}
                    <div className="truncate">
                      <button
                        type="button"
                        className="font-medium text-primary hover:underline"
                        title={it.iri}
                        onClick={() => navigate(`/concepts/browser/${encodeURIComponent(it.iri)}`)}
                      >
                        {it.label || readableName(it.iri)}
                      </button>
                      {it.scheme && (
                        <>
                          <span className="text-muted-foreground"> {t('enrich.deliver.pendingInScheme', 'in')} </span>
                          <button
                            type="button"
                            className="text-primary hover:underline"
                            title={it.scheme}
                            onClick={() => navigate(`/concepts/browser?source=${encodeURIComponent(it.scheme!)}`)}
                          >
                            {it.scheme_label || readableName(it.scheme)}
                          </button>
                        </>
                      )}
                    </div>
                    {/* Physical asset the tag will be applied to (linkable). */}
                    <div className="text-xs text-muted-foreground truncate">
                      {t('enrich.deliver.pendingAppliesTo', 'applies to')}{' '}
                      <button
                        type="button"
                        className="text-primary hover:underline"
                        title={it.entity_id}
                        onClick={() => goToPendingAsset(it)}
                      >
                        {it.asset_name || readableName(it.entity_id)}
                      </button>
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
