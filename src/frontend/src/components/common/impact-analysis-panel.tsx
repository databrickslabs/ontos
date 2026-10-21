import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, AlertCircle, RefreshCw, Target, ExternalLink } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { LineageGraph } from '@/types/ontology-schema';
import { BusinessLineageView } from '@/components/lineage';

interface ImpactAnalysisPanelProps {
  entityType: string;
  entityId: string;
  maxDepth?: number;
}

const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
};

function getEntityRoute(entityType: string, entityId: string): string {
  const base = TYPE_ROUTE_MAP[entityType];
  if (base) return `${base}/${entityId}`;
  return `/assets/${entityId}`;
}

export function ImpactAnalysisPanel({
  entityType,
  entityId,
  maxDepth = 4,
}: ImpactAnalysisPanelProps) {
  const navigate = useNavigate();
  const { t } = useTranslation('common');
  const [graphData, setGraphData] = useState<LineageGraph | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchImpact = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/business-lineage/${entityType}/${entityId}/impact?max_depth=${maxDepth}`
      );
      if (!res.ok) throw new Error(t('common:impactAnalysis.failedStatus', { status: res.status }));
      setGraphData(await res.json());
    } catch (e: any) {
      setError(e.message || t('common:impactAnalysis.failedLoad'));
    } finally {
      setIsLoading(false);
    }
  }, [entityType, entityId, maxDepth, t]);

  useEffect(() => { fetchImpact(); }, [fetchImpact]);

  const groupedImpact = useMemo(() => {
    if (!graphData) return {};
    const groups: Record<string, { entity_id: string; name: string; status?: string | null }[]> = {};
    for (const node of graphData.nodes) {
      if (node.is_center) continue;
      if (!groups[node.entity_type]) groups[node.entity_type] = [];
      groups[node.entity_type].push({
        entity_id: node.entity_id,
        name: node.name,
        status: node.status,
      });
    }
    return groups;
  }, [graphData]);

  const affectedCount = graphData ? graphData.nodes.length - 1 : 0;

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">{t('common:impactAnalysis.analyzing')}</span>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-6 text-center">
          <AlertCircle className="h-5 w-5 text-destructive mx-auto mb-2" />
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={fetchImpact}>
            <RefreshCw className="mr-2 h-3.5 w-3.5" /> {t('common:retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Target className="h-4 w-4" />
              {t('common:impactAnalysis.summary')}
            </span>
            <Badge variant={affectedCount > 0 ? 'secondary' : 'outline'}>
              {t('common:impactAnalysis.affectedCount', { count: affectedCount })}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {affectedCount === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('common:impactAnalysis.noDownstream', { type: entityType })}
            </p>
          ) : (
            <div className="space-y-3">
              {Object.entries(groupedImpact).map(([type, entities]) => (
                <div key={type}>
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                    {type.replace(/([A-Z])/g, ' $1').trim()} ({entities.length})
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    {entities.map((e) => (
                      <Badge
                        key={e.entity_id}
                        variant="outline"
                        className="cursor-pointer hover:bg-accent text-xs"
                        onClick={() => navigate(getEntityRoute(type, e.entity_id))}
                      >
                        {e.name}
                        <ExternalLink className="ml-1 h-2.5 w-2.5" />
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Graph visualization */}
      {affectedCount > 0 && (
        <BusinessLineageView
          entityType={entityType}
          entityId={entityId}
          direction="downstream"
          maxDepth={maxDepth}
          showToolbar={false}
          className="h-[500px]"
        />
      )}
    </div>
  );
}
