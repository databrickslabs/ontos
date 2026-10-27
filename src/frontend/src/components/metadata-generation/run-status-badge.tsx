import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { GenerationRunStatus } from '@/types/metadata-generation';

const VARIANT: Record<GenerationRunStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  pending: 'outline',
  running: 'secondary',
  ingesting: 'secondary',
  completed: 'default',
  failed: 'destructive',
  cancelled: 'outline',
};

export default function RunStatusBadge({ status }: { status: GenerationRunStatus }) {
  const { t } = useTranslation('metadata-generation');
  return (
    <Badge variant={VARIANT[status]} className="gap-1">
      {(status === 'pending' || status === 'running' || status === 'ingesting') && <Loader2 className="h-3 w-3 animate-spin" />}
      {t(`runStatus.${status}`)}
    </Badge>
  );
}
