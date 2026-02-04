import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Loader2, AlertCircle, SparklesIcon } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from "@/hooks/use-toast";
import {
    ReviewedAsset,
    ReviewedAssetStatus,
    AssetType,
    AssetDefinition,
    TablePreview,
    ReviewedAssetUpdate,
    AssetAnalysisResponse
} from '@/types/data-asset-review';
import { LLMConfig } from '@/types/llm';
import { DataTable } from "@/components/ui/data-table"; // For table preview
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { RelativeDate } from '@/components/common/relative-date';
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import ReactMarkdown from 'react-markdown';
import LLMConsentDialog, { hasLLMConsent } from '@/components/common/llm-consent-dialog';
import MdmMatchReview from '@/components/mdm/mdm-match-review';

// Register languages
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('python', python);

interface AssetReviewEditorProps {
    requestId: string;
    asset: ReviewedAsset;
    api: ReturnType<typeof useApi>;
    onReviewSave: (updatedAsset: ReviewedAsset) => void; // Callback after saving
    onNext?: () => void; // Callback to navigate to next asset
    hasNext?: boolean; // Whether there's a next asset
    currentIndex?: number; // Current position (1-based)
    totalCount?: number; // Total assets in review
}

// Helper function to check API response
const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    if (response.error) throw new Error(`${name} fetch failed: ${response.error}`);
    if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(`${name} fetch failed: ${response.data.detail}`);
    }
    // Allow null/undefined for content fetching (e.g., definition might be null)
    // if (response.data === null || response.data === undefined) {
    //     throw new Error(`${name} fetch returned null or undefined data.`);
    // }
    return response.data as T;
};

export default function AssetReviewEditor({ 
    requestId, 
    asset, 
    api, 
    onReviewSave,
    onNext,
    hasNext = false,
    currentIndex,
    totalCount,
}: AssetReviewEditorProps) {
    const { get, put, post } = api;
    const { toast } = useToast();

    // Content State
    const [definition, setDefinition] = useState<AssetDefinition | null>(null);
    const [preview, setPreview] = useState<TablePreview | null>(null);
    const [isLoadingContent, setIsLoadingContent] = useState(false);
    const [contentError, setContentError] = useState<string | null>(null);

    // Form State
    const [currentStatus, setCurrentStatus] = useState<ReviewedAssetStatus>(asset.status);
    const [comments, setComments] = useState<string>(asset.comments || '');
    const [isSaving, setIsSaving] = useState(false);

    // LLM Configuration State
    const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null);
    const [showConsentDialog, setShowConsentDialog] = useState(false);

    // LLM Analysis State
    const [analysisResult, setAnalysisResult] = useState<AssetAnalysisResponse | null>(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analysisError, setAnalysisError] = useState<string | null>(null);

    // Fetch LLM configuration on mount
    useEffect(() => {
        const fetchLLMConfig = async () => {
            try {
                const response = await get<LLMConfig>('/api/settings/llm');
                const config = checkApiResponse(response, 'LLM Config');
                setLlmConfig(config);
            } catch (err: any) {
                console.error('Error fetching LLM config:', err);
                // Set disabled config on error
                setLlmConfig({ enabled: false, endpoint: null, system_prompt: null, disclaimer_text: '' });
            }
        };

        fetchLLMConfig();
    }, [get]);

    // Fetch content based on asset type
    useEffect(() => {
        const fetchContent = async () => {
            setIsLoadingContent(true);
            setContentError(null);
            setDefinition(null);
            setPreview(null);
            setAnalysisResult(null); // Reset analysis when asset changes
            setAnalysisError(null);

            try {
                if (asset.asset_type === AssetType.VIEW || asset.asset_type === AssetType.FUNCTION || asset.asset_type === AssetType.NOTEBOOK) {
                    const response = await fetch(`/api/data-asset-reviews/${requestId}/assets/${asset.id}/definition`);
                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(errorText || `Failed to fetch definition (${response.status})`);
                    }
                    const textDefinition = await response.text();
                    setDefinition(textDefinition);
                } else if (asset.asset_type === AssetType.TABLE) {
                    // Fetch table preview
                    const response = await get<TablePreview>(`/api/data-asset-reviews/${requestId}/assets/${asset.id}/preview?limit=50`);
                    const previewData = checkApiResponse(response, 'Table Preview');
                    setPreview(previewData);
                }
            } catch (err: any) {
                console.error('Error fetching asset content:', err);
                setContentError(err.message || 'Failed to load asset content');
            } finally {
                setIsLoadingContent(false);
            }
        };

        fetchContent();
    }, [requestId, asset.id, asset.asset_type, get]); // Re-fetch if asset changes

    const handleSaveReview = async () => {
        setIsSaving(true);
        // setContentError(null); // Error from content fetching should not block saving review itself
        const payload: ReviewedAssetUpdate = {
            status: currentStatus,
            comments: comments || null,
        };

        try {
            const response = await put<ReviewedAsset>(`/api/data-asset-reviews/${requestId}/assets/${asset.id}/status`, payload);
            const updatedAsset = checkApiResponse(response, 'Update Asset Status');
            toast({ title: 'Success', description: `Review for ${asset.asset_fqn} saved.` });
            onReviewSave(updatedAsset);
        } catch (err: any) {
            // Display error related to saving the review, not to be confused with contentError
            toast({ title: 'Error Saving Review', description: `Failed to save review: ${err.message}`, variant: 'destructive' });
        } finally {
            setIsSaving(false);
        }
    };

    const handleAiAnalysisClick = () => {
        // Check if LLM is enabled
        if (!llmConfig || !llmConfig.enabled) {
            toast({
                title: 'AI Features Disabled',
                description: 'AI-powered analysis is currently disabled in settings.',
                variant: 'destructive'
            });
            return;
        }

        // Check if user has consented
        if (!hasLLMConsent(llmConfig)) {
            setShowConsentDialog(true);
            return;
        }

        // Proceed with analysis
        performAiAnalysis();
    };

    const performAiAnalysis = async () => {
        if (!requestId || !asset.id) return;
        setIsAnalyzing(true);
        setAnalysisError(null);
        setAnalysisResult(null);

        try {
            const response = await post<AssetAnalysisResponse>(
                `/api/data-asset-reviews/${requestId}/assets/${asset.id}/analyze`,
                {}
            );
            const result = checkApiResponse(response, 'AI Analysis');
            setAnalysisResult(result);
            toast({ title: 'AI Analysis Complete', description: 'Review summary generated.' });
        } catch (err: any) {
            setAnalysisError(err.message || 'Failed to perform AI analysis.');
            toast({ title: 'AI Analysis Error', description: err.message, variant: 'destructive' });
        } finally {
            setIsAnalyzing(false);
        }
    };

    // --- Render Content --- //
    const renderAssetContent = () => {
        if (isLoadingContent) {
            return <div className="flex justify-center items-center h-40"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
        }
        if (contentError && !definition && !preview) { 
             return <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{contentError}</AlertDescription></Alert>;
        }

        if (definition !== null) {
            const language = (asset.asset_type === AssetType.FUNCTION || asset.asset_type === AssetType.NOTEBOOK) ? 'python' : 'sql';
            return (
                <div className="border rounded text-sm"> 
                    <SyntaxHighlighter
                        language={language}
                        style={oneLight} 
                        showLineNumbers 
                        wrapLines={true}
                        customStyle={{
                            margin: 0, 
                            padding: '0.5rem', 
                            fontSize: '0.75rem', 
                            maxHeight: '24rem', // SyntaxHighlighter handles its own scroll
                        }}
                    >
                        {definition || ''} 
                    </SyntaxHighlighter>
                </div>
            );
        }

        if (preview !== null) {
            const columns = preview.schema.map((col: { name: string; type: string; nullable: boolean }) => ({
                accessorKey: col.name,
                header: col.name,
                cell: ({ row }: { row: any }) => <span className="text-xs font-mono truncate" title={String(row.getValue(col.name))}>{String(row.getValue(col.name))}</span>,
            }));
            return (
                 <div className="border rounded max-h-96 overflow-auto">
                    <DataTable
                        columns={columns}
                        data={preview.data}
                    />
                </div>
            );
        }

        if (asset.asset_type === AssetType.MODEL) {
            return <p className="text-sm text-muted-foreground">Model review details not yet implemented.</p>;
        }

        return <p className="text-sm text-muted-foreground">No preview or definition available for this asset type, or content is still loading.</p>;
    };

    // Handle MDM Match assets with specialized component
    if (asset.asset_type === AssetType.MDM_MATCH) {
        return (
            <div className="px-1 pb-1">
                <MdmMatchReview
                    assetFqn={asset.asset_fqn}
                    onReviewComplete={(status) => {
                        // Update the asset status in the parent based on MDM review outcome
                        const newStatus = status === 'approved' 
                            ? ReviewedAssetStatus.APPROVED 
                            : ReviewedAssetStatus.REJECTED;
                        onReviewSave({
                            ...asset,
                            status: newStatus,
                            updated_at: new Date().toISOString(),
                        });
                    }}
                    onNext={onNext}
                    hasNext={hasNext}
                    currentIndex={currentIndex}
                    totalCount={totalCount}
                />
            </div>
        );
    }

    return (
        <div className="px-1 pb-1">
             {/* Asset Details */}
             <div>
                 <h4 className="font-medium text-lg mb-2">Asset Details</h4>
                 <p className="text-sm"><span className="font-semibold">FQN:</span> <span className="font-mono text-xs">{asset.asset_fqn}</span></p>
                 <p className="text-sm"><span className="font-semibold">Type:</span> <Badge variant="secondary">{asset.asset_type}</Badge></p>
             </div>

            {/* Content Viewer */}
            <div className="space-y-2 mt-6">
                 <h4 className="font-medium text-lg">Content Preview / Definition</h4>
                {renderAssetContent()}
            </div>

            {/* Review Form */}
            <div className="space-y-3 mt-6 border-t">
                <h4 className="font-medium text-lg">Your Review</h4>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="asset-status" className="text-right">Status *</Label>
                     <Select
                        value={currentStatus}
                        onValueChange={(value) => setCurrentStatus(value as ReviewedAssetStatus)}
                    >
                        <SelectTrigger id="asset-status" className="col-span-3">
                            <SelectValue placeholder="Set status" />
                        </SelectTrigger>
                        <SelectContent>
                            {Object.values(ReviewedAssetStatus).map((status) => (
                                <SelectItem key={status} value={status}>{status}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                 <div className="grid grid-cols-4 items-start gap-4">
                    <Label htmlFor="comments" className="text-right pt-2">Comments</Label>
                    <Textarea
                        id="comments"
                        value={comments}
                        onChange={(e) => setComments(e.target.value)}
                        placeholder="Add your review comments here..."
                        className="col-span-3 min-h-[80px]"
                    />
                </div>
                 {contentError && (
                        <Alert variant="destructive">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription>{contentError}</AlertDescription>
                        </Alert>
                    )}
                 {/* Save button is added here, within the form section */}
                 <div className="flex justify-end pt-2">
                     <Button onClick={handleSaveReview} disabled={isSaving}>
                        {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Save Review
                     </Button>
                 </div>
            </div>
            {/* Button for automated checks (placeholder) */}
             {asset.asset_type === AssetType.TABLE && (
                 <div className="pt-4 border-t">
                    <Button variant="outline" disabled>Run Automated Checks (Not Implemented)</Button>
                </div>
             )}

            {/* AI Analysis Section - Conditionally shown based on LLM config and asset type */}
            {llmConfig && llmConfig.enabled && (asset.asset_type === AssetType.VIEW || asset.asset_type === AssetType.FUNCTION || asset.asset_type === AssetType.NOTEBOOK) && (
                <div className="mt-6 border-t space-y-3">
                    <h4 className="font-medium text-lg flex items-center">
                        <SparklesIcon className="w-5 h-5 mr-2 text-purple-500" /> AI Assisted Review
                    </h4>
                    <Button
                        onClick={handleAiAnalysisClick}
                        disabled={isAnalyzing || isLoadingContent || !definition}
                        title={!definition && !isLoadingContent ? "Asset content (definition) must be loaded to run AI analysis." : ""}
                    >
                        {isAnalyzing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        {analysisResult ? 'Re-run AI Analysis' : 'Run AI Analysis'}
                    </Button>
                    {analysisError && (
                        <Alert variant="destructive">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription>{analysisError}</AlertDescription>
                        </Alert>
                    )}
                    {analysisResult && (
                        <Card className="mt-2">
                            <CardHeader className="pb-2">
                                <CardTitle className="text-base">
                                    AI Analysis Summary
                                    {!analysisResult.phase1_passed && (
                                        <Badge variant="destructive" className="ml-2">Security Warning</Badge>
                                    )}
                                </CardTitle>
                                <p className="text-xs text-muted-foreground">
                                    Model: {analysisResult.model_used || 'N/A'} |
                                    Generated: <RelativeDate date={analysisResult.timestamp} />
                                </p>
                            </CardHeader>
                            <CardContent>
                                {/* Render as plain text if security check failed */}
                                {!analysisResult.render_as_markdown ? (
                                    <div className="p-3 bg-muted rounded-md font-mono text-xs whitespace-pre-wrap">
                                        {analysisResult.analysis_summary}
                                    </div>
                                ) : (
                                    <div className="markdown-container prose prose-xs dark:prose-invert max-w-none p-3 bg-muted rounded-md overflow-x-auto">
                                        <ReactMarkdown>
                                            {analysisResult.analysis_summary}
                                        </ReactMarkdown>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    )}
                </div>
            )}

            {/* LLM Consent Dialog */}
            {showConsentDialog && llmConfig && (
                <LLMConsentDialog
                    open={showConsentDialog}
                    onOpenChange={setShowConsentDialog}
                    onAccept={performAiAnalysis}
                    llmConfig={llmConfig}
                />
            )}
        </div>
    );
} 