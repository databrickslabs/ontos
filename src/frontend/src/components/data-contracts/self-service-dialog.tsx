import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Loader2, AlertCircle, XCircle, CheckCircle } from 'lucide-react';
import SchemaPropertyEditor from '@/components/data-contracts/schema-property-editor';
import type { ColumnProperty } from '@/types/data-contract';
import { useProjectContext } from '@/stores/project-store';

interface WorkflowStepResult {
  step_id: string;
  passed: boolean;
  message?: string;
  policy_name?: string;
}

interface WorkflowResult {
  workflow_name: string;
  status: string;
  error?: string;
  step_results?: WorkflowStepResult[];
}

interface PreCreationError {
  message: string;
  workflows: WorkflowResult[];
}

type CreateType = 'catalog' | 'schema' | 'table';

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  initialType?: 'catalog' | 'schema' | 'table';
};

export default function SelfServiceDialog({ isOpen, onOpenChange, initialType }: Props) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { currentProject } = useProjectContext();

  const [createType, setCreateType] = useState<CreateType>('table');
  const [catalog, setCatalog] = useState('');
  const [schema, setSchema] = useState('');
  const [tableName, setTableName] = useState('');
  const [columns, setColumns] = useState<ColumnProperty[]>([]);
  const [createContract, setCreateContract] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workflowErrors, setWorkflowErrors] = useState<PreCreationError | null>(null);
  const [success, setSuccess] = useState<any | null>(null);

  // Bootstrap defaults
  useEffect(() => {
    if (!isOpen) return;
    // Set initial type when opening
    if (initialType) {
      setCreateType(initialType);
    }
    (async () => {
      try {
        setLoading(true);
        const res = await fetch('/api/self-service/bootstrap');
        const data = await res.json();
        if (data?.defaults) {
          setCatalog(prev => prev || data.defaults.catalog || '');
          setSchema(prev => prev || data.defaults.schema || '');
        }
      } catch (e) {
        // ignore
      } finally {
        setLoading(false);
      }
    })();
  }, [isOpen]);

  // Columns are managed inline via SchemaPropertyEditor

  const canSubmit = useMemo(() => {
    if (createType === 'catalog') return !!catalog;
    if (createType === 'schema') return !!catalog && !!schema;
    return !!catalog && !!schema && !!tableName;
  }, [createType, catalog, schema, tableName]);

  const handleSubmit = async () => {
    try {
      setLoading(true);
      setError(null);
      setWorkflowErrors(null);
      setSuccess(null);
      const payload: any = {
        type: createType,
        catalog,
        schema,
        createContract,
        defaultToUserCatalog: true,
        projectId: currentProject?.id,
      };
      if (createType === 'table') {
        payload.table = { name: tableName, columns };
      }
      const res = await fetch('/api/self-service/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        // Try to parse as JSON for workflow errors
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          const errorData = await res.json();
          // Check if it's a pre-creation validation error
          if (errorData.detail?.workflows) {
            setWorkflowErrors(errorData.detail as PreCreationError);
            return;
          }
          throw new Error(errorData.detail?.message || errorData.detail || `HTTP ${res.status}`);
        }
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setSuccess(data);
    } catch (e: any) {
      setError(e?.message || t('data-contracts:selfService.errors.createFailed', 'Failed to create'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-3xl max-h-[90vh] flex flex-col overflow-hidden"
        style={{ top: '5%', transform: 'translateX(-50%)' }}
      >
        <DialogHeader className="flex-shrink-0">
          <DialogTitle>{t('data-contracts:selfService.title', 'Self-service data curation')}</DialogTitle>
        </DialogHeader>

        {/* Top fields outside scroll area to prevent dropdown clipping */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 flex-shrink-0">
          <div>
            <Label>{t('data-contracts:selfService.whatToCreateLabel', 'What to create')}</Label>
            <Select value={createType} onValueChange={(v) => setCreateType(v as CreateType)}>
              <SelectTrigger className="w-full"><SelectValue placeholder={t('common:placeholders.selectType', 'Select type')} /></SelectTrigger>
              <SelectContent>
                <SelectItem value="catalog">{t('common:labels.catalog', 'Catalog')}</SelectItem>
                <SelectItem value="schema">{t('common:labels.schema', 'Schema')}</SelectItem>
                <SelectItem value="table">{t('common:labels.table', 'Table')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t('common:labels.catalog', 'Catalog')}</Label>
            <Input value={catalog} onChange={(e) => setCatalog(e.target.value)} placeholder={t('data-contracts:selfService.catalogPlaceholder', 'e.g. user_jdoe')} />
          </div>
          <div>
            <Label>{t('common:labels.schema', 'Schema')}</Label>
            <Input value={schema} onChange={(e) => setSchema(e.target.value)} placeholder={t('data-contracts:selfService.schemaPlaceholder', 'e.g. sandbox')} />
          </div>
        </div>

        <div className="grid gap-4 overflow-y-auto flex-1 min-h-0 pr-2">
          {createType === 'table' && (
            <Card>
              <CardHeader>
                <CardTitle>{t('data-contracts:selfService.tableDefinition', 'Table definition')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label>{t('data-contracts:selfService.tableName', 'Table name')}</Label>
                    <Input value={tableName} onChange={(e) => setTableName(e.target.value)} placeholder={t('data-contracts:selfService.tableNamePlaceholder', 'e.g. clicks')} />
                  </div>
                </div>
                <div className="mt-4">
                  <SchemaPropertyEditor properties={columns} onChange={setColumns} />
                </div>
              </CardContent>
            </Card>
          )}

          {createType === 'table' && (
            <div className="flex gap-2 items-center">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={createContract} onChange={(e) => setCreateContract(e.target.checked)} />
                {t('data-contracts:selfService.createAsContract', 'Create as Data Contract')}
              </label>
            </div>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {workflowErrors && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t('data-contracts:selfService.validationFailedTitle', 'Pre-creation validation failed')}</AlertTitle>
              <AlertDescription>
                <p className="mb-2">{workflowErrors.message}</p>
                <div className="space-y-2">
                  {workflowErrors.workflows.map((wf, i) => {
                  const isPassed = wf.status === 'succeeded' || wf.status === 'passed';
                  return (
                    <div key={i} className={`border rounded p-2 ${isPassed ? 'bg-green-50 dark:bg-green-950/20' : 'bg-destructive/5'}`}>
                      <div className={`flex items-center gap-2 font-medium ${isPassed ? 'text-green-700 dark:text-green-400' : ''}`}>
                        {isPassed ? (
                          <CheckCircle className="h-4 w-4 text-green-600 dark:text-green-400" />
                        ) : (
                          <XCircle className="h-4 w-4 text-destructive" />
                        )}
                        {wf.workflow_name}
                        <Badge variant="outline" className="ml-auto">{wf.status}</Badge>
                      </div>
                      {wf.step_results && wf.step_results.filter(s => !s.passed).length > 0 && (
                        <div className="mt-2 pl-6 space-y-1">
                          {wf.step_results.filter(s => !s.passed).map((step, j) => (
                            <div key={j} className="text-sm flex items-start gap-2">
                              <XCircle className="h-3 w-3 mt-0.5 text-destructive" />
                              <div>
                                {step.policy_name && (
                                  <span className="font-medium">{step.policy_name}: </span>
                                )}
                                {step.message || t('data-contracts:selfService.stepValidationFailed', 'Validation failed')}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      {wf.error && !wf.step_results?.length && (
                        <p className="mt-1 text-sm pl-6">{wf.error}</p>
                      )}
                    </div>
                  );
                })}
                </div>
                <p className="mt-3 text-sm">{t('data-contracts:selfService.fixIssues', 'Please fix the issues above and try again.')}</p>
              </AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>{t('data-contracts:selfService.createdPrefix', 'Created:')} {JSON.stringify(success.created)}{success.contractId ? t('data-contracts:selfService.contractSuffix', ', contract {{id}}', { id: success.contractId }) : ''}</AlertDescription>
            </Alert>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common:actions.close', 'Close')}</Button>
            <Button onClick={handleSubmit} disabled={!canSubmit || loading}>
              {loading ? (<span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> {t('data-contracts:selfService.working', 'Working…')}</span>) : t('common:actions.create', 'Create')}
            </Button>
          </div>
        </div>

        {/* Columns are edited inline via SchemaPropertyEditor */}
      </DialogContent>
    </Dialog>
  );
}

