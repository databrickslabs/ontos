import { useTranslation } from 'react-i18next';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { CompileTarget } from '@/types/access-policy';

/** Picks one compile target; hidden while there is only one to choose from. */
export default function TargetSelect({
  targets,
  value,
  onChange,
}: {
  targets: CompileTarget[];
  value: string;
  onChange: (key: string) => void;
}) {
  const { t } = useTranslation(['access-policies']);
  if (targets.length < 2) return null;
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-[200px]" aria-label={t('access-policies:targets.target')}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {targets.map((tg) => (
          <SelectItem key={tg.key} value={tg.key}>
            {tg.label} <span className="text-xs text-muted-foreground">({tg.key})</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
