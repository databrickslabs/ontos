import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

// ---------------------------------------------------------------------------
// Map lane — per-concept-scheme coverage matrix.
//
// Columns: Concept scheme | Concepts | Coverage% | Products | Contracts |
//          Assets | Suggested | (Review action).
//
// IMPORTANT (data provenance):
//   Ontos does NOT currently expose a per-scheme coverage read-model. The
//   counts below (concepts / coverage% / products / contracts / assets /
//   suggested) are structural PLACEHOLDERS so the frame is reviewable. They
//   are clearly flagged as such in the UI (a "sample data" note) and must be
//   replaced by a real aggregation endpoint before this ships.
//
// TODO(cb-v2): needs coverage read-model endpoint — a per-concept-scheme
//   aggregation returning {concepts, coveredWithAnyLink, productLinks,
//   contractLinks, assetLinks, pendingSuggestions}. No such endpoint exists in
//   the backend today (term-mapping runs expose run-level stats only, not
//   per-scheme coverage). Do NOT invent one client-side.
// ---------------------------------------------------------------------------

export interface CoverageRow {
  /** Concept scheme (collection) id — used as a key only. */
  id: string;
  /** Scheme display name. */
  name: string;
  /** Total concepts in the scheme. */
  concepts: number;
  /** Share of concepts with >= 1 link, 0..100. */
  coveragePct: number;
  /** Concepts linked to data products (optional extra link). */
  products: number;
  /** Concepts linked to data contracts (optional extra link). */
  contracts: number;
  /** Concepts linked directly to a platform asset (the default path). */
  assets: number;
  /** Pending suggested matches awaiting review. */
  suggested: number;
}

interface Props {
  rows: CoverageRow[];
  platformNoun: string;
  /** Opens the inline "Review suggested matches" modal for a scheme. */
  onReview: (row: CoverageRow) => void;
  /** Whether the current user may act on suggestions. */
  canWrite?: boolean;
}

function InfoDot({ text }: { text: string }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground"
            aria-label={text}
          >
            <Info className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[260px]">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function CoverageMatrix({
  rows,
  platformNoun,
  onReview,
  canWrite = true,
}: Props) {
  const { t } = useTranslation(['concepts', 'common']);

  const totals = rows.reduce(
    (acc, r) => {
      acc.concepts += r.concepts;
      acc.products += r.products;
      acc.contracts += r.contracts;
      acc.assets += r.assets;
      acc.suggested += r.suggested;
      acc.covered += Math.round((r.coveragePct / 100) * r.concepts);
      return acc;
    },
    { concepts: 0, products: 0, contracts: 0, assets: 0, suggested: 0, covered: 0 },
  );
  const totalPct = totals.concepts
    ? Math.round((totals.covered / totals.concepts) * 100)
    : 0;
  const unmapped = totals.concepts - totals.covered;

  const gridCols =
    'grid grid-cols-[1.4fr_0.7fr_1.4fr_0.8fr_0.8fr_0.8fr_0.9fr_90px] gap-3 items-center';

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-lg border bg-card">
        {/* header */}
        <div
          className={`${gridCols} border-b bg-muted/50 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground`}
        >
          <span>{t('enrich.map.col.scheme', 'Concept scheme')}</span>
          <span className="text-right">{t('enrich.map.col.concepts', 'Concepts')}</span>
          <span className="text-right">{t('enrich.map.col.coverage', 'Coverage')}</span>
          <span className="text-right text-sky-700 dark:text-sky-400">
            {t('enrich.map.col.products', 'Products')}
          </span>
          <span className="text-right text-sky-700 dark:text-sky-400">
            {t('enrich.map.col.contracts', 'Contracts')}
          </span>
          <span className="text-right text-amber-700 dark:text-amber-500">
            {t('enrich.map.col.assets', 'Assets')}
          </span>
          <span className="text-right">{t('enrich.map.col.suggested', 'Suggested')}</span>
          <span />
        </div>

        {/* rows */}
        {rows.map((row) => (
          <div key={row.id} className={`${gridCols} border-b px-4 py-2.5 text-sm last:border-b-0`}>
            <span className="font-semibold">{row.name}</span>
            <span className="text-right tabular-nums">{row.concepts}</span>
            <span className="flex items-center justify-end gap-2">
              <span className="h-1.5 w-[70px] overflow-hidden rounded-full bg-secondary">
                <span
                  className="block h-full rounded-full bg-emerald-500"
                  style={{ width: `${row.coveragePct}%` }}
                />
              </span>
              <b className="tabular-nums">{row.coveragePct}%</b>
            </span>
            <span className="text-right tabular-nums text-sky-700 dark:text-sky-400">
              {row.products}
            </span>
            <span className="text-right tabular-nums text-sky-700 dark:text-sky-400">
              {row.contracts}
            </span>
            <span className="text-right tabular-nums text-amber-700 dark:text-amber-500">
              {row.assets}
            </span>
            <span className="text-right">
              {row.suggested > 0 ? (
                <Badge
                  variant="outline"
                  className="border-amber-300 bg-amber-100/60 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200"
                >
                  {row.suggested}
                </Badge>
              ) : (
                <span className="text-muted-foreground">0</span>
              )}
            </span>
            <span className="text-right">
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={!canWrite || row.suggested === 0}
                onClick={() => onReview(row)}
              >
                {t('enrich.map.review', 'Review')}
              </Button>
            </span>
          </div>
        ))}

        {/* totals */}
        {rows.length > 0 && (
          <div className={`${gridCols} bg-muted/40 px-4 py-2.5 text-sm font-semibold`}>
            <span>{t('enrich.map.allSelected', 'All selected')}</span>
            <span className="text-right tabular-nums">{totals.concepts}</span>
            <span className="flex items-center justify-end gap-2">
              <span className="h-1.5 w-[70px] overflow-hidden rounded-full bg-secondary">
                <span
                  className="block h-full rounded-full bg-emerald-500"
                  style={{ width: `${totalPct}%` }}
                />
              </span>
              <b className="tabular-nums">{totalPct}%</b>
            </span>
            <span className="text-right tabular-nums text-sky-700 dark:text-sky-400">
              {totals.products}
            </span>
            <span className="text-right tabular-nums text-sky-700 dark:text-sky-400">
              {totals.contracts}
            </span>
            <span className="text-right tabular-nums text-amber-700 dark:text-amber-500">
              {totals.assets}
            </span>
            <span className="text-right tabular-nums">{totals.suggested}</span>
            <span />
          </div>
        )}
      </div>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
        {t(
          'enrich.map.assetNote',
          'Asset links ({{count}}) are what Deliver enriches in step 2. Asset-direct linking works even before any product or contract exists, so it solves the chicken-and-egg case. The {{unmapped}} unmapped concepts have no link yet.',
          { count: totals.assets, unmapped },
        )}
        <InfoDot
          text={t(
            'enrich.map.coverageTip',
            "Coverage = share of a concept scheme's concepts with at least one link. Products and Contracts are optional extra links, so the three counts don't sum to the total. Only Assets can be enriched in step 2.",
          )}
        />
      </p>

      {/* Placeholder-data disclosure — these counts are NOT live yet. */}
      <p className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {t(
          'enrich.map.placeholderNote',
          'Coverage figures are sample data. A per-scheme coverage read-model endpoint does not exist yet; once it lands these counts become live.',
        )}{' '}
        <span className="font-mono">({platformNoun})</span>
      </p>
    </div>
  );
}
