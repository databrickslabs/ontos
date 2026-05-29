import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import {
  GitBranch,
  GitCommit,
  GitPullRequest,
  FolderGit2,
  RefreshCw,
  Upload,
  Download,
  FileText,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Save,
} from 'lucide-react';
import { GitDiffModal } from './git-diff-modal';

interface GitStatus {
  clone_status: 'not_configured' | 'not_cloned' | 'cloning' | 'cloned' | 'error';
  repo_url?: string;
  branch?: string;
  volume_path?: string;
  last_sync?: string;
  pending_changes_count: number;
  changed_files: Array<{
    path: string;
    change_type: string;
    diff?: string;
  }>;
  error_message?: string;
  current_commit?: string;
}

interface GitSettings {
  gitRepoUrl: string;
  gitBranch: string;
  gitUsername: string;
  gitToken: string;
}

export default function GitSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const hasWriteAccess = hasPermission('settings-git', FeatureAccessLevel.READ_WRITE);

  const [settings, setSettings] = useState<GitSettings>({
    gitRepoUrl: '',
    gitBranch: 'main',
    gitUsername: '',
    gitToken: '',
  });
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isCloning, setIsCloning] = useState(false);
  const [isPulling, setIsPulling] = useState(false);
  const [isPushing, setIsPushing] = useState(false);
  const [showDiffModal, setShowDiffModal] = useState(false);

  // Fetch Git status
  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/settings/git/status');
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      }
    } catch (error) {
      console.error('Failed to fetch Git status:', error);
    }
  }, []);

  // Fetch settings and status on mount
  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true);
      try {
        // Fetch settings
        const settingsResponse = await fetch('/api/settings');
        if (settingsResponse.ok) {
          const data = await settingsResponse.json();
          setSettings({
            gitRepoUrl: data.git_repo_url || '',
            gitBranch: data.git_branch || 'main',
            gitUsername: data.git_username || '',
            gitToken: '',
          });
        }
        // Fetch Git status
        await fetchStatus();
      } catch (error) {
        console.error('Failed to fetch settings:', error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, [fetchStatus]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setSettings((prev) => ({ ...prev, [name]: value }));
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          git_repo_url: settings.gitRepoUrl,
          git_branch: settings.gitBranch,
          git_username: settings.gitUsername,
          git_password: settings.gitToken,
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:git.messages.saveSuccess', 'Git settings saved'),
        });
        await fetchStatus();
      } else {
        throw new Error('Failed to save settings');
      }
    } catch (error) {
      toast({
        title: t('settings:git.messages.saveError', 'Failed to save Git settings'),
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleClone = async () => {
    setIsCloning(true);
    try {
      const response = await fetch('/api/settings/git/clone', {
        method: 'POST',
      });
      const data = await response.json();
      if (response.ok) {
        toast({
          title: t('settings:git.messages.cloneSuccess', 'Repository cloned successfully'),
          description: data.volume_path,
        });
        await fetchStatus();
      } else {
        throw new Error(data.detail || 'Failed to clone repository');
      }
    } catch (error: any) {
      toast({
        title: t('settings:git.messages.cloneError', 'Failed to clone repository'),
        description: error.message,
        variant: 'destructive',
      });
    } finally {
      setIsCloning(false);
    }
  };

  const handlePull = async () => {
    setIsPulling(true);
    try {
      const response = await fetch('/api/settings/git/pull', {
        method: 'POST',
      });
      const data = await response.json();
      if (response.ok) {
        toast({
          title: t('settings:git.messages.pullSuccess', 'Repository updated'),
        });
        await fetchStatus();
      } else {
        throw new Error(data.detail || 'Failed to pull changes');
      }
    } catch (error: any) {
      toast({
        title: t('settings:git.messages.pullError', 'Failed to pull changes'),
        description: error.message,
        variant: 'destructive',
      });
    } finally {
      setIsPulling(false);
    }
  };

  const handlePush = async (commitMessage?: string) => {
    setIsPushing(true);
    try {
      const response = await fetch('/api/settings/git/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ commit_message: commitMessage }),
      });
      const data = await response.json();
      if (response.ok) {
        toast({
          title: t('settings:git.messages.pushSuccess', 'Changes pushed successfully'),
        });
        setShowDiffModal(false);
        await fetchStatus();
      } else {
        throw new Error(data.detail || 'Failed to push changes');
      }
    } catch (error: any) {
      toast({
        title: t('settings:git.messages.pushError', 'Failed to push changes'),
        description: error.message,
        variant: 'destructive',
      });
    } finally {
      setIsPushing(false);
    }
  };

  const getStatusBadge = () => {
    if (!status) return null;

    const statusConfig: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; icon: React.ReactNode; label: string }> = {
      not_configured: {
        variant: 'secondary',
        icon: <AlertCircle className="h-3 w-3 mr-1" />,
        label: t('settings:git.status.notConfigured', 'Not Configured'),
      },
      not_cloned: {
        variant: 'outline',
        icon: <FolderGit2 className="h-3 w-3 mr-1" />,
        label: t('settings:git.status.notCloned', 'Not Cloned'),
      },
      cloning: {
        variant: 'secondary',
        icon: <Loader2 className="h-3 w-3 mr-1 animate-spin" />,
        label: t('settings:git.status.cloning', 'Cloning...'),
      },
      cloned: {
        variant: 'default',
        icon: <CheckCircle2 className="h-3 w-3 mr-1" />,
        label: t('settings:git.status.cloned', 'Cloned'),
      },
      error: {
        variant: 'destructive',
        icon: <AlertCircle className="h-3 w-3 mr-1" />,
        label: t('settings:git.status.error', 'Error'),
      },
    };

    const config = statusConfig[status.clone_status] || statusConfig.not_configured;

    return (
      <Badge variant={config.variant} className="flex items-center">
        {config.icon}
        {config.label}
      </Badge>
    );
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <>
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <GitBranch className="w-8 h-8" />
              {t('settings:git.title', 'Git Repository')}
            </h1>
            <p className="text-muted-foreground mt-1">
              {t('settings:git.description', 'Configure Git repository for indirect delivery mode (YAML exports).')}
            </p>
          </div>
          {getStatusBadge()}
        </div>
      </div>

      <div className="space-y-6">
          {/* Error Alert */}
          {status?.error_message && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t('settings:git.errorTitle', 'Error')}</AlertTitle>
              <AlertDescription>{status.error_message}</AlertDescription>
            </Alert>
          )}

          {/* Repository Configuration */}
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="gitRepoUrl">{t('settings:git.labels.repoUrl', 'Repository URL')}</Label>
              <Input
                id="gitRepoUrl"
                name="gitRepoUrl"
                value={settings.gitRepoUrl}
                onChange={handleChange}
                placeholder={t('settings:git.placeholders.repoUrl', 'https://github.com/org/repo.git')}
                disabled={!hasWriteAccess}
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="gitBranch">{t('settings:git.labels.branch', 'Branch')}</Label>
                <Input
                  id="gitBranch"
                  name="gitBranch"
                  value={settings.gitBranch}
                  onChange={handleChange}
                  placeholder={t('settings:git.placeholders.branch', 'main')}
                  disabled={!hasWriteAccess}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="gitUsername">{t('settings:git.labels.username', 'Username')}</Label>
                <Input
                  id="gitUsername"
                  name="gitUsername"
                  value={settings.gitUsername}
                  onChange={handleChange}
                  placeholder={t('settings:git.placeholders.username', 'x-access-token')}
                  disabled={!hasWriteAccess}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="gitToken">{t('settings:git.labels.token', 'Access Token')}</Label>
                <Input
                  id="gitToken"
                  name="gitToken"
                  type="password"
                  value={settings.gitToken}
                  onChange={handleChange}
                  placeholder={t('settings:git.placeholders.token', 'ghp_xxxxxxxxxxxx')}
                  disabled={!hasWriteAccess}
                />
              </div>
            </div>
          </div>

          {/* Repository Status (when cloned) */}
          {status?.clone_status === 'cloned' && (
            <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-medium flex items-center gap-2">
                  <GitBranch className="h-4 w-4" />
                  {t('settings:git.repoStatus', 'Repository Status')}
                </h4>
                <Button variant="ghost" size="sm" onClick={fetchStatus}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <GitCommit className="h-4 w-4" />
                  <span>{t('settings:git.currentCommit', 'Commit')}: </span>
                  <code className="text-foreground">{status.current_commit || 'N/A'}</code>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Clock className="h-4 w-4" />
                  <span>{t('settings:git.lastSync', 'Last Sync')}: </span>
                  <span className="text-foreground">
                    {status.last_sync
                      ? new Date(status.last_sync).toLocaleString()
                      : 'Never'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <FileText className="h-4 w-4" />
                  <span>{t('settings:git.pendingChanges', 'Pending Changes')}: </span>
                  <Badge
                    variant={status.pending_changes_count > 0 ? 'default' : 'secondary'}
                    className="text-foreground"
                  >
                    {status.pending_changes_count}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <FolderGit2 className="h-4 w-4" />
                  <span>{t('settings:git.volumePath', 'Volume Path')}: </span>
                  <code className="text-foreground text-xs truncate max-w-[200px]">
                    {status.volume_path || 'N/A'}
                  </code>
                </div>
              </div>
            </div>
          )}
        <div className="flex justify-between pt-4">
          <div className="flex gap-2">
            {hasWriteAccess && (
              <Button onClick={handleSaveSettings} disabled={isSaving}>
                {isSaving ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                {t('settings:git.saveButton', 'Save Settings')}
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            {status?.clone_status === 'cloned' ? (
              <>
                <Button
                  variant="outline"
                  onClick={handlePull}
                  disabled={isPulling || !hasWriteAccess}
                >
                  {isPulling ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="mr-2 h-4 w-4" />
                  )}
                  {t('settings:git.pullButton', 'Pull')}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowDiffModal(true)}
                  disabled={status.pending_changes_count === 0}
                >
                  <GitPullRequest className="mr-2 h-4 w-4" />
                  {t('settings:git.viewChangesButton', 'View Changes')}
                  {status.pending_changes_count > 0 && (
                    <Badge variant="secondary" className="ml-2">
                      {status.pending_changes_count}
                    </Badge>
                  )}
                </Button>
                <Button
                  onClick={() => handlePush()}
                  disabled={isPushing || status.pending_changes_count === 0 || !hasWriteAccess}
                >
                  {isPushing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-2 h-4 w-4" />
                  )}
                  {t('settings:git.pushButton', 'Push')}
                </Button>
              </>
            ) : (
              <Button
                onClick={handleClone}
                disabled={isCloning || !settings.gitRepoUrl || !hasWriteAccess}
              >
                {isCloning ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <FolderGit2 className="mr-2 h-4 w-4" />
                )}
                {t('settings:git.cloneButton', 'Clone Repository')}
              </Button>
            )}
          </div>
        </div>
      </div>

      <GitDiffModal
        open={showDiffModal}
        onOpenChange={setShowDiffModal}
        onPush={handlePush}
        isPushing={isPushing}
      />
    </>
  );
}

