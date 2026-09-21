import { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Trash2, AlertTriangle, Box, Table2, Eye, Columns2, Database, Shapes } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';

interface DeletePreviewItem {
  id: string;
  name: string;
  asset_type_name: string | null;
  relationship_type: string | null;
  level: number;
  children: DeletePreviewItem[];
}

interface CascadeDeleteResult {
  deleted: { id: string; name: string; asset_type_name?: string }[];
  failed: { id: string; name: string; error: string }[];
}

interface AssetDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assetId: string;
  assetName: string;
  onDeleted: () => void;
}

const TYPE_ICONS: Record<string, React.ElementType> = {
  Table: Table2,
  View: Eye,
  Column: Columns2,
  Dataset: Database,
};

function getTypeIcon(typeName: string | null): React.ElementType {
  if (!typeName) return Box;
  return TYPE_ICONS[typeName] || Shapes;
}

function flattenTree(node: DeletePreviewItem): string[] {
  const ids = [node.id];
  for (const child of node.children) {
    ids.push(...flattenTree(child));
  }
  return ids;
}

function countNodes(node: DeletePreviewItem): number {
  let count = 1;
  for (const child of node.children) {
    count += countNodes(child);
  }
  return count;
}

export function AssetDeleteDialog({
  open,
  onOpenChange,
  assetId,
  assetName,
  onDeleted,
}: AssetDeleteDialogProps) {
  const [preview, setPreview] = useState<DeletePreviewItem | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const { get: apiGet, post: apiPost } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['assets', 'common']);

  const fetchPreview = useCallback(async () => {
    if (!assetId) return;
    setIsLoadingPreview(true);
    try {
      const response = await apiGet<DeletePreviewItem>(`/api/assets/${assetId}/delete-preview`);
      if (response.error) throw new Error(response.error);
      if (response.data) {
        setPreview(response.data);
        setCheckedIds(new Set(flattenTree(response.data)));
      }
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('common:states.error'), description: err.message || t('assets:cascadeDelete.loadPreviewError') });
      setPreview(null);
    } finally {
      setIsLoadingPreview(false);
    }
  }, [assetId, apiGet, toast]);

  useEffect(() => {
    if (open && assetId) {
      fetchPreview();
    } else {
      setPreview(null);
      setCheckedIds(new Set());
    }
  }, [open, assetId, fetchPreview]);

  const totalCount = useMemo(() => (preview ? countNodes(preview) : 0), [preview]);
  const hasChildren = totalCount > 1;

  const toggleNode = useCallback(
    (node: DeletePreviewItem, checked: boolean) => {
      setCheckedIds((prev) => {
        const next = new Set(prev);
        const ids = flattenTree(node);
        if (checked) {
          ids.forEach((id) => next.add(id));
        } else {
          ids.forEach((id) => next.delete(id));
        }
        return next;
      });
    },
    [],
  );

  const handleDelete = async () => {
    if (checkedIds.size === 0) return;
    setIsDeleting(true);
    try {
      const response = await apiPost<CascadeDeleteResult>('/api/assets/cascade-delete', {
        asset_ids: Array.from(checkedIds),
      });
      if (response.error) throw new Error(response.error);
      const data = response.data;
      if (data) {
        if (data.deleted.length > 0) {
          toast({
            title: t('assets:cascadeDelete.deletedTitle'),
            description: t('assets:cascadeDelete.deletedDescription', { count: data.deleted.length }),
          });
        }
        if (data.failed.length > 0) {
          toast({
            variant: 'destructive',
            title: t('assets:cascadeDelete.failedTitle'),
            description: t('assets:cascadeDelete.failedDescription', { count: data.failed.length }),
          });
        }
      }
      onOpenChange(false);
      onDeleted();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('assets:cascadeDelete.deleteFailedTitle'), description: err.message });
    } finally {
      setIsDeleting(false);
    }
  };

  const renderNode = (node: DeletePreviewItem, isRoot = false) => {
    const indent = node.level * 24;
    const isChecked = checkedIds.has(node.id);
    const Icon = getTypeIcon(node.asset_type_name);
    const childrenSelected = node.children.length > 0
      ? node.children.filter((c) => checkedIds.has(c.id)).length
      : 0;

    return (
      <div key={node.id}>
        <div
          className="flex items-center gap-2 py-1.5 px-2 hover:bg-muted/50 rounded-sm"
          style={{ paddingLeft: `${indent + 8}px` }}
        >
          <Checkbox
            checked={isChecked}
            disabled={isRoot}
            onCheckedChange={(checked) => toggleNode(node, !!checked)}
            className="shrink-0"
          />
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="text-sm truncate flex-1">{node.name}</span>
          {node.asset_type_name && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
              {node.asset_type_name}
            </Badge>
          )}
          {node.relationship_type && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
              {node.relationship_type}
            </Badge>
          )}
          {node.children.length > 0 && (
            <span className="text-[10px] text-muted-foreground shrink-0">
              {childrenSelected}/{node.children.length}
            </span>
          )}
        </div>
        {node.children.map((child) => renderNode(child))}
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Trash2 className="h-5 w-5 text-destructive" />
            {t('assets:cascadeDelete.title')}
          </DialogTitle>
          <DialogDescription>
            {hasChildren
              ? t('assets:cascadeDelete.hasChildrenDescription', { name: assetName })
              : t('assets:cascadeDelete.confirmDescription', { name: assetName })}
          </DialogDescription>
        </DialogHeader>

        {isLoadingPreview ? (
          <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">{t('assets:cascadeDelete.loadingRelated')}</span>
          </div>
        ) : preview && hasChildren ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 rounded-md p-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{t('assets:cascadeDelete.childrenWarning')}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {t('assets:cascadeDelete.selectedCount', { checked: checkedIds.size, total: totalCount })}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs px-2"
                  onClick={() => preview && setCheckedIds(new Set(flattenTree(preview)))}
                >
                  {t('assets:cascadeDelete.selectAll')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs px-2"
                  onClick={() => preview && setCheckedIds(new Set([preview.id]))}
                >
                  {t('assets:cascadeDelete.selectNone')}
                </Button>
              </div>
            </div>
            <div className="border rounded-md overflow-y-auto max-h-80">
              <div className="p-1">{renderNode(preview, true)}</div>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isDeleting}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={isDeleting || isLoadingPreview || checkedIds.size === 0}
          >
            {isDeleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {checkedIds.size > 1
              ? t('assets:cascadeDelete.deleteButtonMany', { count: checkedIds.size })
              : t('assets:cascadeDelete.deleteButtonOne')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
