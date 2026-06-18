import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { ColumnDef, Column } from '@tanstack/react-table';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Upload, ChevronDown, RefreshCw, Trash2, Loader2, Library, Eye, Copy, Check, Network, FileCode2, Pencil } from 'lucide-react';
import type { SemanticModel } from '@/types/ontology';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import OntologyLibraryDialog from '@/components/settings/ontology-library-dialog';
import { usePermissions } from '@/stores/permissions-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { systemRdfNamespaceDisplayLabel, SYSTEM_RDF_NAMESPACE_KEY_SET } from '@/lib/system-rdf-namespace-labels';
import type { TFunction } from 'i18next';

interface TitleCandidateRow {
  iri: string;
  kind: string;
  text: string;
  lang?: string;
}

function semanticModelDisplayTitle(m: SemanticModel, t: TFunction<'semantic-models', undefined>): string {
  const d = m.display_name?.trim();
  if (d) return d;
  return systemRdfNamespaceDisplayLabel(m.name, t);
}

/** Serialization (syntax) for table — prefer API `serialization`, not vocabulary. */
function semanticModelSerializationLabel(m: SemanticModel, tr: (key: string) => string): string {
  const fromApi = m.serialization?.trim();
  if (fromApi) return fromApi;
  const fn = (m.original_filename || m.name || '').toLowerCase();
  if (fn.endsWith('.ttl') || fn.endsWith('.n3')) return tr('rdfSources.serializationTurtle');
  if (fn.endsWith('.owl') || fn.endsWith('.rdf') || fn.endsWith('.xml')) return tr('rdfSources.serializationRdfXml');
  if (fn.endsWith('.jsonld') || fn.endsWith('.json-ld') || fn.endsWith('.json')) return tr('rdfSources.serializationJsonLd');
  if (fn.endsWith('.nt')) return tr('rdfSources.serializationNTriples');
  if (fn.endsWith('.trig')) return tr('rdfSources.serializationTriG');
  const fmt = (m.format || '').toLowerCase();
  if (fmt === 'skos') return tr('rdfSources.serializationTurtle');
  if (fmt === 'rdfs') return tr('rdfSources.serializationRdfXml');
  if (fmt === 'ttl') return tr('rdfSources.serializationTurtle');
  return tr('rdfSources.serializationUnknown');
}

export default function SemanticModelsSettings() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWriteSemantic = !permissionsLoading && hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);
  const { get, post, delete: deleteApi } = useApi();
  const { toast } = useToast();
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);
  const [items, setItems] = useState<SemanticModel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [modelToDelete, setModelToDelete] = useState<SemanticModel | null>(null);
  const [libraryDialogOpen, setLibraryDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [viewingModel, setViewingModel] = useState<SemanticModel | null>(null);
  const [viewContent, setViewContent] = useState<string>('');
  const [viewLoading, setViewLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isRefreshingGraph, setIsRefreshingGraph] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [listSearch, setListSearch] = useState('');
  const [titleDialogOpen, setTitleDialogOpen] = useState(false);
  const [titleEditModel, setTitleEditModel] = useState<SemanticModel | null>(null);
  const [titleCandidates, setTitleCandidates] = useState<TitleCandidateRow[]>([]);
  const [titleCandidatesLoading, setTitleCandidatesLoading] = useState(false);
  const [titleChoice, setTitleChoice] = useState<string>('custom');
  const [titleCustom, setTitleCustom] = useState('');
  const [titleSaving, setTitleSaving] = useState(false);

  const filteredItems = useMemo(() => 
    items.filter(m => !SYSTEM_RDF_NAMESPACE_KEY_SET.has(m.name)),
    [items]
  );

  const tableData = useMemo(() => {
    const q = listSearch.trim().toLowerCase();
    if (!q) return filteredItems;
    return filteredItems.filter((m) => {
      const title = semanticModelDisplayTitle(m, t).toLowerCase();
      return title.includes(q) || m.name.toLowerCase().includes(q);
    });
  }, [filteredItems, listSearch, t]);

  const fetchItems = async () => {
    setIsLoading(true);
    try {
      const res = await get<{ semantic_models: SemanticModel[] } | SemanticModel[]>('/api/semantic-models');
      const data = (res.data as any);
      const models: SemanticModel[] = Array.isArray(data) ? data : (data?.semantic_models || []);
      setItems(models || []);
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to load models', variant: 'destructive' });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const onRefreshGraph = async () => {
    setIsRefreshingGraph(true);
    try {
      const res = await post<{ message: string }>('/api/semantic-models/refresh-graph', {});
      if (res.error) {
        toast({ title: 'Error', description: res.error, variant: 'destructive' });
      } else {
        toast({ title: 'Success', description: res.data?.message ?? 'Knowledge graph refreshed successfully' });
        await fetchItems();
        // Notify other Concepts/Graph views that cached data is now stale.
        bumpKnowledgeGraphRefresh('rebuild-graph');
      }
    } catch (e: any) {
      toast({ title: 'Error', description: e.message ?? 'Failed to refresh knowledge graph', variant: 'destructive' });
    } finally {
      setIsRefreshingGraph(false);
    }
  };

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    setUploadingId('uploading');
    try {
      const res = await post<{ model: SemanticModel; message: string }>('/api/semantic-models/upload', formData);
      
      if (res.error) {
        toast({ title: 'Upload Failed', description: res.error, variant: 'destructive' });
      } else {
        toast({ title: 'Success', description: res.data.message || 'Semantic model uploaded successfully' });
        await fetchItems();
      }
    } catch (e: any) {
      toast({ title: 'Upload Error', description: e.message || 'Failed to upload file', variant: 'destructive' });
    } finally {
      setUploadingId(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const onToggleEnabled = async (modelId: string, currentEnabled: boolean) => {
    setUploadingId(modelId);
    try {
      const response = await fetch(`/api/semantic-models/${modelId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !currentEnabled }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to update model');
      }

      toast({ title: 'Success', description: `Model ${!currentEnabled ? 'enabled' : 'disabled'} successfully` });
      await fetchItems();
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to update model', variant: 'destructive' });
    } finally {
      setUploadingId(null);
    }
  };

  const onDeleteClick = (model: SemanticModel) => {
    setModelToDelete(model);
    setDeleteDialogOpen(true);
  };

  const onViewClick = async (model: SemanticModel) => {
    setViewingModel(model);
    setViewDialogOpen(true);
    setViewLoading(true);
    setViewContent('');
    setCopied(false);
    
    try {
      const res = await get<{ content: string; format: string; name: string }>(
        `/api/semantic-models/${encodeURIComponent(model.id)}/content`
      );
      if (res.error) {
        toast({ title: 'Error', description: res.error, variant: 'destructive' });
        setViewContent('Failed to load content.');
      } else {
        setViewContent(res.data.content || '');
      }
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to load content', variant: 'destructive' });
      setViewContent('Failed to load content.');
    } finally {
      setViewLoading(false);
    }
  };

  const onCopyContent = async () => {
    try {
      await navigator.clipboard.writeText(viewContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast({ title: 'Error', description: 'Failed to copy to clipboard', variant: 'destructive' });
    }
  };

  const onDeleteConfirm = async () => {
    if (!modelToDelete) return;

    try {
      const res = await deleteApi(`/api/semantic-models/${modelToDelete.id}`);
      
      if (res.error) {
        toast({ title: 'Delete Failed', description: res.error, variant: 'destructive' });
      } else {
        toast({ title: 'Success', description: 'Semantic model deleted successfully' });
        await fetchItems();
      }
    } catch (e: any) {
      toast({ title: 'Delete Error', description: e.message || 'Failed to delete model', variant: 'destructive' });
    } finally {
      setDeleteDialogOpen(false);
      setModelToDelete(null);
    }
  };

  const openTitleDialog = useCallback(
    async (model: SemanticModel) => {
      setTitleEditModel(model);
      setTitleDialogOpen(true);
      setTitleCandidatesLoading(true);
      setTitleCandidates([]);
      setTitleChoice('custom');
      setTitleCustom(model.display_name?.trim() || '');
      try {
        const res = await get<{ candidates: TitleCandidateRow[] }>(
          `/api/semantic-models/${encodeURIComponent(model.id)}/title-candidates`
        );
        if (res.error) {
          toast({ title: t('messages.error'), description: res.error, variant: 'destructive' });
          setTitleCandidatesLoading(false);
          return;
        }
        const candidates = res.data?.candidates ?? [];
        setTitleCandidates(candidates);
        const cur = model.display_name?.trim();
        if (cur) {
          const idx = candidates.findIndex((c) => c.text.trim() === cur);
          if (idx >= 0) {
            setTitleChoice(`c:${idx}`);
          } else {
            setTitleChoice('custom');
            setTitleCustom(cur);
          }
        } else if (candidates.length > 0) {
          setTitleChoice('c:0');
          setTitleCustom(candidates[0].text);
        }
      } catch (e: any) {
        toast({
          title: t('messages.error'),
          description: e.message || t('rdfSources.loadSuggestionsFailed'),
          variant: 'destructive',
        });
      } finally {
        setTitleCandidatesLoading(false);
      }
    },
    [get, toast, t]
  );

  const saveTitleDialog = async () => {
    if (!titleEditModel) return;
    let displayName = '';
    if (titleChoice.startsWith('c:')) {
      const idx = parseInt(titleChoice.slice(2), 10);
      displayName = (titleCandidates[idx]?.text ?? '').trim();
    } else {
      displayName = titleCustom.trim();
    }
    setTitleSaving(true);
    try {
      const response = await fetch(`/api/semantic-models/${encodeURIComponent(titleEditModel.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: displayName }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update title');
      }
      toast({ title: t('messages.success'), description: t('rdfSources.titleSaved') });
      setTitleDialogOpen(false);
      setTitleEditModel(null);
      await fetchItems();
    } catch (e: any) {
      toast({ title: t('messages.error'), description: e.message || 'Failed to save', variant: 'destructive' });
    } finally {
      setTitleSaving(false);
    }
  };

  const clearDisplayTitle = async () => {
    if (!titleEditModel) return;
    setTitleSaving(true);
    try {
      const response = await fetch(`/api/semantic-models/${encodeURIComponent(titleEditModel.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: '' }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to clear title');
      }
      toast({ title: t('messages.success'), description: t('rdfSources.titleSaved') });
      setTitleDialogOpen(false);
      setTitleEditModel(null);
      await fetchItems();
    } catch (e: any) {
      toast({ title: t('messages.error'), description: e.message || 'Failed to clear', variant: 'destructive' });
    } finally {
      setTitleSaving(false);
    }
  };

  const columns = useMemo<ColumnDef<SemanticModel>[]>(() => [
    {
      id: 'displayTitle',
      accessorFn: (row) => semanticModelDisplayTitle(row, t),
      header: ({ column }: { column: Column<SemanticModel, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('rdfSources.nameColumn')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const model = row.original;
        const title = semanticModelDisplayTitle(model, t);
        const showFileHint = Boolean(model.display_name?.trim());
        return (
          <div className="min-w-0">
            <div className="font-medium truncate" title={title}>
              {title}
            </div>
            {showFileHint && (
              <div className="text-xs text-muted-foreground truncate" title={model.name}>
                {model.name}
              </div>
            )}
          </div>
        );
      },
    },
    { 
      id: 'source',
      header: 'Source', 
      cell: ({ row }) => {
        const model = row.original;
        const createdBy = model.created_by || '';
        
        let label = 'Unknown';
        let variant: 'default' | 'secondary' | 'outline' = 'secondary';
        
        if (createdBy === 'system@startup') {
          label = 'System';
          variant = 'outline';
        } else if (createdBy === 'system@file') {
          label = 'File';
          variant = 'secondary';
        } else if (createdBy === 'system@schema') {
          label = 'Schema';
          variant = 'secondary';
        } else if (createdBy.startsWith('system@')) {
          label = 'System';
          variant = 'outline';
        } else if (createdBy && createdBy !== '') {
          label = 'Upload';
          variant = 'default';
        }
        
        return <Badge variant={variant}>{label}</Badge>;
      }
    },
    {
      id: 'serialization',
      accessorFn: (row) => semanticModelSerializationLabel(row, t),
      header: t('rdfSources.syntaxColumn'),
      cell: ({ row }) => (
        <Badge variant="secondary">{semanticModelSerializationLabel(row.original, t)}</Badge>
      ),
    },
    { 
      accessorKey: 'size_bytes', 
      header: 'Size', 
      cell: ({ row }) => {
        const bytes = row.getValue('size_bytes') as number | undefined | null;
        if (bytes === undefined || bytes === null) return <span>-</span>;
        const kb = (bytes / 1024).toFixed(1);
        return <span>{kb} KB</span>;
      }
    },
    {
      accessorKey: 'enabled',
      header: 'Enabled',
      cell: ({ row }) => {
        const model = row.original;
        const isToggling = uploadingId === model.id;
        const isFileBased = model.id?.startsWith('file-');
        const createdBy = model.created_by || '';
        const isSystemManaged = createdBy.startsWith('system@') && createdBy !== 'system@startup';
        
        if (isFileBased || isSystemManaged) {
          return (
            <div data-action-cell="true">
              <Badge variant="outline" className="text-xs">Always On</Badge>
            </div>
          );
        }
        
        return (
          <div data-action-cell="true">
            <Switch
              checked={row.getValue('enabled')}
              onCheckedChange={() => onToggleEnabled(model.id, row.getValue('enabled'))}
              disabled={isToggling}
            />
          </div>
        );
      },
    },
    {
      id: 'actions',
      header: () => <div className="text-right">Actions</div>,
      cell: ({ row }) => {
        const model = row.original;
        const isFileBased = model.id?.startsWith('file-');
        const createdBy = model.created_by || '';
        const isSystemManaged = createdBy.startsWith('system@') && createdBy !== 'system@startup';
        const canDelete = !isFileBased && !isSystemManaged;
        const canEditTitle = canWriteSemantic && !isFileBased && !isSystemManaged;
        
        return (
          <div className="flex items-center justify-end gap-1">
            {canEditTitle && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => openTitleDialog(model)}
                title={t('rdfSources.editDisplayTitle')}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => onViewClick(model)}
              title="View content"
            >
              <Eye className="h-4 w-4" />
            </Button>
            {canDelete && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => onDeleteClick(model)}
                title="Delete model"
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            )}
          </div>
        );
      },
      enableSorting: false,
    },
  ], [uploadingId, canWriteSemantic, t, openTitleDialog]);

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <FileCode2 className="w-8 h-8" />
          RDF Sources
        </h1>
        <p className="text-muted-foreground mt-1">Upload and manage RDF ontology and taxonomy files (RDFS, SKOS, OWL).</p>
      </div>

      <Input ref={fileInputRef} type="file" accept=".ttl,.rdf,.xml,.skos,.rdfs,.owl,.nt,.n3,.trig,.trix,.jsonld,.json" className="hidden" onChange={onUpload} />

      <DataTable
        columns={columns}
        data={tableData}
        searchColumn="name"
        searchValue={listSearch}
        onSearchChange={setListSearch}
        defaultSortColumn="displayTitle"
        isLoading={isLoading}
        storageKey="rdf-sources-sort"
        toolbarActions={
          <div className="flex items-center gap-2">
            <Button 
              variant="default"
              className="h-9"
              onClick={() => setLibraryDialogOpen(true)}
            >
              <Library className="h-4 w-4 mr-2" />
              Industry Library
            </Button>
            <Button 
              variant="outline"
              className="h-9"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingId === 'uploading'}
            >
              {uploadingId === 'uploading' ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Uploading...</>
              ) : (
                <><Upload className="h-4 w-4 mr-2" /> Upload</>
              )}
            </Button>
            <Button
              variant="outline"
              className="h-9"
              onClick={onRefreshGraph}
              disabled={isRefreshingGraph || uploadingId === 'uploading'}
              title={t('rebuildGraphTooltip')}
            >
              {isRefreshingGraph ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> {t('rebuildingGraph')}</>
              ) : (
                <><Network className="h-4 w-4 mr-2" /> {t('rebuildGraph')}</>
              )}
            </Button>
            <Button variant="ghost" className="h-9" onClick={fetchItems} title="Refresh list">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete RDF Source</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete{' '}
              <strong>{modelToDelete ? semanticModelDisplayTitle(modelToDelete, t) : ''}</strong>?
              This action cannot be undone and will remove the model from the semantic graph.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onDeleteConfirm} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={titleDialogOpen}
        onOpenChange={(open) => {
          setTitleDialogOpen(open);
          if (!open) {
            setTitleEditModel(null);
            setTitleCandidates([]);
            setTitleChoice('custom');
            setTitleCustom('');
          }
        }}
      >
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('rdfSources.titleDialog')}</DialogTitle>
            <DialogDescription>{t('rdfSources.titleDialogDescription')}</DialogDescription>
          </DialogHeader>
          {titleCandidatesLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : (
            <RadioGroup value={titleChoice} onValueChange={setTitleChoice} className="space-y-4">
              {titleCandidates.length > 0 && (
                <div className="space-y-3">
                  <Label className="text-muted-foreground text-xs uppercase tracking-wide">
                    {t('rdfSources.suggestedFromFile')}
                  </Label>
                  {titleCandidates.map((c, i) => (
                    <div key={`${c.iri}-${c.text}-${i}`} className="flex items-start gap-3">
                      <RadioGroupItem value={`c:${i}`} id={`title-c-${i}`} className="mt-1 shrink-0" />
                      <Label htmlFor={`title-c-${i}`} className="font-normal cursor-pointer leading-snug min-w-0">
                        <span className="font-medium block">{c.text}</span>
                        <span className="block text-xs text-muted-foreground break-all">
                          {c.kind}
                          {c.lang ? ` · ${c.lang}` : ''}
                        </span>
                      </Label>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex items-start gap-3">
                <RadioGroupItem value="custom" id="title-custom" className="mt-1 shrink-0" />
                <div className="grid gap-2 flex-1 min-w-0">
                  <Label htmlFor="title-custom-input" className="font-normal cursor-pointer">
                    {t('rdfSources.customTitle')}
                  </Label>
                  <Input
                    id="title-custom-input"
                    value={titleCustom}
                    onChange={(e) => setTitleCustom(e.target.value)}
                    onFocus={() => setTitleChoice('custom')}
                    placeholder={titleEditModel?.name ?? ''}
                  />
                </div>
              </div>
            </RadioGroup>
          )}
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between sm:space-x-0">
            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => void clearDisplayTitle()}
              disabled={titleSaving || !titleEditModel?.display_name?.trim()}
            >
              {t('rdfSources.useFilename')}
            </Button>
            <div className="flex gap-2 justify-end w-full sm:w-auto">
              <Button type="button" variant="ghost" onClick={() => setTitleDialogOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                type="button"
                className="inline-flex items-center gap-2"
                onClick={() => void saveTitleDialog()}
                disabled={titleSaving}
              >
                {titleSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                    {t('common:actions.saving')}
                  </>
                ) : (
                  t('common:actions.save')
                )}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <OntologyLibraryDialog
        isOpen={libraryDialogOpen}
        onOpenChange={setLibraryDialogOpen}
        onImportSuccess={() => { fetchItems(); }}
      />

      <Dialog open={viewDialogOpen} onOpenChange={(open) => {
        setViewDialogOpen(open);
        if (!open) {
          setViewingModel(null);
          setViewContent('');
        }
      }}>
        <DialogContent className="max-w-4xl w-[90vw] h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Eye className="h-5 w-5" />
              {viewingModel ? semanticModelDisplayTitle(viewingModel, t) : 'View Ontology'}
            </DialogTitle>
            <DialogDescription>
              {viewingModel
                ? t('rdfSources.viewRawDescription', {
                    syntax: semanticModelSerializationLabel(viewingModel, t),
                  })
                : t('rdfSources.viewRawDescriptionFallback')}
            </DialogDescription>
          </DialogHeader>
          <div className="flex-1 min-h-0">
            {viewLoading ? (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                <Loader2 className="h-6 w-6 animate-spin mr-2" />
                Loading content...
              </div>
            ) : (
              <ScrollArea className="h-full rounded-md border bg-muted/30">
                <pre className="p-4 text-sm font-mono whitespace-pre-wrap break-words">
                  {viewContent || 'No content available.'}
                </pre>
              </ScrollArea>
            )}
          </div>
          <DialogFooter className="flex-shrink-0">
            <Button
              variant="outline"
              onClick={onCopyContent}
              disabled={viewLoading || !viewContent}
            >
              {copied ? (
                <><Check className="h-4 w-4 mr-2" /> Copied!</>
              ) : (
                <><Copy className="h-4 w-4 mr-2" /> Copy to Clipboard</>
              )}
            </Button>
            <Button variant="default" onClick={() => setViewDialogOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
