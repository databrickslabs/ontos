import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Info } from 'lucide-react';
import type { Column, ColumnDef, Table as TanStackTable } from '@tanstack/react-table';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { TableCell, TableRow } from '@/components/ui/table';
import { RelativeDate } from '@/components/common/relative-date';
import { cn } from '@/lib/utils';
import { useEnrichCoverageTableStore } from '@/stores/enrich-coverage-table-store';
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
//          Assets | Suggested | Last run | (Review action).
//
// Rendered with the shared DataTable (sorting, column visibility, paging).
// Sort, page size and search live in useEnrichCoverageTableStore so they
// survive navigation and reload.
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
  /** ISO timestamp of the latest term-mapping run targeting this scheme. */
  lastRun?: string | null;
}

interface Props {
  rows: CoverageRow[];
  platformNoun: string;
  /** Opens the inline "Review suggested matches" modal for a scheme. */
  onReview: (row: CoverageRow) => void;
  /** Whether the current user may act on suggestions. */
  canWrite?: boolean;
  /** True when rows come from the live coverage read-model; false when the
   *  endpoint was unavailable and placeholder rows are shown. */
  isLive?: boolean;
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

// Column colors shared by the body cells and the totals footer.
const SKY = 'text-sky-700 dark:text-sky-400';
const AMBER = 'text-amber-700 dark:text-amber-500';
const NUM = 'text-right tabular-nums';

function SortHeader<T>({
  column,
  label,
  align = 'right',
  className,
}: {
  column: Column<T, unknown>;
  label: string;
  align?: 'left' | 'right';
  className?: string;
}) {
  const sorted = column.getIsSorted();
  // The arrow shows on the sorted column only; the ghost button's hover state signals the rest.
  const Icon = sorted === 'asc' ? ArrowUp : ArrowDown;
  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn(
        'relative h-7 px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground',
        align === 'right' ? '-mr-1 ml-auto flex' : '-ml-1',
        className,
      )}
      onClick={() => column.toggleSorting(sorted === 'asc')}
    >
      {label}
      {/* The arrow sits in the cell's side padding, so sorting never widens the header. */}
      {sorted && (
        <Icon
          className="absolute -right-3.5 top-1/2 h-3 w-3 -translate-y-1/2"
        />
      )}
    </Button>
  );
}

function CoverageBar({ pct }: { pct: number }) {
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="h-1.5 w-[48px] overflow-hidden rounded-full bg-secondary">
        <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
      </span>
      <b className="tabular-nums">{pct}%</b>
    </span>
  );
}

export default function CoverageMatrix({
  rows,
  platformNoun,
  onReview,
  canWrite = true,
  isLive = true,
}: Props) {
  const { t } = useTranslation(['concepts', 'common']);
  const search = useEnrichCoverageTableStore((s) => s.search);
  const setSearch = useEnrichCoverageTableStore((s) => s.setSearch);
  const sorting = useEnrichCoverageTableStore((s) => s.sorting);
  const setSorting = useEnrichCoverageTableStore((s) => s.setSorting);
  const pageSize = useEnrichCoverageTableStore((s) => s.pageSize);
  const setPageSize = useEnrichCoverageTableStore((s) => s.setPageSize);

  // Rollup over ALL rows (not the filtered/paged subset), so the totals
  // footer stays accurate on every page and for any search.
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

  // DataTable's controlled search does not filter client-side, so filter by
  // scheme name here and hand the result to the table.
  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.name.toLowerCase().includes(q));
  }, [rows, search]);

  const columns = useMemo<ColumnDef<CoverageRow>[]>(
    () => [
      {
        id: 'scheme',
        accessorKey: 'name',
        header: ({ column }) => (
          <SortHeader column={column} align="left" label={t('enrich.map.col.scheme', 'Concept scheme')} />
        ),
        // Long names truncate inside a bounded width; the full name is in the
        // tooltip, so the column never stretches.
        cell: ({ row }) => (
          <div className="min-w-0">
            <span className="block truncate font-semibold" title={row.original.name}>
              {row.original.name}
            </span>
            {row.original.lastRun && (
              <span className="block truncate text-[11px] text-muted-foreground">
                {t('enrich.map.col.lastRun', 'Last run')} <RelativeDate date={row.original.lastRun} />
              </span>
            )}
          </div>
        ),
      },
      {
        id: 'concepts',
        size: 84,
        accessorKey: 'concepts',
        header: ({ column }) => (
          <SortHeader column={column} label={t('enrich.map.col.concepts', 'Concepts')} />
        ),
        cell: ({ row }) => <div className={NUM}>{row.original.concepts}</div>,
      },
      {
        id: 'coverage',
        size: 116,
        accessorKey: 'coveragePct',
        header: ({ column }) => (
          <SortHeader column={column} label={t('enrich.map.col.coverage', 'Coverage')} />
        ),
        cell: ({ row }) => <CoverageBar pct={row.original.coveragePct} />,
      },
      {
        id: 'products',
        size: 84,
        accessorKey: 'products',
        header: ({ column }) => (
          <SortHeader column={column} className={SKY} label={t('enrich.map.col.products', 'Products')} />
        ),
        cell: ({ row }) => <div className={cn(NUM, SKY)}>{row.original.products}</div>,
      },
      {
        id: 'contracts',
        size: 92,
        accessorKey: 'contracts',
        header: ({ column }) => (
          <SortHeader column={column} className={SKY} label={t('enrich.map.col.contracts', 'Contracts')} />
        ),
        cell: ({ row }) => <div className={cn(NUM, SKY)}>{row.original.contracts}</div>,
      },
      {
        id: 'assets',
        size: 100,
        accessorKey: 'assets',
        header: ({ column }) => (
          <div className="flex items-center justify-end gap-1">
            <SortHeader column={column} className={cn(AMBER, 'ml-0')} label={t('enrich.map.col.assets', 'Assets')} />
            <InfoDot
              text={t(
                'enrich.map.assetNote',
                'Asset links are what Deliver enriches in step 2. Asset-direct linking works even before any product or contract exists, so it solves the chicken-and-egg case.',
              )}
            />
          </div>
        ),
        cell: ({ row }) => <div className={cn(NUM, AMBER)}>{row.original.assets}</div>,
      },
      {
        id: 'suggested',
        size: 92,
        accessorKey: 'suggested',
        header: ({ column }) => (
          <SortHeader column={column} label={t('enrich.map.col.suggested', 'Suggested')} />
        ),
        cell: ({ row }) => (
          <div className="text-right">
            {row.original.suggested > 0 ? (
              <Badge
                variant="outline"
                className="border-amber-300 bg-amber-100/60 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200"
              >
                {row.original.suggested}
              </Badge>
            ) : (
              <span className="text-muted-foreground">0</span>
            )}
          </div>
        ),
      },
      {
        id: 'actions',
        size: 72,
        header: () => null,
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={!canWrite || row.original.suggested === 0}
              onClick={() => onReview(row.original)}
            >
              {t('enrich.map.review', 'Review')}
            </Button>
          </div>
        ),
      },
    ],
    [t, canWrite, onReview],
  );

  // "All selected" footer: one cell per VISIBLE column so it stays aligned
  // when the user hides columns from the Columns menu.
  const renderTotals = (table: TanStackTable<CoverageRow>) => (
    <TableRow className="font-semibold hover:bg-transparent">
      {table.getVisibleLeafColumns().map((col) => {
        let content: ReactNode = null;
        switch (col.id) {
          case 'scheme':
            content = t('enrich.map.allSelected', 'All selected');
            break;
          case 'concepts':
            content = <div className={NUM}>{totals.concepts}</div>;
            break;
          case 'coverage':
            content = <CoverageBar pct={totalPct} />;
            break;
          case 'products':
            content = <div className={cn(NUM, SKY)}>{totals.products}</div>;
            break;
          case 'contracts':
            content = <div className={cn(NUM, SKY)}>{totals.contracts}</div>;
            break;
          case 'assets':
            content = <div className={cn(NUM, AMBER)}>{totals.assets}</div>;
            break;
          case 'suggested':
            content = <div className={NUM}>{totals.suggested}</div>;
            break;
        }
        return (
          <TableCell key={col.id} data-column={col.id} className="px-3 py-2">
            {content}
          </TableCell>
        );
      })}
    </TableRow>
  );

  return (
    <div className="space-y-3">
      <DataTable<CoverageRow, unknown>
        columns={columns}
        data={filteredRows}
        searchColumn="scheme"
        selectable={false}
        dense
        fixedLayout
        searchValue={search}
        onSearchChange={setSearch}
        sorting={sorting}
        onSortingChange={setSorting}
        pageSize={pageSize}
        onPageSizeChange={setPageSize}
        footer={rows.length > 0 ? renderTotals : undefined}
      />

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
        {t(
          'enrich.map.unmappedNote',
          '{{unmapped}} concepts have no link yet.',
          { unmapped },
        )}
        <InfoDot
          text={t(
            'enrich.map.coverageTip',
            "Coverage = share of a concept scheme's concepts with at least one link. Products and Contracts are optional extra links, so the three counts don't sum to the total. Only Assets can be enriched in step 2.",
          )}
        />
      </p>

      {/* Disclosure only when the live coverage read-model is unavailable and
          we are showing placeholder rows. When live, no note is needed. */}
      {!isLive && (
        <p className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {t(
            'enrich.map.placeholderNote',
            'Coverage figures are sample data — the live coverage service is unavailable right now.',
          )}{' '}
          <span className="font-mono">({platformNoun})</span>
        </p>
      )}
    </div>
  );
}
