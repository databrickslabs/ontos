import React, { useState, useEffect } from 'react';
import { Check, ChevronsUpDown, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
// Input - unused
// import { Input } from '@/components/ui/input';
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

export interface TagSelectorProps {
  /** Currently selected tags */
  value: (string | AssignedTag)[];
  /** Callback when tags change */
  onChange: (tags: (string | AssignedTag)[]) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Whether the selector is disabled */
  disabled?: boolean;
  /** Maximum number of tags that can be selected */
  maxTags?: number;
  /** Allow creating new simple tags (FQN strings) */
  allowCreate?: boolean;
  /** Label for the selector */
  label?: string;
  /** Additional CSS classes */
  className?: string;
}

const TagSelector: React.FC<TagSelectorProps> = ({
  value,
  onChange,
  placeholder = 'Select tags...',
  disabled = false,
  maxTags,
  allowCreate = true,
  label,
  className,
}) => {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);
  const { get } = useApi();

  // Check if user has permission to create tags
  const { hasPermission } = usePermissions();
  const canCreateTags = hasPermission('tags', FeatureAccessLevel.READ_WRITE);
  const effectiveAllowCreate = allowCreate && canCreateTags;

  // Fetch available tags from backend
  useEffect(() => {
    const fetchTags = async () => {
      if (!open) return;

      setLoading(true);
      try {
        const response = await get<Tag[]>('/api/tags?limit=1000');
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
  }, [open, get]);

  // Get display value for a tag (available for future features)
  // const getTagDisplay = (tag: string | AssignedTag): string => {
  //   if (typeof tag === 'string') return tag;
  //   return tag.assigned_value ?
  //     `${tag.fully_qualified_name}: ${tag.assigned_value}` :
  //     tag.fully_qualified_name;
  // };

  // Get tag key for comparison
  const getTagKey = (tag: string | AssignedTag): string => {
    if (typeof tag === 'string') {
      return tag;
    }
    return tag.fully_qualified_name;
  };

  // Check if a tag is already selected
  const isTagSelected = (tagFqn: string): boolean => {
    return value.some(tag => getTagKey(tag) === tagFqn);
  };

  // Add a tag to selection
  const addTag = (tag: Tag | string) => {
    if (maxTags && value.length >= maxTags) return;

    if (typeof tag === 'string') {
      // Simple string tag (FQN)
      if (!isTagSelected(tag)) {
        onChange([...value, tag]);
      }
    } else {
      // Rich tag object - use fully_qualified_name for display and backend lookup
      if (!isTagSelected(tag.fully_qualified_name)) {
        onChange([...value, tag.fully_qualified_name]);
      }
    }

    setSearchValue('');
    setOpen(false);
  };

  // Remove a tag from selection
  const removeTag = (tagToRemove: string | AssignedTag) => {
    const keyToRemove = getTagKey(tagToRemove);
    onChange(value.filter(tag => getTagKey(tag) !== keyToRemove));
  };

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

      {/* Selected tags display */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 p-2 border rounded-md bg-background">
          {value.map((tag, index) => (
            <TagChip
              key={`${getTagKey(tag)}-${index}`}
              tag={tag}
              removable={!disabled}
              onRemove={removeTag}
              size="sm"
            />
          ))}
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
                {value.length === 1 ? '1 tag selected' : `${value.length} tags selected`}
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
              placeholder="Search tags..."
              value={searchValue}
              onValueChange={setSearchValue}
            />
            <div 
              className="max-h-60 overflow-y-auto"
              onWheel={(e) => e.stopPropagation()}
            >
              <CommandList>
                {loading ? (
                  <CommandEmpty>Loading tags...</CommandEmpty>
                ) : (
                  <>
                    {filteredTags.length === 0 && !effectiveAllowCreate && (
                      <CommandEmpty>No tags found.</CommandEmpty>
                    )}

                    {filteredTags.length === 0 && effectiveAllowCreate && searchValue && !exactMatch && (
                      <CommandGroup>
                        <CommandItem onSelect={handleCreateTag}>
                          <Plus className="mr-2 h-4 w-4" />
                          Create "{searchValue}"
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
                          Create "{searchValue}"
                        </CommandItem>
                      </CommandGroup>
                    )}
                  </>
                )}
              </CommandList>
            </div>
          </Command>
        </PopoverContent>
      </Popover>

      {maxTags && (
        <p className="text-sm text-muted-foreground">
          {value.length} of {maxTags} tags selected
        </p>
      )}
    </div>
  );
};

export default TagSelector;