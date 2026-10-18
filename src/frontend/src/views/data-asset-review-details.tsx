import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from "@tanstack/react-table";
import { Loader2, AlertCircle, ArrowLeft, X, ArrowUpDown, Pencil, Check, Copy } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from "@/hooks/use-toast";
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import {
    DataAssetReviewRequest, ReviewedAsset, ReviewRequestStatus,
    ReviewedAssetStatus,
    DataAssetReviewRequestUpdate,
    DataAssetReviewRequestUpdateStatus
} from '@/types/data-asset-review';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
// Textarea - unused
// import { Textarea } from '@/components/ui/textarea';
import { DataTable } from "@/components/ui/data-table";
import {
  CardSkeleton,
  DetailHeaderSkeleton,
  TableSkeleton,
} from '@/components/common/list-view-skeleton';
import { Toaster } from "@/components/ui/toaster";
import { RelativeDate } from '@/components/common/relative-date';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// Import Asset Review Editor Component
import AssetReviewEditor from '@/components/data-asset-reviews/asset-review-editor';

// Helper function to check API response (reuse if available globally)
const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    // ... (implementation as in data-asset-reviews.tsx)
    if (response.error) throw new Error(`${name} fetch failed: ${response.error}`);
    if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(`${name} fetch failed: ${response.data.detail}`);
    }
    if (response.data === null || response.data === undefined) {
        throw new Error(`${name} fetch returned null or undefined data.`);
    }
    return response.data as T;
};

export default function DataAssetReviewDetails() {
    const { t } = useTranslation(['data-asset-reviews', 'common']);
    const { requestId } = useParams<{ requestId: string }>();
    const navigate = useNavigate();
    const api = useApi();
    const { get, put, patch } = api;
    const { toast } = useToast();
    const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
    const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);

    const [request, setRequest] = useState<DataAssetReviewRequest | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
    const [selectedAsset, setSelectedAsset] = useState<ReviewedAsset | null>(null);
    const [selectedAssetIndex, setSelectedAssetIndex] = useState<number>(0);
    const [isEditorOpen, setIsEditorOpen] = useState(false);
    const [isEditingTitle, setIsEditingTitle] = useState(false);
    const [titleDraft, setTitleDraft] = useState('');
    const [isSavingTitle, setIsSavingTitle] = useState(false);

    // Navigation helpers for asset review
    const pendingAssets = useMemo(() => 
        request?.assets?.filter(a => a.status === ReviewedAssetStatus.PENDING) ?? [], 
        [request?.assets]
    );
    
    const currentAssetIndexInPending = useMemo(() => {
        if (!selectedAsset) return -1;
        return pendingAssets.findIndex(a => a.id === selectedAsset.id);
    }, [pendingAssets, selectedAsset]);
    
    const hasNextAsset = currentAssetIndexInPending >= 0 && currentAssetIndexInPending < pendingAssets.length - 1;
    
    const goToNextAsset = () => {
        if (hasNextAsset) {
            const nextAsset = pendingAssets[currentAssetIndexInPending + 1];
            setSelectedAsset(nextAsset);
            setSelectedAssetIndex(currentAssetIndexInPending + 2); // 1-based
        }
    };

    // Fetch request details
    const fetchRequestDetails = async () => {
        if (!requestId) {
            setError(t('data-asset-reviews:details.requestIdMissing'));
            setLoading(false);
            setStaticSegments([{ label: t('data-asset-reviews:title'), path: '/data-asset-reviews'}]);
            setDynamicTitle(null);
            return;
        }
        setLoading(true);
        setError(null);
        setStaticSegments([{ label: t('data-asset-reviews:title'), path: '/data-asset-reviews'}]);
        setDynamicTitle(t('data-asset-reviews:details.loadingReview'));
        try {
            const response = await get<DataAssetReviewRequest>(`/api/data-asset-reviews/${requestId}`);
            const requestData = checkApiResponse(response, 'Review Request Details');
            setRequest(requestData);
            setDynamicTitle(requestData.title || t('data-asset-reviews:details.reviewTitleShort', { id: requestData.id.substring(0, 8) }));
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : t('data-asset-reviews:details.fetchFailed');
            setError(errorMessage);
            setRequest(null);
            setStaticSegments([{ label: t('data-asset-reviews:title'), path: '/data-asset-reviews'}]);
            setDynamicTitle(t('common:states.error'));
            toast({ title: t('common:toast.error'), description: t('data-asset-reviews:details.loadRequestError', { error: errorMessage }), variant: 'destructive' });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchRequestDetails();
        // Cleanup function
        return () => {
            setStaticSegments([]);
            setDynamicTitle(null);
        };
    }, [requestId, get, toast, setDynamicTitle, setStaticSegments]);

    const beginEditTitle = () => {
        if (!request) return;
        setTitleDraft(request.title ?? '');
        setIsEditingTitle(true);
    };

    const cancelEditTitle = () => {
        setIsEditingTitle(false);
        setTitleDraft('');
    };

    const handleSaveTitle = async () => {
        if (!requestId || !request) return;
        const trimmed = titleDraft.trim();
        // No-op if unchanged (treat empty draft as "clear / regenerate").
        if (trimmed === (request.title ?? '').trim()) {
            cancelEditTitle();
            return;
        }
        setIsSavingTitle(true);
        const payload: DataAssetReviewRequestUpdate = { title: trimmed || null };
        try {
            const response = await patch<DataAssetReviewRequest>(`/api/data-asset-reviews/${requestId}`, payload);
            const updated = checkApiResponse(response, 'Update Review Title');
            setRequest(updated);
            setDynamicTitle(updated.title || `Review ${updated.id.substring(0, 8)}`);
            toast({ title: t('common:toast.success'), description: t('data-asset-reviews:toast.titleUpdated') });
            setIsEditingTitle(false);
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : t('data-asset-reviews:details.updateTitleFailed');
            toast({ title: t('common:toast.error'), description: errorMessage, variant: 'destructive' });
        } finally {
            setIsSavingTitle(false);
        }
    };

    const handleCopyId = async () => {
        if (!request) return;
        try {
            await navigator.clipboard.writeText(request.id);
            toast({ title: t('data-asset-reviews:toast.idCopied') });
        } catch {
            // Silently fail if clipboard is unavailable
        }
    };

    const handleOverallStatusChange = async (newStatus: ReviewRequestStatus) => {
        if (!requestId || !request || newStatus === request.status) return;
        setIsUpdatingStatus(true);
        const updatePayload: DataAssetReviewRequestUpdateStatus = { status: newStatus };
        // Potentially add a dialog here to capture notes for NEEDS_REVIEW or DENIED

        try {
            const response = await put<DataAssetReviewRequest>(`/api/data-asset-reviews/${requestId}/status`, updatePayload);
            const updatedRequest = checkApiResponse(response, 'Update Request Status');
            setRequest(updatedRequest); // Update local state
            toast({ title: t('common:toast.success'), description: t('data-asset-reviews:details.statusUpdated', { status: newStatus }) });
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : t('data-asset-reviews:details.updateStatusFailed');
            toast({ title: t('common:toast.error'), description: t('data-asset-reviews:details.updateStatusError', { error: errorMessage }), variant: 'destructive' });
        } finally {
            setIsUpdatingStatus(false);
        }
    };

    // --- Status Color Helpers (copied/adapted) --- //
    const getRequestStatusColor = (status: ReviewRequestStatus): "default" | "secondary" | "destructive" | "outline" => {
         switch (status) {
            case ReviewRequestStatus.APPROVED: return 'default';
            case ReviewRequestStatus.IN_REVIEW: return 'secondary';
            case ReviewRequestStatus.NEEDS_REVIEW: return 'outline'; // Map to outline
            case ReviewRequestStatus.DENIED: return 'destructive';
            case ReviewRequestStatus.CANCELLED: return 'outline';
            case ReviewRequestStatus.QUEUED: return 'outline';
            default: return 'outline';
        }
    };
     const getAssetStatusColor = (status: ReviewedAssetStatus): "default" | "secondary" | "destructive" | "outline" => {
         switch (status) {
            case ReviewedAssetStatus.APPROVED: return 'default';
            case ReviewedAssetStatus.PENDING: return 'outline';
            case ReviewedAssetStatus.NEEDS_CLARIFICATION: return 'secondary';
            case ReviewedAssetStatus.REJECTED: return 'destructive';
            default: return 'outline';
        }
    };

    // --- Asset Table Columns --- //
    const assetColumns = useMemo<ColumnDef<ReviewedAsset>[]>(() => [
        {
            accessorKey: "asset_fqn",
            header: ({ column }) => (
                <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} className="h-8 px-2 -ml-2">
                    {t('data-asset-reviews:details.columnAssetFqn')}
                    <ArrowUpDown className="ml-2 h-4 w-4" />
                </Button>
            ),
            cell: ({ row }) => <span className="font-mono text-xs">{row.original.asset_fqn}</span>,
        },
        {
            accessorKey: "asset_type",
            header: ({ column }) => (
                <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} className="h-8 px-2 -ml-2">
                    {t('common:labels.type')}
                    <ArrowUpDown className="ml-2 h-4 w-4" />
                </Button>
            ),
            cell: ({ row }) => <Badge variant="secondary">{row.original.asset_type}</Badge>,
        },
        {
            accessorKey: "status",
            header: ({ column }) => (
                <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} className="h-8 px-2 -ml-2">
                    {t('common:labels.status')}
                    <ArrowUpDown className="ml-2 h-4 w-4" />
                </Button>
            ),
            cell: ({ row }) => (
                <Badge variant={getAssetStatusColor(row.original.status)}>{row.original.status}</Badge>
            ),
        },
        {
            accessorKey: "updated_at",
            header: ({ column }) => (
                <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} className="h-8 px-2 -ml-2">
                    {t('data-asset-reviews:details.columnLastReviewed')}
                    <ArrowUpDown className="ml-2 h-4 w-4" />
                </Button>
            ),
            cell: ({ row }) => <RelativeDate date={row.original.updated_at} />,
        },
        {
            id: "actions",
            cell: ({ row }) => (
                <Button variant="outline" size="sm" onClick={() => {
                    setSelectedAsset(row.original);
                    // Find the index in the pending assets for navigation
                    const idx = pendingAssets.findIndex(a => a.id === row.original.id);
                    setSelectedAssetIndex(idx >= 0 ? idx + 1 : 1); // 1-based
                    setIsEditorOpen(true);
                }}>
                    {t('data-asset-reviews:details.review')}
                </Button>
            ),
        },
    ], [getAssetStatusColor]);


    // --- Render Logic --- //
    if (loading) {
        return (
            <div className="py-6 space-y-6">
                <DetailHeaderSkeleton actionButtons={1} />
                <CardSkeleton titleWidth="w-56" descriptionWidth="w-72" contentRows={4} />
                <TableSkeleton columns={5} rows={5} />
            </div>
        );
    }
    if (error) {
        return <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>;
    }
    if (!request) {
        return <Alert><AlertDescription>{t('data-asset-reviews:details.notFound')}</AlertDescription></Alert>;
    }

    return (
        <div className="py-6">
            <div className="space-y-6">
                <div className="flex justify-between items-start mb-4 gap-4">
                    <div className="min-w-0 flex-1">
                        <Button variant="outline" size="sm" onClick={() => navigate('/data-asset-reviews')} className="mb-2">
                            <ArrowLeft className="mr-2 h-4 w-4" /> {t('data-asset-reviews:details.backToList')}
                        </Button>
                        {isEditingTitle ? (
                            <div className="flex items-center gap-2">
                                <Input
                                    autoFocus
                                    value={titleDraft}
                                    maxLength={200}
                                    onChange={(e) => setTitleDraft(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                            e.preventDefault();
                                            handleSaveTitle();
                                        } else if (e.key === 'Escape') {
                                            e.preventDefault();
                                            cancelEditTitle();
                                        }
                                    }}
                                    placeholder={t('data-asset-reviews:form.titlePlaceholder')}
                                    className="text-2xl font-bold h-auto py-1 px-2"
                                    disabled={isSavingTitle}
                                />
                                <Button
                                    size="icon"
                                    variant="default"
                                    onClick={handleSaveTitle}
                                    disabled={isSavingTitle}
                                    aria-label={t('common:actions.save')}
                                >
                                    {isSavingTitle ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                </Button>
                                <Button
                                    size="icon"
                                    variant="ghost"
                                    onClick={cancelEditTitle}
                                    disabled={isSavingTitle}
                                    aria-label={t('common:actions.cancel')}
                                >
                                    <X className="h-4 w-4" />
                                </Button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 group">
                                <h1 className="text-3xl font-bold truncate">
                                    {request.title || t('data-asset-reviews:table.untitled')}
                                </h1>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                                    onClick={beginEditTitle}
                                    aria-label={t('data-asset-reviews:actions.editTitle')}
                                    title={t('data-asset-reviews:actions.editTitle')}
                                >
                                    <Pencil className="h-4 w-4" />
                                </Button>
                            </div>
                        )}
                        <div className="flex items-center gap-1 mt-1">
                            <span className="text-xs text-muted-foreground font-mono">{request.id}</span>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-muted-foreground"
                                onClick={handleCopyId}
                                aria-label={t('data-asset-reviews:actions.copyId')}
                                title={t('data-asset-reviews:actions.copyId')}
                            >
                                <Copy className="h-3 w-3" />
                            </Button>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <Label htmlFor="overall-status" className="text-sm font-medium">{t('data-asset-reviews:details.overallStatus')}:</Label>
                        <Select
                            value={request.status}
                            onValueChange={(value) => handleOverallStatusChange(value as ReviewRequestStatus)}
                            disabled={isUpdatingStatus}
                        >
                            <SelectTrigger id="overall-status" className="w-[180px]">
                                <SelectValue placeholder={t('common:placeholders.setStatus')} />
                            </SelectTrigger>
                            <SelectContent>
                                {Object.values(ReviewRequestStatus).map((status) => (
                                    <SelectItem key={status} value={status}>{status}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {isUpdatingStatus && <Loader2 className="h-4 w-4 animate-spin" />}
                    </div>
                </div>

                {/* Request Info Card */}
                <Card>
                    <CardHeader>
                        <CardTitle>{t('data-asset-reviews:details.requestInformation')}</CardTitle>
                    </CardHeader>
                    <CardContent className="grid md:grid-cols-3 gap-4 text-sm">
                        <div><Label>{t('common:labels.requester')}:</Label> {request.requester_email}</div>
                        <div><Label>{t('common:labels.reviewer')}:</Label> {request.reviewer_email}</div>
                        <div><Label>{t('data-asset-reviews:details.currentStatus')}:</Label> <Badge variant={getRequestStatusColor(request.status)}>{request.status}</Badge></div>
                        <div><Label>{t('common:labels.created')}:</Label> <RelativeDate date={request.created_at} /></div>
                        <div><Label>{t('common:labels.lastUpdated')}:</Label> <RelativeDate date={request.updated_at} /></div>
                        <div className="md:col-span-3"><Label>{t('common:labels.notes')}:</Label> <p className="text-xs mt-1 whitespace-pre-wrap">{request.notes || t('common:states.none')}</p></div>
                    </CardContent>
                </Card>

                {/* Assets Table Card */}
                <Card>
                    <CardHeader>
                        <CardTitle>{t('data-asset-reviews:details.assetsForReview', { count: request.assets?.length ?? 0 })}</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <DataTable
                            columns={assetColumns}
                            data={request.assets ?? []}
                            // No search needed for this small table within details
                        />
                    </CardContent>
                </Card>
            </div>

            {/* Asset Review Editor - Now outside the space-y-6 wrapper */}
            {isEditorOpen && selectedAsset && (
                <div className="fixed inset-0 bg-black/50 z-50 flex justify-center items-center p-4">
                    <Card className="w-full max-w-4xl max-h-[90vh] flex flex-col bg-background">
                        <CardHeader className="flex flex-row justify-between items-center">
                            <CardTitle>{t('data-asset-reviews:details.reviewing', { fqn: selectedAsset.asset_fqn })}</CardTitle>
                            <Button variant="ghost" size="icon" onClick={() => setIsEditorOpen(false)}><X className="h-4 w-4" /></Button>
                        </CardHeader>
                        <CardContent className="flex-1 overflow-auto space-y-4">
                             {/* Render AssetReviewEditor component */}
                             <AssetReviewEditor
                                requestId={requestId!}
                                asset={selectedAsset}
                                reviewerEmail={request?.reviewer_email}
                                api={api}
                                onReviewSave={(updatedAsset) => {
                                    // Update the asset list in the main request state
                                    setRequest(prevRequest => {
                                        if (!prevRequest) return null;
                                        return {
                                            ...prevRequest,
                                            assets: prevRequest.assets.map(a =>
                                                a.id === updatedAsset.id ? updatedAsset : a
                                            ),
                                            // Optionally update the overall request updated_at timestamp
                                            updated_at: new Date().toISOString(),
                                        };
                                    });
                                    // Don't close dialog here - let Save & Next handle navigation
                                    // Only close if no next or user explicitly closes
                                    if (!hasNextAsset) {
                                        setIsEditorOpen(false);
                                    }
                                }}
                                onNext={goToNextAsset}
                                hasNext={hasNextAsset}
                                currentIndex={selectedAssetIndex}
                                totalCount={pendingAssets.length}
                             />
                             {/* Footer with save button is now part of AssetReviewEditor logic,
                                but usually triggered from parent dialog for consistency.
                                Keeping a simplified footer here for closing. */}
                             <div className="flex justify-end p-4 border-t">
                                <Button variant="outline" onClick={() => setIsEditorOpen(false)} className="mr-2">{t('common:actions.close')}</Button>
                                {/* Save action is triggered within AssetReviewEditor via its internal state/button */}
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}

            <Toaster />
        </div>
    );
} 