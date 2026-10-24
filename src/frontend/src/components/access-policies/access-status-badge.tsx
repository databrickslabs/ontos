import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import type { AccessStatus } from '@/types/access-policy';

const STATUS_CLASS: Record<AccessStatus, string> = {
  draft: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  under_review: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  approved: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
  active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  needs_review: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  deprecated: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  retired: 'bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
};

export default function AccessStatusBadge({ status }: { status: AccessStatus }) {
  const { t } = useTranslation(['access-policies']);
  return (
    <Badge variant="outline" className={`border-transparent ${STATUS_CLASS[status] || ''}`}>
      {t(`access-policies:status.${status}`)}
    </Badge>
  );
}
