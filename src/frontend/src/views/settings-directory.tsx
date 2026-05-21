/**
 * Settings → Integrations → Directory.
 *
 * Configures the Directory abstraction (PRD #335). v1 ships one
 * concrete provider (Microsoft Entra ID via Microsoft Graph). The
 * provider Select renders future providers visible-but-disabled so
 * the abstraction is telegraphed to the user.
 *
 * All Graph traffic goes through a UC HTTP Connection so the app
 * never holds a client secret or token cache. The Test button hits
 * POST /api/directory/test which surfaces auth / connectivity errors.
 */

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Plug2 } from 'lucide-react';

import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useDirectoryStore } from '@/stores/directory-store';
import type {
  DirectorySettingsUpdate,
  DirectoryStatus,
  DirectoryTestResult,
  UcHttpConnection,
} from '@/types/directory';

// Provider options. Only `entra` is enabled in v1; the others render
// disabled so the abstraction is visible (matches the plan).
const PROVIDER_OPTIONS: Array<{
  value: string;
  label: string;
  disabled: boolean;
  helpKey?: string;
}> = [
  { value: 'entra', label: 'Microsoft Entra ID', disabled: false, helpKey: 'entra' },
  { value: 'okta', label: 'Okta (coming soon)', disabled: true },
  { value: 'ping', label: 'Ping (coming soon)', disabled: true },
];

const ENTRA_HELP_LINES = [
  ['Token URL', 'https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token'],
  ['Base URL', 'https://graph.microsoft.com'],
  ['Scope', 'https://graph.microsoft.com/.default'],
  ['Grant type', 'client_credentials'],
] as const;

export default function SettingsDirectoryView() {
  const { get, put, post } = useApi();
  const { toast } = useToast();
  const refreshStore = useDirectoryStore((s) => s.refresh);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [providerType, setProviderType] = useState<string>('');
  const [connectionName, setConnectionName] = useState<string>('');
  const [status, setStatus] = useState<DirectoryStatus | null>(null);
  const [connections, setConnections] = useState<UcHttpConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(false);

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [statusRes, connsRes] = await Promise.all([
        get<DirectoryStatus>('/api/directory/status'),
        (async () => {
          setConnectionsLoading(true);
          try {
            return await get<UcHttpConnection[]>('/api/directory/uc-http-connections');
          } finally {
            if (!cancelled) setConnectionsLoading(false);
          }
        })(),
      ]);
      if (cancelled) return;
      if (statusRes.data && !statusRes.error) {
        setStatus(statusRes.data);
        setProviderType(statusRes.data.provider_type ?? '');
        setConnectionName(statusRes.data.connection_name ?? '');
      }
      if (connsRes.data && Array.isArray(connsRes.data)) {
        setConnections(connsRes.data);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [get]);

  const dirty = useMemo(() => {
    const persistedProvider = status?.provider_type ?? '';
    const persistedConn = status?.connection_name ?? '';
    return providerType !== persistedProvider || connectionName !== persistedConn;
  }, [providerType, connectionName, status]);

  const canSave = !saving && dirty;
  const canTest = !!status?.configured && !testing && !dirty;

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: DirectorySettingsUpdate = {
        provider_type: providerType || null,
        connection_name: connectionName || null,
      };
      const res = await put<DirectoryStatus>('/api/directory/settings', body);
      if (res.error) throw new Error(res.error);
      setStatus(res.data);
      // Re-pull status into the shared store so existing pickers pick
      // up the change without a full page reload, and clear the
      // session-sticky degraded flag.
      await refreshStore();
      toast({ title: 'Directory settings saved' });
    } catch (err: any) {
      toast({
        variant: 'destructive',
        title: 'Failed to save',
        description: err.message ?? String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const res = await post<DirectoryTestResult>('/api/directory/test', {});
      if (res.error) throw new Error(res.error);
      if (res.data.healthy) {
        toast({ title: 'Directory test succeeded' });
      } else {
        toast({
          variant: 'destructive',
          title: 'Directory test failed',
          description: res.data.error ?? 'Unknown error',
        });
      }
    } catch (err: any) {
      toast({
        variant: 'destructive',
        title: 'Directory test failed',
        description: err.message ?? String(err),
      });
    } finally {
      setTesting(false);
    }
  };

  const handleClear = async () => {
    setSaving(true);
    try {
      const body: DirectorySettingsUpdate = { provider_type: null, connection_name: null };
      const res = await put<DirectoryStatus>('/api/directory/settings', body);
      if (res.error) throw new Error(res.error);
      setStatus(res.data);
      setProviderType('');
      setConnectionName('');
      await refreshStore();
      toast({ title: 'Directory settings cleared' });
    } catch (err: any) {
      toast({
        variant: 'destructive',
        title: 'Failed to clear',
        description: err.message ?? String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SettingsPageWrapper title="Directory">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </SettingsPageWrapper>
    );
  }

  return (
    <SettingsPageWrapper title="Directory">
      <div className="flex flex-col gap-6 max-w-2xl">
        <p className="text-sm text-muted-foreground">
          Connect an external identity provider so users and groups can be picked
          from a live directory. All traffic flows through a Unity Catalog HTTP
          Connection; the app never stores a client secret.
        </p>

        <div className="grid gap-2">
          <Label htmlFor="directory-provider">Provider</Label>
          <Select value={providerType} onValueChange={setProviderType} disabled={saving}>
            <SelectTrigger id="directory-provider">
              <SelectValue placeholder="Select a provider…" />
            </SelectTrigger>
            <SelectContent>
              {PROVIDER_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value} disabled={opt.disabled}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="directory-connection">UC HTTP Connection</Label>
          <Select
            value={connectionName}
            onValueChange={setConnectionName}
            disabled={saving || connectionsLoading || connections.length === 0}
          >
            <SelectTrigger id="directory-connection">
              <SelectValue
                placeholder={
                  connectionsLoading
                    ? 'Loading connections…'
                    : connections.length === 0
                    ? 'No HTTP connections found'
                    : 'Select a connection…'
                }
              />
            </SelectTrigger>
            <SelectContent>
              {connections.map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  <div className="flex items-center gap-2">
                    <Plug2 className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{c.name}</span>
                    {c.comment && (
                      <span className="text-xs text-muted-foreground">— {c.comment}</span>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {providerType === 'entra' && (
          <Alert>
            <AlertTitle>Entra ID connection setup</AlertTitle>
            <AlertDescription>
              <p className="mb-2 text-sm">
                Create a Unity Catalog HTTP connection against Microsoft Graph with
                client_credentials. The app&apos;s enterprise app must hold at least
                <code className="mx-1">User.Read.All</code> and
                <code className="mx-1">GroupMember.Read.All</code> (or
                <code className="mx-1">Group.Read.All</code>) application scopes.
              </p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                {ENTRA_HELP_LINES.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd>
                      <code>{v}</code>
                    </dd>
                  </div>
                ))}
              </dl>
            </AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={!canSave}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save
          </Button>
          <Button variant="outline" onClick={handleTest} disabled={!canTest}>
            {testing && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Test connection
          </Button>
          <Button
            variant="ghost"
            onClick={handleClear}
            disabled={saving || (!status?.provider_type && !status?.connection_name)}
          >
            Clear
          </Button>
        </div>

        {status && (
          <p className="text-xs text-muted-foreground">
            Status:{' '}
            {status.configured ? (
              <span className="text-foreground">Configured ({status.provider_type})</span>
            ) : (
              <span>Not configured</span>
            )}
          </p>
        )}
      </div>
    </SettingsPageWrapper>
  );
}
