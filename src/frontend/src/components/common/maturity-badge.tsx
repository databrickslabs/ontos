import { Badge } from '@/components/ui/badge';
import {
  LockKeyhole, FileText, BookOpen, Activity, ShieldCheck,
} from 'lucide-react';

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  'lock-keyhole': LockKeyhole,
  'file-text': FileText,
  'book-open': BookOpen,
  'activity': Activity,
  'shield-check': ShieldCheck,
};

const COLOR_CLASSES: Record<string, string> = {
  blue: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  cyan: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
  green: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  red: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  slate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
};

interface MaturityBadgeProps {
  levelName: string | null;
  levelIcon?: string | null;
  levelColor?: string | null;
  levelOrder?: number | null;
  totalLevels?: number;
  className?: string;
}

export function MaturityBadge({
  levelName,
  levelIcon,
  levelColor,
  levelOrder,
  totalLevels,
  className,
}: MaturityBadgeProps) {
  if (!levelName) {
    return (
      <Badge variant="outline" className={`text-muted-foreground ${className || ''}`}>
        Not assessed
      </Badge>
    );
  }

  const Icon = ICON_MAP[levelIcon || 'shield-check'] || ShieldCheck;
  const colorClass = COLOR_CLASSES[levelColor || 'blue'] || COLOR_CLASSES.blue;

  return (
    <Badge variant="outline" className={`${colorClass} ${className || ''}`}>
      <Icon className="h-3 w-3 mr-1" />
      {levelName}
      {levelOrder != null && totalLevels ? (
        <span className="ml-1 opacity-70">({levelOrder}/{totalLevels})</span>
      ) : null}
    </Badge>
  );
}
