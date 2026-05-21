/**
 * Unified picker for directory principals (users + groups).
 *
 * One component, two runtime modes -- selected automatically from
 * `useDirectoryStore().status`:
 *
 * - Configured: 2-char-debounced type-ahead against /api/directory/search
 *   with two-line result rows (display name + sub_label), plus a
 *   "Browse directory" dialog with type-filter chips.
 * - Unconfigured: plain manual entry. Enter / Tab / comma turns the
 *   typed value into a badge; clicking the badge reverts it to text.
 *
 * Pre-existing values render as plain badges with no error
 * decoration in either mode, satisfying the plan's
 * graceful-degradation rule.
 *
 * Component API: discriminated on `multiple` so callers get
 * `string | null` or `string[]` typed correctly without casts.
 */

import {
  KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Loader2, Search, Users, User, UserSquare, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useDirectoryStore } from '@/stores/directory-store';
import type { Principal, PrincipalType } from '@/types/directory';

// ----- props ------------------------------------------------------------------

type PrincipalKind = 'user' | 'group';

interface CommonProps {
  /** Which principal types to accept. Defaults to both. */
  accepts?: PrincipalKind[];
  /** Disables the entire control. */
  disabled?: boolean;
  /** Placeholder shown in the input when no selection exists. */
  placeholder?: string;
  /** Input id for label association. */
  id?: string;
  /** Optional aria-label when no surrounding <Label htmlFor=...> exists. */
  'aria-label'?: string;
  className?: string;
}

type SingleProps = CommonProps & {
  multiple?: false;
  value: string | null | undefined;
  onChange: (next: string | null) => void;
};

type MultiProps = CommonProps & {
  multiple: true;
  value: string[];
  onChange: (next: string[]) => void;
};

export type PrincipalPickerProps = SingleProps | MultiProps;

// ----- helpers ----------------------------------------------------------------

const DEFAULT_ACCEPTS: PrincipalKind[] = ['user', 'group'];

const ICON_FOR_TYPE: Record<PrincipalType, typeof User> = {
  user: User,
  group: Users,
  unknown: UserSquare,
};

function typeIcon(type: PrincipalType | undefined) {
  const Icon = ICON_FOR_TYPE[type ?? 'unknown'];
  return <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-hidden />;
}

/** Debounce a single value; returns the latest value after `delay` ms of quiet. */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

// ----- component --------------------------------------------------------------

export function PrincipalPicker(props: PrincipalPickerProps) {
  const {
    accepts = DEFAULT_ACCEPTS,
    disabled,
    placeholder,
    className,
    multiple,
  } = props as PrincipalPickerProps & { multiple?: boolean };
  const inputId = useId();

  const status = useDirectoryStore((s) => s.status);
  const loaded = useDirectoryStore((s) => s.loaded);
  const degraded = useDirectoryStore((s) => s.degraded);
  const fetchStatus = useDirectoryStore((s) => s.fetchStatus);
  const markDegraded = useDirectoryStore((s) => s.markDegraded);

  useEffect(() => {
    if (!loaded) {
      void fetchStatus();
    }
  }, [loaded, fetchStatus]);

  // Internal map of id -> Principal populated by recent picks so newly-added
  // badges show the friendly display name with tooltip even though the
  // underlying value is just the id string. Pre-existing values are NOT
  // resolved against the directory -- they render as plain badges.
  const [resolved, setResolved] = useState<Record<string, Principal>>({});
  const remember = useCallback((p: Principal) => {
    setResolved((prev) => (prev[p.id] ? prev : { ...prev, [p.id]: p }));
  }, []);

  // Normalise value to an array for the internal selection list.
  // Wrapped in useMemo so the array identity is stable across renders
  // when the underlying value hasn't changed -- otherwise callbacks
  // that close over ``selectedIds`` would invalidate every render.
  const rawValue = (props as PrincipalPickerProps).value;
  const selectedIds: string[] = useMemo(
    () => {
      if (multiple) return (rawValue as string[] | undefined) ?? [];
      const v = rawValue as string | null | undefined;
      return v ? [v] : [];
    },
    [multiple, rawValue],
  );

  const emit = useCallback(
    (next: string[]) => {
      if (multiple) {
        (props as MultiProps).onChange(next);
      } else {
        (props as SingleProps).onChange(next[0] ?? null);
      }
    },
    [multiple, props],
  );

  const addPrincipal = useCallback(
    (p: Principal) => {
      if (selectedIds.includes(p.id)) return;
      remember(p);
      emit(multiple ? [...selectedIds, p.id] : [p.id]);
    },
    [selectedIds, multiple, emit, remember],
  );

  const addManual = useCallback(
    (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed || selectedIds.includes(trimmed)) return;
      emit(multiple ? [...selectedIds, trimmed] : [trimmed]);
    },
    [selectedIds, multiple, emit],
  );

  const removeId = useCallback(
    (id: string) => {
      emit(selectedIds.filter((x) => x !== id));
    },
    [selectedIds, emit],
  );

  const configured = !!status?.configured && !degraded;

  // The dialog is only available in configured mode; we hoist its open
  // state up here so the trigger button can sit beside the input.
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <SelectionBadges
        ids={selectedIds}
        resolved={resolved}
        disabled={disabled}
        onRemove={removeId}
      />
      <div className="flex gap-1">
        {configured ? (
          <ConfiguredInput
            id={props.id ?? inputId}
            placeholder={placeholder}
            disabled={disabled}
            accepts={accepts}
            selectedIds={selectedIds}
            onPick={addPrincipal}
            onSearchFail={markDegraded}
            ariaLabel={props['aria-label']}
          />
        ) : (
          <ManualInput
            id={props.id ?? inputId}
            placeholder={placeholder}
            disabled={disabled}
            onAdd={addManual}
            ariaLabel={props['aria-label']}
          />
        )}
        {configured && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            disabled={disabled}
            onClick={() => setDialogOpen(true)}
            title="Browse directory"
            aria-label="Browse directory"
          >
            <Search className="h-4 w-4" />
          </Button>
        )}
      </div>
      {configured && (
        <PrincipalPickerDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          accepts={accepts}
          selectedIds={selectedIds}
          onPick={(p) => {
            addPrincipal(p);
            if (!multiple) setDialogOpen(false);
          }}
          onSearchFail={markDegraded}
        />
      )}
    </div>
  );
}

// ----- selection badges -------------------------------------------------------

interface SelectionBadgesProps {
  ids: string[];
  resolved: Record<string, Principal>;
  disabled?: boolean;
  onRemove: (id: string) => void;
}

function SelectionBadges({ ids, resolved, disabled, onRemove }: SelectionBadgesProps) {
  if (ids.length === 0) return null;
  return (
    <TooltipProvider>
      <div className="flex flex-wrap gap-1.5">
        {ids.map((id) => {
          const p = resolved[id];
          const displayName = p?.display_name ?? id;
          // Tooltip exposes the sub_label so users can confirm the
          // underlying email / GUID. Falls back to the id itself for
          // pre-existing values where we have no resolved Principal.
          const tooltip = p?.sub_label ?? id;
          const Icon = ICON_FOR_TYPE[p?.type ?? 'unknown'];
          return (
            <Tooltip key={id} delayDuration={200}>
              <TooltipTrigger asChild>
                <Badge
                  variant="secondary"
                  className="gap-1 pl-1.5 pr-1 font-normal"
                  title={tooltip}
                  data-testid="principal-badge"
                >
                  <Icon className="h-3 w-3 text-muted-foreground" aria-hidden />
                  <span className="truncate max-w-[16rem]">{displayName}</span>
                  {!disabled && (
                    <button
                      type="button"
                      onClick={() => onRemove(id)}
                      className="ml-0.5 rounded-sm opacity-70 hover:opacity-100 focus:outline-none focus:ring-1 focus:ring-ring"
                      aria-label={`Remove ${displayName}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <span className="text-xs">{tooltip}</span>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

// ----- configured-mode inline type-ahead --------------------------------------

interface ConfiguredInputProps {
  id: string;
  placeholder?: string;
  disabled?: boolean;
  accepts: PrincipalKind[];
  selectedIds: string[];
  onPick: (p: Principal) => void;
  onSearchFail: () => void;
  ariaLabel?: string;
}

function ConfiguredInput({
  id,
  placeholder,
  disabled,
  accepts,
  selectedIds,
  onPick,
  onSearchFail,
  ariaLabel,
}: ConfiguredInputProps) {
  const [query, setQuery] = useState('');
  // ``userClosed`` lets the user dismiss the dropdown (Esc / click
  // outside) without us re-opening it on the next render. It's
  // cleared whenever the query changes so a new keystroke re-opens
  // the dropdown.
  const [userClosed, setUserClosed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debouncedQuery = useDebouncedValue(query, 250);
  const { results, loading } = usePrincipalSearch({
    query: debouncedQuery,
    accepts,
    enabled: !disabled,
    onError: onSearchFail,
  });

  const visible = useMemo(
    () => results.filter((p) => !selectedIds.includes(p.id)),
    [results, selectedIds],
  );

  // Derived open state -- no effect needed. Once the debounced query
  // is long enough and we have unfiltered matches, the popover opens;
  // anything else hides it.
  const popoverOpen =
    !userClosed && debouncedQuery.trim().length >= 2 && visible.length > 0;

  return (
    <Popover
      open={popoverOpen}
      onOpenChange={(next) => {
        if (!next) setUserClosed(true);
      }}
    >
      <PopoverTrigger asChild>
        <Input
          id={id}
          ref={inputRef}
          type="text"
          autoComplete="off"
          value={query}
          disabled={disabled}
          placeholder={placeholder ?? 'Search directory…'}
          aria-label={ariaLabel}
          onChange={(e) => {
            setQuery(e.target.value);
            // Any new keystroke is a fresh user intent to see results.
            if (userClosed) setUserClosed(false);
          }}
          data-testid="principal-picker-input"
        />
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-1"
        align="start"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {loading ? (
          <div className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Searching…
          </div>
        ) : visible.length === 0 ? (
          <div className="px-2 py-2 text-sm text-muted-foreground">No matches.</div>
        ) : (
          <ul className="flex flex-col">
            {visible.map((p) => (
              <PrincipalRow
                key={`${p.type}:${p.id}`}
                principal={p}
                onPick={() => {
                  onPick(p);
                  setQuery('');
                  setUserClosed(false);
                  inputRef.current?.focus();
                }}
              />
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

// ----- unconfigured-mode manual input -----------------------------------------

interface ManualInputProps {
  id: string;
  placeholder?: string;
  disabled?: boolean;
  onAdd: (raw: string) => void;
  ariaLabel?: string;
}

function ManualInput({ id, placeholder, disabled, onAdd, ariaLabel }: ManualInputProps) {
  const [value, setValue] = useState('');

  const commit = () => {
    if (value.trim().length === 0) return;
    onAdd(value);
    setValue('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === 'Tab' || e.key === ',') {
      if (value.trim().length === 0) return;
      e.preventDefault();
      commit();
    }
  };

  return (
    <Input
      id={id}
      type="text"
      autoComplete="off"
      value={value}
      disabled={disabled}
      placeholder={placeholder ?? 'Type and press Enter…'}
      aria-label={ariaLabel}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={onKeyDown}
      onBlur={commit}
      data-testid="principal-picker-input"
    />
  );
}

// ----- shared row -------------------------------------------------------------

interface PrincipalRowProps {
  principal: Principal;
  onPick: () => void;
}

function PrincipalRow({ principal, onPick }: PrincipalRowProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-sm text-left hover:bg-accent focus:bg-accent focus:outline-none"
        data-testid="principal-row"
      >
        {typeIcon(principal.type)}
        <div className="flex flex-col min-w-0">
          <span className="truncate text-sm font-medium">{principal.display_name}</span>
          {principal.sub_label && (
            <span className="truncate text-xs text-muted-foreground">{principal.sub_label}</span>
          )}
        </div>
      </button>
    </li>
  );
}

// ----- popup dialog variant ---------------------------------------------------

interface PrincipalPickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accepts: PrincipalKind[];
  selectedIds: string[];
  onPick: (p: Principal) => void;
  onSearchFail: () => void;
}

function PrincipalPickerDialog({
  open,
  onOpenChange,
  accepts,
  selectedIds,
  onPick,
  onSearchFail,
}: PrincipalPickerDialogProps) {
  const [filter, setFilter] = useState<PrincipalKind[]>(accepts);
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query, 250);
  const { results, loading } = usePrincipalSearch({
    query: debouncedQuery,
    accepts: filter,
    enabled: open,
    onError: onSearchFail,
  });

  // Reset query and type filter whenever the dialog transitions to
  // closed. Done in the onOpenChange handler (not an effect) to keep
  // state writes out of effect bodies.
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setQuery('');
      setFilter(accepts);
    }
    onOpenChange(next);
  };

  const visible = results.filter((p) => !selectedIds.includes(p.id));

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Browse directory</DialogTitle>
          <DialogDescription>Search users and groups from the configured provider.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {accepts.length > 1 && (
            <div className="flex gap-2" role="group" aria-label="Filter by type">
              {accepts.map((kind) => {
                const active = filter.includes(kind);
                return (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => {
                      // Always keep at least one filter active so the
                      // user can't enter a state where no results are
                      // possible.
                      setFilter((prev) => {
                        const without = prev.filter((k) => k !== kind);
                        if (active && without.length > 0) return without;
                        if (!active) return [...prev, kind];
                        return prev;
                      });
                    }}
                    className={cn(
                      'px-2.5 py-1 rounded-full text-xs border',
                      active
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background text-foreground border-input',
                    )}
                    data-testid={`type-chip-${kind}`}
                  >
                    {kind === 'user' ? 'Users' : 'Groups'}
                  </button>
                );
              })}
            </div>
          )}
          <Input
            type="text"
            autoComplete="off"
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            data-testid="principal-picker-dialog-input"
          />
          <div className="max-h-72 overflow-y-auto rounded-md border">
            {loading ? (
              <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Searching…
              </div>
            ) : debouncedQuery.trim().length < 2 ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">
                Type at least 2 characters.
              </div>
            ) : visible.length === 0 ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">No matches.</div>
            ) : (
              <ul className="flex flex-col p-1">
                {visible.map((p) => (
                  <PrincipalRow
                    key={`${p.type}:${p.id}`}
                    principal={p}
                    onPick={() => onPick(p)}
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ----- search hook ------------------------------------------------------------

interface UsePrincipalSearchArgs {
  query: string;
  accepts: PrincipalKind[];
  enabled: boolean;
  onError: () => void;
}

function usePrincipalSearch({ query, accepts, enabled, onError }: UsePrincipalSearchArgs) {
  // ``fetched`` is the most recent result set we successfully loaded
  // from the server. We never clear it synchronously from the
  // effect; instead the returned ``results`` derive from ``fetched``
  // + the live query so consumers see an empty list whenever the
  // query is below the 2-char threshold without us having to call
  // setState in the effect body.
  const [fetched, setFetched] = useState<Principal[]>([]);
  const [loading, setLoading] = useState(false);
  const errorReported = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    const trimmed = query.trim();
    if (trimmed.length < 2) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      q: trimmed,
      types: accepts.join(','),
      limit: '20',
    });
    // setState wrapped in an inner async function to keep the
    // effect body free of synchronous state writes (matches the
    // pattern used elsewhere in this repo and satisfies the
    // react-hooks/set-state-in-effect rule).
    const run = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/directory/search?${params.toString()}`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { results: Principal[] };
        if (!controller.signal.aborted) {
          setFetched(Array.isArray(body.results) ? body.results : []);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setFetched([]);
        if (!errorReported.current) {
          errorReported.current = true;
          console.warn('[PrincipalPicker] directory search failed, falling back to manual entry', err);
          onError();
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void run();
    return () => controller.abort();
  }, [query, accepts.join(','), enabled, onError]); // eslint-disable-line react-hooks/exhaustive-deps

  // Derived: hide any stale ``fetched`` while the live query is below
  // the threshold. Avoids clearing state inside the effect.
  const trimmedNow = query.trim();
  const results = trimmedNow.length < 2 ? [] : fetched;
  return { results, loading };
}

export default PrincipalPicker;
