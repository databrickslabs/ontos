import React, { useState, useMemo } from 'react';
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
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import {
  OntologyConcept,
  KnowledgeCollection,
} from '@/types/ontology';
import {
  Loader2,
  ArrowUp,
  ArrowDown,
  ArrowLeftRight,
  AlertTriangle,
  Info,
} from 'lucide-react';
import { buildSchemeOptionGroups, flattenSchemeTree } from '@/lib/scheme-select-options';
import { SchemeSelectItems } from './scheme-select-items';

type PromotionAction = 'promote' | 'demote' | 'migrate';

interface PromotionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  concept: OntologyConcept;
  collections: KnowledgeCollection[];
  currentCollection?: KnowledgeCollection;
  action?: PromotionAction;
  onPromote: (
    concept: OntologyConcept,
    targetCollectionIri: string,
    deprecateSource: boolean
  ) => Promise<void>;
  onMigrate: (
    concept: OntologyConcept,
    targetCollectionIri: string,
    deleteSource: boolean
  ) => Promise<void>;
}

export const PromotionDialog: React.FC<PromotionDialogProps> = ({
  open,
  onOpenChange,
  concept,
  collections,
  currentCollection,
  action: initialAction,
  onPromote,
  onMigrate,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [isLoading, setIsLoading] = useState(false);
  const [action, setAction] = useState<PromotionAction>(initialAction || 'promote');
  const [targetCollectionIri, setTargetCollectionIri] = useState('');
  const [deprecateSource, setDeprecateSource] = useState(true);
  const [deleteSource, setDeleteSource] = useState(false);

  // Target options: any editable scheme other than the concept's own, judged
  // on its own wherever it sits in the tree.
  const targetOptionGroups = useMemo(
    () =>
      buildSchemeOptionGroups(collections, {
        include: (c) => c.iri !== concept.source_context && c.is_editable,
      }),
    [collections, concept.source_context]
  );

  // Scope level per scheme, shown as a badge next to each target option.
  const scopeByIri = useMemo(
    () => new Map(flattenSchemeTree(collections).map((c) => [c.iri, c.scope_level] as const)),
    [collections]
  );

  const handleSubmit = async () => {
    if (!targetCollectionIri) return;

    setIsLoading(true);
    try {
      if (action === 'migrate') {
        await onMigrate(concept, targetCollectionIri, deleteSource);
      } else {
        await onPromote(concept, targetCollectionIri, deprecateSource);
      }
      onOpenChange(false);
    } finally {
      setIsLoading(false);
    }
  };

  const getActionIcon = () => {
    switch (action) {
      case 'promote':
        return <ArrowUp className="h-5 w-5 text-green-500" />;
      case 'demote':
        return <ArrowDown className="h-5 w-5 text-orange-500" />;
      case 'migrate':
        return <ArrowLeftRight className="h-5 w-5 text-blue-500" />;
    }
  };

  const getActionTitle = () => {
    switch (action) {
      case 'promote':
        return t('semantic-models:promotion.promoteConcept');
      case 'demote':
        return t('semantic-models:promotion.demoteConcept');
      case 'migrate':
        return t('semantic-models:promotion.migrateConcept');
    }
  };

  const canDelete = concept.status === 'draft';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {getActionIcon()}
            {getActionTitle()}
          </DialogTitle>
          <DialogDescription>
            {t('semantic-models:promotion.move')} <strong>{concept.label}</strong> {t('semantic-models:promotion.toDifferentCollection')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Action type */}
          <div className="grid gap-2">
            <Label>{t('semantic-models:promotion.actionLabel')}</Label>
            <Select value={action} onValueChange={(v) => setAction(v as PromotionAction)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="promote">
                  <div className="flex items-center gap-2">
                    <ArrowUp className="h-4 w-4 text-green-500" />
                    <span>{t('semantic-models:promotion.promote')}</span>
                  </div>
                </SelectItem>
                <SelectItem value="migrate">
                  <div className="flex items-center gap-2">
                    <ArrowLeftRight className="h-4 w-4 text-blue-500" />
                    <span>{t('semantic-models:promotion.migrate')}</span>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Current collection */}
          <div className="grid gap-2">
            <Label className="text-muted-foreground">{t('semantic-models:promotion.currentLocation')}</Label>
            <div className="flex items-center gap-2 bg-muted px-3 py-2 rounded">
              <span className="text-sm">
                {currentCollection?.label || concept.source_context}
              </span>
              {currentCollection?.scope_level && (
                <Badge variant="outline" className="text-xs">
                  {currentCollection.scope_level}
                </Badge>
              )}
            </div>
          </div>

          {/* Target collection */}
          <div className="grid gap-2">
            <Label>{t('semantic-models:import.targetCollection')}</Label>
            <Select value={targetCollectionIri} onValueChange={setTargetCollectionIri}>
              <SelectTrigger>
                <SelectValue placeholder={t('semantic-models:promotion.selectTargetPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SchemeSelectItems
                  groups={targetOptionGroups}
                  renderSuffix={(opt) => {
                    const scope = scopeByIri.get(opt.iri);
                    return scope ? (
                      <Badge variant="outline" className="text-xs">
                        {scope}
                      </Badge>
                    ) : null;
                  }}
                />
              </SelectContent>
            </Select>
          </div>

          {/* Info about new IRI */}
          {targetCollectionIri && (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                {t('semantic-models:promotion.newIri')}: <code className="text-xs">{targetCollectionIri}/{concept.label?.toLowerCase().replace(/\s+/g, '-')}</code>
              </AlertDescription>
            </Alert>
          )}

          {/* Source handling options */}
          <div className="space-y-3">
            <Label>{t('semantic-models:promotion.sourceConcept')}</Label>
            
            {action !== 'migrate' && (
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="deprecate"
                  checked={deprecateSource}
                  onCheckedChange={(checked) => setDeprecateSource(checked as boolean)}
                />
                <label
                  htmlFor="deprecate"
                  className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  {t('semantic-models:promotion.deprecateOriginal')}
                </label>
              </div>
            )}

            {action === 'migrate' && (
              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="delete"
                    checked={deleteSource}
                    onCheckedChange={(checked) => setDeleteSource(checked as boolean)}
                    disabled={!canDelete}
                  />
                  <label
                    htmlFor="delete"
                    className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                  >
                    {t('semantic-models:promotion.deleteOriginal')}
                  </label>
                </div>
                {!canDelete && (
                  <p className="text-xs text-muted-foreground ml-6">
                    {t('semantic-models:promotion.deleteHelp')}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Warning for promotion */}
          {action === 'promote' && (
            <Alert variant="default">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {t('semantic-models:promotion.promoteWarning')}
              </AlertDescription>
            </Alert>
          )}
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
          <Button
            onClick={handleSubmit}
            disabled={isLoading || !targetCollectionIri}
          >
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {getActionTitle()}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PromotionDialog;

