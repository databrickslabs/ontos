import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, Plus } from 'lucide-react';
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
import TagChip, { AssignedTag } from './tag-chip';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';

// Available tag from the backend
interface Tag {
  id: string;
  name: string;
  namespace_name: string;
  fully_qualified_name: string;
  status: string;
  description?: string;
  possible_values?: string[];
}

// A tag as selected in the picker. `value` is set only when the user edits the
// value here: undefined makes the backend keep the stored value (#1420), '' clears it.
export interface TagSelection {
  fqn: string;
  value?: string;
  /** Value stored on the entity. Shown in the picker, never sent back unless edited. */
  storedValue?: string;
}

/** Selections from tags as loaded from the API (or FQN strings from older callers). */
export const toTagSelections = (tags: (string | AssignedTag)[] = []): TagSelection[] =>
  tags.map(tag =>
    typeof tag === 'string'
      ? { fqn: tag }
      : { fqn: tag.fully_qualified_name, storedValue: tag.assigned_value },
  );

/** Request payload for tags:set and entity create/update. Untouched tags carry no value. */
export type TagPayload = { tag_fqn: string; assigned_value?: string };

export const toTagPayload = (tags: TagSelection[]): TagPayload[] =>
  tags.map(tag =>
    tag.value === undefined
      ? { tag_fqn: tag.fqn }
      : { tag_fqn: tag.fqn, assigned_value: tag.value },
  );

// Radix Select cannot use '' as an item value.
const NO_VALUE = '__no_value__';

export interface TagSelectorProps {
  /** Currently selected tags */
  value: TagSelection[];
  /** Callback when tags change */
  onChange: (tags: TagSelection[]) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Whether the selector is disabled */
  disabled?: boolean;
  /** Maximum number of tags that can be selected */
  maxTags?: number;
  /** Allow creating new simple tags (FQN strings) */
  allowCreate?: boolean;
  /** Show a value editor per selected tag. Off where the stored tags carry no values. */
  editValues?: boolean;
  /** Label for the selector */
  label?: string;
  /** Additional CSS classes */
  className?: string;
}

const TagSelector: React.FC<TagSelectorProps> = ({
  value,
  onChange,
  placeholder,
  disabled = false,
  maxTags,
  allowCreate = true,
  editValues = true,
  label,
  className,
}) => {
  const { t } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);
  const { get } = useApi();

  // Escape should close only this popover, not the surrounding modal Dialog.
  // Radix's document-level Escape listeners (registered before this child mounts)
  // otherwise close both; a window capture-phase listener fires first, so we
  // intercept Escape while open, close the popover, and stop the event. Mirrors
  // the DomainMultiSelector fix.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopImmediatePropagation();
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open]);

  // Check if user has permission to create tags
  const { hasPermission } = usePermissions();
  const canCreateTags = hasPermission('tags', FeatureAccessLevel.READ_WRITE);
  const effectiveAllowCreate = allowCreate && canCreateTags;

  // Fetch available tags from backend. Closed, it still loads them when tags are
  // selected and value editors are shown: they need each tag's possible_values.
  const needsDefinitions = editValues && value.length > 0;
  useEffect(() => {
    const fetchTags = async () => {
      if (!open && !needsDefinitions) return;

      setLoading(true);
      try {
        const response = await get<Tag[]>('/api/tags');
        if (response.data) {
          setAvailableTags(response.data);
        }
      } catch (error) {
        console.error('Failed to fetch tags:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTags();
  }, [open, needsDefinitions, get]);

  // Get display value for a tag (available for future features)
  // const getTagDisplay = (tag: string | AssignedTag): string => {
  //   if (typeof tag === 'string') return tag;
  //   return tag.assigned_value ?
  //     `${tag.fully_qualified_name}: ${tag.assigned_value}` :
  //     tag.fully_qualified_name;
  // };

  // Check if a tag is already selected
  const isTagSelected = (tagFqn: string): boolean => {
    return value.some(tag => tag.fqn === tagFqn);
  };

  // Add a tag to selection (its value starts out untouched)
  const addTag = (tag: Tag | string) => {
    if (maxTags && value.length >= maxTags) return;

    const fqn = typeof tag === 'string' ? tag : tag.fully_qualified_name;
    if (!isTagSelected(fqn)) {
      onChange([...value, { fqn }]);
    }

    setSearchValue('');
    setOpen(false);
  };

  // Remove a tag from selection
  const removeTag = (fqn: string) => {
    onChange(value.filter(tag => tag.fqn !== fqn));
  };

  // Set the value of a selected tag. This marks it as edited.
  const setTagValue = (fqn: string, next: string) => {
    onChange(value.map(tag => (tag.fqn === fqn ? { ...tag, value: next } : tag)));
  };

  // Tag definition for a selected tag, when loaded (carries possible_values)
  const definitionFor = (fqn: string): Tag | undefined =>
    availableTags.find(tag => tag.fully_qualified_name === fqn);

  // Handle creating a new tag (simple string)
  const handleCreateTag = () => {
    if (!effectiveAllowCreate || !searchValue.trim()) return;

    const newTag = searchValue.trim();
    if (!isTagSelected(newTag)) {
      addTag(newTag);
    }
  };

  // Filter available tags based on search
  const filteredTags = availableTags.filter(tag =>
    (tag.fully_qualified_name?.toLowerCase() || '').includes(searchValue.toLowerCase()) ||
    (tag.name?.toLowerCase() || '').includes(searchValue.toLowerCase()) ||
    (tag.namespace_name?.toLowerCase() || '').includes(searchValue.toLowerCase())
  );

  // Check if search value matches any existing tag
  const exactMatch = filteredTags.some(tag =>
    tag.fully_qualified_name?.toLowerCase() === searchValue.toLowerCase()
  );

  return (
    <div className={cn('space-y-2', className)}>
      {label && <Label>{label}</Label>}

      {/* Selected tags display, each with its value: a select when the tag has
          possible_values, free text otherwise */}
      {value.length > 0 && (
        <div className="flex flex-col gap-2 p-2 border rounded-md bg-background">
          {value.map((tag, index) => {
            const possibleValues = definitionFor(tag.fqn)?.possible_values ?? [];
            const current = tag.value ?? tag.storedValue ?? '';
            const valueLabel = t('common:tagSelector.valueLabel');
            return (
              <div key={`${tag.fqn}-${index}`} className="flex flex-wrap items-center gap-2">
                <TagChip
                  tag={tag.fqn}
                  removable={!disabled}
                  onRemove={() => removeTag(tag.fqn)}
                  size="sm"
                />
                {editValues && (possibleValues.length > 0 ? (
                  <Select
                    value={current || NO_VALUE}
                    onValueChange={next => setTagValue(tag.fqn, next === NO_VALUE ? '' : next)}
                    disabled={disabled}
                  >
                    <SelectTrigger className="h-7 w-48 text-xs" aria-label={valueLabel}>
                      <SelectValue placeholder={t('common:tagSelector.noValue')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_VALUE}>{t('common:tagSelector.noValue')}</SelectItem>
                      {(current && !possibleValues.includes(current) ? [...possibleValues, current] : possibleValues).map(option => (
                        <SelectItem key={option} value={option}>{option}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    className="h-7 w-48 text-xs"
                    aria-label={valueLabel}
                    placeholder={t('common:tagSelector.valuePlaceholder')}
                    value={current}
                    onChange={e => setTagValue(tag.fqn, e.target.value)}
                    disabled={disabled}
                  />
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* Tag selector */}
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
            disabled={disabled || (maxTags ? value.length >= maxTags : false)}
          >
            {value.length > 0 ? (
              <span className="truncate">
                {t('common:tagSelector.selectedCount', { count: value.length })}
              </span>
            ) : (
              placeholder ?? t('common:tagSelector.selectPlaceholder')
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        {/*
          pointer-events-auto is the real scroll fix: a modal Dialog sets
          `body { pointer-events: none }`, which cascades to this popover
          (portaled to <body>, a sibling of the dialog), making it click/wheel-
          through so the wheel scrolls the dialog behind it. Mirrors the
          DomainMultiSelector fix.
        */}
        <PopoverContent
          className="w-full p-0 pointer-events-auto"
          align="start"
          onKeyDown={(e) => {
            // Escape closes only this popover, not the surrounding modal Dialog.
            // Stop it before Radix's document-level Escape listeners fire and
            // close the popover manually. Mirrors the DomainMultiSelector fix.
            if (e.key === 'Escape' && open) {
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
            }
          }}
        >
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={t('common:tagSelector.searchPlaceholder')}
              value={searchValue}
              onValueChange={setSearchValue}
            />
            {/*
              Single scroll container (primitive supplies overflow-y-auto;
              max-h-60 caps height via twMerge). A wrapper <div> previously added
              a second, shorter scroller that clipped long lists.
              onWheel stopPropagation is REQUIRED: the modal Dialog's body-level
              wheel scroll-lock would otherwise preventDefault the bubbled event
              (this popover is portaled to <body>) and cancel the list's scroll.
              overscroll-contain stops chaining at the edges. (Interactivity —
              pointer-events-auto — is on PopoverContent above.) Mirrors the
              DomainMultiSelector fix.
            */}
            <CommandList
              className="max-h-60 overscroll-contain"
              onWheel={(e) => e.stopPropagation()}
            >
                {loading ? (
                  <CommandEmpty>{t('common:states.loadingTags')}</CommandEmpty>
                ) : (
                  <>
                    {filteredTags.length === 0 && !effectiveAllowCreate && (
                      <CommandEmpty>{t('common:states.noTagsFound')}</CommandEmpty>
                    )}

                    {filteredTags.length === 0 && effectiveAllowCreate && searchValue && !exactMatch && (
                      <CommandGroup>
                        <CommandItem onSelect={handleCreateTag}>
                          <Plus className="mr-2 h-4 w-4" />
                          {t('common:tagSelector.create', { value: searchValue })}
                        </CommandItem>
                      </CommandGroup>
                    )}

                    {filteredTags.length > 0 && (
                      <CommandGroup>
                        {filteredTags.map((tag) => (
                          <CommandItem
                            key={tag.id}
                            value={tag.fully_qualified_name}
                            onSelect={() => addTag(tag)}
                            disabled={isTagSelected(tag.fully_qualified_name)}
                          >
                            <Check
                              className={cn(
                                'mr-2 h-4 w-4',
                                isTagSelected(tag.fully_qualified_name) ? 'opacity-100' : 'opacity-0'
                              )}
                            />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="font-medium truncate">{tag.fully_qualified_name}</span>
                                <Badge variant="secondary" className="text-xs">
                                  {tag.status}
                                </Badge>
                              </div>
                              {tag.description && (
                                <div className="text-sm text-muted-foreground truncate">
                                  {tag.description}
                                </div>
                              )}
                            </div>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    )}

                    {effectiveAllowCreate && searchValue && !exactMatch && filteredTags.length > 0 && (
                      <CommandGroup>
                        <CommandItem onSelect={handleCreateTag}>
                          <Plus className="mr-2 h-4 w-4" />
                          {t('common:tagSelector.create', { value: searchValue })}
                        </CommandItem>
                      </CommandGroup>
                    )}
                  </>
                )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {maxTags && (
        <p className="text-sm text-muted-foreground">
          {t('common:tagSelector.selectedOfMax', { count: value.length, max: maxTags })}
        </p>
      )}
    </div>
  );
};

export default TagSelector;