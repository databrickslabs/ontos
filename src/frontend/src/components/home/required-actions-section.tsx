import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, CheckSquare, ChevronLeft, ChevronRight } from 'lucide-react';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Link } from 'react-router-dom';
import ConfirmRoleRequestDialog from '@/components/settings/confirm-role-request-dialog';

interface ApprovalsQueue {
  contracts: { id: string; name?: string; status?: string }[];
  products: { id: string; title?: string; status?: string }[];
}

export default function RequiredActionsSection() {
  const { t, i18n } = useTranslation('home');
  const { notifications, isLoading, fetchNotifications, markAsRead } = useNotificationsStore();
  const [approvals, setApprovals] = useState<ApprovalsQueue>({ contracts: [], products: [] });
  const [loadingApprovals, setLoadingApprovals] = useState<boolean>(true);
  const [approvalsError, setApprovalsError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogPayload, setDialogPayload] = useState<Record<string, any> | null>(null);
  const [roleRequestPage, setRoleRequestPage] = useState(0);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  useEffect(() => {
    const fetchApprovals = async () => {
      setLoadingApprovals(true);
      setApprovalsError(null);
      try {
        const res = await fetch('/api/approvals/queue', { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setApprovals({
          contracts: Array.isArray(data?.contracts) ? data.contracts : [],
          products: Array.isArray(data?.products) ? data.products : [],
        });
      } catch (e: any) {
        setApprovals({ contracts: [], products: [] });
        setApprovalsError(e?.message || 'Failed to load approvals');
      } finally {
        setLoadingApprovals(false);
      }
    };
    fetchApprovals();
  }, []);

  // Filter role access requests separately
  const roleRequests = notifications.filter(
    n => n.type === 'action_required' && n.action_type === 'handle_role_request'
  );

  // Filter other action items (excluding role requests)
  const actionItems = notifications.filter(
    n => n.type === 'action_required' && n.action_type !== 'handle_role_request'
  );

  // Create unified approvals list
  type UnifiedApproval = {
    id: string;
    type: 'role_request' | 'contract' | 'product';
    title: string;
    subtitle?: string;
    date: string;
    link?: string;
    payload?: Record<string, any>;
  };

  const unifiedApprovals: UnifiedApproval[] = [
    // Role requests
    ...roleRequests.map(req => ({
      id: req.id,
      type: 'role_request' as const,
      title: req.action_payload?.requester_email || 'Unknown user',
      subtitle: req.action_payload?.role_name || 'Unknown role',
      date: req.created_at,
      payload: req.action_payload ?? undefined,
    })),
    // Contracts
    ...approvals.contracts.map(c => ({
      id: c.id,
      type: 'contract' as const,
      title: c.name || c.id,
      subtitle: c.status,
      date: new Date().toISOString(), // Contracts don't have date from API
      link: `/data-contracts/${c.id}`,
    })),
    // Products
    ...approvals.products.map(p => ({
      id: p.id,
      type: 'product' as const,
      title: p.title || p.id,
      subtitle: p.status,
      date: new Date().toISOString(), // Products don't have date from API
      link: `/data-products/${p.id}`,
    })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  const handleOpenConfirmDialog = (payload: Record<string, any> | null) => {
    setDialogPayload(payload);
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setDialogPayload(null);
    fetchNotifications(); // Refresh notifications after approval/denial
  };

  // Type badge helper
  const getTypeBadge = (type: UnifiedApproval['type']) => {
    const badges = {
      role_request: {
        label: 'Role Request',
        className: 'bg-blue-500/15 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300'
      },
      contract: {
        label: 'Contract',
        className: 'bg-purple-500/15 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300'
      },
      product: {
        label: 'Product',
        className: 'bg-green-500/15 text-green-700 dark:bg-green-500/20 dark:text-green-300'
      },
    };
    const badge = badges[type];
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  return (
    <section className="mb-16">
      <h2 className="text-2xl font-semibold mb-4">{t('requiredActionsSection.title')}</h2>

      <Card>
        <CardHeader>
          <CardTitle>Approvals & Actions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loadingApprovals || isLoading ? (
            <div className="flex justify-center items-center h-32">{t('requiredActionsSection.loading')}</div>
          ) : approvalsError ? (
            <div className="text-sm text-destructive p-6">{approvalsError}</div>
          ) : unifiedApprovals.length === 0 && actionItems.length === 0 ? (
            <p className="text-center text-muted-foreground p-12">{t('requiredActionsSection.noActions')}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/30 border-b">
                    <tr>
                      <th className="text-left p-2.5 font-medium">Type</th>
                      <th className="text-left p-2.5 font-medium">Requester / Name</th>
                      <th className="text-left p-2.5 font-medium">Role / Status / Reason</th>
                      <th className="text-left p-2.5 font-medium">Date</th>
                      <th className="text-right p-2.5 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {/* Unified approvals */}
                    {unifiedApprovals.slice(roleRequestPage * 10, (roleRequestPage + 1) * 10).map(item => (
                      <tr key={item.id} className="hover:bg-muted/20 transition-colors">
                        <td className="p-2.5">
                          {getTypeBadge(item.type)}
                        </td>
                        <td className="p-2.5">
                          <div className="font-medium truncate max-w-[250px]">
                            {item.title}
                          </div>
                        </td>
                        <td className="p-2.5">
                          <div className="text-muted-foreground truncate max-w-[250px]">
                            {item.type === 'role_request' ? (
                              <>
                                <div className="font-medium text-foreground">{item.subtitle}</div>
                                {item.payload?.requester_message && (
                                  <div className="text-xs italic" title={item.payload.requester_message}>
                                    "{item.payload.requester_message}"
                                  </div>
                                )}
                              </>
                            ) : (
                              <span>{item.subtitle || '-'}</span>
                            )}
                          </div>
                        </td>
                        <td className="p-2.5 text-muted-foreground whitespace-nowrap text-xs">
                          {new Date(item.date).toLocaleDateString(i18n.language)}
                        </td>
                        <td className="p-2.5">
                          <div className="flex items-center justify-end gap-1">
                            {item.type === 'role_request' ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2"
                                  onClick={() => handleOpenConfirmDialog(item.payload!)}
                                  title="Approve/Deny request"
                                >
                                  <CheckSquare className="h-3.5 w-3.5" />
                                </Button>
                              </>
                            ) : (
                              <Button asChild size="sm" variant="ghost" className="h-7 px-2">
                                <Link to={item.link!}>Open</Link>
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {/* Other action items (notifications) */}
                    {actionItems.slice(0, 10 - Math.min(10, unifiedApprovals.length)).map(n => (
                      <tr key={n.id} className="hover:bg-muted/20 transition-colors">
                        <td className="p-2.5">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-orange-500/15 text-orange-700 dark:bg-orange-500/20 dark:text-orange-300">
                            Notification
                          </span>
                        </td>
                        <td className="p-2.5">
                          <div className="font-medium truncate max-w-[250px]">{n.title}</div>
                        </td>
                        <td className="p-2.5">
                          <div className="text-muted-foreground truncate max-w-[250px]">{n.subtitle || '-'}</div>
                        </td>
                        <td className="p-2.5 text-muted-foreground whitespace-nowrap text-xs">
                          {n.created_at ? new Date(n.created_at).toLocaleDateString(i18n.language) : '-'}
                        </td>
                        <td className="p-2.5">
                          <div className="flex items-center justify-end gap-1">
                            {n.link && (
                              <Button asChild size="sm" variant="ghost" className="h-7 px-2">
                                <Link to={n.link}>Open</Link>
                              </Button>
                            )}
                            {!n.read && (
                              <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => markAsRead(n.id)}>
                                Mark Read
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              {(unifiedApprovals.length > 10 || actionItems.length > 10) && (
                <div className="flex items-center justify-between p-3 border-t bg-muted/10">
                  <div className="text-xs text-muted-foreground">
                    Showing {roleRequestPage * 10 + 1} to {Math.min((roleRequestPage + 1) * 10, unifiedApprovals.length + actionItems.length)} of {unifiedApprovals.length + actionItems.length}
                  </div>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setRoleRequestPage(p => Math.max(0, p - 1))}
                      disabled={roleRequestPage === 0}
                      className="h-7"
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setRoleRequestPage(p => Math.min(Math.ceil((unifiedApprovals.length + actionItems.length) / 10) - 1, p + 1))}
                      disabled={(roleRequestPage + 1) * 10 >= unifiedApprovals.length + actionItems.length}
                      className="h-7"
                    >
                      <ChevronRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
      <Alert variant="default" className="mt-4">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('requiredActionsSection.alertMessage')}</AlertDescription>
      </Alert>

      {/* Role Request Confirmation Dialog */}
      {dialogPayload && (
        <ConfirmRoleRequestDialog
          isOpen={dialogOpen}
          onOpenChange={setDialogOpen}
          requesterEmail={dialogPayload.requester_email || ''}
          roleId={dialogPayload.role_id || ''}
          roleName={dialogPayload.role_name || ''}
          requesterMessage={dialogPayload.requester_message}
          onDecisionMade={handleCloseDialog}
        />
      )}
    </section>
  );
}


