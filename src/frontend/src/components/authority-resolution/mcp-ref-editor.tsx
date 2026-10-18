import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import NativeSelect from '@/components/ui/native-select';
import { useApi } from '@/hooks/use-api';
import { Loader2, RefreshCw } from 'lucide-react';
import { InfoHint } from '@/components/authority-resolution/info-hint';
import type { McpServiceInfo, McpToolInfo, ResourceRefInput } from '@/types/authority-resolution';

interface Props {
  value: ResourceRefInput;
  onChange: (patch: Partial<ResourceRefInput>) => void;
}

const templateFor = (tool: McpToolInfo): Record<string, string> =>
  Object.fromEntries(Object.keys(tool.input_schema?.properties || {}).map((k) => [k, `{{ ${k} }}`]));

/** Server → tool → params/result-pointer cascade for an `mcp_tool` resource ref. */
export default function McpRefEditor({ value, onChange }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const { get } = useApi();
  const [schemas, setSchemas] = useState('');
  const [services, setServices] = useState<McpServiceInfo[]>([]);
  const [servicesLoading, setServicesLoading] = useState(false);
  // Tools are keyed by the service they were fetched for, so "loading" is derived.
  const [toolsFor, setToolsFor] = useState<{ service: string; tools: McpToolInfo[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [identity, setIdentity] = useState<'caller' | 'app_sp' | null>(null);
  const [paramsText, setParamsText] = useState(() => JSON.stringify(value.mcp_params ?? {}, null, 2));
  const [paramsError, setParamsError] = useState<string | null>(null);

  const fetchServices = async (extraSchemas: string) => {
    const qs = extraSchemas.trim() ? `?schemas=${encodeURIComponent(extraSchemas.trim())}` : '';
    return get<{ identity: 'caller' | 'app_sp'; services: McpServiceInfo[] }>(`/api/authority/mcp-services${qs}`);
  };

  const refreshServices = async () => {
    setServicesLoading(true);
    const { data, error: err } = await fetchServices(schemas);
    setServicesLoading(false);
    setError(err || null);
    if (!err) { setServices(data?.services || []); setIdentity(data?.identity ?? null); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data, error: err } = await fetchServices('');
      if (cancelled) return;
      setError(err || null);
      if (!err) { setServices(data?.services || []); setIdentity(data?.identity ?? null); }
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const serviceName = value.mcp_service_name;
  useEffect(() => {
    if (!serviceName) return;
    let cancelled = false;
    (async () => {
      const { data, error: err } = await get<{ identity: string; tools: McpToolInfo[] }>(
        `/api/authority/mcp-services/tools?service_name=${encodeURIComponent(serviceName)}`,
      );
      if (cancelled) return;
      setError(err || null);
      setToolsFor({ service: serviceName, tools: !err ? data?.tools || [] : [] });
    })();
    return () => { cancelled = true; };
  }, [serviceName, get]);

  const tools = toolsFor && toolsFor.service === serviceName ? toolsFor.tools : [];
  const toolsLoading = !!serviceName && toolsFor?.service !== serviceName;
  const selectedTool = tools.find((t) => t.name === value.mcp_tool_name);

  const setParams = (text: string) => {
    setParamsText(text);
    try {
      const parsed = text.trim() ? JSON.parse(text) : {};
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParamsError(t('mcp.params.errorNotObject'));
        return;
      }
      setParamsError(null);
      onChange({ mcp_params: parsed });
    } catch {
      setParamsError(t('mcp.params.errorInvalid'));
    }
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_auto] gap-2 items-end">
        <div className="space-y-1">
          <Label className="text-xs flex items-center gap-1.5">{t('mcp.extraSchemas.label')} <InfoHint>{t('mcp.extraSchemas.hint')}</InfoHint></Label>
          <Input value={schemas} onChange={(e) => setSchemas(e.target.value)} placeholder={t('mcp.extraSchemas.placeholder')} />
        </div>
        <Button variant="outline" size="sm" onClick={refreshServices} disabled={servicesLoading}>
          {servicesLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {servicesLoading ? (
          <Skeleton className="h-9 w-full" />
        ) : (
          <NativeSelect
            value={value.mcp_service_name || ''}
            onChange={(e) => onChange({ mcp_service_name: e.target.value || null, mcp_tool_name: null })}
          >
            <option value="">{t('mcp.services.selectLabel')}</option>
            {services.map((s) => (
              <option key={s.name} value={s.name}>{s.short_name}</option>
            ))}
            {value.mcp_service_name && !services.some((s) => s.name === value.mcp_service_name) && (
              <option value={value.mcp_service_name}>{value.mcp_service_name}</option>
            )}
          </NativeSelect>
        )}
        {toolsLoading ? (
          <Skeleton className="h-9 w-full" />
        ) : (
          <NativeSelect
            value={value.mcp_tool_name || ''}
            disabled={!value.mcp_service_name}
            onChange={(e) => {
              const tool = tools.find((t) => t.name === e.target.value);
              onChange({ mcp_tool_name: e.target.value || null });
              if (tool && !Object.keys(value.mcp_params || {}).length) {
                const tpl = templateFor(tool);
                setParamsText(JSON.stringify(tpl, null, 2));
                onChange({ mcp_tool_name: tool.name, mcp_params: tpl });
              }
            }}
          >
            <option value="">{t('mcp.tools.selectLabel')}</option>
            {tools.map((t) => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
            {value.mcp_tool_name && !tools.some((t) => t.name === value.mcp_tool_name) && (
              <option value={value.mcp_tool_name}>{value.mcp_tool_name}</option>
            )}
          </NativeSelect>
        )}
      </div>
      {selectedTool?.description && <p className="text-xs text-muted-foreground">{selectedTool.description}</p>}
      <div className="space-y-1">
        <Label className="text-xs flex items-center gap-1.5">
          {t('mcp.params.label')}
          <InfoHint><Trans i18nKey="mcp.params.hint" ns="authority-resolution" values={{ exampleActor: '{{ actor_identity }}', exampleMarket: '{{ ar.domain_context.market }}' }} shouldUnescape components={{ code: <code /> }} /></InfoHint>
        </Label>
        <Textarea value={paramsText} onChange={(e) => setParams(e.target.value)} rows={4} className="font-mono text-xs" />
        {paramsError && <p className="text-xs text-destructive">{paramsError}</p>}
      </div>
      <div className="space-y-1">
        <Label className="text-xs flex items-center gap-1.5">{t('mcp.resultPointer.label')} <InfoHint><Trans i18nKey="mcp.resultPointer.hint" ns="authority-resolution" components={{ code: <code /> }} /></InfoHint></Label>
        <Input
          value={value.mcp_result_pointer || ''}
          onChange={(e) => onChange({ mcp_result_pointer: e.target.value || null })}
          placeholder={t('mcp.resultPointer.placeholder')}
          className="font-mono text-xs"
        />
      </div>
      {identity === 'app_sp' && (
        <p className="text-xs text-amber-600">
          {t('editor.hints.mcpNoCallerToken')}
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
