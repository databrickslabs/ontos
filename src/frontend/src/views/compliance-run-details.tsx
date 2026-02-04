import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/ui/data-table';
import { ColumnDef } from '@tanstack/react-table';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, ArrowLeft } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';

interface Run {
  id: string; // UUID
  policy_id: string;
  status: string;
  started_at: string;
  finished_at?: string;
  success_count: number;
  failure_count: number;
  score: number;
  error_message?: string;
}

interface Result {
  id: string;
  run_id: string;
  object_type: string;
  object_id: string;
  object_name?: string;
  passed: boolean;
  message?: string;
  details_json?: string;
  created_at: string;
}

export default function ComplianceRunDetails() {
  const { t } = useTranslation(['compliance', 'common']);
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { get } = useApi();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [onlyFailed, setOnlyFailed] = useState(true);

  const columns: ColumnDef<Result>[] = useMemo(() => [
    { accessorKey: 'object_type', header: 'Type' },
    { accessorKey: 'object_name', header: 'Name', cell: ({ row }) => (
      <code className="text-xs bg-muted px-2 py-1 rounded">{row.original.object_name || row.original.object_id}</code>
    ) },
    { accessorKey: 'passed', header: 'Status', cell: ({ row }) => (
      <Badge variant={row.original.passed ? 'secondary' : 'destructive'}>
        {row.original.passed ? 'Passed' : 'Failed'}
      </Badge>
    ) },
    { accessorKey: 'message', header: 'Message', cell: ({ row }) => (
      <span className="text-sm text-muted-foreground break-words">{row.original.message || '-'}</span>
    ) },
  ], []);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await get<any>(`/api/compliance/runs/${runId}/results?only_failed=${onlyFailed ? 'true' : 'false'}`);
      if (!res.data) throw new Error(res.error || 'Failed to load run results');
      setRun(res.data.run);
      setResults(Array.isArray(res.data.results) ? res.data.results : []);
      setDynamicTitle(`Run ${runId}`);
    } catch (e: any) {
      setError(e.message || 'Failed to load');
      setRun(null);
      setResults([]);
      setDynamicTitle('Error');
    } finally {
      setLoading(false);
    }
  }, [get, runId, onlyFailed, setDynamicTitle]);

  useEffect(() => {
    setStaticSegments([{ label: 'Compliance', path: '/compliance' }]);
    load();
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [load, setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    load();
  }, [onlyFailed]);

  if (loading) {
    return (
      <div className="container mx-auto py-10 text-center text-muted-foreground">{t('common:labels.loading')}</div>
    );
  }
  if (error || !run) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error || 'Run not found.'}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate(-1)} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
        <div className="flex items-center gap-2">
          <Link to={`/compliance/policies/${run.policy_id}`} className="text-sm text-primary hover:underline">View Policy</Link>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Run {run.id}</CardTitle>
          <CardDescription>
            Status: <span className="font-medium">{run.status}</span> • Score: <span className="font-medium">{run.score}%</span> •
            {' '}Passed: <span className="font-medium text-green-600">{run.success_count}</span> / Failed: <span className="font-medium text-red-600">{run.failure_count}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm text-muted-foreground">Started: {new Date(run.started_at).toLocaleString()}</div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant={onlyFailed ? 'default' : 'outline'} onClick={() => setOnlyFailed(true)}>Show Failed</Button>
              <Button size="sm" variant={!onlyFailed ? 'default' : 'outline'} onClick={() => setOnlyFailed(false)}>Show All</Button>
            </div>
          </div>
          <DataTable columns={columns} data={results} searchColumn="object_name" />
        </CardContent>
      </Card>
    </div>
  );
}


