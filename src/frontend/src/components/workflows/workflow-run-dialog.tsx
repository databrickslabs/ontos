/**
 * WorkflowRunDialog — starts a `manual` workflow from the Workflows list.
 *
 * Asks for the entity the run is about (type + entity), calls
 * `POST /api/workflows/{id}/execute?entity_type=...&entity_id=...` and shows
 * the resulting execution. Types that have a list endpoint get a picker; the
 * rest take the entity id as text.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Play } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { getEntityTypeLabel } from '@/lib/workflow-labels';
import { useDefaultWorkflowText } from '@/lib/workflow-default-texts';
import type { EntityType, ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

/** Entity types a manual workflow can be run against when its trigger lists none. */
const RUNNABLE_ENTITY_TYPES: EntityType[] = [
  'data_product',
  'data_contract',
  'domain',
  'project',
  'catalog',
  'schema',
  'table',
  'view',
];

/** Entity types that can be picked from a list; the others take an id as text. */
const LIST_ENDPOINTS: Partial<Record<EntityType, string>> = {
  data_product: '/api/data-products',
  data_contract: '/api/data-contracts',
  domain: '/api/data-domains',
  project: '/api/projects',
};

interface EntityOption {
  id: string;
  label: string;
}

function toOptions(raw: unknown): EntityOption[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item: any) => {
      const id = item?.id;
      if (!id) return null;
      const label = item.name ?? item.title ?? item.info?.title ?? id;
      return { id: String(id), label: String(label) };
    })
    .filter((o): o is EntityOption => o !== null);
}

export interface WorkflowRunDialogProps {
  workflow: ProcessWorkflow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after the run was accepted, with the execution the API returned. */
  onExecuted?: (execution: WorkflowExecution) => void;
  /** Opens the execution detail; the parent owns that dialog. */
  onViewExecution?: (execution: WorkflowExecution) => void;
}

export function WorkflowRunDialog({
  workflow,
  open,
  onOpenChange,
  onExecuted,
  onViewExecution,
}: WorkflowRunDialogProps) {
  const { t } = useTranslation(['workflows', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const defaultWorkflowText = useDefaultWorkflowText();

  const entityTypes = useMemo<EntityType[]>(() => {
    const declared = workflow?.trigger?.entity_types ?? [];
    return declared.length > 0 ? declared : RUNNABLE_ENTITY_TYPES;
  }, [workflow]);

  const [entityType, setEntityType] = useState<EntityType>(entityTypes[0]);
  const [entityId, setEntityId] = useState('');
  const [entityName, setEntityName] = useState('');
  const [options, setOptions] = useState<EntityOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<WorkflowExecution | null>(null);

  // Reset whenever the dialog opens for a workflow.
  useEffect(() => {
    if (!open) return;
    setEntityType(entityTypes[0]);
    setEntityId('');
    setEntityName('');
    setRunError(null);
    setResult(null);
  }, [open, workflow?.id, entityTypes]);

  const listEndpoint = LIST_ENDPOINTS[entityType];

  useEffect(() => {
    if (!open || !listEndpoint) {
      setOptions([]);
      setOptionsError(false);
      return;
    }
    let cancelled = false;
    setOptionsLoading(true);
    setOptionsError(false);
    (async () => {
      const res = await get<unknown>(listEndpoint);
      if (cancelled) return;
      if (res.error) {
        setOptions([]);
        setOptionsError(true);
      } else {
        setOptions(toOptions(res.data));
      }
      setOptionsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // `get` is stable (useCallback) in useApi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, listEndpoint]);

  const handleTypeChange = (value: string) => {
    setEntityType(value as EntityType);
    setEntityId('');
    setEntityName('');
  };

  const handlePick = (id: string) => {
    setEntityId(id);
    setEntityName(options.find((o) => o.id === id)?.label ?? '');
  };

  const canRun = !!workflow && entityId.trim().length > 0 && !isRunning && !result;

  const handleRun = async () => {
    if (!workflow || !canRun) return;
    setIsRunning(true);
    setRunError(null);
    const params = new URLSearchParams({ entity_type: entityType, entity_id: entityId.trim() });
    if (entityName.trim()) params.set('entity_name', entityName.trim());
    const res = await post<WorkflowExecution>(
      `/api/workflows/${encodeURIComponent(workflow.id)}/execute?${params.toString()}`,
      {},
    );
    setIsRunning(false);
    if (res.error || !res.data) {
      // The endpoint's detail is English text; show it only when it carries a code
      const message = res.errorCode
        ? t(`workflows:runDialog.errors.${res.errorCode}`, {
            defaultValue: t('workflows:runDialog.failed'),
          })
        : t('workflows:runDialog.failed');
      setRunError(message);
      toast({
        title: t('common:toast.error'),
        description: message,
        variant: 'destructive',
      });
      return;
    }
    setResult(res.data);
    onExecuted?.(res.data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('workflows:runDialog.title', { name: workflow?.name ?? '' })}</DialogTitle>
          <DialogDescription>{t('workflows:runDialog.description')}</DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-3 py-2" data-testid="run-result">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{t('workflows:runDialog.resultStatus')}</span>
              <Badge variant={result.status === 'failed' ? 'destructive' : 'default'}>
                {t(`workflows:execution.executionStates.${result.status}`, {
                  defaultValue: result.status,
                })}
              </Badge>
            </div>
            {result.entity_name || result.entity_id ? (
              <div className="text-sm text-muted-foreground">
                {t('workflows:runDialog.resultEntity', {
                  type: getEntityTypeLabel(entityType, t),
                  name: result.entity_name || result.entity_id,
                })}
              </div>
            ) : null}
            {result.error_message ? (
              <p className="text-sm text-destructive">{defaultWorkflowText(result.error_message)}</p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="run-entity-type">{t('workflows:runDialog.entityType')}</Label>
              <Select value={entityType} onValueChange={handleTypeChange} disabled={isRunning}>
                <SelectTrigger id="run-entity-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {entityTypes.map((et) => (
                    <SelectItem key={et} value={et}>
                      {getEntityTypeLabel(et, t)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {listEndpoint && !optionsError ? (
              <div className="space-y-2">
                <Label htmlFor="run-entity">{t('workflows:runDialog.entity')}</Label>
                <Select value={entityId} onValueChange={handlePick} disabled={isRunning || optionsLoading}>
                  <SelectTrigger id="run-entity">
                    <SelectValue
                      placeholder={
                        optionsLoading
                          ? t('workflows:runDialog.loading')
                          : t('workflows:runDialog.selectEntity')
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((o) => (
                      <SelectItem key={o.id} value={o.id}>
                        {o.label}
                      </SelectItem>
                    ))}
                    {options.length === 0 && !optionsLoading && (
                      <div className="px-2 py-1.5 text-xs text-muted-foreground">
                        {t('workflows:runDialog.noEntities')}
                      </div>
                    )}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <>
                {optionsError && (
                  <p className="text-xs text-muted-foreground">{t('workflows:runDialog.listFailed')}</p>
                )}
                <div className="space-y-2">
                  <Label htmlFor="run-entity-id">{t('workflows:runDialog.entityId')}</Label>
                  <Input
                    id="run-entity-id"
                    value={entityId}
                    onChange={(e) => setEntityId(e.target.value)}
                    placeholder={t('workflows:runDialog.entityIdPlaceholder')}
                    disabled={isRunning}
                  />
                  <p className="text-xs text-muted-foreground">{t('workflows:runDialog.entityIdHelp')}</p>
                </div>
              </>
            )}

            {runError && <p className="text-sm text-destructive" role="alert">{runError}</p>}
          </div>
        )}

        <DialogFooter>
          {result ? (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t('common:actions.close')}
              </Button>
              {onViewExecution && (
                <Button onClick={() => onViewExecution(result)}>
                  {t('workflows:runDialog.viewExecution')}
                </Button>
              )}
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isRunning}>
                {t('common:actions.cancel')}
              </Button>
              <Button onClick={handleRun} disabled={!canRun}>
                {isRunning ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                {t('workflows:runDialog.run')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default WorkflowRunDialog;
