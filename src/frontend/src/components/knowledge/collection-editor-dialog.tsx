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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
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
  const { t } = useTranslation();
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
    <TooltipProvider>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isNew ? t('Create scheme') : t('Edit scheme')}
          </DialogTitle>
          <DialogDescription>
            {isNew
              ? t('Create a new concept scheme. Start simple as a glossary; you can add structure later.')
              : t('Update scheme settings.')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            {/* Name */}
            <div className="grid gap-2">
              <Label htmlFor="label">{t('Name')}</Label>
              <Input
                id="label"
                value={formData.label}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, label: e.target.value }))
                }
                placeholder={t('e.g., Finance Glossary')}
                required
              />
            </div>

            {/* Description */}
            <div className="grid gap-2">
              <Label htmlFor="description">{t('Description')}</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, description: e.target.value }))
                }
                placeholder={t('Optional description...')}
                rows={3}
              />
            </div>

            {/* Collection Type (only for new) */}
            {isNew && (
              <div className="grid gap-2">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="collection_type">{t('Type')}</Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-help text-xs text-muted-foreground border rounded-full h-4 w-4 inline-flex items-center justify-center">i</span>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-[280px]">
                      {t(
                        'collection.typeTooltip',
                        'Glossary, taxonomy, and ontology are points on a maturity ladder, not different tools. Glossary = a flat list of agreed terms and definitions. Taxonomy = terms arranged in a broader/narrower hierarchy. Ontology = formal classes and properties a machine can reason over. Pick where you are today; you can add structure later.',
                      )}
                    </TooltipContent>
                  </Tooltip>
                </div>
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
                    <SelectItem value="glossary">{t('Glossary')}</SelectItem>
                    <SelectItem value="taxonomy">{t('Taxonomy')}</SelectItem>
                    <SelectItem value="ontology">{t('Ontology')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Scope Level */}
            <div className="grid gap-2">
              <Label htmlFor="scope_level">{t('Scope')}</Label>
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
                  <SelectItem value="enterprise">{t('Enterprise')}</SelectItem>
                  <SelectItem value="domain">{t('Domain')}</SelectItem>
                  <SelectItem value="department">{t('Department')}</SelectItem>
                  <SelectItem value="team">{t('Team')}</SelectItem>
                  <SelectItem value="project">{t('Project')}</SelectItem>
                  <SelectItem value="external">{t('External')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Parent Collection */}
            <div className="grid gap-2">
              <Label htmlFor="parent">{t('Parent Collection')}</Label>
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
                  <SelectValue placeholder={t('None (root collection)')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">{t('None (root collection)')}</SelectItem>
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
                <Label htmlFor="is_editable">{t('Editable')}</Label>
                <p className="text-xs text-muted-foreground">
                  {t('Allow creating and editing concepts in this collection')}
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
              {t('Cancel')}
            </Button>
            <Button type="submit" disabled={isLoading || !formData.label}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('Create') : t('Save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    </TooltipProvider>
  );
};

export default CollectionEditorDialog;

