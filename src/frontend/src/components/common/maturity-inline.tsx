import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { HoverCard, HoverCardTrigger, HoverCardContent } from '@/components/ui/hover-card';
import { useToast } from '@/hooks/use-toast';
import {
  CheckCircle2, XCircle, AlertTriangle, Loader2, RefreshCw,
} from 'lucide-react';
import { MaturityBadge } from '@/components/common/maturity-badge';
import type { MaturityReport, LevelResult } from '@/types/maturity';

interface MaturityInlineProps {
  entityType: 'DataProduct' | 'DataContract';
  entityId: string;
  /** Render as a compact column (for header badges area) vs inline row */
  compact?: boolean;
}

const API_PREFIX: Record<string, string> = {
  DataProduct: '/api/data-products',
  DataContract: '/api/data-contracts',
};

const GATE_ICON: Record<string, { icon: typeof CheckCircle2; cls: string }> = {
  pass: { icon: CheckCircle2, cls: 'text-green-600 dark:text-green-400' },
  fail: { icon: XCircle, cls: 'text-red-600 dark:text-red-400' },
  warn: { icon: AlertTriangle, cls: 'text-amber-600 dark:text-amber-400' },
};

export function MaturityInline({ entityType, entityId, compact = false }: MaturityInlineProps) {
  const [report, setReport] = useState<MaturityReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const { toast } = useToast();

  const prefix = API_PREFIX[entityType] || API_PREFIX.DataProduct;

  const fetchReport = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${prefix}/${entityId}/maturity`);
      if (res.ok) setReport(await res.json());
    } catch { /* silent */ }
    setIsLoading(false);
  }, [entityId, prefix]);

  const evaluate = useCallback(async () => {
    setIsEvaluating(true);
    try {
      const res = await fetch(`${prefix}/${entityId}/maturity/evaluate`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setReport(data);
        const passed = data.gates_passed ?? 0;
        const total = data.gates_total ?? 0;
        const level = data.achieved_level_name || 'Not assessed';
        toast({
          title: 'Maturity evaluated',
          description: `${level} — ${passed}/${total} gates passed`,
        });
      } else {
        toast({ title: 'Evaluation failed', description: `Server returned ${res.status}`, variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Evaluation failed', description: String(e), variant: 'destructive' });
    }
    setIsEvaluating(false);
  }, [entityId, prefix, toast]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  if (isLoading) {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
  }

  if (!report) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  const achievedLevel = report.levels.find(l => l.achieved && l.level_order === report.achieved_level_order);
  const levelName = report.achieved_level_name || 'Not assessed';
  const passed = report.gates_passed ?? 0;
  const total = report.gates_total ?? 0;

  if (compact) {
    return (
      <HoverCard openDelay={200}>
        <HoverCardTrigger asChild>
          <div className="flex flex-col items-center gap-1 cursor-default group" role="button" tabIndex={0}>
            <div className="flex items-center gap-1">
              <span className="text-sm font-semibold leading-none text-muted-foreground group-hover:text-foreground transition-colors">
                {levelName}
              </span>
              <button
                className="inline-flex items-center justify-center h-4 w-4 rounded-sm hover:bg-muted transition-colors"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); evaluate(); }}
                title="Re-evaluate maturity"
              >
                {isEvaluating
                  ? <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                  : <RefreshCw className="h-3 w-3 text-muted-foreground hover:text-foreground" />}
              </button>
            </div>
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Maturity</span>
          </div>
        </HoverCardTrigger>
        <HoverCardContent className="w-72" side="bottom" align="end">
          <HoverDetail report={report} levelName={levelName} passed={passed} total={total} />
        </HoverCardContent>
      </HoverCard>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <HoverCard openDelay={200}>
        <HoverCardTrigger asChild>
          <button className="flex items-center gap-1.5 cursor-default">
            <MaturityBadge
              levelName={report.achieved_level_name}
              levelIcon={achievedLevel?.level_icon}
              levelColor={achievedLevel?.level_color}
              levelOrder={report.achieved_level_order}
              totalLevels={report.total_levels}
            />
          </button>
        </HoverCardTrigger>
        <HoverCardContent className="w-72" side="bottom" align="start">
          <HoverDetail report={report} levelName={levelName} passed={passed} total={total} />
        </HoverCardContent>
      </HoverCard>
      <span className="text-[10px] text-muted-foreground">
        {passed}/{total}
      </span>
      <Button
        variant="ghost" size="icon"
        className="h-5 w-5"
        onClick={evaluate}
        disabled={isEvaluating}
        title="Re-evaluate maturity"
      >
        {isEvaluating
          ? <Loader2 className="h-3 w-3 animate-spin" />
          : <RefreshCw className="h-3 w-3" />}
      </Button>
    </div>
  );
}

function HoverDetail({ report, levelName, passed, total }: {
  report: MaturityReport; levelName: string; passed: number; total: number;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Maturity: {levelName}</p>
        <span className="text-xs text-muted-foreground">
          {passed}/{total} gates
        </span>
      </div>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {report.levels.map((level: LevelResult) => (
          <LevelRow key={level.level_order} level={level} />
        ))}
      </div>
      {report.evaluated_at && (
        <p className="text-[10px] text-muted-foreground pt-1 border-t">
          Evaluated {new Date(report.evaluated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

function LevelRow({ level }: { level: LevelResult }) {
  const hasFails = level.gates.some(g => !g.passed && g.required);
  const hasWarns = level.gates.some(g => !g.passed && !g.required);
  const status = hasFails ? 'fail' : hasWarns ? 'warn' : 'pass';
  const { icon: Icon, cls } = GATE_ICON[status];
  const passed = level.gates.filter(g => g.passed).length;

  return (
    <div className="flex items-center gap-2 py-0.5">
      <Icon className={`h-3 w-3 shrink-0 ${cls}`} />
      <span className="font-mono text-[10px] text-muted-foreground w-3">{level.level_order}</span>
      <span className={`text-xs flex-1 truncate ${level.achieved ? 'font-medium' : 'text-muted-foreground'}`}>
        {level.level_name}
      </span>
      <span className="text-[10px] text-muted-foreground">
        {passed}/{level.gates.length}
      </span>
    </div>
  );
}
