/**
 * Settings → Integrations → Directory.
 *
 * Configures the Directory abstraction (PRD #335). v1 ships three
 * concrete providers; the dropdown enables all three and the panel
 * below the provider Select switches to the provider-specific inputs
 * and help block on the fly. All Directory traffic flows through the
 * provider's transport of choice (UC HTTP Connection for Entra; the
 * app's own Lakebase DB for Lakebase; a local CSV for File) so the
 * app never holds a client secret.
 */

import { ReactNode, useEffect, useMemo, useState } from 'react';
import { Loader2, Plug2 } from 'lucide-react';

import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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

// Provider options enabled in v1. Adding a new one only requires
// extending this array and the form-state below; the manager picks
// the provider up via its registry on the backend.
const PROVIDER_OPTIONS: Array<{
  value: 'entra' | 'lakebase' | 'file';
  label: string;
}> = [
  { value: 'entra', label: 'Microsoft Entra ID' },
  { value: 'lakebase', label: 'Lakebase table' },
  { value: 'file', label: 'CSV file (test / demo)' },
];

const ENTRA_HELP_LINES = [
  ['Token URL', 'https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token'],
  ['Base URL', 'https://graph.microsoft.com'],
  ['Scope', 'https://graph.microsoft.com/.default'],
  ['Grant type', 'client_credentials'],
] as const;

const LAKEBASE_SCHEMA_SQL = `CREATE TABLE main.directory.principals (
  type         TEXT NOT NULL,           -- 'user' | 'group'
  id           TEXT NOT NULL,           -- UPN/email for users, displayName for groups
  display_name TEXT NOT NULL,
  sub_label    TEXT
);
CREATE INDEX ON main.directory.principals (LOWER(display_name));
CREATE INDEX ON main.directory.principals (LOWER(id));`;

const FILE_HELP_CSV = `type,id,display_name,sub_label
user,alice@example.com,Alice Liddell,alice@example.com
user,bob@example.com,Bob Builder,bob@example.com
group,Producers,Data Producers,producers-guid`;

export default function SettingsDirectoryView() {
  const { get, put, post } = useApi();
  const { toast } = useToast();
  const refreshStore = useDirectoryStore((s) => s.refresh);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  // Form state. Each provider only reads the field it cares about,
  // but we keep all three around so switching providers preserves
  // previously-entered values.
  const [providerType, setProviderType] = useState<string>('');
  const [connectionName, setConnectionName] = useState<string>('');
  const [lakebaseTable, setLakebaseTable] = useState<string>('');
  const [filePath, setFilePath] = useState<string>('');

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
        setLakebaseTable(statusRes.data.lakebase_table ?? '');
        setFilePath(statusRes.data.file_path ?? '');
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
    if (providerType !== (status?.provider_type ?? '')) return true;
    if (connectionName !== (status?.connection_name ?? '')) return true;
    if (lakebaseTable !== (status?.lakebase_table ?? '')) return true;
    if (filePath !== (status?.file_path ?? '')) return true;
    return false;
  }, [providerType, connectionName, lakebaseTable, filePath, status]);

  const canSave = !saving && dirty;
  const canTest = !!status?.configured && !testing && !dirty;

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: DirectorySettingsUpdate = {
        provider_type: providerType || null,
        connection_name: connectionName || null,
        lakebase_table: lakebaseTable || null,
        file_path: filePath || null,
      };
      const res = await put<DirectoryStatus>('/api/directory/settings', body);
      if (res.error) throw new Error(res.error);
      setStatus(res.data);
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
      const body: DirectorySettingsUpdate = {
        provider_type: null,
        connection_name: null,
        lakebase_table: null,
        file_path: null,
      };
      const res = await put<DirectoryStatus>('/api/directory/settings', body);
      if (res.error) throw new Error(res.error);
      setStatus(res.data);
      setProviderType('');
      setConnectionName('');
      setLakebaseTable('');
      setFilePath('');
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
      <SettingsPageWrapper title="Directory" permissionId="settings-directory">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </SettingsPageWrapper>
    );
  }

  const providerPanel: ReactNode = (() => {
    switch (providerType) {
      case 'entra':
        return (
          <EntraPanel
            connectionName={connectionName}
            setConnectionName={setConnectionName}
            saving={saving}
            connections={connections}
            connectionsLoading={connectionsLoading}
          />
        );
      case 'lakebase':
        return (
          <LakebasePanel
            lakebaseTable={lakebaseTable}
            setLakebaseTable={setLakebaseTable}
            saving={saving}
          />
        );
      case 'file':
        return (
          <FilePanel
            filePath={filePath}
            setFilePath={setFilePath}
            saving={saving}
          />
        );
      default:
        return null;
    }
  })();

  return (
    <SettingsPageWrapper title="Directory" permissionId="settings-directory">
      <div className="flex flex-col gap-6 max-w-2xl">
        <p className="text-sm text-muted-foreground">
          Connect a principal directory so users and groups can be picked
          throughout the app. v1 supports Microsoft Entra ID (via a UC HTTP
          Connection), a Postgres / Lakebase table, or a local CSV file for
          tests and demos.
        </p>

        <div className="grid gap-2">
          <Label htmlFor="directory-provider">Provider</Label>
          <Select value={providerType} onValueChange={setProviderType} disabled={saving}>
            <SelectTrigger id="directory-provider">
              <SelectValue placeholder="Select a provider…" />
            </SelectTrigger>
            <SelectContent>
              {PROVIDER_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {providerPanel}

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
            disabled={saving || (!status?.provider_type && !status?.connection_name && !status?.lakebase_table && !status?.file_path)}
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

// ----- per-provider panels ----------------------------------------------------

function EntraPanel({
  connectionName,
  setConnectionName,
  saving,
  connections,
  connectionsLoading,
}: {
  connectionName: string;
  setConnectionName: (v: string) => void;
  saving: boolean;
  connections: UcHttpConnection[];
  connectionsLoading: boolean;
}) {
  return (
    <>
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
    </>
  );
}

function LakebasePanel({
  lakebaseTable,
  setLakebaseTable,
  saving,
}: {
  lakebaseTable: string;
  setLakebaseTable: (v: string) => void;
  saving: boolean;
}) {
  return (
    <>
      <div className="grid gap-2">
        <Label htmlFor="directory-lakebase-table">Lakebase table</Label>
        <Input
          id="directory-lakebase-table"
          value={lakebaseTable}
          onChange={(e) => setLakebaseTable(e.target.value)}
          placeholder="catalog.schema.table"
          disabled={saving}
        />
        <p className="text-xs text-muted-foreground">
          Fully-qualified name of a Postgres table on the app&apos;s primary
          Lakebase database. Identifier segments must contain only letters,
          digits, and underscores.
        </p>
      </div>
      <Alert>
        <AlertTitle>Required schema</AlertTitle>
        <AlertDescription>
          <p className="text-sm">
            Populate this table from your IdP sync pipeline. Indexes on
            lower-cased columns are optional but recommended for snappy
            prefix search.
          </p>
          <pre className="mt-2 text-xs bg-muted/50 rounded-md p-2 overflow-x-auto">
            {LAKEBASE_SCHEMA_SQL}
          </pre>
        </AlertDescription>
      </Alert>
    </>
  );
}

function FilePanel({
  filePath,
  setFilePath,
  saving,
}: {
  filePath: string;
  setFilePath: (v: string) => void;
  saving: boolean;
}) {
  return (
    <>
      <div className="grid gap-2">
        <Label htmlFor="directory-file-path">CSV file path</Label>
        <Input
          id="directory-file-path"
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          placeholder="/etc/ontos/principals.csv"
          disabled={saving}
        />
        <p className="text-xs text-muted-foreground">
          Absolute path to a CSV file readable by the app process. Re-read
          automatically when the file&apos;s mtime advances; no restart needed.
        </p>
      </div>
      <Alert>
        <AlertTitle>CSV format</AlertTitle>
        <AlertDescription>
          <p className="text-sm">
            Required columns: <code>type</code>, <code>id</code>,
            {' '}<code>display_name</code>. The <code>sub_label</code> column
            is optional. <code>type</code> must be <code>user</code> or
            {' '}<code>group</code>.
          </p>
          <pre className="mt-2 text-xs bg-muted/50 rounded-md p-2 overflow-x-auto">
            {FILE_HELP_CSV}
          </pre>
        </AlertDescription>
      </Alert>
    </>
  );
}
