import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import SchemaBrowser from '@/components/schema-importer/schema-browser';
import type { Connection } from '@/types/connections';

export interface CatalogSchemaResult {
  name: string;
  physicalName: string;
  description: string;
  physicalType: string;
  properties: Array<{
    name: string;
    physicalType: string;
    logicalType: string;
    required: boolean;
    description: string;
    partitioned: boolean;
  }>;
}

interface InferFromCatalogDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onInfer: (schemas: CatalogSchemaResult[]) => void;
}

export default function InferFromCatalogDialog({
  isOpen,
  onOpenChange,
  onInfer,
}: InferFromCatalogDialogProps) {
  const { get: apiGet } = useApi();
  const { t } = useTranslation(['data-contracts', 'common']);

  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoadingConnections, setIsLoadingConnections] = useState(true);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [isInferring, setIsInferring] = useState(false);

  const fetchConnections = useCallback(async () => {
    setIsLoadingConnections(true);
    try {
      const resp = await apiGet<Connection[]>('/api/connections');
      if (resp.data) {
        const enabled = resp.data.filter((c) => c.enabled);
        setConnections(enabled);
        if (enabled.length === 1) {
          setSelectedConnectionId(enabled[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch connections:', err);
    } finally {
      setIsLoadingConnections(false);
    }
  }, [apiGet]);

  useEffect(() => {
    if (isOpen) {
      fetchConnections();
      setSelectedConnectionId(null);
      setSelectedPaths(new Set());
    }
  }, [isOpen, fetchConnections]);

  const handleConnectionChange = (id: string) => {
    setSelectedConnectionId(id);
    setSelectedPaths(new Set());
  };

  const handleInfer = async () => {
    if (!selectedConnectionId || selectedPaths.size === 0) return;

    setIsInferring(true);
    const schemas: CatalogSchemaResult[] = [];

    try {
      for (const path of selectedPaths) {
        const resp = await fetch(
          `/api/schema-import/metadata/${selectedConnectionId}?path=${encodeURIComponent(path)}`
        );
        if (!resp.ok) continue;
        const metadata = await resp.json();

        const columns = metadata.schema_info?.columns || [];
        schemas.push({
          name: metadata.name || path.split('.').pop() || path,
          physicalName: metadata.path || metadata.identifier || path,
          description: metadata.description || metadata.comment || '',
          physicalType: metadata.asset_type || 'table',
          properties: columns.map((c: any) => ({
            name: c.name || '',
            physicalType: c.data_type || '',
            logicalType: c.logical_type || 'string',
            required: c.nullable === undefined ? false : !c.nullable,
            description: c.description || '',
            partitioned: c.is_partition_key || false,
          })),
        });
      }

      if (schemas.length > 0) {
        onInfer(schemas);
      }
    } finally {
      setIsInferring(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="w-[85vw] max-w-5xl h-[80vh] max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('data-contracts:infer.catalogDialogTitle', 'Infer Schema from Catalog')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:infer.catalogDialogDescription', 'Browse a connected catalog and select tables or views to infer their schema into this contract.')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 flex flex-col min-h-0 gap-4">
          {/* Connection selector */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="text-sm font-medium whitespace-nowrap">{t('data-contracts:infer.connectionLabel', 'Connection:')}</span>
            {isLoadingConnections ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common:states.loading')}
              </div>
            ) : connections.length === 0 ? (
              <span className="text-sm text-muted-foreground">
                {t('data-contracts:infer.noConnections', 'No connections configured. Add one in Settings > Connectors.')}
              </span>
            ) : (
              <Select
                value={selectedConnectionId || ''}
                onValueChange={handleConnectionChange}
              >
                <SelectTrigger className="w-[300px]">
                  <SelectValue placeholder={t('data-contracts:infer.chooseConnection', 'Choose connection...')} />
                </SelectTrigger>
                <SelectContent>
                  {connections.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      <div className="flex items-center gap-2">
                        <span>{c.name}</span>
                        <Badge variant="outline" className="text-[10px] px-1 py-0">
                          {c.connector_type}
                        </Badge>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {selectedPaths.size > 0 && (
              <Badge variant="secondary">{t('data-contracts:infer.selectedCount', '{{count}} selected', { count: selectedPaths.size })}</Badge>
            )}
          </div>

          {/* Schema browser */}
          <div className="flex-1 min-h-0 overflow-auto border rounded-md p-2">
            <SchemaBrowser
              connectionId={selectedConnectionId}
              selectedPaths={selectedPaths}
              onSelectionChange={setSelectedPaths}
            />
          </div>
        </div>

        <DialogFooter className="flex-shrink-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleInfer}
            disabled={selectedPaths.size === 0 || isInferring}
          >
            {isInferring && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {selectedPaths.size > 0
              ? t('data-contracts:infer.inferSchemasButton', {
                  count: selectedPaths.size,
                  defaultValue: 'Infer {{count}} Schema',
                  defaultValue_other: 'Infer {{count}} Schemas',
                })
              : t('data-contracts:infer.inferSchema', 'Infer Schema')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
