/**
 * Data Catalog / Data Dictionary View
 * 
 * Main view for browsing all columns across Unity Catalog tables.
 * Features:
 * - Flat table of all columns (Data Dictionary style)
 * - Table filter dropdown
 * - Column name search
 * - Sortable columns
 * - Click-through to table details
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
  // ChevronDown, // Available for future use
  Database,
  RefreshCw,
  Tag
} from 'lucide-react';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
// CardHeader, CardTitle, CardDescription - Available for future use
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
  TableListResponse,
  TableListItem
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
  console.log("DataCatalog component rendering");
  const { t } = useTranslation(['data-catalog', 'common']);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  // Get initial search from URL params (supports both 'search' and 'concept' for semantic links)
  const initialSearch = searchParams.get('search') || searchParams.get('concept') || '';

  // State
  const [columns, setColumns] = useState<ColumnDictionaryEntry[]>([]);
  const [tables, setTables] = useState<TableListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Filters - initialize from URL if available
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [selectedTable, setSelectedTable] = useState<string>('all');
  
  // Sorting
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    field: 'column_name',
    direction: 'asc'
  });
  
  // Stats
  const [tableCount, setTableCount] = useState(0);
  const [columnCount, setColumnCount] = useState(0);

  // Set breadcrumbs
  useEffect(() => {
    setStaticSegments([
      { label: t('common:home'), path: '/' },
      { label: t('data-catalog:title', 'Data Catalog'), path: '/data-catalog' }
    ]);
    setDynamicTitle('');
  }, [setStaticSegments, setDynamicTitle, t]);

  // Fetch table list for dropdown
  const fetchTableList = useCallback(async () => {
    try {
      const response = await fetch('/api/data-catalog/tables');
      if (!response.ok) throw new Error('Failed to fetch tables');
      const data: TableListResponse = await response.json();
      setTables(data.tables);
    } catch (err) {
      console.error('Error fetching table list:', err);
    }
  }, []);

  // Fetch columns
  const fetchColumns = useCallback(async (tableFilter?: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const params = new URLSearchParams();
      if (tableFilter && tableFilter !== 'all') {
        params.append('table', tableFilter);
      }
      
      const url = `/api/data-catalog/columns${params.toString() ? '?' + params.toString() : ''}`;
      const response = await fetch(url);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch columns: ${response.statusText}`);
      }
      
      const data: DataDictionaryResponse = await response.json();
      setColumns(data.columns);
      setTableCount(data.table_count);
      setColumnCount(data.column_count);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      toast({
        title: t('common:error'),
        description: message,
        variant: 'destructive'
      });
    } finally {
      setIsLoading(false);
    }
  }, [t, toast]);

  // Search columns
  const searchColumns = useCallback(async (query: string) => {
    if (!query.trim()) {
      fetchColumns(selectedTable !== 'all' ? selectedTable : undefined);
      return;
    }
    
    setIsSearching(true);
    
    try {
      const params = new URLSearchParams({ q: query });
      if (selectedTable && selectedTable !== 'all') {
        params.append('table', selectedTable);
      }
      
      const response = await fetch(`/api/data-catalog/columns/search?${params.toString()}`);
      if (!response.ok) throw new Error('Search failed');
      
      const data = await response.json();
      setColumns(data.columns);
      setColumnCount(data.total_count);
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setIsSearching(false);
    }
  }, [selectedTable, fetchColumns]);

  // Initial load - also trigger search if URL param was provided
  useEffect(() => {
    fetchTableList();
    if (initialSearch) {
      // If we have a search from URL, trigger the search
      searchColumns(initialSearch);
    } else {
      fetchColumns();
    }
  }, [fetchTableList, fetchColumns, initialSearch, searchColumns]);

  // Handle table filter change
  useEffect(() => {
    if (selectedTable === 'all') {
      fetchColumns();
    } else {
      fetchColumns(selectedTable);
    }
  }, [selectedTable, fetchColumns]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery) {
        searchColumns(searchQuery);
      }
    }, 300);
    
    return () => clearTimeout(timer);
  }, [searchQuery, searchColumns]);

  // Sort handler
  const handleSort = (field: SortField) => {
    setSortConfig(prev => ({
      field,
      direction: prev.field === field && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  // Sorted columns
  const sortedColumns = useMemo(() => {
    const sorted = [...columns];
    sorted.sort((a, b) => {
      let aVal: string = '';
      let bVal: string = '';
      
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

  // Navigate to table details or contract details
  const handleRowClick = (entry: ColumnDictionaryEntry) => {
    if (entry.table_type === 'CONTRACT' && entry.contract_id) {
      // Navigate to Data Contract details page
      navigate(`/data-contracts/${entry.contract_id}`);
    } else {
      // Navigate to Data Catalog table details for actual UC tables
      navigate(`/data-catalog/${encodeURIComponent(entry.table_full_name)}`);
    }
  };

  // Render sort header
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

  // Get display label for column
  const getDisplayLabel = (entry: ColumnDictionaryEntry): string => {
    return entry.column_label || entry.column_name;
  };

  // Truncate description
  const truncateDescription = (desc: string | null, maxLength: number = 100): string => {
    if (!desc) return '—';
    if (desc.length <= maxLength) return desc;
    return desc.substring(0, maxLength) + '...';
  };

  return (
    <div className="flex flex-col h-full p-6 gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {t('data-catalog:title', 'Data Dictionary')} 
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
            setSearchQuery('');
            setSelectedTable('all');
            fetchColumns();
          }}
          disabled={isLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          {t('common:refresh', 'Refresh')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        {/* Table Filter Dropdown */}
        <Select value={selectedTable} onValueChange={setSelectedTable}>
          <SelectTrigger className="w-[300px]">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-muted-foreground" />
              <SelectValue>
                {selectedTable === 'all' 
                  ? `All Tables (${columnCount} Columns)` 
                  : tables.find(t => t.full_name === selectedTable)?.name || selectedTable}
              </SelectValue>
            </div>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              <div className="flex items-center justify-between w-full gap-4">
                <span>All Tables</span>
                <Badge variant="secondary" className="ml-auto">{columnCount}</Badge>
              </div>
            </SelectItem>
            {tables.map((table) => (
              <SelectItem key={table.full_name} value={table.full_name}>
                <div className="flex items-center justify-between w-full gap-4">
                  <span className="truncate max-w-[200px]" title={table.full_name}>
                    {table.name}
                  </span>
                  <Badge variant="secondary" className="ml-auto">{table.column_count}</Badge>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t('data-catalog:searchPlaceholder', 'Search columns...')}
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
                    <TableHead className="min-w-[300px]">
                      {t('data-catalog:columns.description', 'Description')}
                    </TableHead>
                    <SortHeader field="column_name">
                      {t('data-catalog:columns.columnName', 'Column Name')}
                    </SortHeader>
                    <SortHeader field="column_type">
                      {t('data-catalog:columns.type', 'Type')}
                    </SortHeader>
                    <TableHead className="min-w-[150px]">
                      {t('data-catalog:columns.businessTerms', 'Business Terms')}
                    </TableHead>
                    <SortHeader field="table_name">
                      {t('data-catalog:columns.tableName', 'Table Name')}
                    </SortHeader>
                    <TableHead className="w-[50px]"></TableHead>
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
                            {entry.business_terms.map((term, termIdx) => (
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

      {/* Footer stats */}
      {!isLoading && !error && (
        <div className="text-sm text-muted-foreground">
          {t('data-catalog:showingColumns', 'Showing {{count}} columns', { count: sortedColumns.length })}
          {searchQuery && ` ${t('data-catalog:matchingSearch', 'matching')} "${searchQuery}"`}
        </div>
      )}
    </div>
  );
};

export default DataCatalog;

