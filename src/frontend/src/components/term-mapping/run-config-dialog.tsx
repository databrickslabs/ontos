import { useEffect, useMemo, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';

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
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

import type {
  Run,
  RunCreatePayload,
  TermMappingTargetEntityType,
} from '@/types/term-mapping';
import {
  SHIPPED_OPT_IN_CONTEXTS,
  TARGET_ENTITY_TYPE_LABELS,
} from '@/types/term-mapping';

interface SemanticModelLite {
  id: string;
  name: string;
  display_name?: string | null;
  enabled?: boolean;
}

interface SemanticModelsResponse {
  semantic_models: SemanticModelLite[];
}

/**
 * The /api/semantic-models endpoint returns DB-backed customer models AND
 * file/schema taxonomies in one list. File/schema rows use synthetic IDs
 * prefixed with `file-` (see backend route); only the un-prefixed ones are
 * persisted in the `semantic_models` table and therefore valid as
 * `urn:semantic-model:*` mapping contexts.
 */
const isCustomerModel = (m: SemanticModelLite): boolean =>
  typeof m.id === 'string' && !m.id.startsWith('file-');

interface RunConfigDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the created run once the suggester finishes. */
  onCreated: (run: Run) => void;
}

const DEFAULT_ENTITY_TYPES: TermMappingTargetEntityType[] = [
  'asset',
  'data_contract_property',
];

export default function RunConfigDialog({
  isOpen,
  onOpenChange,
  onCreated,
}: RunConfigDialogProps) {
  const { t } = useTranslation(['term-mapping', 'common']);
  const { toast } = useToast();
  const { get, post } = useApi();

  const [models, setModels] = useState<SemanticModelLite[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // Form state ---------------------------------------------------------------
  // Empty selectedContexts === "use every enabled customer ontology"
  // (backend default). We still surface the list so users see what will run.
  const [selectedContexts, setSelectedContexts] = useState<Set<string>>(new Set());
  const [allContexts, setAllContexts] = useState<boolean>(true);
  const [shippedSelected, setShippedSelected] = useState<Set<string>>(new Set());
  const [entityTypes, setEntityTypes] = useState<Set<TermMappingTargetEntityType>>(
    new Set(DEFAULT_ENTITY_TYPES),
  );
  const [assetTypeNames, setAssetTypeNames] = useState<string>('Column');
  const [limit, setLimit] = useState<string>('500');
  const [comment, setComment] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Reset whenever the dialog opens fresh.
  useEffect(() => {
    if (!isOpen) return;
    setSelectedContexts(new Set());
    setAllContexts(true);
    setShippedSelected(new Set());
    setEntityTypes(new Set(DEFAULT_ENTITY_TYPES));
    setAssetTypeNames('Column');
    setLimit('500');
    setComment('');
    void fetchModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const fetchModels = async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const res = await get<SemanticModelsResponse>('/api/semantic-models');
      if (res.error) throw new Error(res.error);
      // Endpoint returns BOTH DB-backed customer models and file/schema
      // taxonomies under `semantic_models`. Only customer models are valid as
      // `ontology_contexts`; shipped taxonomies use the opt-in checkboxes.
      const all = res.data?.semantic_models ?? [];
      const customer = all.filter((m) => isCustomerModel(m) && m.enabled !== false);
      setModels(customer);
      // Out-of-the-box ergonomics: when the user has zero customer ontologies
      // loaded, pre-check the Databricks shipped taxonomy so "Create run" is
      // immediately useful for demos / first-time exploration. They can still
      // uncheck it. When customer ontologies exist, leave shipped opt-ins off
      // — those are the authoritative source.
      if (customer.length === 0) {
        setShippedSelected((prev) =>
          prev.size === 0 ? new Set(['urn:taxonomy:databricks_ontology']) : prev,
        );
      }
    } catch (e) {
      setModelsError(
        e instanceof Error ? e.message : t('runConfig.toast.loadOntologiesFailed'),
      );
    } finally {
      setModelsLoading(false);
    }
  };

  const enabledCustomerCount = models.length;

  const previewContextNames = useMemo(() => {
    if (allContexts) return models.map((m) => m.display_name || m.name);
    return models
      .filter((m) => selectedContexts.has(modelToContextUrn(m)))
      .map((m) => m.display_name || m.name);
  }, [models, selectedContexts, allContexts]);

  const handleToggleContext = (urn: string) => {
    setAllContexts(false);
    setSelectedContexts((prev) => {
      const next = new Set(prev);
      if (next.has(urn)) {
        next.delete(urn);
      } else {
        next.add(urn);
      }
      return next;
    });
  };

  const handleToggleAll = () => {
    setAllContexts(true);
    setSelectedContexts(new Set());
  };

  const handleToggleShipped = (urn: string) => {
    setShippedSelected((prev) => {
      const next = new Set(prev);
      if (next.has(urn)) {
        next.delete(urn);
      } else {
        next.add(urn);
      }
      return next;
    });
  };

  const handleToggleEntityType = (et: TermMappingTargetEntityType) => {
    setEntityTypes((prev) => {
      const next = new Set(prev);
      if (next.has(et)) {
        next.delete(et);
      } else {
        next.add(et);
      }
      return next;
    });
  };

  const handleSubmit = async () => {
    if (entityTypes.size === 0) {
      toast({
        title: t('runConfig.validation.noTargetType'),
        description: t('runConfig.validation.noTargetTypeDescription'),
        variant: 'destructive',
      });
      return;
    }
    if (allContexts === false && selectedContexts.size === 0 && shippedSelected.size === 0) {
      toast({
        title: t('runConfig.validation.noOntology'),
        description: t('runConfig.validation.noOntologyDescription'),
        variant: 'destructive',
      });
      return;
    }

    const payload: RunCreatePayload = {
      target_filter: {
        entity_types: Array.from(entityTypes),
        asset_type_names: entityTypes.has('asset')
          ? assetTypeNames
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : undefined,
        limit: Number.isFinite(parseInt(limit, 10)) ? parseInt(limit, 10) : undefined,
      },
      include_shipped: Array.from(shippedSelected),
      engines: ['heuristic'],
      comment: comment.trim() || undefined,
    };
    if (!allContexts) {
      payload.ontology_contexts = Array.from(selectedContexts);
    }

    setSubmitting(true);
    try {
      const res = await post<Run>('/api/term-mappings/runs', payload);
      if (res.error) throw new Error(res.error);
      const run = res.data;
      if (!run || !run.id) throw new Error(t('runConfig.toast.createdEmpty'));
      const total = (run.stats?.suggestions_total as number) ?? 0;
      const targets = (run.stats?.targets as number) ?? 0;
      toast({
        title: t('runConfig.toast.created'),
        description: t(
          total === 1
            ? 'runConfig.toast.createdDescriptionOne'
            : 'runConfig.toast.createdDescriptionMany',
          { total, targets },
        ),
      });
      onCreated(run);
      onOpenChange(false);
    } catch (e) {
      toast({
        title: t('runConfig.toast.failed'),
        description: e instanceof Error ? e.message : t('toast.unknownError'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {t('runConfig.title')}
          </DialogTitle>
          <DialogDescription>{t('runConfig.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Customer ontologies ---------------------------------------- */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium">{t('runConfig.customerOntologies')}</Label>
              <Badge variant="outline" className="text-xs">
                {t('runConfig.enabledCount', { count: enabledCustomerCount })}
              </Badge>
            </div>
            {modelsLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('runConfig.loadingOntologies')}
              </div>
            ) : modelsError ? (
              <Alert variant="destructive">
                <AlertDescription>{modelsError}</AlertDescription>
              </Alert>
            ) : enabledCustomerCount === 0 ? (
              <Alert>
                <AlertDescription>{t('runConfig.noCustomerOntologies')}</AlertDescription>
              </Alert>
            ) : (
              <div className="rounded-md border p-3 space-y-2 max-h-48 overflow-y-auto">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={allContexts}
                    onCheckedChange={() => handleToggleAll()}
                  />
                  <span className="font-medium">{t('runConfig.useAll')}</span>
                </label>
                <div className="pl-6 space-y-1.5 border-l">
                  {models.map((m) => {
                    const urn = modelToContextUrn(m);
                    const checked = allContexts || selectedContexts.has(urn);
                    return (
                      <label key={m.id} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={checked}
                          disabled={allContexts}
                          onCheckedChange={() => handleToggleContext(urn)}
                        />
                        <span>{m.display_name || m.name}</span>
                        <span className="text-xs text-muted-foreground font-mono ml-auto">
                          {urn}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

          {/* Shipped opt-in --------------------------------------------- */}
          <section className="space-y-2">
            <Label className="text-sm font-medium">{t('runConfig.shippedTitle')}</Label>
            <div className="rounded-md border p-3 space-y-2">
              {SHIPPED_OPT_IN_CONTEXTS.map((opt) => (
                <label key={opt.value} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={shippedSelected.has(opt.value)}
                    onCheckedChange={() => handleToggleShipped(opt.value)}
                  />
                  <span>{opt.label}</span>
                  <span className="text-xs text-muted-foreground font-mono ml-auto">
                    {opt.value}
                  </span>
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              <Trans i18nKey="term-mapping:runConfig.shippedHelp" components={{ code: <code /> }} />
            </p>
          </section>

          {/* Target selection ------------------------------------------- */}
          <section className="space-y-2">
            <Label className="text-sm font-medium">{t('runConfig.targetTypes')}</Label>
            <div className="rounded-md border p-3 grid grid-cols-2 gap-2">
              {(Object.keys(TARGET_ENTITY_TYPE_LABELS) as TermMappingTargetEntityType[])
                .filter((et) => et !== 'dataset')
                .map((et) => (
                  <label key={et} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={entityTypes.has(et)}
                      onCheckedChange={() => handleToggleEntityType(et)}
                    />
                    <span>{TARGET_ENTITY_TYPE_LABELS[et]}</span>
                  </label>
                ))}
            </div>
            {entityTypes.has('asset') && (
              <div className="space-y-1.5 pl-1">
                <Label htmlFor="tm-asset-types" className="text-xs text-muted-foreground">
                  {t('runConfig.assetTypesLabel')}
                </Label>
                <Input
                  id="tm-asset-types"
                  value={assetTypeNames}
                  onChange={(e) => setAssetTypeNames(e.target.value)}
                  placeholder={t('runConfig.assetTypesPlaceholder')}
                />
              </div>
            )}
          </section>

          {/* Limit + comment -------------------------------------------- */}
          <section className="grid grid-cols-3 gap-3">
            <div className="col-span-1">
              <Label htmlFor="tm-limit" className="text-sm">{t('runConfig.limit')}</Label>
              <Input
                id="tm-limit"
                type="number"
                min={1}
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </div>
            <div className="col-span-2">
              <Label htmlFor="tm-comment" className="text-sm">{t('runConfig.comment')}</Label>
              <Textarea
                id="tm-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={2}
                placeholder={t('runConfig.commentPlaceholder')}
              />
            </div>
          </section>

          {/* Preview line ----------------------------------------------- */}
          <Alert>
            <AlertDescription>
              {(() => {
                const customerPart =
                  previewContextNames.length === 0
                    ? t('runConfig.previewNoOntologies')
                    : t(
                        previewContextNames.length === 1
                          ? 'runConfig.previewCustomerOne'
                          : 'runConfig.previewCustomerMany',
                        { count: previewContextNames.length },
                      );
                const shippedPart =
                  shippedSelected.size > 0
                    ? t(
                        shippedSelected.size === 1
                          ? 'runConfig.previewShippedOne'
                          : 'runConfig.previewShippedMany',
                        { count: shippedSelected.size },
                      )
                    : null;
                const targetPart = t(
                  entityTypes.size === 1
                    ? 'runConfig.previewTargetTypeOne'
                    : 'runConfig.previewTargetTypeMany',
                  { count: entityTypes.size },
                );
                return (
                  <Trans
                    i18nKey={
                      shippedPart
                        ? 'term-mapping:runConfig.previewLineWithShipped'
                        : 'term-mapping:runConfig.previewLine'
                    }
                    components={{ strong: <strong /> }}
                    values={{ customerPart, shippedPart: shippedPart ?? '', targetPart }}
                  />
                );
              })()}
            </AlertDescription>
          </Alert>
        </div>

        <DialogFooter className="border-t pt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || modelsLoading}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {t('runConfig.submitting')}
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-2" />
                {t('runConfig.submit')}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- helpers ----------

/**
 * Convert a SemanticModelLite into the context URN the backend expects.
 * Mirrors src/backend/src/controller/semantic_models_manager._sanitize_context_name.
 */
function modelToContextUrn(model: SemanticModelLite): string {
  const sanitized = (model.name || '')
    .replace(/ /g, '_')
    .replace(/[^\w\-._~]/g, '_');
  return `urn:semantic-model:${sanitized}`;
}
