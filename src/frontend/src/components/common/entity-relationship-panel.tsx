import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Link2, ArrowRight, ArrowLeft, Loader2, AlertCircle, ExternalLink,
  PlusCircle, Trash2,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import { AddRelationshipDialog } from '@/components/common/add-relationship-dialog';

interface RelationshipRecord {
  id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  relationship_type: string;
  relationship_label?: string | null;
  source_name?: string | null;
  target_name?: string | null;
  properties?: Record<string, any> | null;
  created_by?: string | null;
  created_at: string;
}

interface RelationshipSummary {
  entity_type: string;
  entity_id: string;
  outgoing: RelationshipRecord[];
  incoming: RelationshipRecord[];
  total: number;
}

interface EntityRelationshipPanelProps {
  entityType: string;
  entityId: string;
  title?: string;
  className?: string;
  canEdit?: boolean;
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

export function EntityRelationshipPanel({
  entityType,
  entityId,
  title,
  className,
  canEdit = false,
}: EntityRelationshipPanelProps) {
  const { t } = useTranslation('common');
  const resolvedTitle = title ?? t('common:entityRelationships.title');
  const [data, setData] = useState<RelationshipSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add relationship state
  const [isAddOpen, setIsAddOpen] = useState(false);

  // Delete state
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Type filter for relationship table
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const { get: apiGet, delete: apiDelete } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();

  const fetchRelationships = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiGet<RelationshipSummary>(
        `/api/entities/${entityType}/${entityId}/relationships`
      );
      if (response.error) throw new Error(response.error);
      setData(response.data ?? null);
    } catch (err: any) {
      setError(err.message || t('common:entityRelationships.failedLoad'));
    } finally {
      setLoading(false);
    }
  }, [apiGet, entityType, entityId, t]);

  useEffect(() => { fetchRelationships(); }, [fetchRelationships]);

  const handleDeleteRelationship = async () => {
    if (!deleteId) return;
    setDeleteLoading(true);
    try {
      const response = await apiDelete(`/api/entity-relationships/${deleteId}`);
      if (response.error) throw new Error(response.error);
      toast({ title: t('common:entityRelationships.relationshipRemoved') });
      setDeleteId(null);
      fetchRelationships();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('common:toast.error'), description: err.message });
    } finally {
      setDeleteLoading(false);
    }
  };

  const outgoing = data?.outgoing || [];
  const incoming = data?.incoming || [];
  const total = outgoing.length + incoming.length;

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const rel of outgoing) {
      const t = rel.target_type;
      counts[t] = (counts[t] || 0) + 1;
    }
    for (const rel of incoming) {
      const t = rel.source_type;
      counts[t] = (counts[t] || 0) + 1;
    }
    return counts;
  }, [outgoing, incoming]);

  const filteredOutgoing = typeFilter
    ? outgoing.filter(r => r.target_type === typeFilter)
    : outgoing;
  const filteredIncoming = typeFilter
    ? incoming.filter(r => r.source_type === typeFilter)
    : incoming;
  const filteredTotal = filteredOutgoing.length + filteredIncoming.length;

  if (loading) {
    return (
      <Card className={className}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            {resolvedTitle}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={className}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            {resolvedTitle}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card className={className}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Link2 className="h-4 w-4" />
              {resolvedTitle}
              <Badge variant="secondary" className="ml-1 text-xs">{total}</Badge>
            </CardTitle>
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setIsAddOpen(true)}>
                <PlusCircle className="mr-1 h-3.5 w-3.5" /> {t('common:actions.add')}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {total === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              {t('common:entityRelationships.noneFound')}
            </p>
          ) : (
            <div className="space-y-2">
              {/* Type filter bar */}
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setTypeFilter(null)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    !typeFilter ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'
                  }`}
                >
                  {t('common:entityRelationships.allCount', { count: total })}
                </button>
                {Object.entries(typeCounts).map(([type, count]) => (
                  <button
                    key={type}
                    onClick={() => setTypeFilter(typeFilter === type ? null : type)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      typeFilter === type ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'
                    }`}
                  >
                    {count} {type.replace(/([A-Z])/g, ' $1').trim()}
                  </button>
                ))}
              </div>

              <Separator />

              {filteredTotal === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  {t('common:entityRelationships.noneMatchFilter')}
                </p>
              ) : (
                <div className="space-y-0">
                  {filteredOutgoing.map((rel) => (
                    <div key={rel.id} className="group flex items-center gap-2 px-3 py-1 rounded-md hover:bg-muted transition-colors">
                      <button
                        onClick={() => navigate(getEntityRoute(rel.target_type, rel.target_id))}
                        className="flex items-center gap-2 flex-1 text-left min-w-0"
                      >
                        <ArrowRight className="h-3.5 w-3.5 text-blue-500 flex-shrink-0" />
                        <span className="text-sm truncate flex-1">
                          {rel.target_name || rel.target_id}
                        </span>
                        <Badge variant="secondary" className="text-xs flex-shrink-0">
                          {rel.target_type.replace(/([A-Z])/g, ' $1').trim()}
                        </Badge>
                        <span className="text-xs text-muted-foreground flex-shrink-0 hidden sm:inline">
                          {t('common:entityRelationships.thisAsset')} <span className="font-medium text-foreground">{rel.relationship_label || rel.relationship_type}</span> {rel.target_name || rel.target_id}
                        </span>
                        <ExternalLink className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                      </button>
                      {canEdit && (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                                onClick={() => setDeleteId(rel.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t('common:entityRelationships.removeRelationshipTooltip')}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </div>
                  ))}
                  {filteredOutgoing.length > 0 && filteredIncoming.length > 0 && <Separator />}
                  {filteredIncoming.map((rel) => (
                    <div key={rel.id} className="group flex items-center gap-2 px-3 py-1 rounded-md hover:bg-muted transition-colors">
                      <button
                        onClick={() => navigate(getEntityRoute(rel.source_type, rel.source_id))}
                        className="flex items-center gap-2 flex-1 text-left min-w-0"
                      >
                        <ArrowLeft className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
                        <span className="text-sm truncate flex-1">
                          {rel.source_name || rel.source_id}
                        </span>
                        <Badge variant="secondary" className="text-xs flex-shrink-0">
                          {rel.source_type.replace(/([A-Z])/g, ' $1').trim()}
                        </Badge>
                        <span className="text-xs text-muted-foreground flex-shrink-0 hidden sm:inline">
                          <span className="font-medium text-foreground">{rel.source_name || rel.source_id}</span> <span className="font-medium text-foreground">{rel.relationship_label || rel.relationship_type}</span> {t('common:entityRelationships.thisAsset')}
                        </span>
                        <ExternalLink className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                      </button>
                      {canEdit && (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                                onClick={() => setDeleteId(rel.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t('common:entityRelationships.removeRelationshipTooltip')}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Relationship Dialog */}
      <AddRelationshipDialog
        isOpen={isAddOpen}
        onOpenChange={setIsAddOpen}
        entityType={entityType}
        entityId={entityId}
        onRelationshipCreated={fetchRelationships}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteId} onOpenChange={(open) => { if (!open) setDeleteId(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('common:entityRelationships.removeRelationshipTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('common:entityRelationships.removeConfirm')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteRelationship}
              className="bg-red-600 hover:bg-red-700"
              disabled={deleteLoading}
            >
              {deleteLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('common:actions.remove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
