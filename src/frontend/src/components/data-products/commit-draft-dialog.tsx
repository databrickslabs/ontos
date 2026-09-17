import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import type { DiffFromParentResponse } from '@/types/data-product';

interface CommitDraftDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string;
  productName?: string;
  onSuccess: (newProductId: string) => void;
}

function calculateNextSemver(currentVersion: string, bump: 'major' | 'minor' | 'patch'): string {
  const version = currentVersion.replace('-draft', '');
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) return '0.0.1';
  
  const major = parseInt(match[1], 10);
  const minor = parseInt(match[2], 10);
  const patch = parseInt(match[3], 10);
  
  if (bump === 'major') return `${major + 1}.0.0`;
  if (bump === 'minor') return `${major}.${minor + 1}.0`;
  return `${major}.${minor}.${patch + 1}`;
}

export default function CommitDraftDialog({
  isOpen,
  onOpenChange,
  productId,
  productName,
  onSuccess,
}: CommitDraftDialogProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  
  const [loadingDiff, setLoadingDiff] = useState(true);
  const [diffAnalysis, setDiffAnalysis] = useState<DiffFromParentResponse | null>(null);
  const [suggestedVersion, setSuggestedVersion] = useState('');
  const [selectedVersionBump, setSelectedVersionBump] = useState<'major' | 'minor' | 'patch' | 'custom'>('patch');
  const [customVersion, setCustomVersion] = useState('');
  const [changeSummary, setChangeSummary] = useState('');
  const [isCommitting, setIsCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch diff when dialog opens
  useEffect(() => {
    if (isOpen && productId) {
      fetchDiff();
    }
  }, [isOpen, productId]);

  const fetchDiff = async () => {
    setLoadingDiff(true);
    setError(null);
    try {
      const response = await get<DiffFromParentResponse>(`/api/data-products/${productId}/diff-from-parent`);
      if (response.error) {
        throw new Error(response.error);
      }
      if (response.data) {
        setDiffAnalysis(response.data);
        setSuggestedVersion(response.data.suggested_version);
        setSelectedVersionBump(response.data.suggested_bump as 'major' | 'minor' | 'patch');
      }
    } catch (e: any) {
      // If no parent, just use 1.0.0
      if (e.message?.includes('no parent')) {
        setSuggestedVersion('1.0.0');
        setSelectedVersionBump('minor');
      } else {
        setError(e.message || 'Failed to analyze changes');
      }
    } finally {
      setLoadingDiff(false);
    }
  };

  const getVersionForBump = (bump: 'major' | 'minor' | 'patch' | 'custom'): string => {
    if (bump === 'custom') return customVersion;
    if (!diffAnalysis) return suggestedVersion;
    return calculateNextSemver(diffAnalysis.parent_version, bump);
  };

  const handleSubmit = async () => {
    const finalVersion = getVersionForBump(selectedVersionBump);
    
    if (!finalVersion || !/^\d+\.\d+\.\d+$/.test(finalVersion)) {
      setError('Please enter a valid version number (e.g., 1.0.0)');
      return;
    }
    
    if (!changeSummary.trim()) {
      setError('Please provide a summary of changes');
      return;
    }
    
    setError(null);
    setIsCommitting(true);
    
    try {
      const response = await post(`/api/data-products/${productId}/commit`, {
        new_version: finalVersion,
        change_summary: changeSummary.trim(),
      });
      
      if (response.error) {
        throw new Error(response.error);
      }
      
      toast({
        title: 'Draft Committed',
        description: `Product version ${finalVersion} is now visible to your team.`,
      });
      
      onSuccess(productId);
      onOpenChange(false);
      
    } catch (e: any) {
      setError(e.message || 'Failed to commit draft');
    } finally {
      setIsCommitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            Commit Draft Changes
          </DialogTitle>
          <DialogDescription>
            {productName && <span className="font-medium">{productName}</span>}
            <span className="text-muted-foreground ml-2">
              Commit your personal draft to make it visible to your team.
            </span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {loadingDiff ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              Analyzing changes...
            </div>
          ) : (
            <>
              {/* Change Analysis Summary */}
              {diffAnalysis && (
                <Alert className="bg-blue-50 border-blue-200 dark:bg-blue-950 dark:border-blue-800">
                  <AlertTitle className="text-blue-800 dark:text-blue-200">{t('data-products:commitDraft.changeAnalysisTitle')}</AlertTitle>
                  <AlertDescription className="text-blue-700 dark:text-blue-300">
                    Based on your changes, we recommend a <strong>{diffAnalysis.suggested_bump}</strong> version bump.
                    {diffAnalysis.analysis?.summary && (
                      <p className="mt-1 text-sm">{diffAnalysis.analysis.summary}</p>
                    )}
                  </AlertDescription>
                </Alert>
              )}

              {/* Version Selection */}
              <div className="space-y-3">
                <Label>{t('data-products:commitDraft.selectVersion')}</Label>
                <RadioGroup
                  value={selectedVersionBump}
                  onValueChange={(v) => setSelectedVersionBump(v as typeof selectedVersionBump)}
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="patch" id="patch" />
                    <Label htmlFor="patch" className="font-normal">
                      Patch ({diffAnalysis ? calculateNextSemver(diffAnalysis.parent_version, 'patch') : '?.?.?'})
                      <span className="text-muted-foreground ml-2">- Bug fixes</span>
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="minor" id="minor" />
                    <Label htmlFor="minor" className="font-normal">
                      Minor ({diffAnalysis ? calculateNextSemver(diffAnalysis.parent_version, 'minor') : '?.?.?'})
                      <span className="text-muted-foreground ml-2">- New features</span>
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="major" id="major" />
                    <Label htmlFor="major" className="font-normal">
                      Major ({diffAnalysis ? calculateNextSemver(diffAnalysis.parent_version, 'major') : '?.?.?'})
                      <span className="text-muted-foreground ml-2">- Breaking changes</span>
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="custom" id="custom" />
                    <Label htmlFor="custom" className="font-normal">{t('data-products:commitDraft.customVersion')}</Label>
                  </div>
                </RadioGroup>
                
                {selectedVersionBump === 'custom' && (
                  <Input
                    value={customVersion}
                    onChange={(e) => setCustomVersion(e.target.value)}
                    placeholder={t('data-products:commitDraft.customVersionPlaceholder')}
                    className="mt-2"
                  />
                )}
              </div>

              {/* Change Summary */}
              <div className="space-y-2">
                <Label htmlFor="change-summary">Change Summary *</Label>
                <Textarea
                  id="change-summary"
                  value={changeSummary}
                  onChange={(e) => setChangeSummary(e.target.value)}
                  placeholder={t('data-products:commitDraft.changeSummaryPlaceholder')}
                  className="min-h-[100px] resize-none"
                  disabled={isCommitting}
                />
              </div>

              {/* Error Display */}
              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isCommitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isCommitting || loadingDiff}>
            {isCommitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Committing...
              </>
            ) : (
              'Commit Draft'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

