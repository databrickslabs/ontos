import { useState, useEffect, useCallback } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { PanelSkeleton } from '@/components/common/list-view-skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { RelativeDate } from '@/components/common/relative-date';
import HandleAccessGrantDialog from './handle-access-grant-dialog';
import { 
  Shield, 
  Clock, 
  Users, 
  AlertTriangle, 
  XCircle, 
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Loader2
} from 'lucide-react';

interface AccessGrant {
  id: string;
  grantee_email: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  permission_level: string;
  granted_at: string;
  expires_at: string;
  granted_by?: string;
  status: string;
  days_until_expiry?: number;
  is_active: boolean;
}

interface AccessGrantRequest {
  id: string;
  requester_email: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  requested_duration_days: number;
  permission_level: string;
  reason?: string;
  status: string;
  created_at: string;
}

interface AccessGrantSummary {
  active_grants_count: number;
  pending_requests_count: number;
  expiring_soon_count: number;
  total_grants_count: number;
}

interface AccessGrantsPanelProps {
  entityType: string;
  entityId: string;
  canManage?: boolean;
  showPendingRequests?: boolean;
  compact?: boolean;
}

const PERMISSION_BADGES: Record<string, { variant: 'default' | 'secondary' | 'outline'; label: string }> = {
  READ: { variant: 'secondary', label: 'Read' },
  WRITE: { variant: 'default', label: 'Write' },
  MANAGE: { variant: 'outline', label: 'Manage' },
};

const STATUS_BADGES: Record<string, { className: string; label: string }> = {
  active: { className: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300', label: 'Active' },
  expired: { className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300', label: 'Expired' },
  revoked: { className: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', label: 'Revoked' },
  pending: { className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300', label: 'Pending' },
};

export default function AccessGrantsPanel({
  entityType,
  entityId,
  canManage = false,
  showPendingRequests = true,
  compact = false,
}: AccessGrantsPanelProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['access-grants', 'common']);

  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [pendingRequests, setPendingRequests] = useState<AccessGrantRequest[]>([]);
  const [summary, setSummary] = useState<AccessGrantSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(!compact);
  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false);
  const [grantToRevoke, setGrantToRevoke] = useState<AccessGrant | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [handleRequestDialogOpen, setHandleRequestDialogOpen] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState<AccessGrantRequest | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [grantsRes, summaryRes] = await Promise.all([
        get<{ grants: AccessGrant[]; total: number }>(
          `/api/access-grants/entity/${entityType}/${entityId}?include_inactive=false`
        ),
        get<AccessGrantSummary>(`/api/access-grants/entity/${entityType}/${entityId}/summary`),
      ]);

      if (grantsRes.data) {
        setGrants(grantsRes.data.grants || []);
      }
      if (summaryRes.data) {
        setSummary(summaryRes.data);
      }

      // Fetch pending requests if needed
      if (showPendingRequests && canManage) {
        const requestsRes = await get<{ requests: AccessGrantRequest[]; total: number }>(
          `/api/access-grants/entity/${entityType}/${entityId}/requests`
        );
        if (requestsRes.data) {
          setPendingRequests(requestsRes.data.requests || []);
        }
      }
    } catch (err) {
      console.error('Failed to fetch access grants:', err);
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, showPendingRequests, canManage, get]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRevoke = async () => {
    if (!grantToRevoke) return;

    setRevoking(true);
    try {
      const res = await post(`/api/access-grants/${grantToRevoke.id}/revoke`, {});
      if (res.error) {
        throw new Error(res.error);
      }

      toast({
        title: t('access-grants:panel.revokedTitle', 'Access Revoked'),
        description: t('access-grants:panel.revokedDescription', {
          user: grantToRevoke.grantee_email,
          defaultValue: 'Access for {{user}} has been revoked.',
        }),
      });

      setRevokeDialogOpen(false);
      setGrantToRevoke(null);
      fetchData();
    } catch (e: any) {
      toast({
        title: t('common:toast.error', 'Error'),
        description: e.message || t('access-grants:panel.revokeError', 'Failed to revoke access'),
        variant: 'destructive',
      });
    } finally {
      setRevoking(false);
    }
  };

  const openRevokeDialog = (grant: AccessGrant) => {
    setGrantToRevoke(grant);
    setRevokeDialogOpen(true);
  };

  const openHandleRequestDialog = (request: AccessGrantRequest) => {
    setSelectedRequest(request);
    setHandleRequestDialogOpen(true);
  };

  const formatDaysUntilExpiry = (days?: number): string => {
    if (days === undefined || days === null) return t('access-grants:panel.expiry.unknown', 'Unknown');
    if (days < 0) return t('access-grants:panel.expiry.expired', 'Expired');
    if (days === 0) return t('access-grants:panel.expiry.today', 'Today');
    if (days < 7) return t('access-grants:panel.expiry.days', { count: days });
    if (days < 30) return t('access-grants:panel.expiry.weeks', { count: Math.floor(days / 7) });
    return t('access-grants:panel.expiry.months', { count: Math.floor(days / 30) });
  };

  const getExpiryBadgeClass = (days?: number): string => {
    if (days === undefined || days === null || days < 0) {
      return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300';
    }
    if (days <= 7) {
      return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300';
    }
    return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
  };

  if (loading) {
    return <PanelSkeleton rows={2} rowHeight="h-10" />;
  }

  const hasContent = grants.length > 0 || pendingRequests.length > 0;
  const totalCount = (summary?.active_grants_count || 0) + (summary?.pending_requests_count || 0);

  return (
    <Card>
      <CardHeader className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            <span>{t('access-grants:panel.title', 'Access Grants')}</span>
            {totalCount > 0 && (
              <Badge variant="secondary">{totalCount}</Badge>
            )}
            {summary && summary.expiring_soon_count > 0 && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <Badge variant="outline" className="bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300">
                      <AlertTriangle className="h-3 w-3 mr-1" />
                      {t('access-grants:panel.expiringBadge', {
                        count: summary.expiring_soon_count,
                        defaultValue: '{{count}} expiring',
                      })}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{t('access-grants:panel.expiringSoonTooltip', { count: summary.expiring_soon_count })}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation();
                fetchData();
              }}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </div>
        </CardTitle>
        <CardDescription>
          {t('access-grants:panel.description', 'Users with time-limited access to this resource')}
        </CardDescription>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4">
          {/* Pending Requests Section */}
          {showPendingRequests && canManage && pendingRequests.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-orange-600 dark:text-orange-400">
                <Clock className="h-4 w-4" />
                {t('access-grants:panel.pendingRequestsCount', { count: pendingRequests.length })}
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('access-grants:panel.columns.requester', 'Requester')}</TableHead>
                    <TableHead>{t('common:labels.permission', 'Permission')}</TableHead>
                    <TableHead>{t('access-grants:panel.columns.duration', 'Duration')}</TableHead>
                    <TableHead>{t('access-grants:panel.requestedAt', 'Requested')}</TableHead>
                    <TableHead className="text-right">{t('access-grants:panel.columns.actions', 'Actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingRequests.map((request) => (
                    <TableRow key={request.id}>
                      <TableCell className="font-medium">{request.requester_email}</TableCell>
                      <TableCell>
                        <Badge variant={PERMISSION_BADGES[request.permission_level]?.variant || 'secondary'}>
                          {t(`access-grants:permissionLevels.${request.permission_level}`, PERMISSION_BADGES[request.permission_level]?.label || request.permission_level)}
                        </Badge>
                      </TableCell>
                      <TableCell>{t('access-grants:panel.durationDays', { count: request.requested_duration_days })}</TableCell>
                      <TableCell>
                        <RelativeDate date={request.created_at} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openHandleRequestDialog(request)}
                        >
                          {t('access-grants:panel.review', 'Review')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Active Grants Section */}
          {grants.length > 0 ? (
            <div className="space-y-2">
              {pendingRequests.length > 0 && (
                <div className="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
                  <Users className="h-4 w-4" />
                  {t('access-grants:panel.activeGrantsCount', { count: grants.length })}
                </div>
              )}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('access-grants:panel.columns.user', 'User')}</TableHead>
                    <TableHead>{t('common:labels.permission', 'Permission')}</TableHead>
                    <TableHead>{t('access-grants:panel.columns.expires', 'Expires')}</TableHead>
                    <TableHead>{t('access-grants:panel.columns.grantedBy', 'Granted By')}</TableHead>
                    <TableHead>{t('common:labels.status', 'Status')}</TableHead>
                    {canManage && <TableHead className="text-right">{t('access-grants:panel.columns.actions', 'Actions')}</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {grants.map((grant) => (
                    <TableRow key={grant.id}>
                      <TableCell className="font-medium">{grant.grantee_email}</TableCell>
                      <TableCell>
                        <Badge variant={PERMISSION_BADGES[grant.permission_level]?.variant || 'secondary'}>
                          {t(`access-grants:permissionLevels.${grant.permission_level}`, PERMISSION_BADGES[grant.permission_level]?.label || grant.permission_level)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger>
                              <Badge className={getExpiryBadgeClass(grant.days_until_expiry)}>
                                {formatDaysUntilExpiry(grant.days_until_expiry)}
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>{t('access-grants:panel.expiresTooltip', { date: new Date(grant.expires_at).toLocaleString() })}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {grant.granted_by || '-'}
                      </TableCell>
                      <TableCell>
                        <Badge className={STATUS_BADGES[grant.status]?.className || ''}>
                          {t(`access-grants:statuses.${grant.status}`, STATUS_BADGES[grant.status]?.label || grant.status)}
                        </Badge>
                      </TableCell>
                      {canManage && (
                        <TableCell className="text-right">
                          {grant.is_active && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openRevokeDialog(grant)}
                              className="text-destructive hover:text-destructive"
                            >
                              <XCircle className="h-4 w-4" />
                            </Button>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : !hasContent ? (
            <div className="text-center py-8 text-muted-foreground">
              <Users className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>{t('access-grants:panel.noGrants', 'No access grants for this resource')}</p>
              <p className="text-sm">
                {t('access-grants:panel.noGrantsHint', 'Users can request time-limited access using the "Request Access" button.')}
              </p>
            </div>
          ) : null}
        </CardContent>
      )}

      {/* Revoke Confirmation Dialog */}
      <AlertDialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('access-grants:panel.revokeTitle', 'Revoke Access')}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="access-grants:panel.revokeConfirmDetailed"
                values={{ user: grantToRevoke?.grantee_email }}
                components={{ bold: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revoking}>{t('common:actions.cancel', 'Cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevoke}
              disabled={revoking}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {revoking && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('access-grants:panel.revokeTitle', 'Revoke Access')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Handle Request Dialog */}
      {selectedRequest && (
        <HandleAccessGrantDialog
          isOpen={handleRequestDialogOpen}
          onOpenChange={setHandleRequestDialogOpen}
          request={selectedRequest}
          onDecisionMade={() => {
            fetchData();
            setSelectedRequest(null);
          }}
        />
      )}
    </Card>
  );
}

