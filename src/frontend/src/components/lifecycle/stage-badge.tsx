import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { stageColorClass, stageLabel } from '@/lib/lifecycle-stages';
import type { LifecycleStage } from '@/types/lifecycle-stage-groups';

interface StageBadgeProps {
  /** The stage, from the entity's group; null shows `status` as sent. */
  stage: Pick<LifecycleStage, 'key' | 'label' | 'color' | 'category'> | null | undefined;
  /** The stored status, shown when the stage is unknown. */
  status?: string | null;
  className?: string;
}

/** A status badge drawn from the stage's label and colour. */
export default function StageBadge({ stage, status, className }: StageBadgeProps) {
  const { t } = useTranslation(['lifecycle']);
  const text = stage ? stageLabel(stage, t) : status || '';
  if (!text) return null;
  return (
    <Badge
      variant="outline"
      className={cn(stageColorClass(stage), className)}
      data-stage={stage?.key ?? status ?? undefined}
      data-category={stage?.category}
    >
      {text}
    </Badge>
  );
}
