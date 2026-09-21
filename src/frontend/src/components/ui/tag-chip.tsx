import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { X, Info } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useAppSettingsStore } from '@/stores/app-settings-store';

// Type for rich tag object (matches backend AssignedTag)
export interface AssignedTag {
  tag_id: string;
  tag_name: string;
  namespace_id: string;
  namespace_name: string;
  status: 'active' | 'draft' | 'candidate' | 'deprecated' | 'inactive' | 'retired';
  fully_qualified_name: string;
  assigned_value?: string;
  assigned_by?: string;
  assigned_at: string;
}

export type TagDisplayFormat = 'short' | 'long';

export interface TagChipProps {
  /** Tag data - can be a simple string or rich AssignedTag object */
  tag: string | AssignedTag;
  /** Whether the tag can be removed */
  removable?: boolean;
  /** Callback when tag is removed */
  onRemove?: (tag: string | AssignedTag) => void;
  /** Additional CSS classes */
  className?: string;
  /** Size variant */
  size?: 'sm' | 'md' | 'lg';
  /** Color variant based on tag status or custom */
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'info';
  /** Whether clicking the tag opens search (default: true) */
  clickable?: boolean;
  /** Display format: 'short' shows only tag name, 'long' shows namespace/tagname */
  displayFormat?: TagDisplayFormat;
}

const getVariantFromStatus = (status?: string): 'default' | 'secondary' | 'destructive' | 'outline' | 'info' => {
  switch (status) {
    case 'active':
      return 'info'; // Light blue for active tags
    case 'deprecated':
    case 'retired':
    case 'inactive':
      return 'destructive';
    case 'draft':
    case 'candidate':
      return 'secondary';
    default:
      return 'info'; // Default to light blue for tags
  }
};

const getSizeClasses = (size: TagChipProps['size'] = 'md') => {
  switch (size) {
    case 'sm':
      return 'text-xs px-1.5 py-0.5';
    case 'lg':
      return 'text-base px-3 py-1.5';
    case 'md':
    default:
      return 'text-sm px-2 py-1';
  }
};

const TagChip: React.FC<TagChipProps> = ({
  tag,
  removable = false,
  onRemove,
  className,
  size = 'md',
  variant,
  clickable = true,
  displayFormat,
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation('common');
  const { tagDisplayFormat: globalFormat, fetchSettings } = useAppSettingsStore();
  
  // Fetch global settings on first render
  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);
  
  // Use explicit prop if provided, otherwise use global setting
  const effectiveDisplayFormat = displayFormat ?? globalFormat;
  
  const isRichTag = typeof tag === 'object';
  const tagName = isRichTag ? tag.tag_name : tag;
  
  // Determine display name based on format
  const getDisplayName = () => {
    if (isRichTag) {
      const baseName = effectiveDisplayFormat === 'long' ? tag.fully_qualified_name : tag.tag_name;
      return tag.assigned_value ? `${baseName}: ${tag.assigned_value}` : baseName;
    }
    return tag;
  };
  
  const displayName = getDisplayName();

  // Get the search query for the tag (fully qualified name for search)
  const getSearchQuery = () => {
    if (isRichTag) {
      return tag.fully_qualified_name;
    }
    return tag;
  };

  // Determine variant based on tag status if not explicitly provided
  const effectiveVariant = variant || (isRichTag ? getVariantFromStatus(tag.status) : 'info');

  const handleRemove = (e: React.MouseEvent) => {
    e.stopPropagation();
    onRemove?.(tag);
  };

  const handleClick = (e: React.MouseEvent) => {
    if (!clickable) return;
    e.stopPropagation();
    const searchQuery = encodeURIComponent(`tag:${getSearchQuery()}`);
    navigate(`/search/index?query=${searchQuery}`);
  };

  const chipContent = (
    <Badge
      variant={effectiveVariant}
      onClick={clickable ? handleClick : undefined}
      className={cn(
        'inline-flex items-center gap-1.5 font-medium',
        getSizeClasses(size),
        removable && 'pr-1',
        clickable && 'cursor-pointer hover:opacity-80 transition-opacity',
        className
      )}
    >
      <span className="truncate">{displayName}</span>

      {isRichTag && (
        <Info className="h-3 w-3 text-muted-foreground flex-shrink-0" />
      )}

      {removable && (
        <button
          onClick={handleRemove}
          className="flex-shrink-0 rounded-full p-0.5 hover:bg-background/20 transition-colors"
          aria-label={t('common:tagChip.removeAria', { name: tagName })}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </Badge>
  );

  // If it's a rich tag, wrap with tooltip to show metadata
  if (isRichTag) {
    return (
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          {chipContent}
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <div className="space-y-0.5">
            <div className="font-semibold text-xs mb-1">{tag.fully_qualified_name}</div>
            {tag.assigned_value && (
              <div className="text-xs"><span className="text-muted-foreground">{t('common:tagChip.value')}</span> {tag.assigned_value}</div>
            )}
            <div className="text-xs"><span className="text-muted-foreground">{t('common:tagChip.status')}</span> <span className="capitalize">{tag.status}</span></div>
            <div className="text-xs"><span className="text-muted-foreground">{t('common:tagChip.namespace')}</span> {tag.namespace_name}</div>
            {tag.assigned_by && (
              <div className="text-xs"><span className="text-muted-foreground">{t('common:tagChip.by')}</span> {tag.assigned_by}</div>
            )}
            <div className="text-xs text-muted-foreground">{new Date(tag.assigned_at).toLocaleDateString()}</div>
            {clickable && (
              <div className="text-xs text-primary mt-1">{t('common:tagChip.clickToSearch')}</div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    );
  }

  return chipContent;
};

export default TagChip;
