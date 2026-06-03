import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import {
    Dialog, DialogContent, DialogHeader, DialogTitle,
    DialogFooter, DialogClose, DialogDescription
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useApi } from '@/hooks/use-api';
import { useToast } from "@/hooks/use-toast";
import { TreeView } from '@/components/ui/tree-view';
import { CatalogItem, DataAssetReviewRequest, DataAssetReviewRequestCreate, AssetType } from '@/types/data-asset-review';
import { Loader2, AlertCircle, Folder, FolderOpen, Table, Layout, FunctionSquare } from 'lucide-react';
import { PrincipalPicker } from '@/components/common/principal-picker';

// Define user info type based on backend response
interface UserInfo {
    email: string | null;
    username?: string | null;
    user?: string | null;
    ip?: string | null;
}

// Define structure for custom asset data stored separately
interface CustomAssetData {
    type: AssetType | 'catalog' | 'schema';
    isSelectable: boolean;
}

interface CreateReviewRequestDialogProps {
    isOpen: boolean;
    onOpenChange: (isOpen: boolean) => void;
    api: ReturnType<typeof useApi>;
    onSubmitSuccess: (newRequest: DataAssetReviewRequest) => void;
}

const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    if (response.error) throw new Error(`${name} creation failed: ${response.error}`);
    if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(`${name} creation failed: ${response.data.detail}`);
    }
    if (response.data === null || response.data === undefined) {
        throw new Error(`${name} creation returned null or undefined data.`);
    }
    return response.data as T;
};

export default function CreateReviewRequestDialog({ isOpen, onOpenChange, api, onSubmitSuccess }: CreateReviewRequestDialogProps) {
    const { post, get } = api;
    const { toast } = useToast();
    const [requesterEmail, setRequesterEmail] = useState<string | null>(null);
    const [_, setIsFetchingUser] = useState(false);
    const [reviewerEmail, setReviewerEmail] = useState('');
    const [title, setTitle] = useState('');
    const [notes, setNotes] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
    const [isLoadingCatalog, setIsLoadingCatalog] = useState(true);
    const [catalogError, setCatalogError] = useState<string | null>(null);
    const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
    const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set());
    const [selectedAssetFqns, setSelectedAssetFqns] = useState<Set<string>>(new Set());
    const [assetDataMap, setAssetDataMap] = useState<Map<string, CustomAssetData>>(new Map());

    useEffect(() => {
        const newMap = new Map<string, CustomAssetData>();
        const traverse = (items: CatalogItem[]) => {
            items.forEach(item => {
                const isSelectable = [AssetType.TABLE, AssetType.VIEW, AssetType.FUNCTION, AssetType.MODEL].includes(item.type as AssetType);
                newMap.set(item.id, { type: item.type as (AssetType | 'catalog' | 'schema'), isSelectable });
                if (item.children) {
                    traverse(item.children);
                }
            });
        };
        traverse(catalogItems);
        setAssetDataMap(newMap);
    }, [catalogItems]);

    // Fetch User Info
    const fetchUserInfo = useCallback(async () => {
        setIsFetchingUser(true);
        try {
            const response = await get<UserInfo>('/api/user/info');
            const userData = checkApiResponse(response, 'User Info');
            setRequesterEmail(userData.email || 'not-found@example.com'); // Set email or fallback
        } catch (err: any) {
             console.error("Error fetching user info:", err);
             toast({ title: 'Error', description: 'Could not fetch your email.', variant: 'destructive' });
             setRequesterEmail('error@example.com'); // Indicate error
        } finally {
            setIsFetchingUser(false);
        }
    }, [get, toast]);

    const fetchCatalogs = useCallback(async () => {
        setIsLoadingCatalog(true);
        setCatalogError(null);
        try {
            const response = await get<CatalogItem[]>('/api/catalogs');
            const data = checkApiResponse(response, 'Catalogs');
            setCatalogItems(Array.isArray(data) ? data : []);
        } catch (err: any) {
            setCatalogError(err.message || 'Failed to load catalog structure');
            setCatalogItems([]);
        } finally {
            setIsLoadingCatalog(false);
        }
    }, [get]);

    useEffect(() => {
        if (isOpen) {
            setRequesterEmail(null); // Reset email on open before fetching
            setIsFetchingUser(true);
            fetchUserInfo();
            fetchCatalogs();
            setReviewerEmail('');
            setTitle('');
            setNotes('');
            setSelectedAssetFqns(new Set());
            setExpandedNodes(new Set());
            setFormError(null);
        }
    }, [isOpen, fetchCatalogs, fetchUserInfo]);

    const getIcon = (type: string | undefined) => {
         switch (type) {
            case 'catalog': return <Folder className="h-4 w-4 text-blue-500" />;
            case 'schema': return <FolderOpen className="h-4 w-4 text-green-500" />;
            case AssetType.TABLE: return <Table className="h-4 w-4 text-orange-500" />;
            case AssetType.VIEW: return <Layout className="h-4 w-4 text-purple-500" />;
            case AssetType.FUNCTION: return <FunctionSquare className="h-4 w-4 text-red-500" />;
            default: return null;
        }
    };

    const updateNodeChildren = (items: CatalogItem[], nodeId: string, children: CatalogItem[]): CatalogItem[] => {
        return items.map(item => {
            if (item.id === nodeId) {
                return { ...item, children: children || [] };
            }
            if (item.children) {
                return { ...item, children: updateNodeChildren(item.children, nodeId, children) };
            }
            return item;
        });
    };

    const fetchChildren = async (nodeId: string, nodeType: string | undefined): Promise<CatalogItem[]> => {
        if (!nodeType) return [];
        setLoadingNodes(prev => new Set(prev).add(nodeId));
        try {
            let urls: string[] = [];
            if (nodeType === 'catalog') {
                urls.push(`/api/catalogs/${nodeId}/schemas`);
            } else if (nodeType === 'schema') {
                const [catalogName, schemaName] = nodeId.split('.');
                if (!catalogName || !schemaName) {
                    throw new Error(`Invalid schema FQN: ${nodeId}`);
                }
                // Fetch tables, views, and functions concurrently for a schema
                urls.push(`/api/catalogs/${catalogName}/schemas/${schemaName}/tables`);
                urls.push(`/api/catalogs/${catalogName}/schemas/${schemaName}/views`);
                urls.push(`/api/catalogs/${catalogName}/schemas/${schemaName}/functions`);
            }

            if (urls.length === 0) return [];

            // Use Promise.all to fetch from all URLs concurrently
            const responses = await Promise.all(urls.map(url => get<CatalogItem[]>(url)));

            // Combine results and check for errors
            let combinedResults: CatalogItem[] = [];
            responses.forEach((response, index) => {
                try {
                     // Check each response individually
                    const data = checkApiResponse(response, `Children from ${urls[index]}`);
                    if (Array.isArray(data)) {
                         combinedResults = combinedResults.concat(data);
                    }
                } catch (err: any) {
                    // Log individual fetch errors but continue combining results from others
                    console.error("Error fetching children from", urls[index], ":", err);
                    toast({ title: 'Partial Load Error', description: `Could not load some children for ${nodeId}: ${err.message}`, variant: 'default' });
                }
            });

            return combinedResults;

        } catch (err: any) {
            console.error('Error fetching children:', err);
            toast({ title: 'Error', description: `Could not load children for ${nodeId}: ${err.message}`, variant: 'destructive' });
            return [];
        } finally {
             setLoadingNodes(prev => {
                const next = new Set(prev);
                next.delete(nodeId);
                return next;
            });
        }
    };

    const handleNodeExpand = async (nodeId: string) => {
        if (loadingNodes.has(nodeId)) return;

        const customData = assetDataMap.get(nodeId);
        const nodeType = customData?.type;

        const isCurrentlyExpanded = expandedNodes.has(nodeId);
        setExpandedNodes(prev => {
            const next = new Set(prev);
            if (isCurrentlyExpanded) {
                next.delete(nodeId);
            } else {
                next.add(nodeId);
            }
            return next;
        });

        if (!isCurrentlyExpanded) {
             const node = findCatalogItem(catalogItems, nodeId);
             if (node && (!node.children || node.children.length === 0) && nodeType) {
                 setExpandedNodes(prev => new Set(prev).add(nodeId));
                 const children = await fetchChildren(nodeId, nodeType);
                 if (children.length >= 0) {
                     setCatalogItems(prev => updateNodeChildren(prev, nodeId, children));
                 } else {
                      setExpandedNodes(prev => {
                           const next = new Set(prev);
                           next.delete(nodeId);
                           return next;
                      });
                 }
             }
        }
    };

    const findCatalogItem = (items: CatalogItem[], id: string): CatalogItem | null => {
         for (const item of items) {
            if (item.id === id) return item;
            if (item.children) {
                const found = findCatalogItem(item.children, id);
                if (found) return found;
            }
        }
        return null;
    }

    const handleSelectionChange = (selectedItem: { id: string } | undefined) => {
         if (!selectedItem) return;

         const customData = assetDataMap.get(selectedItem.id);

         if (!customData || !customData.isSelectable) return;

         const fqn = selectedItem.id;
         setSelectedAssetFqns(prev => {
             const next = new Set(prev);
             if (next.has(fqn)) {
                 next.delete(fqn);
             } else {
                 next.add(fqn);
             }
             return next;
         });
     };

    const renderTree = (items: CatalogItem[]): any[] => {
        return items.map((item) => {
            const customData = assetDataMap.get(item.id);
            const hasActualChildren = item.hasChildren || (item.children !== undefined);
            return {
                id: item.id,
                name: item.name,
                icon: getIcon(customData?.type),
                children: item.children ? renderTree(item.children) : [],
                selected: selectedAssetFqns.has(item.id),
                expanded: expandedNodes.has(item.id),
                onExpand: () => handleNodeExpand(item.id),
                loading: loadingNodes.has(item.id),
                hasChildren: hasActualChildren,
            };
        });
    };

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setFormError(null);

        if (!requesterEmail || requesterEmail.includes('error') || requesterEmail.includes('not-found')) {
            setFormError('Could not verify requester email. Please refresh.');
            return;
        }

        if (!reviewerEmail) {
            setFormError('Reviewer email is required.');
            return;
        }
        if (selectedAssetFqns.size === 0) {
            setFormError('Please select at least one asset to review.');
            return;
        }
        setIsSubmitting(true);
        const trimmedTitle = title.trim();
        const payload: DataAssetReviewRequestCreate = {
            requester_email: requesterEmail,
            reviewer_email: reviewerEmail,
            asset_fqns: Array.from(selectedAssetFqns),
            title: trimmedTitle || null,
            notes: notes || null,
        };
        try {
            const response = await post<DataAssetReviewRequest>('/api/data-asset-reviews/', payload);
            const newRequest = checkApiResponse(response, 'Create Review Request');
            onSubmitSuccess(newRequest);
        } catch (err: any) {
            setFormError(err.message || 'An unexpected error occurred.');
            toast({ title: 'Submission Failed', description: err.message, variant: 'destructive' });
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[600px] max-h-[90vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle>Create New Data Asset Review Request</DialogTitle>
                    <DialogDescription>Select assets and assign a reviewer.</DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="flex-1 overflow-hidden flex flex-col space-y-4 py-4">
                    <div className="grid grid-cols-2 gap-4 px-1">
                        <div>
                            <Label htmlFor="requester-email">Your Email</Label>
                            <Input
                                id="requester-email"
                                value={requesterEmail ?? 'Loading...'}
                                disabled
                                aria-disabled={true}
                            />
                        </div>
                        <div>
                            <Label htmlFor="reviewer-email">Reviewer *</Label>
                            <PrincipalPicker
                                id="reviewer-email"
                                accepts={['user']}
                                value={reviewerEmail || null}
                                onChange={(next) => {
                                    setReviewerEmail(next ?? '');
                                    setFormError(null);
                                }}
                                placeholder="user@example.com"
                                aria-label="Reviewer"
                            />
                        </div>
                    </div>
                    <div className="px-1">
                        <Label htmlFor="review-title">Title (Optional)</Label>
                        <Input
                            id="review-title"
                            value={title}
                            maxLength={200}
                            onChange={(e) => {
                                setTitle(e.target.value);
                                setFormError(null);
                            }}
                            placeholder="Leave empty to auto-generate from selected assets"
                        />
                    </div>
                    <div className="px-1">
                        <Label htmlFor="notes">Notes (Optional)</Label>
                        <Textarea
                            id="notes"
                            value={notes}
                            onChange={(e) => {
                                setNotes(e.target.value);
                                setFormError(null);
                            }}
                            placeholder="Add any relevant context for the reviewer..."
                            rows={3}
                        />
                    </div>

                    <div className="flex-1 overflow-hidden border rounded-md mx-1">
                         <Label className="text-sm font-medium block p-2 border-b">Select Assets *</Label>
                         <div className="h-[300px] overflow-y-auto p-2">
                            {isLoadingCatalog ? (
                                 <div className="flex justify-center items-center h-full">
                                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                                </div>
                            ) : catalogError ? (
                                <Alert variant="destructive">
                                    <AlertCircle className="h-4 w-4" />
                                    <AlertDescription>{catalogError}</AlertDescription>
                                </Alert>
                            ) : (
                                <TreeView
                                    data={renderTree(catalogItems)}
                                    className="text-sm"
                                    onSelectChange={handleSelectionChange}
                                />
                            )}
                        </div>
                    </div>

                    {formError && (
                        <Alert variant="destructive" className="mx-1">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription className="break-words">{formError}</AlertDescription>
                        </Alert>
                    )}
                </form>
                 <DialogFooter className="mt-auto pt-4 border-t">
                    <DialogClose asChild>
                        <Button type="button" variant="outline" disabled={isSubmitting}>Cancel</Button>
                    </DialogClose>
                    <Button type="submit" onClick={handleSubmit} disabled={isSubmitting || selectedAssetFqns.size === 0}>
                        {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Submit Request
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
} 