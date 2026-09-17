import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  KnowledgeCollection,
  KnowledgeCollectionCreate,
  KnowledgeCollectionUpdate,
  CollectionType,
  ScopeLevel,
} from '@/types/ontology';
import { Loader2 } from 'lucide-react';

interface CollectionEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collection?: KnowledgeCollection | null; // null = create mode
  collections?: KnowledgeCollection[]; // For parent selection
  onSave: (data: KnowledgeCollectionCreate | KnowledgeCollectionUpdate, isNew: boolean) => Promise<void>;
}

export const CollectionEditorDialog: React.FC<CollectionEditorDialogProps> = ({
  open,
  onOpenChange,
  collection,
  collections = [],
  onSave,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [isLoading, setIsLoading] = useState(false);
  const [formData, setFormData] = useState({
    label: '',
    description: '',
    collection_type: 'glossary' as CollectionType,
    scope_level: 'enterprise' as ScopeLevel,
    parent_collection_iri: '',
    is_editable: true,
  });

  const isNew = !collection;

  useEffect(() => {
    if (collection) {
      setFormData({
        label: collection.label || '',
        description: collection.description || '',
        collection_type: collection.collection_type,
        scope_level: collection.scope_level,
        parent_collection_iri: collection.parent_collection_iri || '',
        is_editable: collection.is_editable,
      });
    } else {
      setFormData({
        label: '',
        description: '',
        collection_type: 'glossary',
        scope_level: 'enterprise',
        parent_collection_iri: '',
        is_editable: true,
      });
    }
  }, [collection, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const data = {
        label: formData.label,
        description: formData.description || undefined,
        collection_type: isNew ? formData.collection_type : undefined,
        scope_level: formData.scope_level,
        parent_collection_iri: formData.parent_collection_iri || undefined,
        is_editable: formData.is_editable,
      };
      await onSave(data, isNew);
      onOpenChange(false);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter out current collection from parent options
  const parentOptions = collections.filter(
    (c) => c.iri !== collection?.iri
  );

  // Flatten hierarchy for dropdown
  const flattenCollections = (
    colls: KnowledgeCollection[],
    level = 0
  ): Array<{ iri: string; label: string; level: number }> => {
    let result: Array<{ iri: string; label: string; level: number }> = [];
    for (const c of colls) {
      result.push({ iri: c.iri, label: c.label, level });
      if (c.child_collections && c.child_collections.length > 0) {
        result = result.concat(flattenCollections(c.child_collections, level + 1));
      }
    }
    return result;
  };

  const flatParentOptions = flattenCollections(parentOptions);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isNew ? t('semantic-models:actions.createCollection') : t('semantic-models:collectionEditor.editTitle')}
          </DialogTitle>
          <DialogDescription>
            {isNew
              ? t('semantic-models:collectionEditor.createDescription')
              : t('semantic-models:collectionEditor.editDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            {/* Name */}
            <div className="grid gap-2">
              <Label htmlFor="label">{t('common:labels.name')}</Label>
              <Input
                id="label"
                value={formData.label}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, label: e.target.value }))
                }
                placeholder={t('semantic-models:collectionEditor.namePlaceholder')}
                required
              />
            </div>

            {/* Description */}
            <div className="grid gap-2">
              <Label htmlFor="description">{t('common:labels.description')}</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, description: e.target.value }))
                }
                placeholder={t('semantic-models:collectionEditor.descriptionPlaceholder')}
                rows={3}
              />
            </div>

            {/* Collection Type (only for new) */}
            {isNew && (
              <div className="grid gap-2">
                <Label htmlFor="collection_type">{t('common:labels.type')}</Label>
                <Select
                  value={formData.collection_type}
                  onValueChange={(value: CollectionType) =>
                    setFormData((prev) => ({ ...prev, collection_type: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="glossary">{t('semantic-models:collections.glossary')}</SelectItem>
                    <SelectItem value="taxonomy">{t('semantic-models:collections.taxonomy')}</SelectItem>
                    <SelectItem value="ontology">{t('semantic-models:collections.ontology')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Scope Level */}
            <div className="grid gap-2">
              <Label htmlFor="scope_level">{t('semantic-models:fields.scope')}</Label>
              <Select
                value={formData.scope_level}
                onValueChange={(value: ScopeLevel) =>
                  setFormData((prev) => ({ ...prev, scope_level: value }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="enterprise">{t('semantic-models:scopes.enterprise')}</SelectItem>
                  <SelectItem value="domain">{t('semantic-models:scopes.domain')}</SelectItem>
                  <SelectItem value="department">{t('semantic-models:scopes.department')}</SelectItem>
                  <SelectItem value="team">{t('semantic-models:scopes.team')}</SelectItem>
                  <SelectItem value="project">{t('semantic-models:scopes.project')}</SelectItem>
                  <SelectItem value="external">{t('semantic-models:scopes.external')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Parent Collection */}
            <div className="grid gap-2">
              <Label htmlFor="parent">{t('semantic-models:collectionEditor.parentCollection')}</Label>
              <Select
                value={formData.parent_collection_iri || '_none'}
                onValueChange={(value) =>
                  setFormData((prev) => ({
                    ...prev,
                    parent_collection_iri: value === '_none' ? '' : value,
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('semantic-models:collectionEditor.noneRootCollection')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">{t('semantic-models:collectionEditor.noneRootCollection')}</SelectItem>
                  {flatParentOptions.map((opt) => (
                    <SelectItem key={opt.iri} value={opt.iri}>
                      {'—'.repeat(opt.level)} {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Editable Toggle */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="is_editable">{t('semantic-models:collectionEditor.editable')}</Label>
                <p className="text-xs text-muted-foreground">
                  {t('semantic-models:collectionEditor.editableHelp')}
                </p>
              </div>
              <Switch
                id="is_editable"
                checked={formData.is_editable}
                onCheckedChange={(checked) =>
                  setFormData((prev) => ({ ...prev, is_editable: checked }))
                }
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isLoading}
            >
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={isLoading || !formData.label}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('common:actions.create') : t('common:actions.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default CollectionEditorDialog;

