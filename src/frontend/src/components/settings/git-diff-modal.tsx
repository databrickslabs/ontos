import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  FileText,
  FilePlus,
  FileX,
  FilePen,
  ChevronDown,
  ChevronRight,
  Upload,
  Loader2,
} from 'lucide-react';

interface GitFileChange {
  path: string;
  change_type: 'added' | 'modified' | 'deleted';
  diff?: string;
}

interface GitDiffData {
  pending_changes_count: number;
  changed_files: GitFileChange[];
}

interface GitDiffModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPush: (commitMessage?: string) => Promise<void>;
  isPushing: boolean;
}

export function GitDiffModal({
  open,
  onOpenChange,
  onPush,
  isPushing,
}: GitDiffModalProps) {
  const { t } = useTranslation(['settings', 'common']);
  const [diffData, setDiffData] = useState<GitDiffData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [commitMessage, setCommitMessage] = useState('');
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());

  // Fetch diff data when modal opens
  useEffect(() => {
    if (open) {
      fetchDiff();
    }
  }, [open]);

  const fetchDiff = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/settings/git/diff');
      if (response.ok) {
        const data = await response.json();
        setDiffData(data);
      }
    } catch (error) {
      console.error('Failed to fetch diff:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleFileExpanded = (path: string) => {
    const newExpanded = new Set(expandedFiles);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedFiles(newExpanded);
  };

  const expandAll = () => {
    if (diffData) {
      setExpandedFiles(new Set(diffData.changed_files.map((f) => f.path)));
    }
  };

  const collapseAll = () => {
    setExpandedFiles(new Set());
  };

  const getChangeIcon = (changeType: string) => {
    switch (changeType) {
      case 'added':
        return <FilePlus className="h-4 w-4 text-green-500" />;
      case 'deleted':
        return <FileX className="h-4 w-4 text-red-500" />;
      case 'modified':
        return <FilePen className="h-4 w-4 text-yellow-500" />;
      default:
        return <FileText className="h-4 w-4" />;
    }
  };

  const getChangeBadge = (changeType: string) => {
    const variants: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
      added: 'default',
      deleted: 'destructive',
      modified: 'secondary',
    };
    return (
      <Badge variant={variants[changeType] || 'outline'} className="text-xs">
        {changeType}
      </Badge>
    );
  };

  const handlePush = async () => {
    await onPush(commitMessage || undefined);
    setCommitMessage('');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('settings:git.diff.title', 'Pending Changes')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'settings:git.diff.description',
              'Review changes before committing and pushing to the repository.'
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : diffData ? (
          <>
            {/* Stats and Actions */}
            <div className="flex items-center justify-between border-b pb-3">
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                <span>
                  {t('settings:git.diff.fileCount', '{{count}} file(s) changed', {
                    count: diffData.pending_changes_count,
                  })}
                </span>
                <div className="flex gap-2">
                  <Badge variant="default" className="text-xs">
                    +{diffData.changed_files.filter((f) => f.change_type === 'added').length}
                  </Badge>
                  <Badge variant="secondary" className="text-xs">
                    ~{diffData.changed_files.filter((f) => f.change_type === 'modified').length}
                  </Badge>
                  <Badge variant="destructive" className="text-xs">
                    -{diffData.changed_files.filter((f) => f.change_type === 'deleted').length}
                  </Badge>
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={expandAll}>
                  {t('settings:git.diff.expandAll', 'Expand All')}
                </Button>
                <Button variant="ghost" size="sm" onClick={collapseAll}>
                  {t('settings:git.diff.collapseAll', 'Collapse All')}
                </Button>
              </div>
            </div>

            {/* File List */}
            <ScrollArea className="flex-1 pr-4">
              <div className="space-y-2 py-2">
                {diffData.changed_files.map((file) => (
                  <Collapsible
                    key={file.path}
                    open={expandedFiles.has(file.path)}
                    onOpenChange={() => toggleFileExpanded(file.path)}
                  >
                    <CollapsibleTrigger asChild>
                      <div className="flex items-center gap-2 p-2 hover:bg-muted/50 rounded-md cursor-pointer">
                        {expandedFiles.has(file.path) ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                        {getChangeIcon(file.change_type)}
                        <code className="text-sm flex-1 truncate">{file.path}</code>
                        {getChangeBadge(file.change_type)}
                      </div>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="ml-8 mt-2 mb-4">
                        {file.diff ? (
                          <pre className="text-xs bg-muted p-3 rounded-md overflow-x-auto whitespace-pre-wrap font-mono">
                            {file.diff.split('\n').map((line, index) => {
                              let lineClass = '';
                              if (line.startsWith('+') && !line.startsWith('+++')) {
                                lineClass = 'text-green-600 dark:text-green-400';
                              } else if (line.startsWith('-') && !line.startsWith('---')) {
                                lineClass = 'text-red-600 dark:text-red-400';
                              } else if (line.startsWith('@@')) {
                                lineClass = 'text-blue-600 dark:text-blue-400';
                              }
                              return (
                                <span key={index} className={lineClass}>
                                  {line}
                                  {'\n'}
                                </span>
                              );
                            })}
                          </pre>
                        ) : (
                          <p className="text-sm text-muted-foreground italic">
                            {file.change_type === 'added'
                              ? t('settings:git.diff.newFile', 'New file')
                              : t('settings:git.diff.noDiff', 'No diff available')}
                          </p>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                ))}
              </div>
            </ScrollArea>

            {/* Commit Message */}
            <div className="space-y-2 border-t pt-4">
              <Label htmlFor="commitMessage">
                {t('settings:git.diff.commitMessage', 'Commit Message (optional)')}
              </Label>
              <Input
                id="commitMessage"
                value={commitMessage}
                onChange={(e) => setCommitMessage(e.target.value)}
                placeholder={t(
                  'settings:git.diff.commitPlaceholder',
                  'Auto-generated if left empty'
                )}
              />
            </div>
          </>
        ) : (
          <div className="py-10 text-center text-muted-foreground">
            {t('settings:git.diff.noChanges', 'No pending changes')}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:cancel', 'Cancel')}
          </Button>
          <Button
            onClick={handlePush}
            disabled={isPushing || !diffData || diffData.pending_changes_count === 0}
          >
            {isPushing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            {t('settings:git.diff.commitAndPush', 'Commit & Push')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

