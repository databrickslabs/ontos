import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { useDomains } from '@/hooks/use-domains';
import type { GateExemptions } from '@/types/process-workflow';

interface Option {
  id: string;
  name: string;
}

/** The ``{id, name}`` items of a list response (a plain array or ``{items: [...]}``). Pure. */
export function toOptions(data: unknown): Option[] {
  const rows = Array.isArray(data)
    ? data
    : Array.isArray((data as { items?: unknown[] } | null)?.items)
      ? (data as { items: unknown[] }).items
      : [];
  return rows
    .map((row) => row as { id?: unknown; name?: unknown })
    .filter((row) => typeof row.id === 'string')
    .map((row) => ({ id: row.id as string, name: typeof row.name === 'string' && row.name ? row.name : (row.id as string) }));
}

export const EMPTY_GATE_EXEMPTIONS: GateExemptions = { domains: [], data_products: [], data_contracts: [] };

/**
 * The selected ids that are not in their loaded list (the entity was deleted),
 * so the save would be refused. A list that didn't load (``null``) counts none. Pure.
 */
export function missingExemptionIds(
  value: GateExemptions,
  lists: { domains: Option[] | null; data_products: Option[] | null; data_contracts: Option[] | null },
): string[] {
  return (['domains', 'data_products', 'data_contracts'] as const).flatMap((kind) => {
    const options = lists[kind];
    if (!options) return [];
    return value[kind].filter((id) => !options.some((o) => o.id === id));
  });
}

/** The ``{id, name}`` items of ``url``; ``null`` until loaded, or when the list can't be read. */
function useEntityOptions(url: string): Option[] | null {
  const [options, setOptions] = useState<Option[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((data) => {
        if (!cancelled) setOptions(toOptions(data));
      })
      .catch(() => {
        if (!cancelled) setOptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return options;
}

interface PickerProps {
  id: string;
  label: string;
  options: Option[] | null;
  value: string[];
  onChange: (ids: string[]) => void;
}

function Picker({ id, label, options, value, onChange }: PickerProps) {
  const { t } = useTranslation('workflows');
  const [open, setOpen] = useState(false);
  // Once the list is loaded, an id that isn't in it is an entity that was deleted
  const isMissing = (optionId: string) => !!options && !options.some((o) => o.id === optionId);
  const nameOf = (optionId: string) => {
    const name = options?.find((o) => o.id === optionId)?.name;
    if (name) return name;
    if (!isMissing(optionId)) return optionId;
    // Short enough that the "no longer exists" part stays visible
    const shortId = optionId.length > 12 ? `${optionId.slice(0, 8)}…` : optionId;
    return t('designer.triggerConfig.disabledFor.notFound', { id: shortId });
  };
  const toggle = (optionId: string) =>
    onChange(value.includes(optionId) ? value.filter((v) => v !== optionId) : [...value, optionId]);

  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1" data-testid={`${id}-selected`}>
          {value.map((optionId) => (
            <Badge
              key={optionId}
              variant={isMissing(optionId) ? 'destructive' : 'secondary'}
              className="flex items-center gap-1"
              title={isMissing(optionId) ? optionId : undefined}
            >
              <span className={isMissing(optionId) ? undefined : 'truncate max-w-[12rem]'}>{nameOf(optionId)}</span>
              <button
                type="button"
                onClick={() => toggle(optionId)}
                aria-label={t('designer.triggerConfig.disabledFor.remove', { name: nameOf(optionId) })}
                className="focus:outline-none"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button id={id} variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between">
            <span className="truncate text-muted-foreground">
              {value.length > 0
                ? t('designer.triggerConfig.disabledFor.selectedCount', { count: value.length })
                : t('designer.triggerConfig.disabledFor.none')}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-full p-0 pointer-events-auto" align="start">
          <Command>
            <CommandInput placeholder={t('designer.triggerConfig.disabledFor.search')} />
            <CommandList>
              <CommandEmpty>{t('designer.triggerConfig.disabledFor.noResults')}</CommandEmpty>
              <CommandGroup>
                {(options ?? []).map((option) => (
                  <CommandItem key={option.id} value={`${option.name} ${option.id}`} onSelect={() => toggle(option.id)}>
                    <Check className={cn('mr-2 h-4 w-4', value.includes(option.id) ? 'opacity-100' : 'opacity-0')} />
                    {option.name}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}

interface GateExemptionsFieldProps {
  value: GateExemptions;
  onChange: (value: GateExemptions) => void;
  /** The selected ids whose entity no longer exists (the backend refuses to save them). */
  onMissingChange?: (ids: string[]) => void;
}

/** Domains, data products and data contracts a before_status_change gate is switched off for. */
export default function GateExemptionsField({ value, onChange, onMissingChange }: GateExemptionsFieldProps) {
  const { t } = useTranslation('workflows');
  const { domains, loading: domainsLoading, error: domainsError } = useDomains();
  const products = useEntityOptions('/api/data-products');
  const contracts = useEntityOptions('/api/data-contracts');
  const domainOptions = domainsLoading || domainsError
    ? null
    : domains.map((d) => ({ id: d.id, name: d.name || d.id }));
  const missing = missingExemptionIds(value, {
    domains: domainOptions, data_products: products, data_contracts: contracts,
  });
  const missingKey = missing.join('\n');
  useEffect(() => {
    onMissingChange?.(missingKey ? missingKey.split('\n') : []);
  }, [missingKey, onMissingChange]);

  return (
    <div className="space-y-2 rounded-md border p-3" data-testid="gate-exemptions">
      <div className="space-y-1">
        <Label>{t('designer.triggerConfig.disabledFor.title')}</Label>
        <p className="text-xs text-muted-foreground">{t('designer.triggerConfig.disabledFor.hint')}</p>
      </div>
      <Picker
        id="gate-disabled-domains"
        label={t('designer.triggerConfig.disabledFor.domains')}
        options={domainOptions}
        value={value.domains}
        onChange={(ids) => onChange({ ...value, domains: ids })}
      />
      <Picker
        id="gate-disabled-products"
        label={t('designer.triggerConfig.disabledFor.dataProducts')}
        options={products}
        value={value.data_products}
        onChange={(ids) => onChange({ ...value, data_products: ids })}
      />
      <Picker
        id="gate-disabled-contracts"
        label={t('designer.triggerConfig.disabledFor.dataContracts')}
        options={contracts}
        value={value.data_contracts}
        onChange={(ids) => onChange({ ...value, data_contracts: ids })}
      />
    </div>
  );
}
