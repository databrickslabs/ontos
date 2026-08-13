import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Reusable client-side pagination primitive (Concept Builder v2 polish).
//
// A single small helper reused by every long-list surface (Define in-progress
// runs, Enrich coverage matrix, Concepts list view, Version history) so we get
// one consistent "Prev / Page X of Y / Next" control instead of four bespoke
// paginators. Matches the neutral shadcn theme + lucide icons already in use.
//
//   const { pageItems, page, setPage, pageCount } = usePagination(items, 10);
//   ...render pageItems...
//   <PaginationControls page={page} pageCount={pageCount} onPageChange={setPage} />
// ---------------------------------------------------------------------------

export interface UsePaginationResult<T> {
  /** The slice of items for the current page. */
  pageItems: T[];
  /** 1-based current page. */
  page: number;
  /** Set the current page (clamped to [1, pageCount]). */
  setPage: (page: number) => void;
  /** Total number of pages (>= 1). */
  pageCount: number;
}

export function usePagination<T>(items: T[], pageSize: number): UsePaginationResult<T> {
  const [page, setPageRaw] = useState(1);

  const pageCount = Math.max(1, Math.ceil(items.length / Math.max(1, pageSize)));

  // Clamp the page if the underlying list shrinks (filtering, deletes) so we
  // never strand the user on an empty page past the end.
  useEffect(() => {
    if (page > pageCount) setPageRaw(pageCount);
  }, [page, pageCount]);

  const setPage = (next: number) => {
    setPageRaw(Math.min(Math.max(1, next), pageCount));
  };

  const pageItems = useMemo(() => {
    const clamped = Math.min(Math.max(1, page), pageCount);
    const start = (clamped - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, page, pageCount, pageSize]);

  return { pageItems, page: Math.min(page, pageCount), setPage, pageCount };
}

interface PaginationControlsProps {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  /** Show first/last jump buttons. Cheap, so on by default. */
  showEdges?: boolean;
  className?: string;
}

// Compact Prev / "Page X of Y" / Next control, with optional first/last jumps.
// Renders nothing when there is only a single page (no clutter on short lists).
export function PaginationControls({
  page,
  pageCount,
  onPageChange,
  showEdges = true,
  className,
}: PaginationControlsProps) {
  const { t } = useTranslation('common');
  if (pageCount <= 1) return null;

  const atStart = page <= 1;
  const atEnd = page >= pageCount;

  return (
    <div className={cn('flex items-center justify-end gap-1.5 pt-1', className)}>
      {showEdges && (
        <Button
          variant="outline"
          size="icon"
          className="h-7 w-7"
          disabled={atStart}
          aria-label={t('pagination.first', 'First page')}
          onClick={() => onPageChange(1)}
        >
          <ChevronsLeft className="h-4 w-4" />
        </Button>
      )}
      <Button
        variant="outline"
        size="icon"
        className="h-7 w-7"
        disabled={atStart}
        aria-label={t('pagination.previous', 'Previous page')}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="px-2 text-xs tabular-nums text-muted-foreground whitespace-nowrap">
        {t('pagination.pageOf', 'Page {{page}} of {{pageCount}}', { page, pageCount })}
      </span>
      <Button
        variant="outline"
        size="icon"
        className="h-7 w-7"
        disabled={atEnd}
        aria-label={t('pagination.next', 'Next page')}
        onClick={() => onPageChange(page + 1)}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      {showEdges && (
        <Button
          variant="outline"
          size="icon"
          className="h-7 w-7"
          disabled={atEnd}
          aria-label={t('pagination.last', 'Last page')}
          onClick={() => onPageChange(pageCount)}
        >
          <ChevronsRight className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

export default PaginationControls;
