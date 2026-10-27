import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Folder, FolderOpen, Layout, Loader2, Table, X } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TreeView } from '@/components/ui/tree-view';
import { useApi } from '@/hooks/use-api';
import type { CatalogItem } from '@/types/data-asset-review';
import type {
  CommentStyle,
  SelectionItem,
  StartRunRequest,
  StartRunResponse,
} from '@/types/metadata-generation';

interface NewRunDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (runId: string) => void;
}

const SELECTION_TYPE: Record<string, SelectionItem['type'] | undefined> = {
  catalog: 'catalog',
  schema: 'schema',
  table: 'table',
  view: 'table',
};

export default function NewRunDialog({ isOpen, onOpenChange, onStarted }: NewRunDialogProps) {
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { get, post } = useApi();

  const [items, setItems] = useState<CatalogItem[]>([]);
  const [typeById, setTypeById] = useState<Map<string, string>>(new Map());
  const [isLoadingCatalogs, setIsLoadingCatalogs] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set());

  const [selection, setSelection] = useState<SelectionItem[]>([]);
  const [commentStyle, setCommentStyle] = useState<CommentStyle>('standard');
  const [model, setModel] = useState('');
  const [regenerateExisting, setRegenerateExisting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const rememberTypes = useCallback((nodes: CatalogItem[]) => {
    setTypeById((prev) => {
      const next = new Map(prev);
      nodes.forEach((n) => next.set(n.id, n.type));
      return next;
    });
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    setSelection([]);
    setFormError(null);
    setIsLoadingCatalogs(true);
    setCatalogError(null);
    void (async () => {
      const res = await get<CatalogItem[]>('/api/catalogs');
      if (res.error || !Array.isArray(res.data)) {
        setCatalogError(res.error || t('newRun.catalogLoadFailed'));
        setItems([]);
      } else {
        setItems(res.data);
        rememberTypes(res.data);
      }
      setIsLoadingCatalogs(false);
    })();
  }, [isOpen, get, t, rememberTypes]);

  const replaceChildren = (nodes: CatalogItem[], id: string, children: CatalogItem[]): CatalogItem[] =>
    nodes.map((n) =>
      n.id === id
        ? { ...n, children }
        : n.children
          ? { ...n, children: replaceChildren(n.children, id, children) }
          : n,
    );

  const loadChildren = async (id: string) => {
    const type = typeById.get(id);
    let urls: string[] = [];
    if (type === 'catalog') {
      urls = [`/api/catalogs/${id}/schemas`];
    } else if (type === 'schema') {
      const [catalog, schema] = id.split('.');
      urls = [
        `/api/catalogs/${catalog}/schemas/${schema}/tables`,
        `/api/catalogs/${catalog}/schemas/${schema}/views`,
      ];
    }
    if (urls.length === 0 || loadingNodes.has(id)) return;
    setLoadingNodes((prev) => new Set(prev).add(id));
    try {
      const responses = await Promise.all(urls.map((u) => get<CatalogItem[]>(u)));
      const children = responses.flatMap((r) => (Array.isArray(r.data) ? r.data : []));
      rememberTypes(children);
      setItems((prev) => replaceChildren(prev, id, children));
    } finally {
      setLoadingNodes((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const isSelected = (fqn: string) => selection.some((s) => s.fqn === fqn);

  const toggle = (id: string) => {
    const selectionType = SELECTION_TYPE[typeById.get(id) ?? ''];
    if (!selectionType) return;
    setFormError(null);
    setSelection((prev) =>
      prev.some((s) => s.fqn === id)
        ? prev.filter((s) => s.fqn !== id)
        : [...prev, { type: selectionType, fqn: id }],
    );
  };

  const iconFor = (type?: string) => {
    switch (type) {
      case 'catalog':
        return <Folder className="h-4 w-4 text-blue-500" />;
      case 'schema':
        return <FolderOpen className="h-4 w-4 text-green-500" />;
      case 'view':
        return <Layout className="h-4 w-4 text-purple-500" />;
      case 'table':
        return <Table className="h-4 w-4 text-orange-500" />;
      default:
        return null;
    }
  };

  const toTree = (nodes: CatalogItem[]): any[] =>
    nodes
      .filter((n) => SELECTION_TYPE[n.type])
      .map((n) => ({
        id: n.id,
        name: n.name,
        icon: iconFor(n.type),
        children: n.children ? toTree(n.children) : [],
        selected: isSelected(n.id),
        onExpand: () => void loadChildren(n.id),
        loading: loadingNodes.has(n.id),
        hasChildren: n.type === 'catalog' || n.type === 'schema',
      }));

  const handleSubmit = async () => {
    if (selection.length === 0) {
      setFormError(t('newRun.selectionRequired'));
      return;
    }
    setIsSubmitting(true);
    setFormError(null);
    const body: StartRunRequest = {
      selection,
      comment_style: commentStyle,
      model: model.trim() || null,
      regenerate_existing: regenerateExisting,
      auto_submit: false,
    };
    const res = await post<StartRunResponse>('/api/metadata-generation/runs', body);
    setIsSubmitting(false);
    if (res.error || !res.data?.run_id) {
      setFormError(res.error || t('newRun.startFailed'));
      return;
    }
    onOpenChange(false);
    onStarted(res.data.run_id);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('newRun.title')}</DialogTitle>
          <DialogDescription>{t('newRun.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 px-1">
          <div className="border rounded-md">
            <Label className="text-sm font-medium block p-2 border-b">{t('newRun.selectObjects')}</Label>
            <div className="h-[280px] overflow-y-auto p-2">
              {isLoadingCatalogs ? (
                <div className="flex justify-center items-center h-full">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                </div>
              ) : catalogError ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{catalogError}</AlertDescription>
                </Alert>
              ) : (
                <TreeView data={toTree(items)} className="text-sm" onSelectChange={(item) => toggle(item.id)} />
              )}
            </div>
          </div>

          {selection.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {selection.map((s) => (
                <Badge key={s.fqn} variant="secondary" className="gap-1">
                  <span className="text-muted-foreground">{t(`selectionType.${s.type}`)}</span>
                  <span className="font-mono">{s.fqn}</span>
                  <button
                    type="button"
                    aria-label={t('newRun.removeSelection', { fqn: s.fqn })}
                    onClick={() => toggle(s.fqn)}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <Label htmlFor="metagen-style">{t('newRun.commentStyle')}</Label>
              <Select value={commentStyle} onValueChange={(v) => setCommentStyle(v as CommentStyle)}>
                <SelectTrigger id="metagen-style">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="concise">{t('commentStyle.concise')}</SelectItem>
                  <SelectItem value="standard">{t('commentStyle.standard')}</SelectItem>
                  <SelectItem value="detailed">{t('commentStyle.detailed')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="metagen-model">{t('newRun.model')}</Label>
              <Input
                id="metagen-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={t('newRun.modelPlaceholder')}
              />
            </div>
          </div>

          <div className="flex items-start gap-2">
            <Checkbox
              id="metagen-regenerate"
              checked={regenerateExisting}
              onCheckedChange={(v) => setRegenerateExisting(v === true)}
            />
            <div className="grid gap-0.5">
              <Label htmlFor="metagen-regenerate">{t('newRun.regenerateExisting')}</Label>
              <p className="text-xs text-muted-foreground">{t('newRun.regenerateExistingHint')}</p>
            </div>
          </div>

          {formError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="break-words">{formError}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter className="pt-4 border-t">
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={isSubmitting}>
              {t('common:actions.cancel')}
            </Button>
          </DialogClose>
          <Button onClick={() => void handleSubmit()} disabled={isSubmitting || selection.length === 0}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('newRun.start')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
