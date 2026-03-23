import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  FolderTree,
  Plus,
  Upload,
  Loader2,
} from 'lucide-react';
import type { KnowledgeCollection } from '@/types/ontology';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useToast } from '@/hooks/use-toast';
import {
  CollectionsTab,
  CollectionEditorDialog,
} from '@/components/knowledge';

export default function CollectionsView() {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();

  const canWrite = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  // Data state
  const [isLoading, setIsLoading] = useState(true);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [selectedCollection, setSelectedCollection] = useState<KnowledgeCollection | null>(null);

  // Dialog state
  const [collectionEditorOpen, setCollectionEditorOpen] = useState(false);
  const [editingCollection, setEditingCollection] = useState<KnowledgeCollection | null>(null);

  // Breadcrumbs
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);

  useEffect(() => {
    setStaticSegments([
      { label: t('semantic-models:title'), path: '/ontology' },
      { label: t('semantic-models:tabs.collections'), path: '/collections' },
    ]);
  }, [setStaticSegments, t]);

  // Fetch data
  const fetchData = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/knowledge/collections?hierarchical=true');
      if (res.ok) {
        const data = await res.json();
        setCollections(data.collections || []);
      }
    } catch (error) {
      console.error('Failed to fetch collections:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Collection handlers
  const handleCreateCollection = () => {
    setEditingCollection(null);
    setCollectionEditorOpen(true);
  };

  const handleEditCollection = (collection: KnowledgeCollection) => {
    setEditingCollection(collection);
    setCollectionEditorOpen(true);
  };

  const handleSaveCollection = async (data: any, isNew: boolean) => {
    try {
      const url = isNew
        ? '/api/knowledge/collections'
        : `/api/knowledge/collections/${encodeURIComponent(editingCollection!.iri)}`;
      const method = isNew ? 'POST' : 'PATCH';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save collection');
      }

      toast({
        title: t('common:toast.success'),
        description: isNew
          ? t('semantic-models:messages.collectionCreated')
          : t('semantic-models:messages.collectionUpdated'),
      });

      setCollectionEditorOpen(false);
      await fetchData();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
      throw error;
    }
  };

  const handleDeleteCollection = async (collection: KnowledgeCollection) => {
    if (!confirm(t('semantic-models:messages.confirmDeleteCollection', { name: collection.label }))) {
      return;
    }

    try {
      const response = await fetch(
        `/api/knowledge/collections/${encodeURIComponent(collection.iri)}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete collection');
      }

      toast({
        title: t('common:toast.success'),
        description: t('semantic-models:messages.collectionDeleted'),
      });

      await fetchData();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  };

  const handleExportCollection = async (collection: KnowledgeCollection, format: 'turtle' | 'rdfxml') => {
    try {
      const response = await fetch(
        `/api/knowledge/collections/${encodeURIComponent(collection.iri)}/export?format=${format}`
      );

      if (!response.ok) {
        throw new Error('Export failed');
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${collection.label || 'collection'}.${format === 'turtle' ? 'ttl' : 'rdf'}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message,
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="flex flex-col py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <FolderTree className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">{t('semantic-models:tabs.collections')}</h1>
            <p className="text-sm text-muted-foreground">
              {collections.length} {t('semantic-models:collections.title').toLowerCase()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {canWrite && (
            <Button onClick={handleCreateCollection}>
              <Plus className="h-4 w-4 mr-2" />
              {t('semantic-models:actions.createCollection')}
            </Button>
          )}

          <Button variant="outline" size="icon" title={t('common:actions.import')}>
            <Upload className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Loading state */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <CollectionsTab
          collections={collections}
          selectedCollection={selectedCollection}
          onSelectCollection={setSelectedCollection}
          onCreateCollection={handleCreateCollection}
          onEditCollection={handleEditCollection}
          onDeleteCollection={handleDeleteCollection}
          onExportCollection={handleExportCollection}
          canEdit={canWrite}
        />
      )}

      {/* Collection Editor Dialog */}
      <CollectionEditorDialog
        open={collectionEditorOpen}
        onOpenChange={setCollectionEditorOpen}
        collection={editingCollection}
        collections={collections}
        onSave={handleSaveCollection}
      />
    </div>
  );
}
