import { useEffect, useMemo, useState } from 'react';
import { Loader2, Sparkles, Info } from 'lucide-react';
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useConceptMode } from '@/components/concepts/mode-switch';

import type {
  Run,
  RunCreatePayload,
  TermMappingTargetEntityType,
} from '@/types/term-mapping';
import {
  SHIPPED_OPT_IN_CONTEXTS,
  TARGET_ENTITY_TYPE_LABELS,
} from '@/types/term-mapping';

/**
 * A selectable concept-scheme mapping source, as returned by
 * GET /api/term-mappings/contexts. This is provenance-agnostic: it includes
 * schemes authored/imported on the Explore/Define page (urn:glossary /
 * urn:ontology / urn:taxonomy) AND uploaded RDF sources (urn:semantic-model) —
 * exactly the set the engine runs against. (Previously the dialog read the
 * semantic_models table, so Explore-authored ontologies were invisible and it
 * wrongly reported 'no customer ontologies loaded'.)
 */
interface SelectableContext {
  context: string;
  label: string;
  concept_count: number;
}

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
  const [mode] = useConceptMode();
  const advanced = mode === 'advanced';

  const [models, setModels] = useState<SelectableContext[]>([]);
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
      // Provenance-agnostic: every selectable concept scheme in the graph
      // (authored/imported on Explore/Define AND uploaded RDF sources), i.e.
      // exactly what the engine will run against. NOT the semantic_models table.
      const res = await get<SelectableContext[]>('/api/term-mappings/contexts');
      if (res.error) throw new Error(res.error);
      const contexts = Array.isArray(res.data) ? res.data : [];
      setModels(contexts);
      // Out-of-the-box ergonomics: when the user has zero customer schemes,
      // pre-check the Databricks shipped taxonomy so "Create run" is immediately
      // useful for demos / first-time exploration. They can still uncheck it.
      if (contexts.length === 0) {
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
    if (allContexts) return models.map((m) => m.label);
    return models
      .filter((m) => selectedContexts.has(m.context))
      .map((m) => m.label);
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
    setAllContexts((prev) => !prev);
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
              <div className="flex items-center gap-2">
                <Label className="text-sm font-medium">{t('runConfig.customerOntologies')}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button type="button" aria-label="Info" className="text-muted-foreground hover:text-foreground">
                        <Info className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-[240px]">
                      {t('runConfig.customerOntologiesTooltip', 'Select which ontologies to use for matching. Choose all or pick specific ones.')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
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
                    const urn = m.context;
                    const checked = allContexts || selectedContexts.has(urn);
                    return (
                      <label key={urn} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={checked}
                          disabled={allContexts}
                          onCheckedChange={() => handleToggleContext(urn)}
                        />
                        <span>{m.label}</span>
                        <Badge variant="secondary" className="h-4 text-[10px] px-1">
                          {m.concept_count}
                        </Badge>
                        <span className={`text-xs text-muted-foreground font-mono ml-auto ${!advanced ? 'hidden' : ''}`}>
                          {urn}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

          {/* Shipped opt-in (advanced-only) ----------------------------- */}
          {advanced && (
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <Label className="text-sm font-medium">{t('runConfig.shippedTitle')}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button type="button" aria-label="Info" className="text-muted-foreground hover:text-foreground">
                        <Info className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-[240px]">
                      {t('runConfig.shippedTooltip', 'Databricks-provided reference taxonomies you can also match against, in addition to your own.')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
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
          )}

          {/* Target selection ------------------------------------------- */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <Label className="text-sm font-medium">{t('runConfig.targetTypes')}</Label>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" aria-label="Info" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[240px]">
                    {t('runConfig.targetTypesTooltip', 'Entity types to match concepts against. Select which platforms to include.')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <div className="rounded-md border p-3 grid grid-cols-2 gap-2">
              {(Object.keys(TARGET_ENTITY_TYPE_LABELS) as TermMappingTargetEntityType[])
                .filter((et) => et !== 'dataset')
                .map((et) => {
                  // In Simple mode, hide non-core entity types
                  const isCore = ['asset', 'data_product', 'data_contract'].includes(et);
                  const hidden = !advanced && !isCore;
                  return (
                    <div key={et} className={hidden ? 'hidden' : ''}>
                      <label className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={entityTypes.has(et)}
                          onCheckedChange={() => handleToggleEntityType(et)}
                        />
                        <span>{TARGET_ENTITY_TYPE_LABELS[et]}</span>
                      </label>
                    </div>
                  );
                })}
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
