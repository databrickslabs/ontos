/**
 * MCP Tokens Settings Component
 * 
 * Allows administrators to create, view, and revoke MCP API tokens
 * for AI assistant integrations.
 */

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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
  Key,
  Plus,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  Clock,
  Shield,
  Loader2,
  RefreshCw,
  Eye,
  EyeOff,
} from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';
import {
  MCPTokenInfo,
  MCPTokenList,
  MCPTokenResponse,
  MCPTokenCreate,
  MCP_SCOPE_CATEGORIES,
} from '@/types/mcp-token';

export default function MCPTokensSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { get, post, delete: del } = useApi();

  // State
  const [tokens, setTokens] = useState<MCPTokenInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [includeInactive, setIncludeInactive] = useState(false);

  // Create dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newTokenName, setNewTokenName] = useState('');
  const [newTokenScopes, setNewTokenScopes] = useState<string[]>([]);
  const [newTokenExpiresDays, setNewTokenExpiresDays] = useState<number | null>(90);
  const [isCreating, setIsCreating] = useState(false);

  // Token created dialog (shows the token once)
  const [createdToken, setCreatedToken] = useState<MCPTokenResponse | null>(null);
  const [tokenCopied, setTokenCopied] = useState(false);
  const [showToken, setShowToken] = useState(false);

  // Revoke dialog state
  const [tokenToRevoke, setTokenToRevoke] = useState<MCPTokenInfo | null>(null);

  // Load tokens
  const loadTokens = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await get<MCPTokenList>(
        `/api/mcp-tokens?include_inactive=${includeInactive}`
      );
      if (response.data?.tokens) {
        setTokens(response.data.tokens);
      }
    } catch (error) {
      console.error('Failed to load MCP tokens:', error);
      toast({
        title: t('common:toast.error'),
        description: t('settings:mcpTokens.messages.loadError'),
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  }, [get, includeInactive, toast]);

  useEffect(() => {
    loadTokens();
  }, [loadTokens]);

  // Handle scope toggle
  const toggleScope = (scope: string) => {
    setNewTokenScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };

  // Create token
  const handleCreateToken = async () => {
    if (!newTokenName.trim()) {
      toast({
        title: t('common:errors.validationError'),
        description: t('settings:mcpTokens.messages.tokenNameRequired'),
        variant: 'destructive',
      });
      return;
    }

    if (newTokenScopes.length === 0) {
      toast({
        title: t('common:errors.validationError'),
        description: t('settings:mcpTokens.messages.scopeRequired'),
        variant: 'destructive',
      });
      return;
    }

    setIsCreating(true);
    try {
      const payload: MCPTokenCreate = {
        name: newTokenName.trim(),
        scopes: newTokenScopes,
        expires_days: newTokenExpiresDays,
      };

      const response = await post<MCPTokenResponse>('/api/mcp-tokens', payload);

      if (response.error) {
        throw new Error(response.error);
      }

      if (response.data) {
        setCreatedToken(response.data);
        setCreateDialogOpen(false);
        setNewTokenName('');
        setNewTokenScopes([]);
        setNewTokenExpiresDays(90);
        loadTokens();
      }
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message || t('settings:mcpTokens.messages.createError'),
        variant: 'destructive',
      });
    } finally {
      setIsCreating(false);
    }
  };

  // Copy token to clipboard
  const handleCopyToken = async () => {
    if (createdToken?.token) {
      await navigator.clipboard.writeText(createdToken.token);
      setTokenCopied(true);
      setTimeout(() => setTokenCopied(false), 2000);
      toast({
        title: t('common:toast.copied'),
        description: t('settings:mcpTokens.messages.copied'),
      });
    }
  };

  // Revoke token
  const handleRevokeToken = async () => {
    if (!tokenToRevoke) return;

    try {
      const response = await del(`/api/mcp-tokens/${tokenToRevoke.id}`);

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: t('common:toast.success'),
        description: t('settings:mcpTokens.messages.revoked', { name: tokenToRevoke.name }),
      });

      setTokenToRevoke(null);
      loadTokens();
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message || t('settings:mcpTokens.messages.revokeError'),
        variant: 'destructive',
      });
    }
  };

  // Format date
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    try {
      return format(new Date(dateStr), 'MMM d, yyyy HH:mm');
    } catch {
      return dateStr;
    }
  };

  // Format relative date
  const formatRelative = (dateStr: string | null) => {
    if (!dateStr) return null;
    try {
      return formatDistanceToNow(new Date(dateStr), { addSuffix: true });
    } catch {
      return null;
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Key className="h-6 w-6 text-primary" />
            <div>
              <CardTitle>{t('settings:mcpTokens.title')}</CardTitle>
              <CardDescription>
                {t('settings:mcpTokens.description')}
              </CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={loadTokens}
              disabled={isLoading}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
              {t('settings:mcpTokens.refresh')}
            </Button>
            <Button onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              {t('settings:mcpTokens.createToken')}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Filter */}
        <div className="flex items-center gap-2 mb-4">
          <Checkbox
            id="include-inactive"
            checked={includeInactive}
            onCheckedChange={(checked) => setIncludeInactive(!!checked)}
          />
          <Label htmlFor="include-inactive" className="text-sm text-muted-foreground">
            {t('settings:mcpTokens.showRevokedTokens')}
          </Label>
        </div>

        {/* Tokens Table */}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : tokens.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Key className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg font-medium">{t('settings:mcpTokens.emptyState.title')}</p>
            <p className="text-sm">{t('settings:mcpTokens.emptyState.description')}</p>
          </div>
        ) : (
          <div className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('settings:mcpTokens.table.name')}</TableHead>
                  <TableHead>{t('settings:mcpTokens.table.scopes')}</TableHead>
                  <TableHead>{t('settings:mcpTokens.table.created')}</TableHead>
                  <TableHead>{t('settings:mcpTokens.table.lastUsed')}</TableHead>
                  <TableHead>{t('settings:mcpTokens.table.expires')}</TableHead>
                  <TableHead>{t('settings:mcpTokens.table.status')}</TableHead>
                  <TableHead className="w-[80px]">{t('settings:mcpTokens.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tokens.map((token) => (
                  <TableRow key={token.id} className={!token.is_active ? 'opacity-50' : ''}>
                    <TableCell className="font-medium">{token.name}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1 max-w-[300px]">
                        {token.scopes.slice(0, 3).map((scope) => (
                          <Badge key={scope} variant="secondary" className="text-xs">
                            {scope}
                          </Badge>
                        ))}
                        {token.scopes.length > 3 && (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger>
                                <Badge variant="outline" className="text-xs">
                                  {t('settings:mcpTokens.table.moreScopes', { count: token.scopes.length - 3 })}
                                </Badge>
                              </TooltipTrigger>
                              <TooltipContent>
                                <div className="flex flex-col gap-1">
                                  {token.scopes.slice(3).map((scope) => (
                                    <span key={scope}>{scope}</span>
                                  ))}
                                </div>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger className="text-sm">
                            {formatRelative(token.created_at) || formatDate(token.created_at)}
                          </TooltipTrigger>
                          <TooltipContent>
                            <div className="text-xs">
                              <div>{formatDate(token.created_at)}</div>
                              {token.created_by && (
                                <div className="text-muted-foreground">{t('settings:mcpTokens.table.createdBy', { name: token.created_by })}</div>
                              )}
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </TableCell>
                    <TableCell>
                      {token.last_used_at ? (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger className="text-sm">
                              {formatRelative(token.last_used_at)}
                            </TooltipTrigger>
                            <TooltipContent>{formatDate(token.last_used_at)}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        <span className="text-muted-foreground text-sm">{t('settings:mcpTokens.table.never')}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {token.expires_at ? (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger
                              className={`text-sm flex items-center gap-1 ${
                                token.is_expired ? 'text-destructive' : ''
                              }`}
                            >
                              {token.is_expired && <AlertTriangle className="h-3 w-3" />}
                              {formatRelative(token.expires_at)}
                            </TooltipTrigger>
                            <TooltipContent>{formatDate(token.expires_at)}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        <span className="text-muted-foreground text-sm">{t('settings:mcpTokens.table.never')}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {!token.is_active ? (
                        <Badge variant="secondary" className="bg-muted">
                          {t('settings:mcpTokens.status.revoked')}
                        </Badge>
                      ) : token.is_expired ? (
                        <Badge variant="destructive">{t('settings:mcpTokens.status.expired')}</Badge>
                      ) : (
                        <Badge variant="default" className="bg-green-600">
                          {t('settings:mcpTokens.status.active')}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {token.is_active && !token.is_expired && (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setTokenToRevoke(token)}
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t('settings:mcpTokens.tooltips.revokeToken')}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Info Section */}
        <div className="mt-6 p-4 bg-muted/50 rounded-lg">
          <h4 className="font-medium flex items-center gap-2 mb-2">
            <Shield className="h-4 w-4" />
            {t('settings:mcpTokens.info.title')}
          </h4>
          <p className="text-sm text-muted-foreground mb-2">
            {t('settings:mcpTokens.info.description')}
          </p>
          <div className="text-sm text-muted-foreground">
            <strong>{t('settings:mcpTokens.info.endpoint')}</strong>{' '}
            <code className="bg-background px-1 rounded">/api/mcp</code>
          </div>
          <div className="text-sm text-muted-foreground">
            <strong>{t('settings:mcpTokens.info.header')}</strong>{' '}
            <code className="bg-background px-1 rounded">X-API-Key: mcp_...</code>
          </div>
        </div>
      </CardContent>

      {/* Create Token Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              {t('settings:mcpTokens.createDialog.title')}
            </DialogTitle>
            <DialogDescription>
              {t('settings:mcpTokens.createDialog.description')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Token Name */}
            <div className="space-y-2">
              <Label htmlFor="token-name">{t('settings:mcpTokens.createDialog.tokenName')} *</Label>
              <Input
                id="token-name"
                placeholder={t('settings:mcpTokens.createDialog.tokenNamePlaceholder')}
                value={newTokenName}
                onChange={(e) => setNewTokenName(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t('settings:mcpTokens.createDialog.tokenNameHelp')}
              </p>
            </div>

            {/* Expiration */}
            <div className="space-y-2">
              <Label htmlFor="token-expires">{t('settings:mcpTokens.createDialog.expiration')}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="token-expires"
                  type="number"
                  min={1}
                  max={365}
                  placeholder="90"
                  value={newTokenExpiresDays ?? ''}
                  onChange={(e) =>
                    setNewTokenExpiresDays(e.target.value ? parseInt(e.target.value) : null)
                  }
                  className="w-32"
                />
                <span className="text-sm text-muted-foreground">
                  {t('settings:mcpTokens.createDialog.expirationHelp')}
                </span>
              </div>
            </div>

            {/* Scopes */}
            <div className="space-y-2">
              <Label>{t('settings:mcpTokens.createDialog.scopes')} *</Label>
              <p className="text-xs text-muted-foreground mb-2">
                {t('settings:mcpTokens.createDialog.scopesHelp')}
              </p>
              <ScrollArea className="h-[300px] border rounded-lg p-4">
                {Object.entries(MCP_SCOPE_CATEGORIES).map(([category, scopes]) => (
                  <div key={category} className="mb-4">
                    <h5 className="font-medium text-sm mb-2">{category}</h5>
                    <div className="space-y-2">
                      {scopes.map((scope) => (
                        <div key={scope.value} className="flex items-start gap-2">
                          <Checkbox
                            id={`scope-${scope.value}`}
                            checked={newTokenScopes.includes(scope.value)}
                            onCheckedChange={() => toggleScope(scope.value)}
                          />
                          <div className="grid gap-0.5">
                            <Label
                              htmlFor={`scope-${scope.value}`}
                              className="text-sm font-medium cursor-pointer"
                            >
                              {scope.label}
                            </Label>
                            <p className="text-xs text-muted-foreground">{scope.description}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                    <Separator className="mt-3" />
                  </div>
                ))}
              </ScrollArea>
              {newTokenScopes.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  <span className="text-xs text-muted-foreground">{t('settings:mcpTokens.createDialog.selectedScopes')}</span>
                  {newTokenScopes.map((scope) => (
                    <Badge key={scope} variant="secondary" className="text-xs">
                      {scope}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              {t('settings:mcpTokens.createDialog.cancel')}
            </Button>
            <Button onClick={handleCreateToken} disabled={isCreating}>
              {isCreating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t('settings:mcpTokens.createDialog.creating')}
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4 mr-2" />
                  {t('settings:mcpTokens.createDialog.create')}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Token Created Dialog */}
      <Dialog open={!!createdToken} onOpenChange={() => setCreatedToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-green-600">
              <Check className="h-5 w-5" />
              {t('settings:mcpTokens.createdDialog.title')}
            </DialogTitle>
            <DialogDescription>
              <span className="text-destructive font-medium">
                {t('settings:mcpTokens.createdDialog.warning')}
              </span>
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t('settings:mcpTokens.createdDialog.tokenName')}</Label>
              <div className="font-medium">{createdToken?.name}</div>
            </div>

            <div className="space-y-2">
              <Label>{t('settings:mcpTokens.createdDialog.apiToken')}</Label>
              <div className="flex items-center gap-2">
                <div className="flex-1 relative">
                  <Input
                    readOnly
                    type={showToken ? 'text' : 'password'}
                    value={createdToken?.token || ''}
                    className="pr-20 font-mono text-sm"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute right-1 top-1/2 -translate-y-1/2 h-7"
                    onClick={() => setShowToken(!showToken)}
                  >
                    {showToken ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                <Button onClick={handleCopyToken} variant={tokenCopied ? 'default' : 'secondary'}>
                  {tokenCopied ? (
                    <>
                      <Check className="h-4 w-4 mr-2" />
                      {t('settings:mcpTokens.createdDialog.copied')}
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4 mr-2" />
                      {t('settings:mcpTokens.createdDialog.copy')}
                    </>
                  )}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label>{t('settings:mcpTokens.createdDialog.scopes')}</Label>
              <div className="flex flex-wrap gap-1">
                {createdToken?.scopes.map((scope) => (
                  <Badge key={scope} variant="secondary">
                    {scope}
                  </Badge>
                ))}
              </div>
            </div>

            {createdToken?.expires_at && (
              <div className="space-y-2">
                <Label>{t('settings:mcpTokens.createdDialog.expires')}</Label>
                <div className="flex items-center gap-2 text-sm">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  {formatDate(createdToken.expires_at)}
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button onClick={() => setCreatedToken(null)}>{t('settings:mcpTokens.createdDialog.done')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revoke Confirmation Dialog */}
      <AlertDialog open={!!tokenToRevoke} onOpenChange={() => setTokenToRevoke(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              {t('settings:mcpTokens.revokeDialog.title')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings:mcpTokens.revokeDialog.description')} <strong>"{tokenToRevoke?.name}"</strong>?
              <br />
              <br />
              {t('settings:mcpTokens.revokeDialog.warning')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('settings:mcpTokens.revokeDialog.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeToken}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t('settings:mcpTokens.revokeDialog.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

