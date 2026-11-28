import type { ModelImportStatus } from '@/types/model-import';

/** Badge variant for a model import run status. */
export function modelImportStatusVariant(status: ModelImportStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default';
  if (status === 'failed') return 'destructive';
  if (status === 'running' || status === 'previewed') return 'secondary';
  return 'outline';
}
