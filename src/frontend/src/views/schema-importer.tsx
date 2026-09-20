import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Import, Loader2, Eye } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { Connection } from '@/types/connections';
import type { ImportDepth, ImportResult, SchemaImportRunDetail } from '@/types/schema-import';
import SchemaBrowser from '@/components/schema-importer/schema-browser';
import ImportPreviewDialog from '@/components/schema-importer/import-preview-dialog';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { useToast } from '@/hooks/use-toast';

export default function SchemaImporterView() {
  const { t } = useTranslation(['settings', 'common']);
  const appName = useUICustomizationStore((s) => s.getAppName());
  const { get: apiGet } = useApi();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoadingConnections, setIsLoadingConnections] = useState(true);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [importDepth, setImportDepth] = useState<ImportDepth>('full_recursive');
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  // Result-only view for a completed run reopened from its notification (?runId=).
  const [runResult, setRunResult] = useState<ImportResult | null>(null);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('settings:schemaImporter.title', 'Schema Importer'));
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [t, setStaticSegments, setDynamicTitle]);

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
    fetchConnections();
  }, [fetchConnections]);

  // Reopen a completed background import's result when deep-linked via ?runId=
  // (from the completion notification's "Open" button).
  const runIdParam = searchParams.get('runId');
  useEffect(() => {
    if (!runIdParam) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiGet<SchemaImportRunDetail>(`/api/schema-import/runs/${runIdParam}`);
        if (cancelled) return;
        if (resp.data?.result) {
          setRunResult(resp.data.result);
        } else {
          toast({
            title: 'Import still running',
            description: "You'll be notified when it completes.",
          });
        }
      } catch (err) {
        console.error('Failed to load import run:', err);
        toast({ title: 'Could not load import result', description: String(err), variant: 'destructive' });
      }
    })();
    return () => { cancelled = true; };
  }, [runIdParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const closeRunResult = () => {
    setRunResult(null);
    // Drop ?runId= so a refresh/re-close doesn't reopen the result.
    searchParams.delete('runId');
    setSearchParams(searchParams, { replace: true });
  };

  const handleConnectionChange = (id: string) => {
    setSelectedConnectionId(id);
    setSelectedPaths(new Set());
  };

  const selectedConnection = connections.find((c) => c.id === selectedConnectionId);
  const canPreview = selectedPaths.size > 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">
          {t('settings:schemaImporter.title', 'Schema Importer')}
        </h2>
        <p className="text-muted-foreground">
          {t(
            'settings:schemaImporter.description',
            'Browse remote systems and import their structure as {{appName}} assets.',
            { appName },
          )}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Left panel: connection + options */}
        <div className="space-y-4">
          {/* Connection selector */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Connection</CardTitle>
              <CardDescription className="text-xs">
                Select a data platform connection
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingConnections ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading...
                </div>
              ) : connections.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No connections configured. Add one in Settings &gt; Connectors.
                </p>
              ) : (
                <Select
                  value={selectedConnectionId || ''}
                  onValueChange={handleConnectionChange}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose connection..." />
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
            </CardContent>
          </Card>

          {/* Import depth */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Import Depth</CardTitle>
              <CardDescription className="text-xs">
                How deep to recurse below selected nodes
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RadioGroup
                value={importDepth}
                onValueChange={(v) => setImportDepth(v as ImportDepth)}
                className="space-y-2"
              >
                <div className="flex items-start gap-2">
                  <RadioGroupItem value="selected_only" id="depth-selected" />
                  <Label htmlFor="depth-selected" className="text-sm font-normal leading-tight cursor-pointer">
                    <span className="font-medium">Selected only</span>
                    <br />
                    <span className="text-xs text-muted-foreground">
                      Import only the selected items
                    </span>
                  </Label>
                </div>
                <div className="flex items-start gap-2">
                  <RadioGroupItem value="one_level" id="depth-one" />
                  <Label htmlFor="depth-one" className="text-sm font-normal leading-tight cursor-pointer">
                    <span className="font-medium">One level</span>
                    <br />
                    <span className="text-xs text-muted-foreground">
                      Selected items + immediate children
                    </span>
                  </Label>
                </div>
                <div className="flex items-start gap-2">
                  <RadioGroupItem value="full_recursive" id="depth-full" />
                  <Label htmlFor="depth-full" className="text-sm font-normal leading-tight cursor-pointer">
                    <span className="font-medium">Full recursive</span>
                    <br />
                    <span className="text-xs text-muted-foreground">
                      Everything nested below selected nodes
                    </span>
                  </Label>
                </div>
              </RadioGroup>
            </CardContent>
          </Card>

          {/* Actions */}
          <div className="flex flex-col gap-2">
            <Button
              onClick={() => setIsPreviewOpen(true)}
              disabled={!canPreview}
              variant="outline"
              className="w-full"
            >
              <Eye className="mr-2 h-4 w-4" />
              Preview ({selectedPaths.size} selected)
            </Button>
            <Button
              onClick={() => setIsPreviewOpen(true)}
              disabled={!canPreview}
              className="w-full"
            >
              <Import className="mr-2 h-4 w-4" />
              Import
            </Button>
          </div>
        </div>

        {/* Right panel: tree browser */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm font-medium">
                  {selectedConnection
                    ? `${selectedConnection.name} — Resources`
                    : 'Resources'}
                </CardTitle>
                <CardDescription className="text-xs">
                  Expand nodes and check the resources you want to import
                </CardDescription>
              </div>
              {selectedPaths.size > 0 && (
                <Badge variant="secondary">{selectedPaths.size} selected</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <SchemaBrowser
              connectionId={selectedConnectionId}
              selectedPaths={selectedPaths}
              onSelectionChange={setSelectedPaths}
            />
          </CardContent>
        </Card>
      </div>

      {/* Preview / Import dialog */}
      {selectedConnectionId && (
        <ImportPreviewDialog
          open={isPreviewOpen}
          onOpenChange={setIsPreviewOpen}
          connectionId={selectedConnectionId}
          selectedPaths={Array.from(selectedPaths)}
          depth={importDepth}
        />
      )}

      {/* Result-only view for a completed run reopened from its notification */}
      {runResult && (
        <ImportPreviewDialog
          open={true}
          onOpenChange={(open) => { if (!open) closeRunResult(); }}
          initialResult={runResult}
        />
      )}
    </div>
  );
}
