import { useMemo, useState, useEffect, useCallback } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import MarkdownViewer from '@/components/ui/markdown-viewer';
import { useEntityMetadata, useMergedMetadata, DocumentItem, LinkItem, EntityKind } from '@/hooks/use-entity-metadata';
import { Bell, Check, Loader2, ArrowLeft, Share2, Star, ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { StarRatingInput } from '@/components/ratings/star-rating-input';
import { RatingSummary } from '@/components/ratings/rating-summary';
import { useComments } from '@/hooks/use-comments';
import type { RatingAggregation } from '@/types/comments';

interface Props {
  entityType: EntityKind;
  entityId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  // Subscription support (optional)
  onSubscribe?: () => void;
  isSubscribed?: boolean;
  subscriptionLoading?: boolean;
  showBackButton?: boolean;
  // Navigate to the full entity detail view (optional)
  onGoToDetails?: () => void;
  // Inheritance support (for Data Products and Datasets)
  contractIds?: string[];
  maxLevelInheritance?: number;
}

// Replace image references in markdown to target our document content endpoint.
// Supports: ![alt](doc:ID) or ![alt](file:filename.ext)
function rewriteImageLinks(markdown: string, documents: DocumentItem[]): string {
  if (!markdown) return markdown;

  const byId = new Map(documents.map(d => [String(d.id), d]));
  const byName = new Map(documents.map(d => [d.original_filename, d]));

  const replaceUrl = (url: string): string => {
    if (url.startsWith('doc:')) {
      const id = url.slice(4);
      if (byId.has(id)) return `/api/documents/${id}/content`;
    }
    if (url.startsWith('file:')) {
      const name = url.slice(5);
      const doc = byName.get(name);
      if (doc) return `/api/documents/${doc.id}/content`;
    }
    return url;
  };

  let out = markdown.replace(/!\[[^\]]*\]\(([^)]+)\)/g, (m, p1) => m.replace(p1, replaceUrl(p1)));
  out = out.replace(/\[[^\]]*\]\(([^)]+)\)/g, (m, p1) => m.replace(p1, replaceUrl(p1)));
  return out;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

function buildToc(markdown: string) {
  const lines = markdown.split(/\r?\n/);
  const headings: { level: number; text: string; id: string }[] = [];
  for (const line of lines) {
    const m = /^(#{1,6})\s+(.*)$/.exec(line);
    if (m) {
      const level = m[1].length;
      const text = m[2].trim();
      const id = slugify(text);
      headings.push({ level, text, id });
    }
  }
  return headings;
}

export default function EntityInfoDialog({ 
  entityType, 
  entityId, 
  open, 
  onOpenChange, 
  title,
  onSubscribe,
  isSubscribed,
  subscriptionLoading,
  showBackButton = false,
  onGoToDetails,
  contractIds,
  maxLevelInheritance = 99,
}: Props) {
  // Use merged metadata when contractIds are provided (for DP/DS with inheritance)
  const directMetadata = useEntityMetadata(entityType, entityId || undefined);
  const mergedMetadata = useMergedMetadata(
    entityType, 
    entityId || undefined, 
    contractIds, 
    maxLevelInheritance
  );
  
  // Use merged if we have contract IDs, otherwise use direct
  const useMerged = contractIds && contractIds.length > 0;
  const { richTexts, documents, links, loading, error } = useMerged 
    ? { 
        richTexts: mergedMetadata.richTexts, 
        documents: mergedMetadata.documents, 
        links: mergedMetadata.links, 
        loading: mergedMetadata.loading, 
        error: mergedMetadata.error 
      }
    : directMetadata;
  
  const sources = useMerged ? mergedMetadata.sources : {};

  // Ratings state
  const [ratingAggregation, setRatingAggregation] = useState<RatingAggregation | null>(null);
  const [selectedRating, setSelectedRating] = useState(0);
  const [reviewText, setReviewText] = useState('');
  const [submittingRating, setSubmittingRating] = useState(false);
  const [ratingsLoading, setRatingsLoading] = useState(false);
  const { createRating, fetchRatingAggregation } = useComments();

  const loadRatings = useCallback(async () => {
    if (!entityId) return;
    try {
      setRatingsLoading(true);
      const ratingData = await fetchRatingAggregation(entityType, entityId);
      setRatingAggregation(ratingData);
      if (ratingData?.user_current_rating) {
        setSelectedRating(ratingData.user_current_rating);
      }
    } catch {
      // Silently handle rating fetch errors
    } finally {
      setRatingsLoading(false);
    }
  }, [entityId, entityType, fetchRatingAggregation]);

  useEffect(() => {
    if (open && entityId) {
      loadRatings();
    }
  }, [open, entityId, loadRatings]);

  const handleSubmitRating = async () => {
    if (!entityId || selectedRating === 0) return;
    try {
      setSubmittingRating(true);
      await createRating(entityType, entityId, selectedRating, reviewText || undefined);
      setReviewText('');
      loadRatings();
    } catch {
      // Error is handled by the hook
    } finally {
      setSubmittingRating(false);
    }
  };

  const concatenatedMarkdown = useMemo(() => {
    const divider = '\n\n---\n\n';
    const raw = richTexts.map(rt => {
      const source = sources[rt.id];
      const sourceLabel = source?.startsWith('contract:') 
        ? ` _(from contract)_` 
        : source?.startsWith('shared:') 
        ? ` _(shared)_` 
        : '';
      return `# ${rt.title}${sourceLabel}\n\n${rt.short_description ? `_${rt.short_description}_\n\n` : ''}${rt.content_markdown}`;
    }).join(divider);
    const withImages = rewriteImageLinks(raw, documents);
    return withImages;
  }, [richTexts, documents, sources]);

  const toc = useMemo(() => buildToc(concatenatedMarkdown), [concatenatedMarkdown]);

  const showSubscribeFooter = onSubscribe !== undefined;
  const showFooter = showSubscribeFooter || onGoToDetails !== undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-5xl h-[80vh] flex flex-col p-0"
        style={{ top: '2rem', transform: 'translateX(-50%) translateY(0)' }}
      >
        <DialogHeader className="px-6 pt-4 pb-2 flex-shrink-0">
          <DialogTitle className="flex items-center gap-3 text-xl">
            {showBackButton && (
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-8 w-8 p-0"
                onClick={() => onOpenChange(false)}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
            )}
            <span className="font-semibold">{title || 'Entity Information'}</span>
            {isSubscribed && (
              <span className="inline-flex items-center gap-1 text-xs font-normal bg-primary/10 text-primary px-2 py-1 rounded-full">
                <Bell className="h-3 w-3" />
                Subscribed
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              Loading...
            </div>
          ) : error ? (
            <div className="text-destructive p-4">{error}</div>
          ) : (
            <div className="space-y-6 pb-6 [&>*:first-child]:mt-0">
              {toc.length > 0 && (
                <div className="rounded-lg border bg-muted/20 p-4">
                  <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Table of contents</div>
                  <ul className="text-sm space-y-1">
                    {toc.map((h, idx) => (
                      <li key={idx}>
                        <a href={`#${h.id}`} className="hover:underline inline-block" style={{ paddingLeft: `${(h.level - 1) * 12}px` }}>{h.text}</a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {concatenatedMarkdown ? (
                <div className="max-w-none">
                  <MarkdownViewer markdown={concatenatedMarkdown} />
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No notes available.</div>
              )}

              <Separator />

              <div>
                <div className="text-base font-medium mb-2">Related Links</div>
                {links.length === 0 ? (
                  <div className="text-sm text-muted-foreground">No links.</div>
                ) : (
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50">
                        <tr className="text-left">
                          <th className="py-2 px-3">Title</th>
                          <th className="py-2 px-3">URL</th>
                          <th className="py-2 px-3">Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {links.map((l: LinkItem) => {
                          const source = sources[l.id];
                          const isFromContract = source?.startsWith('contract:');
                          const isShared = source?.startsWith('shared:') || l.is_shared;
                          return (
                            <tr key={l.id} className="border-t">
                              <td className="py-2 px-3 whitespace-nowrap">
                                <span className="flex items-center gap-2">
                                  {l.title}
                                  {isFromContract && <Badge variant="outline" className="text-xs">Inherited</Badge>}
                                  {isShared && <Badge variant="secondary" className="text-xs"><Share2 className="h-3 w-3 mr-1" />Shared</Badge>}
                                </span>
                              </td>
                              <td className="py-2 px-3 max-w-[420px] truncate"><a className="text-primary hover:underline" href={l.url} target="_blank" rel="noreferrer">{l.url}</a></td>
                              <td className="py-2 px-3 text-muted-foreground">{l.short_description || ''}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <Separator />

              {/* Ratings Section */}
              <div>
                <div className="text-base font-medium mb-3 flex items-center gap-2">
                  <Star className="h-5 w-5 text-amber-500" />
                  Ratings & Reviews
                </div>
                
                {ratingsLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading ratings...
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Rating Summary */}
                    <RatingSummary 
                      aggregation={ratingAggregation} 
                      loading={ratingsLoading}
                      showDistribution={true}
                    />
                    
                    {/* User Rating Input */}
                    <div className="border rounded-lg p-4 bg-muted/30">
                      <div className="text-sm font-medium mb-2">Your Rating</div>
                      <div className="flex items-center gap-4 mb-3">
                        <StarRatingInput
                          value={selectedRating}
                          onChange={setSelectedRating}
                          size="md"
                          disabled={submittingRating}
                        />
                        {selectedRating > 0 && (
                          <span className="text-sm text-muted-foreground">
                            {selectedRating === 1 && 'Poor'}
                            {selectedRating === 2 && 'Fair'}
                            {selectedRating === 3 && 'Good'}
                            {selectedRating === 4 && 'Very Good'}
                            {selectedRating === 5 && 'Excellent'}
                          </span>
                        )}
                      </div>
                      <div className="mb-3">
                        <Textarea
                          placeholder="Add a review (optional)..."
                          value={reviewText}
                          onChange={(e) => setReviewText(e.target.value)}
                          rows={2}
                          disabled={submittingRating}
                          className="resize-none"
                        />
                      </div>
                      <Button
                        size="sm"
                        disabled={selectedRating === 0 || submittingRating}
                        onClick={handleSubmitRating}
                      >
                        {submittingRating ? (
                          <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Submitting...</>
                        ) : (
                          'Submit Rating'
                        )}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {showFooter && (
          <DialogFooter className="px-6 py-4 border-t flex-shrink-0 bg-background">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Close
            </Button>
            {onGoToDetails && (
              <Button
                variant="outline"
                onClick={onGoToDetails}
              >
                <ExternalLink className="mr-2 h-4 w-4" />
                Go to Details
              </Button>
            )}
            {showSubscribeFooter && (
              isSubscribed ? (
                <Button variant="secondary" disabled>
                  <Check className="mr-2 h-4 w-4" />
                  Already Subscribed
                </Button>
              ) : (
                <Button
                  onClick={onSubscribe}
                  disabled={subscriptionLoading}
                >
                  {subscriptionLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading...
                    </>
                  ) : (
                    <>
                      <Bell className="mr-2 h-4 w-4" />
                      Subscribe
                    </>
                  )}
                </Button>
              )
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
