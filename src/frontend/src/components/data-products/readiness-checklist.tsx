import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CheckCircle2, XCircle, AlertTriangle, Loader2, RefreshCw, ClipboardCheck } from 'lucide-react';
import type { ReadinessReport } from '@/types/ontology-schema';

interface ReadinessChecklistProps {
  productId: string;
}

const STATUS_CONFIG = {
  pass: { icon: CheckCircle2, color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-950/30' },
  fail: { icon: XCircle, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-950/30' },
  warn: { icon: AlertTriangle, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950/30' },
};

const OVERALL_CONFIG: Record<string, { label: string; variant: 'default' | 'destructive' | 'secondary' }> = {
  ready: { label: 'Ready', variant: 'default' },
  not_ready: { label: 'Not Ready', variant: 'destructive' },
  partial: { label: 'Partially Ready', variant: 'secondary' },
};

export function ReadinessChecklist({ productId }: ReadinessChecklistProps) {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/data-products/${productId}/readiness`);
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      setReport(await res.json());
    } catch (e: any) {
      setError(e.message || 'Failed to load readiness report');
    } finally {
      setIsLoading(false);
    }
  }, [productId]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">Checking readiness...</span>
        </CardContent>
      </Card>
    );
  }

  if (error || !report) {
    return (
      <Card>
        <CardContent className="py-6 text-center">
          <p className="text-sm text-destructive">{error || 'Unable to load readiness report'}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={fetchReport}>
            <RefreshCw className="mr-2 h-3.5 w-3.5" /> Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  const overall = OVERALL_CONFIG[report.overall] || OVERALL_CONFIG.not_ready;
  const passCount = report.checks.filter(c => c.status === 'pass').length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4" />
            Production Readiness
          </span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-normal text-muted-foreground">
              {passCount}/{report.checks.length} passed
            </span>
            <Badge variant={overall.variant}>{overall.label}</Badge>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={fetchReport}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {report.checks.map((check, i) => {
            const cfg = STATUS_CONFIG[check.status as keyof typeof STATUS_CONFIG] || STATUS_CONFIG.warn;
            const Icon = cfg.icon;
            return (
              <div
                key={i}
                className={`flex items-start gap-3 rounded-md px-3 py-2.5 ${cfg.bg}`}
              >
                <Icon className={`h-4 w-4 mt-0.5 flex-shrink-0 ${cfg.color}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{check.name}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{check.detail}</p>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
