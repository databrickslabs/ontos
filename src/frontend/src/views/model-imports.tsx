import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { Upload } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { RelativeDate } from '@/components/common/relative-date';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import ModelImportDialog from '@/components/model-import/model-import-dialog';
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { ModelImportRunSummary } from '@/types/model-import';
import { modelImportStatusVariant } from '@/lib/model-import-status';

/** Recent erwin model import runs (own runs; all runs for admins). */
export default function ModelImportsView() {
  const { t } = useTranslation(['model-import', 'common']);
  const navigate = useNavigate();
  const { get } = useApi();
  const { hasPermission } = usePermissions();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  const [runs, setRuns] = useState<ModelImportRunSummary[] | null>(null);
  const [open, setOpen] = useState(false);

  const canImport = hasPermission('data-contracts', FeatureAccessLevel.READ_WRITE)
    || hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('history.title'));
    get<ModelImportRunSummary[]>('/api/model-import/runs').then((r) => setRuns(Array.isArray(r.data) ? r.data : []));
  }, [get, t, setStaticSegments, setDynamicTitle]);

  const columns: ColumnDef<ModelImportRunSummary>[] = useMemo(() => [
    { accessorKey: 'source_model_name', header: t('history.model'),
      cell: ({ row }) => <span className="font-medium">{row.original.source_model_name || row.original.source_filename}</span> },
    { accessorKey: 'source_filename', header: t('history.file') },
    { accessorKey: 'status', header: t('history.status'),
      cell: ({ row }) => <Badge variant={modelImportStatusVariant(row.original.status)}>{t(`status.${row.original.status}`)}</Badge> },
    { accessorKey: 'user_id', header: t('history.by') },
    { accessorKey: 'created_at', header: t('history.created'),
      cell: ({ row }) => row.original.created_at ? <RelativeDate date={row.original.created_at} /> : null },
  ], [t]);

  if (runs === null) return <ListViewSkeleton />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('history.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('history.description')}</p>
        </div>
        {canImport && (
          <Button onClick={() => setOpen(true)} className="gap-2"><Upload className="h-4 w-4" />{t('upload.button')}</Button>
        )}
      </div>
      <DataTable
        columns={columns}
        data={runs}
        searchColumn="source_model_name"
        onRowClick={(row) => navigate(`/model-imports/${row.original.id}`)}
      />
      <ModelImportDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
