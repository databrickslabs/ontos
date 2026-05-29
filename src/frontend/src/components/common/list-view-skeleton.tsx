import { Skeleton } from '@/components/ui/skeleton';

/* ============================================================================
 * Primitives
 * --------------------------------------------------------------------------
 * Thin wrappers around the base Skeleton component so other modules don't
 * have to import @/components/ui/skeleton directly. This keeps all skeleton
 * usage funneled through this shared module (see lint guard in the docs).
 * ==========================================================================*/

interface SkeletonLineProps {
  /** Tailwind width class, e.g. "w-32" or "w-full". Defaults to "w-full". */
  width?: string;
  /** Tailwind height class, e.g. "h-4". Defaults to "h-4". */
  height?: string;
  className?: string;
  style?: React.CSSProperties;
}

/** Simple text-line skeleton. */
export function SkeletonLine({
  width = 'w-full',
  height = 'h-4',
  className = '',
  style,
}: SkeletonLineProps) {
  return <Skeleton className={`${height} ${width} ${className}`.trim()} style={style} />;
}

/** Solid block skeleton (taller than a line). */
export function SkeletonBlock({
  width = 'w-full',
  height = 'h-32',
  className = '',
}: SkeletonLineProps) {
  return <Skeleton className={`${height} ${width} ${className}`.trim()} />;
}

/* ============================================================================
 * Templates
 * ==========================================================================*/

interface ListViewSkeletonProps {
  /** Number of columns to show in the table header/rows */
  columns?: number;
  /** Number of rows to show */
  rows?: number;
  /** Whether to show the toolbar skeleton */
  showToolbar?: boolean;
  /** Whether to show the pagination skeleton */
  showPagination?: boolean;
  /** Number of action buttons in the toolbar */
  toolbarButtons?: number;
}

/**
 * Reusable skeleton loading state for list views with DataTable.
 * Provides a consistent loading experience across all list views.
 */
export function ListViewSkeleton({
  columns = 6,
  rows = 5,
  showToolbar = true,
  showPagination = true,
  toolbarButtons = 2,
}: ListViewSkeletonProps) {
  return (
    <div className="space-y-4">
      {/* Toolbar skeleton */}
      {showToolbar && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-9 w-24" />
          </div>
          <div className="flex items-center gap-2">
            {[...Array(toolbarButtons)].map((_, i) => (
              <Skeleton key={i} className="h-9 w-32" />
            ))}
          </div>
        </div>
      )}

      {/* Table skeleton */}
      <TableSkeleton columns={columns} rows={rows} />

      {/* Pagination skeleton */}
      {showPagination && (
        <div className="flex items-center justify-between">
          <Skeleton className="h-4 w-32" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
          </div>
        </div>
      )}
    </div>
  );
}

interface TableSkeletonProps {
  columns?: number;
  rows?: number;
  /** Show the bordered/rounded wrapper. Set to false when the consumer renders inside a Card already. */
  bordered?: boolean;
  /** Show a header row */
  showHeader?: boolean;
}

/**
 * Pure table skeleton without toolbar / pagination wrappers. Useful when
 * the parent already renders a Card or other surface around the table.
 */
export function TableSkeleton({
  columns = 6,
  rows = 5,
  bordered = true,
  showHeader = true,
}: TableSkeletonProps) {
  // Pre-compute pseudo-random column widths once per render so they stay stable
  // within a single mount. (Math.random in JSX runs on every paint otherwise.)
  const headerWidths = Array.from({ length: columns }, () => Math.round(Math.random() * 40 + 60));
  const rowWidths = Array.from({ length: rows }, () =>
    Array.from({ length: columns }, () => Math.round(Math.random() * 60 + 40))
  );

  return (
    <div className={bordered ? 'border rounded-lg' : ''}>
      {showHeader && (
        <div className={`p-3 ${bordered ? 'border-b bg-muted/30' : ''}`}>
          <div className="flex gap-4 items-center">
            <Skeleton className="h-4 w-4" />
            {headerWidths.map((w, i) => (
              <Skeleton key={i} className="h-4" style={{ width: `${w}px` }} />
            ))}
          </div>
        </div>
      )}
      {[...Array(rows)].map((_, rowIndex) => (
        <div
          key={rowIndex}
          className={`p-3 ${bordered ? 'border-b last:border-b-0' : ''}`}
        >
          <div className="flex gap-4 items-center">
            <Skeleton className="h-4 w-4" />
            {rowWidths[rowIndex].map((w, colIndex) => (
              <Skeleton key={colIndex} className="h-4" style={{ width: `${w}px` }} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Skeleton for detail view headers with back button and action buttons.
 */
export function DetailHeaderSkeleton({ actionButtons = 3 }: { actionButtons?: number }) {
  return (
    <div className="flex items-center justify-between">
      <Skeleton className="h-9 w-32" />
      <div className="flex items-center gap-2">
        {[...Array(actionButtons)].map((_, i) => (
          <Skeleton key={i} className="h-9 w-24" />
        ))}
      </div>
    </div>
  );
}

/**
 * Skeleton for a card with title and content.
 */
export function CardSkeleton({
  titleWidth = 'w-48',
  descriptionWidth = 'w-64',
  contentRows = 3,
}: {
  titleWidth?: string;
  descriptionWidth?: string;
  contentRows?: number;
}) {
  return (
    <div className="border rounded-lg p-6 space-y-4">
      <div>
        <Skeleton className={`h-6 ${titleWidth} mb-2`} />
        <Skeleton className={`h-4 ${descriptionWidth}`} />
      </div>
      <div className="space-y-3">
        {[...Array(contentRows)].map((_, i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    </div>
  );
}

/**
 * Skeleton for metadata grid (used in detail views).
 */
export function MetadataGridSkeleton({ items = 6 }: { items?: number }) {
  return (
    <div className="grid md:grid-cols-3 gap-x-6 gap-y-3">
      {[...Array(items)].map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  );
}

/**
 * Comprehensive skeleton for detail views.
 * Shows header with back button, main card with metadata, and optional additional cards.
 */
export function DetailViewSkeleton({
  cards = 3,
  actionButtons = 3,
}: {
  cards?: number;
  actionButtons?: number;
}) {
  return (
    <div className="py-6 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <Skeleton className="h-9 w-32" />
        <div className="flex items-center gap-2">
          {[...Array(actionButtons)].map((_, i) => (
            <Skeleton key={i} className="h-9 w-24" />
          ))}
        </div>
      </div>

      {/* Core Metadata Card skeleton */}
      <div className="border rounded-lg">
        <div className="p-6 border-b">
          <div className="flex items-center gap-3">
            <Skeleton className="h-7 w-7 rounded" />
            <Skeleton className="h-7 w-64" />
          </div>
          <Skeleton className="h-4 w-96 mt-2" />
        </div>
        <div className="p-6 space-y-3">
          <div className="grid md:grid-cols-3 gap-x-6 gap-y-2">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="flex items-center gap-2">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-24" />
              </div>
            ))}
          </div>
          <div className="pt-3 border-t">
            <div className="flex gap-3">
              <div className="flex-1">
                <Skeleton className="h-3 w-12 mb-1.5" />
                <div className="flex gap-1">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-20" />
                </div>
              </div>
              <div className="flex-1">
                <Skeleton className="h-3 w-24 mb-1.5" />
                <Skeleton className="h-5 w-32" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Additional cards skeleton */}
      {[...Array(Math.max(cards - 1, 0))].map((_, cardIndex) => (
        <div key={cardIndex} className="border rounded-lg">
          <div className="p-6 border-b">
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-5" />
              <Skeleton className="h-5 w-32" />
            </div>
            <Skeleton className="h-4 w-56 mt-1" />
          </div>
          <div className="p-6">
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

interface HierarchyTreeSkeletonProps {
  /** Number of top-level groups to display */
  groups?: number;
  /** Number of items per group */
  itemsPerGroup?: number;
  /** Whether items are indented under their group label */
  indented?: boolean;
  className?: string;
}

/**
 * Skeleton for nested tree / hierarchical browsers.
 * Mirrors the layout used by the Hierarchy Browser side panel and similar
 * grouped tree components.
 */
export function HierarchyTreeSkeleton({
  groups = 3,
  itemsPerGroup = 3,
  indented = true,
  className = '',
}: HierarchyTreeSkeletonProps) {
  return (
    <div className={`space-y-2 p-4 ${className}`.trim()}>
      {[...Array(groups)].map((_, g) => (
        <div key={g} className="space-y-1.5">
          <Skeleton className="h-5 w-32" />
          <div className={`space-y-1 ${indented ? 'pl-6' : ''}`}>
            {[...Array(itemsPerGroup)].map((_, i) => (
              <Skeleton
                key={i}
                className="h-4"
                style={{ width: `${Math.round(Math.random() * 30 + 130)}px` }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

interface PanelSkeletonProps {
  /** Show an icon next to the title */
  withHeaderIcon?: boolean;
  /** Show a description under the title */
  withDescription?: boolean;
  /** Number of stacked content rows */
  rows?: number;
  /** Height class for each row */
  rowHeight?: string;
  /** Outer wrapper class (defaults to bordered card) */
  className?: string;
}

/**
 * Skeleton for a generic side / inline Panel that has an icon+title header
 * and a stack of content rows. Use for entity panels (costs, quality,
 * comments, ratings, access grants, version history, ownership, etc.).
 */
export function PanelSkeleton({
  withHeaderIcon = true,
  withDescription = true,
  rows = 2,
  rowHeight = 'h-10',
  className = 'border rounded-lg',
}: PanelSkeletonProps) {
  return (
    <div className={className}>
      <div className="p-6 border-b">
        <div className="flex items-center gap-2">
          {withHeaderIcon && <Skeleton className="h-5 w-5" />}
          <Skeleton className="h-5 w-32" />
        </div>
        {withDescription && <Skeleton className="h-4 w-48 mt-1" />}
      </div>
      <div className="p-6">
        <div className="space-y-2">
          {[...Array(rows)].map((_, i) => (
            <Skeleton key={i} className={`${rowHeight} w-full`} />
          ))}
        </div>
      </div>
    </div>
  );
}

interface DialogSkeletonProps {
  /** Number of varying-width lines */
  rows?: number;
  className?: string;
}

/**
 * Skeleton for dialog body content - a stack of varying-width text lines.
 */
export function DialogSkeleton({ rows = 3, className = '' }: DialogSkeletonProps) {
  // Cycle through a few canonical widths so the skeleton looks like prose
  const widths = ['w-3/4', 'w-1/2', 'w-2/3', 'w-5/6', 'w-3/5'];
  return (
    <div className={`space-y-4 ${className}`.trim()}>
      {[...Array(rows)].map((_, i) => (
        <Skeleton key={i} className={`h-4 ${widths[i % widths.length]}`} />
      ))}
    </div>
  );
}

interface StatCardsSkeletonProps {
  /** Number of stat cards to show in a row */
  count?: number;
  /** Optional grid override (defaults to responsive 1/3 columns) */
  className?: string;
}

/**
 * Skeleton for a row of stat / summary cards (icon + label + value).
 */
export function StatCardsSkeleton({
  count = 3,
  className = 'grid grid-cols-1 sm:grid-cols-3 gap-4',
}: StatCardsSkeletonProps) {
  return (
    <div className={className}>
      {[...Array(count)].map((_, i) => (
        <div key={i} className="border rounded-lg p-6">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-7 w-16" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

interface ListItemSkeletonProps {
  /** Number of list items to render */
  count?: number;
  /** Tailwind height class for each item */
  height?: string;
  /** Optional class for the wrapper */
  className?: string;
}

/**
 * Skeleton for a vertical stack of list items (rounded rows).
 * Suitable for sidebars showing items, products, projects, etc.
 */
export function ListItemSkeleton({
  count = 4,
  height = 'h-14',
  className = 'space-y-1',
}: ListItemSkeletonProps) {
  return (
    <div className={className}>
      {[...Array(count)].map((_, i) => (
        <Skeleton key={i} className={`${height} w-full rounded-md`} />
      ))}
    </div>
  );
}

/**
 * Skeleton matching a Card with an icon + title header followed by a
 * pseudo-random horizontal table-row pattern. Useful for "data dictionary" /
 * full-bleed table loading states.
 */
export function CatalogColumnsTableSkeleton({ rows = 10 }: { rows?: number }) {
  // Stable widths matching the rendered Data Catalog columns
  const colWidths = ['w-32', 'flex-1', 'w-24', 'w-40'];
  return (
    <div className="p-6 space-y-4">
      {[...Array(rows)].map((_, i) => (
        <div key={i} className="flex gap-4">
          {colWidths.map((w, j) => (
            <Skeleton key={j} className={`h-6 ${w}`} />
          ))}
        </div>
      ))}
    </div>
  );
}

interface VersionLineageSkeletonProps {
  /** Number of version cards to show stacked */
  versions?: number;
}

/**
 * Skeleton for the contract Version History panel.
 * Stacks N version-card-shaped blocks vertically.
 */
export function VersionLineageSkeleton({ versions = 2 }: VersionLineageSkeletonProps) {
  return (
    <div className="space-y-4">
      {[...Array(versions)].map((_, i) => (
        <Skeleton key={i} className="h-32 w-full" />
      ))}
    </div>
  );
}
