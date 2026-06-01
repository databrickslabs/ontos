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

interface DetailHeaderSkeletonProps {
  /** Number of action buttons on the right side */
  actionButtons?: number;
  /**
   * Number of additional left-side controls to render after the back-button stub.
   * Useful for pages that include version navigators, view-mode toggles, etc.
   */
  leftControls?: number;
}

/**
 * Skeleton for detail view headers with back button and action buttons.
 * Optionally renders extra left-side stubs (e.g. version nav, S/M/L toggle).
 */
export function DetailHeaderSkeleton({
  actionButtons = 3,
  leftControls = 0,
}: DetailHeaderSkeletonProps) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Skeleton className="h-9 w-32" />
        {[...Array(leftControls)].map((_, i) => (
          <Skeleton key={i} className="h-9 w-28" />
        ))}
      </div>
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
  /** Padding for each stat card. Use "p-4" for compact rows. */
  cardPadding?: string;
}

/**
 * Skeleton for a row of stat / summary cards (icon + label + value).
 */
export function StatCardsSkeleton({
  count = 3,
  className = 'grid grid-cols-1 sm:grid-cols-3 gap-4',
  cardPadding = 'p-6',
}: StatCardsSkeletonProps) {
  return (
    <div className={className}>
      {[...Array(count)].map((_, i) => (
        <div key={i} className={`border rounded-lg ${cardPadding}`}>
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

interface CatalogColumnsTableSkeletonProps {
  /** Number of body rows */
  rows?: number;
  /**
   * Number of columns. The first column is rendered as a fixed-width name
   * cell, the rest are evenly distributed.
   */
  columns?: number;
  /** Render a header row above the body */
  showHeader?: boolean;
}

/**
 * Skeleton matching the Data Catalog page table (columns / data dictionary
 * style). Renders an optional header row plus configurable body rows.
 */
export function CatalogColumnsTableSkeleton({
  rows = 10,
  columns = 8,
  showHeader = true,
}: CatalogColumnsTableSkeletonProps) {
  // First column gets a fixed name width, remaining columns share flex space
  const colClasses = Array.from({ length: columns }, (_, i) =>
    i === 0 ? 'w-40' : 'flex-1'
  );

  return (
    <div className="p-6 space-y-3">
      {showHeader && (
        <div className="flex gap-4 pb-2 border-b">
          {colClasses.map((w, j) => (
            <Skeleton key={j} className={`h-3 ${w}`} />
          ))}
        </div>
      )}
      {[...Array(rows)].map((_, i) => (
        <div key={i} className="flex gap-4">
          {colClasses.map((w, j) => (
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

interface TabsDetailSkeletonProps {
  /** Number of tab triggers in the strip */
  tabs?: number;
  /** Number of action buttons in the header */
  actionButtons?: number;
  /** Number of left-side header controls (after back button) */
  leftControls?: number;
  /** Whether to render a hero (icon + title + description) above the tabs */
  hero?: boolean;
  /** Layout for the active tab body. 'two-col' renders 2 wide cards + 1 side card. */
  contentVariant?: 'cards' | 'two-col';
  /** Number of cards to render in the content area (cards variant only) */
  contentCards?: number;
}

/**
 * Skeleton for a tabbed detail page: header row, hero block, tab strip,
 * and a content body. Use for asset-detail, data-catalog-details, and
 * other tabbed entity detail views.
 */
export function TabsDetailSkeleton({
  tabs = 3,
  actionButtons = 3,
  leftControls = 0,
  hero = true,
  contentVariant = 'cards',
  contentCards = 2,
}: TabsDetailSkeletonProps) {
  return (
    <div className="py-6 space-y-6">
      <DetailHeaderSkeleton actionButtons={actionButtons} leftControls={leftControls} />

      {hero && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded" />
            <Skeleton className="h-8 w-72" />
            <Skeleton className="h-5 w-20" />
          </div>
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      )}

      {/* Tab triggers */}
      <div className="flex gap-2 border-b pb-2">
        {[...Array(tabs)].map((_, i) => (
          <Skeleton key={i} className="h-9 w-32" />
        ))}
      </div>

      {/* Tab body */}
      {contentVariant === 'two-col' ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <CardSkeleton titleWidth="w-40" descriptionWidth="w-64" contentRows={4} />
            <CardSkeleton titleWidth="w-48" descriptionWidth="w-72" contentRows={3} />
          </div>
          <div className="space-y-4">
            <PanelSkeleton rows={3} />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {[...Array(contentCards)].map((_, i) => (
            <CardSkeleton key={i} contentRows={3} />
          ))}
        </div>
      )}
    </div>
  );
}

interface SplitPaneSkeletonProps {
  /** Tailwind width class for the sidebar (e.g. "w-64", "w-1/4") */
  sidebarWidth?: string;
  /** Sidebar render style */
  sidebarVariant?: 'tree' | 'list' | 'cards';
  /** Number of items in the sidebar list/tree/cards */
  sidebarItems?: number;
  /** Main pane render style */
  main?: 'table' | 'panel' | 'tree' | 'cards';
  /** Number of columns when main='table' */
  tableColumns?: number;
  /** Number of rows when main='table' or items when main is list-like */
  tableRows?: number;
  /** Optional toolbar/header row above the split */
  showHeader?: boolean;
  /** Total min height (Tailwind class) for the split */
  minHeight?: string;
}

/**
 * Skeleton for split-pane layouts (sidebar + main content). Used by
 * asset-explorer, entitlements, master-data-management, catalog-commander,
 * collections, hierarchy-browser, ontology-generator, schema-importer.
 */
export function SplitPaneSkeleton({
  sidebarWidth = 'w-1/4',
  sidebarVariant = 'list',
  sidebarItems = 6,
  main = 'table',
  tableColumns = 6,
  tableRows = 6,
  showHeader = true,
  minHeight = 'min-h-[400px]',
}: SplitPaneSkeletonProps) {
  const renderSidebar = () => {
    if (sidebarVariant === 'tree') {
      return <HierarchyTreeSkeleton groups={Math.max(1, Math.floor(sidebarItems / 3))} itemsPerGroup={3} />;
    }
    if (sidebarVariant === 'cards') {
      return (
        <div className="p-4 space-y-3">
          {[...Array(sidebarItems)].map((_, i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))}
        </div>
      );
    }
    return (
      <div className="p-2">
        <ListItemSkeleton count={sidebarItems} height="h-10" />
      </div>
    );
  };

  const renderMain = () => {
    if (main === 'panel') {
      return <PanelSkeleton rows={tableRows} />;
    }
    if (main === 'tree') {
      return <HierarchyTreeSkeleton groups={3} itemsPerGroup={tableRows} />;
    }
    if (main === 'cards') {
      return (
        <div className="p-4 space-y-3">
          {[...Array(tableRows)].map((_, i) => (
            <CardSkeleton key={i} contentRows={2} />
          ))}
        </div>
      );
    }
    return <TableSkeleton columns={tableColumns} rows={tableRows} />;
  };

  return (
    <div className={`flex flex-col gap-4 ${minHeight}`.trim()}>
      {showHeader && (
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-48" />
          <div className="flex gap-2">
            <Skeleton className="h-9 w-32" />
          </div>
        </div>
      )}
      <div className="flex gap-4 flex-1">
        <div className={`${sidebarWidth} border rounded-lg overflow-hidden`}>
          {renderSidebar()}
        </div>
        <div className="flex-1 border rounded-lg overflow-hidden">
          {renderMain()}
        </div>
      </div>
    </div>
  );
}

interface SettingsFormSkeletonProps {
  /** Number of form sections */
  sections?: number;
  /** Number of fields per section */
  fieldsPerSection?: number;
  /** Show a sticky/footer save bar */
  showSaveBar?: boolean;
  /** Show the page title block at the top */
  showTitle?: boolean;
}

/**
 * Skeleton for settings form pages (general, delivery, git, etc.).
 * Renders a title block, N labeled-field sections and an optional save bar.
 */
export function SettingsFormSkeleton({
  sections = 2,
  fieldsPerSection = 3,
  showSaveBar = true,
  showTitle = true,
}: SettingsFormSkeletonProps) {
  return (
    <div className="space-y-6">
      {showTitle && (
        <div className="space-y-2">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-96" />
        </div>
      )}
      {[...Array(sections)].map((_, s) => (
        <div key={s} className="border rounded-lg">
          <div className="p-6 border-b space-y-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-72" />
          </div>
          <div className="p-6 space-y-4">
            {[...Array(fieldsPerSection)].map((_, f) => (
              <div key={f} className="space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-9 w-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
      {showSaveBar && (
        <div className="flex justify-end gap-2 pt-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-32" />
        </div>
      )}
    </div>
  );
}

interface HomeDashboardSkeletonProps {
  /** Number of overview tiles */
  tileCount?: number;
  /** Whether to render the My Actions / Quick Actions card */
  showMyActions?: boolean;
  /** Whether to render role-specific sections (discovery, curation) */
  showRoleSections?: boolean;
}

/**
 * Skeleton for the personalized Home dashboard. Renders a hero search row,
 * a stat-tile grid, an optional My Actions block, and optional role sections.
 */
export function HomeDashboardSkeleton({
  tileCount = 4,
  showMyActions = true,
  showRoleSections = true,
}: HomeDashboardSkeletonProps) {
  return (
    <div className="py-6 space-y-6">
      {/* Hero (logo + title + search bar) */}
      <div className="flex flex-col items-center text-center space-y-3 py-8">
        <Skeleton className="h-12 w-12 rounded-full" />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-96" />
        <Skeleton className="h-11 w-full max-w-2xl rounded-lg" />
      </div>

      {/* Tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {[...Array(tileCount)].map((_, i) => (
          <div key={i} className="border rounded-lg p-5 space-y-3">
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-8 rounded-md" />
              <Skeleton className="h-5 w-24" />
            </div>
            <Skeleton className="h-7 w-12" />
            <Skeleton className="h-3 w-32" />
          </div>
        ))}
      </div>

      {showMyActions && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <PanelSkeleton rows={3} rowHeight="h-12" />
          <PanelSkeleton rows={3} rowHeight="h-12" />
        </div>
      )}

      {showRoleSections && (
        <div className="space-y-4">
          <PanelSkeleton rows={3} rowHeight="h-14" />
          <PanelSkeleton rows={2} rowHeight="h-12" />
        </div>
      )}
    </div>
  );
}

interface TileGridSkeletonProps {
  /** Number of tiles */
  count?: number;
  /** Columns at the largest breakpoint */
  columns?: 1 | 2 | 3 | 4;
  /** Render an optional title row above the grid */
  withHeader?: boolean;
  /** Tile height class */
  tileHeight?: string;
}

/**
 * Skeleton for tile/card grids (e.g. marketplace product tiles, domain pills).
 */
export function TileGridSkeleton({
  count = 8,
  columns = 4,
  withHeader = false,
  tileHeight = 'h-40',
}: TileGridSkeletonProps) {
  // Map columns to a static class so Tailwind's JIT can pick it up
  const gridClass = {
    1: 'grid-cols-1',
    2: 'grid-cols-1 sm:grid-cols-2',
    3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
    4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
  }[columns];

  return (
    <div className="space-y-4">
      {withHeader && (
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-9 w-32" />
        </div>
      )}
      <div className={`grid ${gridClass} gap-4`}>
        {[...Array(count)].map((_, i) => (
          <div key={i} className={`border rounded-lg p-4 space-y-3 ${tileHeight}`}>
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
            <div className="flex gap-2 pt-2">
              <Skeleton className="h-5 w-12" />
              <Skeleton className="h-5 w-16" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface DocViewerSkeletonProps {
  /** Show a Table-of-Contents sidebar */
  showToc?: boolean;
  /** Number of prose paragraph rows */
  proseRows?: number;
  /** Show a page title above the body */
  showTitle?: boolean;
}

/**
 * Skeleton for documentation / user guide pages with optional TOC sidebar
 * and a markdown-prose body.
 */
export function DocViewerSkeleton({
  showToc = true,
  proseRows = 12,
  showTitle = true,
}: DocViewerSkeletonProps) {
  // Cycle through canonical widths so the prose looks varied
  const widths = ['w-full', 'w-11/12', 'w-5/6', 'w-3/4', 'w-2/3'];
  return (
    <div className="space-y-6">
      {showTitle && (
        <div className="space-y-2">
          <Skeleton className="h-8 w-72" />
          <Skeleton className="h-4 w-96" />
        </div>
      )}
      <div className={`flex gap-6 ${showToc ? '' : 'justify-center'}`}>
        {showToc && (
          <div className="w-64 shrink-0 hidden lg:block">
            <div className="space-y-2 sticky top-4">
              <Skeleton className="h-4 w-24" />
              <div className="space-y-1.5 pt-1">
                {[...Array(8)].map((_, i) => (
                  <Skeleton
                    key={i}
                    className="h-3"
                    style={{ width: `${Math.round(Math.random() * 40 + 100)}px` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div className="flex-1 space-y-3 max-w-4xl">
          <Skeleton className="h-7 w-1/2 mb-2" />
          {[...Array(proseRows)].map((_, i) => (
            <Skeleton key={i} className={`h-3 ${widths[i % widths.length]}`} />
          ))}
        </div>
      </div>
    </div>
  );
}

interface GraphCanvasSkeletonProps {
  /** Show a left-side filter/legend panel */
  showFilterPanel?: boolean;
  /** Show a top toolbar */
  showToolbar?: boolean;
  /** Tailwind height for the canvas block */
  height?: string;
}

/**
 * Skeleton for graph / diagram canvases (React Flow, ER diagrams, ontology).
 */
export function GraphCanvasSkeleton({
  showFilterPanel = false,
  showToolbar = true,
  height = 'h-[600px]',
}: GraphCanvasSkeletonProps) {
  return (
    <div className="space-y-3">
      {showToolbar && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-9 w-24" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-9" />
            <Skeleton className="h-9 w-9" />
            <Skeleton className="h-9 w-32" />
          </div>
        </div>
      )}
      <div className="flex gap-3">
        {showFilterPanel && (
          <div className="w-64 shrink-0 border rounded-lg p-4 space-y-3">
            <Skeleton className="h-5 w-32" />
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Skeleton className="h-4 w-4" />
                  <Skeleton className="h-4 flex-1" />
                </div>
              ))}
            </div>
          </div>
        )}
        <Skeleton className={`${height} flex-1 rounded-lg`} />
      </div>
    </div>
  );
}

interface WorkflowCanvasSkeletonProps {
  /** Show the right-hand inspector panel */
  showSidebar?: boolean;
  /** Tailwind height class for the canvas */
  height?: string;
}

/**
 * Skeleton for the Workflow Designer full-height layout.
 * Renders a top toolbar, a flow canvas and an optional inspector panel.
 */
export function WorkflowCanvasSkeleton({
  showSidebar = true,
  height = 'h-[calc(100vh-12rem)]',
}: WorkflowCanvasSkeletonProps) {
  return (
    <div className={`flex flex-col gap-3 ${height}`.trim()}>
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-9" />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-28" />
        </div>
      </div>

      {/* Canvas + sidebar */}
      <div className="flex gap-3 flex-1">
        <Skeleton className="flex-1 rounded-lg" />
        {showSidebar && (
          <div className="w-72 shrink-0 border rounded-lg p-4 space-y-3">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-32" />
            <div className="space-y-2 pt-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="space-y-1">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface HierarchyDetailSkeletonProps {
  /** Show the depth / view-mode controls bar */
  showControls?: boolean;
  /** Number of tree-row placeholders */
  treeRows?: number;
}

/**
 * Skeleton for the right-hand detail pane of the Hierarchy Browser.
 * Includes an icon header, badge row, control bar, and tree rows.
 */
export function HierarchyDetailSkeleton({
  showControls = true,
  treeRows = 6,
}: HierarchyDetailSkeletonProps) {
  return (
    <div className="space-y-4 p-4">
      {/* Icon + title + badges */}
      <div className="flex items-center gap-3">
        <Skeleton className="h-9 w-9 rounded" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-3 w-40" />
        </div>
        <Skeleton className="h-9 w-24" />
      </div>

      <div className="flex gap-2">
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-16" />
      </div>

      {showControls && (
        <div className="flex items-center gap-2 border-t pt-3">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-8 w-28" />
          <div className="ml-auto flex gap-2">
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        {[...Array(treeRows)].map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-2"
            style={{ paddingLeft: `${(i % 3) * 16}px` }}
          >
            <Skeleton className="h-4 w-4" />
            <Skeleton
              className="h-4"
              style={{ width: `${Math.round(Math.random() * 40 + 140)}px` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

interface FilterBarSkeletonProps {
  /** Number of filter dropdown stubs */
  filterCount?: number;
  /** Show a search input on the left */
  withSearch?: boolean;
  /** Show a trailing action button (e.g. clear filters) */
  withAction?: boolean;
}

/**
 * Skeleton for a filter row (search + N filter dropdowns + optional action).
 * Use above tables, hierarchical browsers, etc.
 */
export function FilterBarSkeleton({
  filterCount = 3,
  withSearch = true,
  withAction = false,
}: FilterBarSkeletonProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {withSearch && <Skeleton className="h-9 w-64" />}
      {[...Array(filterCount)].map((_, i) => (
        <Skeleton key={i} className="h-9 w-32" />
      ))}
      {withAction && <Skeleton className="h-9 w-24 ml-auto" />}
    </div>
  );
}
