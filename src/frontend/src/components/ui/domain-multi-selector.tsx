import React, { useState } from 'react';
import { Check, ChevronsUpDown, Star, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useDomains } from '@/hooks/use-domains';

/** The domain selection state emitted by the selector. */
export interface DomainSelection {
  domainIds: string[];
  primaryDomainId: string | null;
}

/**
 * Resolve the effective primary: the explicit primary if it is still selected,
 * otherwise the first selected domain (or null when nothing is selected).
 * Pure — exported for testing.
 */
export function resolveEffectivePrimary(value: string[], primaryDomainId: string | null | undefined): string | null {
  if (primaryDomainId && value.includes(primaryDomainId)) return primaryDomainId;
  return value[0] ?? null;
}

/** Add a domain (no-op if already present or over max); first added becomes primary. Pure. */
export function addDomainToSelection(
  value: string[],
  primaryDomainId: string | null | undefined,
  domainId: string,
  maxDomains?: number,
): DomainSelection {
  const effective = resolveEffectivePrimary(value, primaryDomainId);
  if (value.includes(domainId) || (maxDomains !== undefined && value.length >= maxDomains)) {
    return { domainIds: value, primaryDomainId: effective };
  }
  const domainIds = [...value, domainId];
  return { domainIds, primaryDomainId: effective ?? domainId };
}

/** Remove a domain; if it was primary, the first remaining becomes primary. Pure. */
export function removeDomainFromSelection(
  value: string[],
  primaryDomainId: string | null | undefined,
  domainId: string,
): DomainSelection {
  const effective = resolveEffectivePrimary(value, primaryDomainId);
  const domainIds = value.filter(id => id !== domainId);
  const nextPrimary = domainId === effective ? domainIds[0] ?? null : effective;
  return { domainIds, primaryDomainId: nextPrimary };
}

export interface DomainMultiSelectorProps {
  /** Currently selected domain IDs */
  value: string[];
  /** Which selected domain is the primary (feeds single-value integrations) */
  primaryDomainId?: string | null;
  /**
   * Callback when the selection or primary changes. Emits the full domain-ID list
   * and the primary domain ID (or null when nothing is selected).
   */
  onChange: (domainIds: string[], primaryDomainId: string | null) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Whether the selector is disabled */
  disabled?: boolean;
  /** Maximum number of domains that can be selected */
  maxDomains?: number;
  /** Label for the selector */
  label?: string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Multi-select for assigning one or more data domains to an entity, with exactly one
 * marked as *primary*. Mirrors the tag-selector UX; domains are read from the shared
 * `useDomains` cache (domains are created/managed elsewhere, so there is no "create").
 */
const DomainMultiSelector: React.FC<DomainMultiSelectorProps> = ({
  value,
  primaryDomainId,
  onChange,
  placeholder = 'Select domains...',
  disabled = false,
  maxDomains,
  label,
  className,
}) => {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const { domains, loading, getDomainName } = useDomains();

  // Resolve the effective primary: the explicit one if still selected, else the first.
  const effectivePrimary = resolveEffectivePrimary(value, primaryDomainId);

  const isSelected = (domainId: string): boolean => value.includes(domainId);

  const addDomain = (domainId: string) => {
    const next = addDomainToSelection(value, primaryDomainId, domainId, maxDomains);
    onChange(next.domainIds, next.primaryDomainId);
    setSearchValue('');
  };

  const removeDomain = (domainId: string) => {
    const next = removeDomainFromSelection(value, primaryDomainId, domainId);
    onChange(next.domainIds, next.primaryDomainId);
  };

  const setPrimary = (domainId: string) => {
    if (!isSelected(domainId)) return;
    onChange(value, domainId);
  };

  const filteredDomains = domains.filter(domain =>
    (domain.name?.toLowerCase() || '').includes(searchValue.toLowerCase())
  );

  return (
    <div className={cn('space-y-2', className)}>
      {label && <Label>{label}</Label>}

      {/* Selected domains display */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 p-2 border rounded-md bg-background">
          {value.map((domainId) => {
            const isPrimary = domainId === effectivePrimary;
            return (
              <Badge
                key={domainId}
                variant={isPrimary ? 'default' : 'secondary'}
                className="flex items-center gap-1"
              >
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => setPrimary(domainId)}
                    title={isPrimary ? 'Primary domain' : 'Set as primary domain'}
                    className="focus:outline-none"
                    aria-label={isPrimary ? 'Primary domain' : 'Set as primary domain'}
                  >
                    <Star className={cn('h-3 w-3', isPrimary ? 'fill-current' : 'opacity-40')} />
                  </button>
                )}
                <span className="truncate max-w-[12rem]">
                  {getDomainName(domainId) || domainId}
                </span>
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => removeDomain(domainId)}
                    title="Remove domain"
                    className="focus:outline-none"
                    aria-label="Remove domain"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </Badge>
            );
          })}
        </div>
      )}

      {/* Domain selector */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className={cn(
              'w-full justify-between',
              value.length === 0 && 'text-muted-foreground'
            )}
            disabled={disabled || (maxDomains ? value.length >= maxDomains : false)}
          >
            {value.length > 0 ? (
              <span className="truncate">
                {value.length === 1 ? '1 domain selected' : `${value.length} domains selected`}
              </span>
            ) : (
              placeholder
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-full p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Search domains..."
              value={searchValue}
              onValueChange={setSearchValue}
            />
            <div
              className="max-h-60 overflow-y-auto"
              onWheel={(e) => e.stopPropagation()}
            >
              <CommandList>
                {loading ? (
                  <CommandEmpty>Loading domains...</CommandEmpty>
                ) : filteredDomains.length === 0 ? (
                  <CommandEmpty>No domains found.</CommandEmpty>
                ) : (
                  <CommandGroup>
                    {filteredDomains.map((domain) => (
                      <CommandItem
                        key={domain.id}
                        value={domain.name}
                        onSelect={() => (isSelected(domain.id) ? removeDomain(domain.id) : addDomain(domain.id))}
                      >
                        <Check
                          className={cn(
                            'mr-2 h-4 w-4',
                            isSelected(domain.id) ? 'opacity-100' : 'opacity-0'
                          )}
                        />
                        <div className="flex-1 min-w-0">
                          <span className="font-medium truncate">{domain.name}</span>
                          {domain.description && (
                            <div className="text-sm text-muted-foreground truncate">
                              {domain.description}
                            </div>
                          )}
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
              </CommandList>
            </div>
          </Command>
        </PopoverContent>
      </Popover>

      {maxDomains && (
        <p className="text-sm text-muted-foreground">
          {value.length} of {maxDomains} domains selected
        </p>
      )}
    </div>
  );
};

export default DomainMultiSelector;
