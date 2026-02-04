import { useState, useEffect, useMemo } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
// Select imports commented out - not currently used
// import {
//   Select,
//   SelectContent,
//   SelectItem,
//   SelectTrigger,
//   SelectValue,
// } from '@/components/ui/select';
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
  ArrowRight,
  Check,
  X,
  Edit2,
  // RefreshCw - unused
  Database,
  GitCompare,
  Loader2,
  AlertCircle,
  Sparkles,
  ArrowLeftRight,
  ChevronRight,
  SkipForward,
} from 'lucide-react';

import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import {
  MdmMatchCandidate,
  MdmMatchCandidateStatus,
  MdmMatchType,
  SurvivorshipStrategy,
} from '@/types/mdm';

interface MdmMatchReviewProps {
  assetFqn: string; // mdm://config_id/run_id/candidate_id
  onReviewComplete?: (status: 'approved' | 'rejected') => void;
  onNext?: () => void; // Callback to navigate to next asset
  hasNext?: boolean; // Whether there's a next asset to review
  currentIndex?: number; // Current index in the list (1-based for display)
  totalCount?: number; // Total number of assets to review
  readOnly?: boolean;
}

interface FieldValue {
  field: string;
  masterValue: unknown;
  sourceValue: unknown;
  selectedSource: 'master' | 'source' | 'custom';
  customValue?: unknown;
  survivorshipStrategy?: SurvivorshipStrategy;
}

function parseMdmFqn(fqn: string): { configId: string; runId: string; candidateId: string } | null {
  // Format: mdm://config_id/run_id/candidate_id
  const match = fqn.match(/^mdm:\/\/([^/]+)\/([^/]+)\/(.+)$/);
  if (!match) return null;
  return {
    configId: match[1],
    runId: match[2],
    candidateId: match[3],
  };
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '(empty)';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function areValuesEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || a === undefined) return b === null || b === undefined;
  if (typeof a === 'object' && typeof b === 'object') {
    return JSON.stringify(a) === JSON.stringify(b);
  }
  return String(a).toLowerCase().trim() === String(b).toLowerCase().trim();
}

export default function MdmMatchReview({
  assetFqn,
  onReviewComplete,
  onNext,
  hasNext = false,
  currentIndex,
  totalCount,
  readOnly = false,
}: MdmMatchReviewProps) {
  const { get, put } = useApi();
  const { toast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [candidate, setCandidate] = useState<MdmMatchCandidate | null>(null);
  const [fieldValues, setFieldValues] = useState<FieldValue[]>([]);
  const [comments, setComments] = useState('');
  const [error, setError] = useState<string | null>(null);

  const parsedFqn = useMemo(() => parseMdmFqn(assetFqn), [assetFqn]);

  // Fetch candidate details
  useEffect(() => {
    const fetchCandidate = async () => {
      if (!parsedFqn) {
        setError('Invalid MDM FQN format');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const response = await get<MdmMatchCandidate>(
          `/api/mdm/candidates/${parsedFqn.candidateId}`
        );

        if (response.error) {
          setError(response.error);
          return;
        }

        if (response.data) {
          setCandidate(response.data);
          initializeFieldValues(response.data);
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load match candidate');
      } finally {
        setLoading(false);
      }
    };

    fetchCandidate();
  }, [parsedFqn, get]);

  const initializeFieldValues = (data: MdmMatchCandidate) => {
    const masterData = data.master_record_data || {};
    const sourceData = data.source_record_data || {};
    const mergedData = data.merged_record_data || {};

    // Get all unique fields from both records
    const allFields = new Set([
      ...Object.keys(masterData),
      ...Object.keys(sourceData),
    ]);

    // Filter out internal/system fields
    const systemFields = ['golden_id', 'source_record_id', 'created_at', 'updated_at', 'last_merged_at', 'confidence_score', 'source_systems'];
    
    const values: FieldValue[] = Array.from(allFields)
      .filter(field => !systemFields.includes(field))
      .map(field => {
        const masterValue = masterData[field];
        const sourceValue = sourceData[field];
        const mergedValue = mergedData[field];

        // Determine initial selection
        let selectedSource: 'master' | 'source' | 'custom' = 'master';
        let customValue: unknown = undefined;

        if (mergedValue !== undefined) {
          // Already has a merged value
          if (areValuesEqual(mergedValue, masterValue)) {
            selectedSource = 'master';
          } else if (areValuesEqual(mergedValue, sourceValue)) {
            selectedSource = 'source';
          } else {
            selectedSource = 'custom';
            customValue = mergedValue;
          }
        } else if (data.match_type === 'new') {
          // New record - default to source
          selectedSource = 'source';
        } else if (sourceValue !== null && sourceValue !== undefined && 
                   (masterValue === null || masterValue === undefined)) {
          // Source has value, master doesn't
          selectedSource = 'source';
        }

        return {
          field,
          masterValue,
          sourceValue,
          selectedSource,
          customValue,
        };
      })
      .sort((a, b) => a.field.localeCompare(b.field));

    setFieldValues(values);
  };

  const handleFieldSourceChange = (index: number, source: 'master' | 'source' | 'custom') => {
    setFieldValues(prev => {
      const updated = [...prev];
      updated[index] = {
        ...updated[index],
        selectedSource: source,
        customValue: source === 'custom' ? updated[index].customValue || updated[index].masterValue : undefined,
      };
      return updated;
    });
  };

  const handleCustomValueChange = (index: number, value: string) => {
    setFieldValues(prev => {
      const updated = [...prev];
      updated[index] = {
        ...updated[index],
        customValue: value,
      };
      return updated;
    });
  };

  const buildMergedRecord = (): Record<string, unknown> => {
    const merged: Record<string, unknown> = {};
    
    // Include system fields from master if it's a match
    if (candidate?.master_record_data) {
      merged['golden_id'] = candidate.master_record_data['golden_id'];
    }
    merged['source_record_id'] = candidate?.source_record_id;

    for (const fv of fieldValues) {
      if (fv.selectedSource === 'master') {
        merged[fv.field] = fv.masterValue;
      } else if (fv.selectedSource === 'source') {
        merged[fv.field] = fv.sourceValue;
      } else {
        merged[fv.field] = fv.customValue;
      }
    }

    return merged;
  };

  const handleApprove = async (): Promise<boolean> => {
    if (!candidate || !parsedFqn) return false;

    setSaving(true);
    try {
      const mergedData = buildMergedRecord();
      
      const response = await put<MdmMatchCandidate>(
        `/api/mdm/candidates/${parsedFqn.candidateId}`,
        {
          status: MdmMatchCandidateStatus.APPROVED,
          merged_record_data: mergedData,
        }
      );

      if (response.error) {
        toast({
          title: 'Error',
          description: response.error,
          variant: 'destructive',
        });
        return false;
      }

      toast({
        title: 'Match Approved',
        description: 'The match has been approved and merged record saved.',
      });

      onReviewComplete?.('approved');
      return true;
    } catch (err: any) {
      toast({
        title: 'Error',
        description: err.message || 'Failed to approve match',
        variant: 'destructive',
      });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleApproveAndNext = async () => {
    const success = await handleApprove();
    if (success && onNext) {
      onNext();
    }
  };

  const handleReject = async () => {
    if (!candidate || !parsedFqn) return;

    setSaving(true);
    try {
      const response = await put<MdmMatchCandidate>(
        `/api/mdm/candidates/${parsedFqn.candidateId}`,
        {
          status: MdmMatchCandidateStatus.REJECTED,
        }
      );

      if (response.error) {
        toast({
          title: 'Error',
          description: response.error,
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Match Rejected',
        description: 'The match has been rejected.',
      });

      onReviewComplete?.('rejected');
    } catch (err: any) {
      toast({
        title: 'Error',
        description: err.message || 'Failed to reject match',
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  const applyAllMaster = () => {
    setFieldValues(prev => prev.map(fv => ({ ...fv, selectedSource: 'master' as const })));
  };

  const applyAllSource = () => {
    setFieldValues(prev => prev.map(fv => ({ ...fv, selectedSource: 'source' as const })));
  };

  const applySmartMerge = () => {
    // Apply intelligent defaults: prefer non-null values, prefer more recent
    setFieldValues(prev => prev.map(fv => {
      // If values are equal, keep master
      if (areValuesEqual(fv.masterValue, fv.sourceValue)) {
        return { ...fv, selectedSource: 'master' as const };
      }
      // If master is empty but source has value, use source
      if ((fv.masterValue === null || fv.masterValue === undefined || fv.masterValue === '') 
          && fv.sourceValue !== null && fv.sourceValue !== undefined && fv.sourceValue !== '') {
        return { ...fv, selectedSource: 'source' as const };
      }
      // Otherwise keep master (trust existing data)
      return { ...fv, selectedSource: 'master' as const };
    }));

    toast({
      title: 'Smart Merge Applied',
      description: 'Fields with empty master values now use source values.',
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">Loading match details...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 text-destructive">
        <AlertCircle className="h-6 w-6 mr-2" />
        <span>{error}</span>
      </div>
    );
  }

  if (!candidate) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground">
        <AlertCircle className="h-6 w-6 mr-2" />
        <span>Match candidate not found</span>
      </div>
    );
  }

  const isAlreadyReviewed = candidate.status !== MdmMatchCandidateStatus.PENDING;

  return (
    <div className="space-y-4">
      {/* Match Summary */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitCompare className="h-5 w-5" />
              <CardTitle className="text-lg">Match Review</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={candidate.match_type !== MdmMatchType.NEW ? 'default' : 'secondary'}>
                {candidate.match_type !== MdmMatchType.NEW ? 'Match Found' : 'New Record'}
              </Badge>
              <Badge 
                variant={
                  candidate.status === MdmMatchCandidateStatus.APPROVED ? 'default' :
                  candidate.status === MdmMatchCandidateStatus.REJECTED ? 'destructive' :
                  'outline'
                }
              >
                {candidate.status}
              </Badge>
            </div>
          </div>
          <CardDescription>
            Confidence Score: <span className="font-semibold">{(candidate.confidence_score * 100).toFixed(1)}%</span>
            {candidate.matched_fields && candidate.matched_fields.length > 0 && (
              <span className="ml-4">
                Matched on: {candidate.matched_fields.join(', ')}
              </span>
            )}
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Field Comparison Table */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="h-5 w-5" />
              Field Comparison
            </CardTitle>
            {!readOnly && !isAlreadyReviewed && (
              <div className="flex gap-2">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" onClick={applyAllMaster}>
                        <ArrowRight className="h-4 w-4 mr-1" />
                        All Master
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Use all values from master record</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" onClick={applyAllSource}>
                        <ArrowRight className="h-4 w-4 mr-1 rotate-180" />
                        All Source
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Use all values from source record</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" onClick={applySmartMerge}>
                        <Sparkles className="h-4 w-4 mr-1" />
                        Smart Merge
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Fill empty master fields with source values</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[400px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[180px]">Field</TableHead>
                  <TableHead>Master Value</TableHead>
                  <TableHead className="w-[100px] text-center">
                    <ArrowLeftRight className="h-4 w-4 mx-auto" />
                  </TableHead>
                  <TableHead>Source Value</TableHead>
                  <TableHead className="w-[200px]">Final Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {fieldValues.map((fv, index) => {
                  const valuesMatch = areValuesEqual(fv.masterValue, fv.sourceValue);
                  const masterEmpty = fv.masterValue === null || fv.masterValue === undefined || fv.masterValue === '';
                  const sourceEmpty = fv.sourceValue === null || fv.sourceValue === undefined || fv.sourceValue === '';

                  return (
                    <TableRow key={fv.field} className={valuesMatch ? 'bg-muted/30' : ''}>
                      <TableCell className="font-medium">
                        {fv.field}
                        {candidate.matched_fields?.includes(fv.field) && (
                          <Badge variant="outline" className="ml-2 text-xs">matched</Badge>
                        )}
                      </TableCell>
                      <TableCell 
                        className={`cursor-pointer hover:bg-muted/50 ${fv.selectedSource === 'master' ? 'bg-green-500/10 border-l-2 border-green-500' : ''}`}
                        onClick={() => !readOnly && !isAlreadyReviewed && handleFieldSourceChange(index, 'master')}
                      >
                        <div className="flex items-center justify-between">
                          <span className={masterEmpty ? 'text-muted-foreground italic' : ''}>
                            {formatValue(fv.masterValue)}
                          </span>
                          {fv.selectedSource === 'master' && (
                            <Check className="h-4 w-4 text-green-500 ml-2" />
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        {valuesMatch ? (
                          <Badge variant="secondary" className="text-xs">=</Badge>
                        ) : (
                          <Badge variant="outline" className="text-xs">≠</Badge>
                        )}
                      </TableCell>
                      <TableCell 
                        className={`cursor-pointer hover:bg-muted/50 ${fv.selectedSource === 'source' ? 'bg-blue-500/10 border-l-2 border-blue-500' : ''}`}
                        onClick={() => !readOnly && !isAlreadyReviewed && handleFieldSourceChange(index, 'source')}
                      >
                        <div className="flex items-center justify-between">
                          <span className={sourceEmpty ? 'text-muted-foreground italic' : ''}>
                            {formatValue(fv.sourceValue)}
                          </span>
                          {fv.selectedSource === 'source' && (
                            <Check className="h-4 w-4 text-blue-500 ml-2" />
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        {readOnly || isAlreadyReviewed ? (
                          <span className="text-sm">
                            {fv.selectedSource === 'custom' 
                              ? formatValue(fv.customValue)
                              : fv.selectedSource === 'master' 
                                ? formatValue(fv.masterValue)
                                : formatValue(fv.sourceValue)
                            }
                          </span>
                        ) : fv.selectedSource === 'custom' ? (
                          <Input
                            value={String(fv.customValue || '')}
                            onChange={(e) => handleCustomValueChange(index, e.target.value)}
                            className="h-8"
                          />
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground">
                              {fv.selectedSource === 'master' ? 'Master' : 'Source'}
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2"
                              onClick={() => handleFieldSourceChange(index, 'custom')}
                            >
                              <Edit2 className="h-3 w-3" />
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Review Actions */}
      {!readOnly && !isAlreadyReviewed && (
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="review-comments">Review Comments (Optional)</Label>
                <Textarea
                  id="review-comments"
                  placeholder="Add any notes about this review decision..."
                  value={comments}
                  onChange={(e) => setComments(e.target.value)}
                  rows={2}
                />
              </div>
              
              <Separator />

              <div className="flex items-center justify-between">
                {/* Progress indicator */}
                {currentIndex !== undefined && totalCount !== undefined && (
                  <div className="text-sm text-muted-foreground">
                    Reviewing {currentIndex} of {totalCount}
                  </div>
                )}
                {currentIndex === undefined && <div />}

                <div className="flex gap-3">
                  {/* Skip to next without saving */}
                  {hasNext && onNext && (
                    <Button
                      variant="ghost"
                      onClick={onNext}
                      disabled={saving}
                    >
                      <SkipForward className="h-4 w-4 mr-2" />
                      Skip
                    </Button>
                  )}
                  
                  <Button
                    variant="destructive"
                    onClick={handleReject}
                    disabled={saving}
                  >
                    {saving ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <X className="h-4 w-4 mr-2" />
                    )}
                    Reject
                  </Button>
                  
                  <Button
                    variant="outline"
                    onClick={handleApprove}
                    disabled={saving}
                  >
                    {saving ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4 mr-2" />
                    )}
                    Approve
                  </Button>

                  {/* Save & Next button - only shown when there's a next item */}
                  {hasNext && onNext && (
                    <Button
                      variant="default"
                      onClick={handleApproveAndNext}
                      disabled={saving}
                    >
                      {saving ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <ChevronRight className="h-4 w-4 mr-2" />
                      )}
                      Approve & Next
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {isAlreadyReviewed && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-center gap-2 text-muted-foreground">
              <AlertCircle className="h-5 w-5" />
              <span>
                This match has already been {candidate.status.toLowerCase()}
                {candidate.reviewed_by && ` by ${candidate.reviewed_by}`}
                {candidate.reviewed_at && ` on ${new Date(candidate.reviewed_at).toLocaleString()}`}
              </span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

