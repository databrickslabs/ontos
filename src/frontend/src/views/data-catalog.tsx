/**
 * Data Catalog / Data Dictionary View
 *
 * Column-centric view for browsing all columns across Data Contracts and Assets.
 * Features:
 * - Server-side pagination
 * - Faceted filters (Asset Type, System, Catalog, Schema)
 * - Full-field search
 * - Sortable columns (client-side within page)
 * - Source provenance badges
 * - Click-through to table/contract details
 */

import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  BookOpen,
  Search,
  Loader2,
  Table as TableIcon,
  Eye,
  ArrowUpDown,
  Database,
  RefreshCw,
  Tag,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';

import type {
  ColumnDictionaryEntry,
  DataDictionaryResponse,
  ColumnSearchResponse,
  HierarchyFilters,
} from '@/types/data-catalog';

// =============================================================================
// Types
// =============================================================================

type SortField = 'column_label' | 'column_name' | 'table_name' | 'column_type';
type SortDirection = 'asc' | 'desc';

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

// =============================================================================
// Component
// =============================================================================

const DataCatalog: React.FC = () => {
  const { t } = useTranslation(['data-catalog', 'common']);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const initialSearch = searchParams.get('search') || searchParams.get('concept') || '';

  // Data state
  const [columns, setColumns] = useState<ColumnDictionaryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pagination
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);
  const [tableCount, setTableCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [hierarchyFilters, setHierarchyFilters] = useState<HierarchyFilters | null>(null);
  const [selectedAssetType, setSelectedAssetType] = useState<string>('all');
  const [selectedSystem, setSelectedSystem] = useState<string>('all');
  const [selectedCatalog, setSelectedCatalog] = useState<string>('all');
  const [selectedSchema, setSelectedSchema] = useState<string>('all');

  // Sorting (client-side within page)
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    field: 'column_name',
    direction: 'asc',
  });

  // Set breadcrumbs
  useEffect(() => {
    setStaticSegments([
      { label: t('common:home'), path: '/' },
      { label: t('data-catalog:title', 'Data Catalog'), path: '/data-catalog' },
    ]);
    setDynamicTitle('');
  }, [setStaticSegments, setDynamicTitle, t]);

  // Fetch hierarchy filter values
  const fetchHierarchy = useCallback(async () => {
    try {
      const response = await fetch('/api/data-catalog/hierarchy');
      if (!response.ok) return;
      const data: HierarchyFilters = await response.json();
      setHierarchyFilters(data);
    } catch (err) {
      console.error('Error fetching hierarchy filters:', err);
    }
  }, []);

  // Build query params for API calls
  const buildFilterParams = useCallback(() => {
    const params = new URLSearchParams();
    if (selectedAssetType !== 'all') params.append('asset_type', selectedAssetType);
    if (selectedSystem !== 'all') params.append('system', selectedSystem);
    if (selectedCatalog !== 'all') params.append('catalog', selectedCatalog);
    if (selectedSchema !== 'all') params.append('schema', selectedSchema);
    return params;
  }, [selectedAssetType, selectedSystem, selectedCatalog, selectedSchema]);

  // Fetch columns (paginated)
  const fetchColumns = useCallback(async (currentOffset: number) => {
    setIsLoading(true);
    setError(null);

    try {
      const params = buildFilterParams();
      params.set('offset', String(currentOffset));
      params.set('limit', String(pageSize));

      const response = await fetch(`/api/data-catalog/columns?${params.toString()}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch columns: ${response.statusText}`);
      }

      const data: DataDictionaryResponse = await response.json();
      setColumns(data.columns);
      setTableCount(data.table_count);
      setTotalCount(data.column_count);
      setHasMore(data.has_more);
      setOffset(data.offset);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      toast({
        title: t('common:error'),
        description: message,
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  }, [buildFilterParams, pageSize, t, toast]);

  // Search columns (paginated)
  const searchColumns = useCallback(async (query: string, currentOffset: number) => {
    if (!query.trim()) {
      fetchColumns(0);
      return;
    }

    setIsSearching(true);

    try {
      const params = buildFilterParams();
      params.set('q', query);
      params.set('offset', String(currentOffset));
      params.set('limit', String(pageSize));

      const response = await fetch(`/api/data-catalog/columns/search?${params.toString()}`);
      if (!response.ok) throw new Error('Search failed');

      const data: ColumnSearchResponse = await response.json();
      setColumns(data.columns);
      setTotalCount(data.total_count);
      setHasMore(data.has_more);
      setOffset(data.offset);
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setIsSearching(false);
      setIsLoading(false);
    }
  }, [buildFilterParams, fetchColumns, pageSize]);

  // Initial load
  useEffect(() => {
    fetchHierarchy();
    if (initialSearch) {
      searchColumns(initialSearch, 0);
    } else {
      fetchColumns(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch when filters change
  useEffect(() => {
    setOffset(0);
    if (searchQuery.trim()) {
      searchColumns(searchQuery, 0);
    } else {
      fetchColumns(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAssetType, selectedSystem, selectedCatalog, selectedSchema, pageSize]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      setOffset(0);
      if (searchQuery.trim()) {
        searchColumns(searchQuery, 0);
      } else {
        fetchColumns(0);
      }
    }, 300);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery]);

  // Pagination handlers
  const handleNextPage = () => {
    const newOffset = offset + pageSize;
    if (searchQuery.trim()) {
      searchColumns(searchQuery, newOffset);
    } else {
      fetchColumns(newOffset);
    }
  };

  const handlePrevPage = () => {
    const newOffset = Math.max(0, offset - pageSize);
    if (searchQuery.trim()) {
      searchColumns(searchQuery, newOffset);
    } else {
      fetchColumns(newOffset);
    }
  };

  // Sort handler
  const handleSort = (field: SortField) => {
    setSortConfig((prev) => ({
      field,
      direction: prev.field === field && prev.direction === 'asc' ? 'desc' : 'asc',
    }));
  };

  // Sorted columns (client-side within page)
  const sortedColumns = useMemo(() => {
    const sorted = [...columns];
    sorted.sort((a, b) => {
      let aVal = '';
      let bVal = '';

      switch (sortConfig.field) {
        case 'column_label':
          aVal = a.column_label || a.column_name;
          bVal = b.column_label || b.column_name;
          break;
        case 'column_name':
          aVal = a.column_name;
          bVal = b.column_name;
          break;
        case 'table_name':
          aVal = a.table_name;
          bVal = b.table_name;
          break;
        case 'column_type':
          aVal = a.column_type;
          bVal = b.column_type;
          break;
      }

      const comparison = aVal.localeCompare(bVal);
      return sortConfig.direction === 'asc' ? comparison : -comparison;
    });
    return sorted;
  }, [columns, sortConfig]);

  // Clear all filters
  const clearFilters = () => {
    setSelectedAssetType('all');
    setSelectedSystem('all');
    setSelectedCatalog('all');
    setSelectedSchema('all');
    setSearchQuery('');
  };

  const hasActiveFilters =
    selectedAssetType !== 'all' ||
    selectedSystem !== 'all' ||
    selectedCatalog !== 'all' ||
    selectedSchema !== 'all';

  // Navigate to table details or contract details
  const handleRowClick = (entry: ColumnDictionaryEntry) => {
    if (entry.table_type === 'CONTRACT' && entry.contract_id) {
      navigate(`/data-contracts/${entry.contract_id}`);
    } else if (entry.asset_id) {
      navigate(`/assets/${entry.asset_id}`);
    } else {
      navigate(`/data-catalog/${encodeURIComponent(entry.table_full_name)}`);
    }
  };

  // Render helpers
  const SortHeader: React.FC<{ field: SortField; children: React.ReactNode }> = ({ field, children }) => (
    <TableHead
      className="cursor-pointer hover:bg-muted/50 select-none"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center gap-1">
        {children}
        <ArrowUpDown className={`h-3.5 w-3.5 ${sortConfig.field === field ? 'opacity-100' : 'opacity-40'}`} />
      </div>
    </TableHead>
  );

  const getDisplayLabel = (entry: ColumnDictionaryEntry): string => {
    return entry.column_label || entry.column_name;
  };

  const truncateDescription = (desc: string | null, maxLength: number = 100): string => {
    if (!desc) return '—';
    if (desc.length <= maxLength) return desc;
    return desc.substring(0, maxLength) + '...';
  };

  const getSourceBadge = (source: string) => {
    switch (source) {
      case 'both':
        return <Badge variant="default" className="text-[10px] px-1.5 py-0">Both</Badge>;
      case 'asset':
        return <Badge variant="secondary" className="text-[10px] px-1.5 py-0">Asset</Badge>;
      case 'contract':
        return <Badge variant="outline" className="text-[10px] px-1.5 py-0">Contract</Badge>;
      default:
        return null;
    }
  };

  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div className="flex flex-col h-full p-6 gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {t('data-catalog:title', 'Data Catalog')}
              {!isLoading && <span className="text-muted-foreground ml-2">({tableCount} Tables)</span>}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t('data-catalog:subtitle', 'Browse all columns across Unity Catalog tables and views')}
            </p>
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            clearFilters();
            fetchColumns(0);
          }}
          disabled={isLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          {t('common:refresh', 'Refresh')}
        </Button>
      </div>

      {/* Faceted Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Asset Type */}
        <Select value={selectedAssetType} onValueChange={setSelectedAssetType}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Asset Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            {hierarchyFilters?.asset_types.map((type) => (
              <SelectItem key={type} value={type}>{type}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* System */}
        {hierarchyFilters && hierarchyFilters.systems.length > 0 && (
          <Select value={selectedSystem} onValueChange={setSelectedSystem}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="System" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Systems</SelectItem>
              {hierarchyFilters.systems.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Catalog */}
        {hierarchyFilters && hierarchyFilters.catalogs.length > 0 && (
          <Select value={selectedCatalog} onValueChange={setSelectedCatalog}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Catalog" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Catalogs</SelectItem>
              {hierarchyFilters.catalogs.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Schema */}
        {hierarchyFilters && hierarchyFilters.schemas.length > 0 && (
          <Select value={selectedSchema} onValueChange={setSelectedSchema}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Schema" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Schemas</SelectItem>
              {hierarchyFilters.schemas.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Clear filters */}
        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="h-4 w-4 mr-1" />
            Clear
          </Button>
        )}

        {/* Search */}
        <div className="relative flex-1 max-w-md ml-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t('data-catalog:searchPlaceholder', 'Search columns, tables, terms...')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
          {isSearching && (
            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
          )}
        </div>
      </div>

      {/* Data Table */}
      <Card className="flex-1 flex flex-col min-h-0">
        <CardContent className="flex-1 p-0 min-h-0">
          {isLoading ? (
            <div className="p-6 space-y-4">
              {[...Array(10)].map((_, i) => (
                <div key={i} className="flex gap-4">
                  <Skeleton className="h-6 w-32" />
                  <Skeleton className="h-6 flex-1" />
                  <Skeleton className="h-6 w-24" />
                  <Skeleton className="h-6 w-40" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
              <p className="text-lg mb-2">{t('common:error')}</p>
              <p className="text-sm">{error}</p>
            </div>
          ) : sortedColumns.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
              <TableIcon className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-lg mb-2">{t('data-catalog:noResults', 'No columns found')}</p>
              <p className="text-sm">
                {searchQuery
                  ? t('data-catalog:tryDifferentSearch', 'Try a different search term')
                  : t('data-catalog:noTablesAccessible', 'No tables accessible in Unity Catalog')}
              </p>
            </div>
          ) : (
            <ScrollArea className="h-full">
              <Table>
                <TableHeader className="sticky top-0 bg-background z-10">
                  <TableRow>
                    <SortHeader field="column_label">
                      {t('data-catalog:columns.label', 'Label')}
                    </SortHeader>
                    <TableHead className="min-w-[250px]">
                      {t('data-catalog:columns.description', 'Description')}
                    </TableHead>
                    <SortHeader field="column_name">
                      {t('data-catalog:columns.columnName', 'Column Name')}
                    </SortHeader>
                    <SortHeader field="column_type">
                      {t('data-catalog:columns.type', 'Type')}
                    </SortHeader>
                    <TableHead className="min-w-[120px]">
                      {t('data-catalog:columns.businessTerms', 'Business Terms')}
                    </TableHead>
                    <SortHeader field="table_name">
                      {t('data-catalog:columns.tableName', 'Table Name')}
                    </SortHeader>
                    <TableHead className="w-[70px]">Source</TableHead>
                    <TableHead className="w-[40px]"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedColumns.map((entry, idx) => (
                    <TableRow
                      key={`${entry.table_full_name}-${entry.column_name}-${idx}`}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => handleRowClick(entry)}
                    >
                      <TableCell className="font-medium">
                        {getDisplayLabel(entry)}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {truncateDescription(entry.description)}
                      </TableCell>
                      <TableCell>
                        <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                          {entry.column_name}
                        </code>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-mono text-xs">
                          {entry.column_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {entry.business_terms && entry.business_terms.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {entry.business_terms.slice(0, 2).map((term, termIdx) => (
                              <Badge
                                key={`${term.iri}-${termIdx}`}
                                variant="secondary"
                                className="text-xs cursor-pointer hover:bg-primary/20 transition-colors"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigate(`/semantic-models?concept=${encodeURIComponent(term.iri)}`);
                                }}
                                title={term.iri}
                              >
                                <Tag className="h-3 w-3 mr-1" />
                                {term.label || term.iri.split('#').pop()?.split('/').pop() || 'Term'}
                              </Badge>
                            ))}
                            {entry.business_terms.length > 2 && (
                              <Badge variant="secondary" className="text-xs">
                                +{entry.business_terms.length - 2}
                              </Badge>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm" title={entry.table_full_name}>
                          {entry.table_name}
                        </span>
                      </TableCell>
                      <TableCell>
                        {getSourceBadge(entry.source)}
                      </TableCell>
                      <TableCell>
                        <Eye className="h-4 w-4 text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      {/* Pagination Footer */}
      {!isLoading && !error && totalCount > 0 && (
        <div className="flex items-center justify-between text-sm">
          <div className="text-muted-foreground">
            Showing {offset + 1}–{Math.min(offset + pageSize, totalCount)} of {totalCount.toLocaleString()} columns
            {searchQuery && ` matching "${searchQuery}"`}
          </div>

          <div className="flex items-center gap-4">
            {/* Page size selector */}
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Per page:</span>
              <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
                <SelectTrigger className="w-[70px] h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="25">25</SelectItem>
                  <SelectItem value="50">50</SelectItem>
                  <SelectItem value="100">100</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Page navigation */}
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handlePrevPage}
                disabled={offset === 0}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-muted-foreground">
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleNextPage}
                disabled={!hasMore}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DataCatalog;
