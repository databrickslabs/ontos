import { useState, useEffect, useCallback } from 'react';
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
        title: 'Access Revoked',
        description: `Access for ${grantToRevoke.grantee_email} has been revoked.`,
      });

      setRevokeDialogOpen(false);
      setGrantToRevoke(null);
      fetchData();
    } catch (e: any) {
      toast({
        title: 'Error',
        description: e.message || 'Failed to revoke access',
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
    if (days === undefined || days === null) return 'Unknown';
    if (days < 0) return 'Expired';
    if (days === 0) return 'Today';
    if (days === 1) return '1 day';
    if (days < 7) return `${days} days`;
    if (days < 30) return `${Math.floor(days / 7)} week(s)`;
    return `${Math.floor(days / 30)} month(s)`;
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
            <span>Access Grants</span>
            {totalCount > 0 && (
              <Badge variant="secondary">{totalCount}</Badge>
            )}
            {summary && summary.expiring_soon_count > 0 && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <Badge variant="outline" className="bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300">
                      <AlertTriangle className="h-3 w-3 mr-1" />
                      {summary.expiring_soon_count} expiring
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{summary.expiring_soon_count} grant(s) expiring soon</p>
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
          Users with time-limited access to this resource
        </CardDescription>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4">
          {/* Pending Requests Section */}
          {showPendingRequests && canManage && pendingRequests.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-orange-600 dark:text-orange-400">
                <Clock className="h-4 w-4" />
                Pending Requests ({pendingRequests.length})
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requester</TableHead>
                    <TableHead>Permission</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Requested</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingRequests.map((request) => (
                    <TableRow key={request.id}>
                      <TableCell className="font-medium">{request.requester_email}</TableCell>
                      <TableCell>
                        <Badge variant={PERMISSION_BADGES[request.permission_level]?.variant || 'secondary'}>
                          {PERMISSION_BADGES[request.permission_level]?.label || request.permission_level}
                        </Badge>
                      </TableCell>
                      <TableCell>{request.requested_duration_days} days</TableCell>
                      <TableCell>
                        <RelativeDate date={request.created_at} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openHandleRequestDialog(request)}
                        >
                          Review
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
                  Active Grants ({grants.length})
                </div>
              )}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Permission</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>Granted By</TableHead>
                    <TableHead>Status</TableHead>
                    {canManage && <TableHead className="text-right">Actions</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {grants.map((grant) => (
                    <TableRow key={grant.id}>
                      <TableCell className="font-medium">{grant.grantee_email}</TableCell>
                      <TableCell>
                        <Badge variant={PERMISSION_BADGES[grant.permission_level]?.variant || 'secondary'}>
                          {PERMISSION_BADGES[grant.permission_level]?.label || grant.permission_level}
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
                              <p>Expires: {new Date(grant.expires_at).toLocaleString()}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {grant.granted_by || '-'}
                      </TableCell>
                      <TableCell>
                        <Badge className={STATUS_BADGES[grant.status]?.className || ''}>
                          {STATUS_BADGES[grant.status]?.label || grant.status}
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
              <p>No access grants for this resource</p>
              <p className="text-sm">
                Users can request time-limited access using the "Request Access" button.
              </p>
            </div>
          ) : null}
        </CardContent>
      )}

      {/* Revoke Confirmation Dialog */}
      <AlertDialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke Access</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to revoke access for{' '}
              <strong>{grantToRevoke?.grantee_email}</strong>? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revoking}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevoke}
              disabled={revoking}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {revoking && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Revoke Access
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

