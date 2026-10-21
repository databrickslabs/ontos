import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  Loader2, AlertCircle, ChevronRight, ChevronDown, Database,
  Table2, Eye, Columns2, FileText, Package, ExternalLink,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useApi } from '@/hooks/use-api';
import { cn } from '@/lib/utils';
import type { ProductHierarchy, HierarchyDataset, HierarchyTableOrView, HierarchyColumn } from '@/types/ontology-schema';

interface ProductHierarchyPanelProps {
  productId: string;
  className?: string;
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
};

function ColumnNode({ column }: { column: HierarchyColumn }) {
  const dataType = column.properties?.data_type;
  return (
    <div className="flex items-center gap-2 pl-14 py-1 text-sm hover:bg-muted/50 rounded-md">
      <Columns2 className="h-3.5 w-3.5 text-slate-400 flex-shrink-0" />
      <span className="text-muted-foreground">{column.name}</span>
      {dataType && (
        <Badge variant="outline" className="text-xs font-mono">{dataType}</Badge>
      )}
    </div>
  );
}

function TableNode({ table, type }: { table: HierarchyTableOrView; type: 'table' | 'view' }) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const Icon = type === 'table' ? Table2 : Eye;
  const hasColumns = table.columns && table.columns.length > 0;

  return (
    <div>
      <button
        onClick={() => hasColumns && setExpanded(!expanded)}
        className={cn(
          'w-full flex items-center gap-2 pl-8 py-1.5 text-sm rounded-md transition-colors',
          hasColumns ? 'hover:bg-muted cursor-pointer' : 'cursor-default'
        )}
      >
        {hasColumns ? (
          expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
            : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
        ) : (
          <span className="w-3.5 flex-shrink-0" />
        )}
        <Icon className="h-4 w-4 text-blue-500 flex-shrink-0" />
        <span className="truncate flex-1 text-left">{table.name}</span>
        {table.location && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-xs text-muted-foreground font-mono truncate max-w-48">
                {table.location}
              </span>
            </TooltipTrigger>
            <TooltipContent>{table.location}</TooltipContent>
          </Tooltip>
        )}
        <Badge variant={STATUS_VARIANT[table.status] || 'outline'} className="text-xs flex-shrink-0">
          {table.status}
        </Badge>
        {hasColumns && (
          <Badge variant="secondary" className="text-xs flex-shrink-0">{table.columns.length} cols</Badge>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 flex-shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/assets/${table.id}`);
          }}
        >
          <ExternalLink className="h-3 w-3" />
        </Button>
      </button>
      {expanded && hasColumns && (
        <div className="ml-2">
          {table.columns.map((col) => (
            <ColumnNode key={col.id} column={col} />
          ))}
        </div>
      )}
    </div>
  );
}

function DatasetNode({ dataset }: { dataset: HierarchyDataset }) {
  const [expanded, setExpanded] = useState(true);
  const navigate = useNavigate();
  const { t } = useTranslation(['data-products', 'common']);
  const tableCount = (dataset.tables?.length || 0) + (dataset.views?.length || 0);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 py-2 px-2 rounded-md hover:bg-muted transition-colors"
      >
        {expanded
          ? <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          : <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
        }
        <Database className="h-4 w-4 text-emerald-500 flex-shrink-0" />
        <span className="font-medium text-sm truncate flex-1 text-left">{dataset.name}</span>
        <Badge variant={STATUS_VARIANT[dataset.status] || 'outline'} className="text-xs flex-shrink-0">
          {dataset.status}
        </Badge>
        <Badge variant="secondary" className="text-xs flex-shrink-0">
          {tableCount} {tableCount === 1 ? 'object' : 'objects'}
        </Badge>
        {dataset.contract && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="text-xs flex-shrink-0">
                <FileText className="h-3 w-3 mr-1" />
                Contract
              </Badge>
            </TooltipTrigger>
            <TooltipContent>Governed by contract {dataset.contract.id}</TooltipContent>
          </Tooltip>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 flex-shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/assets/${dataset.dataset_id}`);
          }}
        >
          <ExternalLink className="h-3 w-3" />
        </Button>
      </button>

      {expanded && (
        <div className="ml-2 border-l border-border pl-1">
          {dataset.description && (
            <p className="text-xs text-muted-foreground pl-8 py-1">{dataset.description}</p>
          )}
          {dataset.tables?.map((t) => (
            <TableNode key={t.id} table={t} type="table" />
          ))}
          {dataset.views?.map((v) => (
            <TableNode key={v.id} table={v} type="view" />
          ))}
          {tableCount === 0 && (
            <p className="text-xs text-muted-foreground pl-8 py-2 italic">{t('data-products:hierarchy.noTablesOrViews')}</p>
          )}
        </div>
      )}
    </div>
  );
}

export function ProductHierarchyPanel({ productId, className }: ProductHierarchyPanelProps) {
  const [hierarchy, setHierarchy] = useState<ProductHierarchy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { get: apiGet } = useApi();

  const fetchHierarchy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiGet<ProductHierarchy>(
        `/api/data-products/${productId}/hierarchy`
      );
      if (response.error) throw new Error(response.error);
      setHierarchy(response.data ?? null);
    } catch (err: any) {
      setError(err.message || 'Failed to load hierarchy');
    } finally {
      setLoading(false);
    }
  }, [apiGet, productId]);

  useEffect(() => {
    fetchHierarchy();
  }, [fetchHierarchy]);

  if (loading) {
    return (
      <Card className={className}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Package className="h-4 w-4" />
            Data Hierarchy
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={className}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Package className="h-4 w-4" />
            Data Hierarchy
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const datasets = hierarchy?.datasets || [];

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Package className="h-4 w-4" />
            Data Hierarchy
          </CardTitle>
          <Badge variant="secondary" className="text-xs">
            {datasets.length} {datasets.length === 1 ? 'dataset' : 'datasets'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {datasets.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No datasets linked to this data product yet.
          </p>
        ) : (
          <div className="space-y-1">
            {datasets.map((ds) => (
              <DatasetNode key={ds.dataset_id} dataset={ds} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
