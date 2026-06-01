import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Inbox, XCircle, Loader2, ShieldCheck, Package, Bell } from 'lucide-react';
import { RelativeDate } from '@/components/common/relative-date';
import { ListViewSkeleton, SkeletonLine } from '@/components/common/list-view-skeleton';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { DataProduct } from '@/types/data-product';

interface AccessGrantRequestItem {
  id: string;
  requester_email: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string | null;
  requested_duration_days: number;
  permission_level: string;
  reason?: string | null;
  status: string;
  created_at: string;
  handled_at?: string | null;
  handled_by?: string | null;
  admin_message?: string | null;
}

interface MyRequestsResponse {
  requests: AccessGrantRequestItem[];
  total: number;
}

type RequestRow = {
  id: string;
  entityName: string;
  entityType: string;
  entityId: string;
  permissionLevel: string;
  durationDays: number;
  status: string;
  created_at: string;
  handled_at?: string | null;
  canCancel: boolean;
  raw: AccessGrantRequestItem;
};

const STATUS_VARIANTS: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  pending: 'secondary',
  approved: 'default',
  denied: 'destructive',
  cancelled: 'outline',
  expired: 'outline',
};

function getEntityDetailPath(entityType: string, entityId: string, basePath: string): string | null {
  const key = entityType?.toLowerCase?.() ?? '';
  if (!entityId) return null;
  const prefix = basePath.split('/').slice(0, 2).join('/');
  if (key === 'data_product') return `${prefix}/my-products/${entityId}`;
  if (key === 'data_contract') return `${prefix}/contracts/${entityId}`;
  return null;
}

function entityTypeLabel(entityType: string): string {
  const key = entityType?.toLowerCase?.() ?? '';
  if (key === 'data_product') return 'Data Product';
  if (key === 'data_contract') return 'Data Contract';
  return entityType;
}

export default function MyRequests() {
  const { t } = useTranslation('home');
  const api = useApi();
  const { toast } = useToast();
  const { pathname } = useLocation();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);

  const [activeTab, setActiveTab] = useState('requests');

  // Access requests state
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(true);
  const [requestsError, setRequestsError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  // Subscriptions state
  const [subscriptions, setSubscriptions] = useState<DataProduct[]>([]);
  const [subscriptionsLoading, setSubscriptionsLoading] = useState(true);
  const [subscriptionsError, setSubscriptionsError] = useState<string | null>(null);

  useEffect(() => {
    setStaticSegments([{ label: 'My Requests' }]);
    return () => setStaticSegments([]);
  }, [setStaticSegments]);

  const loadRequests = useCallback(async () => {
    setRequestsLoading(true);
    setRequestsError(null);
    try {
      const resp = await fetch('/api/access-grants/my-requests');
      if (!resp.ok) {
        setRequestsError(`HTTP ${resp.status}`);
        setRows([]);
        return;
      }
      const data: MyRequestsResponse = await resp.json();
      const mapped: RequestRow[] = (data?.requests ?? []).map((req) => ({
        id: req.id,
        entityName: req.entity_name || req.entity_id,
        entityType: req.entity_type,
        entityId: req.entity_id,
        permissionLevel: req.permission_level,
        durationDays: req.requested_duration_days,
        status: req.status,
        created_at: req.created_at,
        handled_at: req.handled_at,
        canCancel: req.status === 'pending',
        raw: req,
      }));
      mapped.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setRows(mapped);
    } catch (e) {
      console.warn('Failed to fetch access requests:', e);
      setRequestsError(e instanceof Error ? e.message : 'Failed to load');
      setRows([]);
    } finally {
      setRequestsLoading(false);
    }
  }, []);

  const loadSubscriptions = useCallback(async () => {
    setSubscriptionsLoading(true);
    setSubscriptionsError(null);
    try {
      const data = await api.get('/api/data-products/my-subscriptions');
      setSubscriptions(Array.isArray(data) ? data : []);
    } catch (e) {
      console.warn('Failed to fetch subscriptions:', e);
      setSubscriptionsError(e instanceof Error ? e.message : 'Failed to load');
      setSubscriptions([]);
    } finally {
      setSubscriptionsLoading(false);
    }
  }, [api]);

  useEffect(() => { loadRequests(); }, [loadRequests]);
  useEffect(() => { loadSubscriptions(); }, [loadSubscriptions]);

  const handleCancel = async (requestId: string) => {
    try {
      setCancellingId(requestId);
      await api.delete(`/api/access-grants/requests/${requestId}`);
      toast({ title: t('myRequests.cancelSuccess'), variant: 'default' });
      await loadRequests();
    } catch (e) {
      toast({
        title: 'Error',
        description: e instanceof Error ? e.message : 'Failed to cancel request',
        variant: 'destructive',
      });
    } finally {
      setCancellingId(null);
    }
  };

  const pendingCount = rows.filter((r) => r.status === 'pending').length;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t('myRequests.title')}</h1>
        <p className="text-muted-foreground mt-1">{t('myRequests.description')}</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-amber-500/10 p-2.5">
                <ShieldCheck className="h-5 w-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Pending Requests</p>
                {requestsLoading ? (
                  <SkeletonLine height="h-7" width="w-10" className="mt-1" />
                ) : (
                  <p className="text-2xl font-bold">{pendingCount}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-500/10 p-2.5">
                <Bell className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Requests</p>
                {requestsLoading ? (
                  <SkeletonLine height="h-7" width="w-10" className="mt-1" />
                ) : (
                  <p className="text-2xl font-bold">{rows.length}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-green-500/10 p-2.5">
                <Package className="h-5 w-5 text-green-600 dark:text-green-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Active Subscriptions</p>
                {subscriptionsLoading ? (
                  <SkeletonLine height="h-7" width="w-10" className="mt-1" />
                ) : (
                  <p className="text-2xl font-bold">{subscriptions.length}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="requests">
            Access Requests
            {pendingCount > 0 && (
              <Badge variant="secondary" className="ml-2 h-5 px-1.5 text-xs">{pendingCount}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="subscriptions">
            My Subscriptions
            {subscriptions.length > 0 && (
              <Badge variant="secondary" className="ml-2 h-5 px-1.5 text-xs">{subscriptions.length}</Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="requests" className="mt-4">
          {requestsLoading ? (
            <ListViewSkeleton columns={7} rows={5} toolbarButtons={0} showToolbar={false} showPagination={false} />
          ) : requestsError ? (
            <div className="flex flex-col gap-2">
              <p className="text-destructive">{requestsError}</p>
              <Button variant="outline" onClick={loadRequests}>Retry</Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="border rounded-lg flex flex-col items-center justify-center py-12">
              <Inbox className="h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground text-center">{t('myRequests.empty')}</p>
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Asset Type</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Permission</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Requested</TableHead>
                    <TableHead>Resolved</TableHead>
                    <TableHead className="w-[80px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const variant = STATUS_VARIANTS[row.status] ?? 'outline';
                    const detailPath = getEntityDetailPath(row.entityType, row.entityId, pathname);
                    return (
                      <TableRow key={row.id}>
                        <TableCell className="text-muted-foreground">
                          {entityTypeLabel(row.entityType)}
                        </TableCell>
                        <TableCell>
                          {detailPath ? (
                            <Link to={detailPath} className="font-medium text-primary hover:underline">
                              {row.entityName}
                            </Link>
                          ) : (
                            <span className="font-medium">{row.entityName}</span>
                          )}
                          <span className="text-muted-foreground text-sm ml-1">
                            ({row.permissionLevel}, {row.durationDays}d)
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{row.permissionLevel}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={variant}>{row.status}</Badge>
                        </TableCell>
                        <TableCell><RelativeDate date={row.created_at} /></TableCell>
                        <TableCell>
                          {row.handled_at ? <RelativeDate date={row.handled_at} /> : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell>
                          {row.canCancel && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                              onClick={() => handleCancel(row.id)}
                              disabled={cancellingId === row.id}
                              title="Cancel"
                            >
                              {cancellingId === row.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <XCircle className="h-4 w-4" />
                              )}
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="subscriptions" className="mt-4">
          {subscriptionsLoading ? (
            <ListViewSkeleton columns={4} rows={4} toolbarButtons={0} showToolbar={false} showPagination={false} />
          ) : subscriptionsError ? (
            <div className="flex flex-col gap-2">
              <p className="text-destructive">{subscriptionsError}</p>
              <Button variant="outline" onClick={loadSubscriptions}>Retry</Button>
            </div>
          ) : subscriptions.length === 0 ? (
            <div className="border rounded-lg flex flex-col items-center justify-center py-12">
              <Package className="h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground text-center">You haven't subscribed to any data products yet.</p>
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Product</TableHead>
                    <TableHead>Domain</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Version</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {subscriptions.map((product) => {
                    const prefix = pathname.split('/').slice(0, 2).join('/');
                    const detailPath = `${prefix}/my-products/${product.id}`;
                    return (
                      <TableRow key={product.id}>
                        <TableCell>
                          <Link to={detailPath} className="font-medium text-primary hover:underline">
                            {product.name ?? product.id}
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {product.domain ?? '—'}
                        </TableCell>
                        <TableCell>
                          <Badge variant={product.status === 'active' ? 'default' : 'secondary'}>
                            {product.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {product.version ?? '—'}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
