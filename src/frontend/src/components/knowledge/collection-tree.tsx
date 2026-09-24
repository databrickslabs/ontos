import React, { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  KnowledgeCollection,
  CollectionType,
} from '@/types/ontology';
import {
  ChevronRight,
  ChevronDown,
  FolderOpen,
  Folder,
  Book,
  Network,
  GitBranch,
  Lock,
  Pencil,
  Plus,
  MoreVertical,
  Import,
  Download,
  Trash2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface CollectionTreeProps {
  collections: KnowledgeCollection[];
  selectedCollection?: string;
  onSelectCollection: (collection: KnowledgeCollection) => void;
  onCreateCollection?: () => void;
  onEditCollection?: (collection: KnowledgeCollection) => void;
  onDeleteCollection?: (collection: KnowledgeCollection) => void;
  onImportToCollection?: (collection: KnowledgeCollection) => void;
  onExportCollection?: (collection: KnowledgeCollection) => void;
  canEdit?: boolean;
}

interface CollectionNodeProps {
  collection: KnowledgeCollection;
  level: number;
  selectedCollection?: string;
  onSelectCollection: (collection: KnowledgeCollection) => void;
  onEditCollection?: (collection: KnowledgeCollection) => void;
  onDeleteCollection?: (collection: KnowledgeCollection) => void;
  onImportToCollection?: (collection: KnowledgeCollection) => void;
  onExportCollection?: (collection: KnowledgeCollection) => void;
  canEdit?: boolean;
  expandedCollections: Set<string>;
  toggleExpand: (iri: string) => void;
}

const getCollectionIcon = (type: CollectionType, isExpanded: boolean) => {
  switch (type) {
    case 'glossary':
      return isExpanded ? <FolderOpen className="h-4 w-4 text-amber-500" /> : <Folder className="h-4 w-4 text-amber-500" />;
    case 'taxonomy':
      return <GitBranch className="h-4 w-4 text-emerald-500" />;
    case 'ontology':
      return <Network className="h-4 w-4 text-blue-500" />;
    default:
      return <Book className="h-4 w-4 text-gray-500" />;
  }
};

const CollectionNode: React.FC<CollectionNodeProps> = ({
  collection,
  level,
  selectedCollection,
  onSelectCollection,
  onEditCollection,
  onDeleteCollection,
  onImportToCollection,
  onExportCollection,
  canEdit,
  expandedCollections,
  toggleExpand,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const isExpanded = expandedCollections.has(collection.iri);
  const isSelected = selectedCollection === collection.iri;
  const hasChildren = collection.child_collections && collection.child_collections.length > 0;

  const handleClick = () => {
    onSelectCollection(collection);
    if (hasChildren) {
      toggleExpand(collection.iri);
    }
  };

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer group",
          "hover:bg-accent hover:text-accent-foreground transition-colors",
          isSelected && "bg-accent text-accent-foreground"
        )}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={handleClick}
      >
        {/* Expand/Collapse button */}
        <div className="flex items-center w-5 justify-center">
          {hasChildren && (
            <button
              className="p-0.5 hover:bg-muted rounded"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand(collection.iri);
              }}
            >
              {isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
          )}
        </div>

        {/* Collection Icon */}
        {getCollectionIcon(collection.collection_type, isExpanded)}

        {/* Label and badges */}
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="truncate text-sm font-medium">
            {collection.label}
          </span>
          
          {/* Editable indicator */}
          {!collection.is_editable && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Lock className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p>{t('semantic-models:collectionTree.readOnly')}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}

          {/* Source type badge for imported */}
          {collection.source_type === 'imported' && (
            <Badge variant="outline" className="text-xs px-1 py-0">
              {t('semantic-models:badges.imported')}
            </Badge>
          )}

          {/* Concept count */}
          <Badge variant="secondary" className="text-xs px-1.5 py-0 ml-auto">
            {collection.concept_count}
          </Badge>
        </div>

        {/* Action menu */}
        {canEdit && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {collection.is_editable && onEditCollection && (
                <DropdownMenuItem onClick={() => onEditCollection(collection)}>
                  <Pencil className="h-4 w-4 mr-2" />
                  {t('common:actions.edit')}
                </DropdownMenuItem>
              )}
              {onExportCollection && (
                <DropdownMenuItem onClick={() => onExportCollection(collection)}>
                  <Download className="h-4 w-4 mr-2" />
                  {t('common:actions.export')}
                </DropdownMenuItem>
              )}
              {collection.is_editable && onImportToCollection && (
                <DropdownMenuItem onClick={() => onImportToCollection(collection)}>
                  <Import className="h-4 w-4 mr-2" />
                  {t('common:actions.import')}
                </DropdownMenuItem>
              )}
              {collection.is_editable && collection.source_type === 'custom' && onDeleteCollection && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => onDeleteCollection(collection)}
                    className="text-destructive"
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    {t('common:actions.delete')}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div>
          {collection.child_collections.map((child) => (
            <CollectionNode
              key={child.iri}
              collection={child}
              level={level + 1}
              selectedCollection={selectedCollection}
              onSelectCollection={onSelectCollection}
              onEditCollection={onEditCollection}
              onDeleteCollection={onDeleteCollection}
              onImportToCollection={onImportToCollection}
              onExportCollection={onExportCollection}
              canEdit={canEdit}
              expandedCollections={expandedCollections}
              toggleExpand={toggleExpand}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const CollectionTree: React.FC<CollectionTreeProps> = ({
  collections,
  selectedCollection,
  onSelectCollection,
  onCreateCollection,
  onEditCollection,
  onDeleteCollection,
  onImportToCollection,
  onExportCollection,
  canEdit = false,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const [expandedCollections, setExpandedCollections] = useState<Set<string>>(
    new Set(collections.map((c) => c.iri)) // Start with all expanded
  );

  const toggleExpand = useCallback((iri: string) => {
    setExpandedCollections((prev) => {
      const next = new Set(prev);
      if (next.has(iri)) {
        next.delete(iri);
      } else {
        next.add(iri);
      }
      return next;
    });
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* Header with Create button */}
      {canEdit && onCreateCollection && (
        <div className="flex items-center justify-between px-2 py-2 border-b">
          <span className="text-sm font-semibold text-muted-foreground">
            {t('semantic-models:collections.title')}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onCreateCollection}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Tree */}
      <div className="flex-1 overflow-auto py-2">
        {collections.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
            <Folder className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm">{t('semantic-models:collectionTree.noCollectionsYet')}</p>
            {canEdit && onCreateCollection && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={onCreateCollection}
              >
                <Plus className="h-4 w-4 mr-1" />
                {t('semantic-models:actions.createCollection')}
              </Button>
            )}
          </div>
        ) : (
          collections.map((collection) => (
            <CollectionNode
              key={collection.iri}
              collection={collection}
              level={0}
              selectedCollection={selectedCollection}
              onSelectCollection={onSelectCollection}
              onEditCollection={onEditCollection}
              onDeleteCollection={onDeleteCollection}
              onImportToCollection={onImportToCollection}
              onExportCollection={onExportCollection}
              canEdit={canEdit}
              expandedCollections={expandedCollections}
              toggleExpand={toggleExpand}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default CollectionTree;

