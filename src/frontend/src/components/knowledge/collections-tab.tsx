import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import {
  FolderTree,
  Pencil,
  Trash2,
  Download,
  MoreHorizontal,
  Lock,
  BookOpen,
  GitBranch,
  Layers,
  Building2,
  Users,
  Briefcase,
  Globe,
  ChevronDown,
  ExternalLink,
} from 'lucide-react';
import { ColumnDef, Column } from "@tanstack/react-table";
import { DataTable } from '@/components/ui/data-table';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
import type { KnowledgeCollection, CollectionType, ScopeLevel } from '@/types/ontology';

interface CollectionsTabProps {
  collections: KnowledgeCollection[];
  selectedCollection: KnowledgeCollection | null;
  onSelectCollection: (collection: KnowledgeCollection | null) => void;
  onEditCollection: (collection: KnowledgeCollection) => void;
  onDeleteCollection: (collection: KnowledgeCollection) => void;
  onExportCollection: (collection: KnowledgeCollection, format: 'turtle' | 'rdfxml') => void;
  canEdit: boolean;
}

const typeIcons: Record<CollectionType, React.ReactNode> = {
  glossary: <BookOpen className="h-4 w-4" />,
  taxonomy: <GitBranch className="h-4 w-4" />,
  ontology: <Layers className="h-4 w-4" />,
};

const typeColors: Record<CollectionType, string> = {
  glossary: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  taxonomy: 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/30',
  ontology: 'bg-violet-500/20 text-violet-700 dark:text-violet-400 border-violet-500/30',
};

const scopeIcons: Record<ScopeLevel, React.ReactNode> = {
  enterprise: <Building2 className="h-4 w-4" />,
  domain: <Briefcase className="h-4 w-4" />,
  department: <Users className="h-4 w-4" />,
  team: <Users className="h-4 w-4" />,
  project: <FolderTree className="h-4 w-4" />,
  external: <Globe className="h-4 w-4" />,
};

const scopeDescriptions: Record<ScopeLevel, string> = {
  enterprise: 'Company-wide definitions used across all domains',
  domain: 'Business domain specific terms and definitions',
  department: 'Department level terminology',
  team: 'Team-specific vocabulary',
  project: 'Project-specific definitions',
  external: 'Imported or external vocabulary',
};

export const CollectionsTab: React.FC<CollectionsTabProps> = ({
  collections,
  selectedCollection,
  onSelectCollection,
  onEditCollection,
  onDeleteCollection,
  onExportCollection,
  canEdit,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);

  const columns: ColumnDef<KnowledgeCollection>[] = useMemo(() => [
    {
      accessorKey: 'label',
      header: ({ column }: { column: Column<KnowledgeCollection, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.name')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const collection = row.original;
        
        return (
          <div className="flex items-center gap-2">
            <div className="flex flex-col">
              <span className="font-medium">{collection.label || collection.iri}</span>
              {collection.description && (
                <span className="text-xs text-muted-foreground line-clamp-1">{collection.description}</span>
              )}
            </div>
            {!collection.is_editable && (
              <Lock className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'collection_type',
      header: ({ column }: { column: Column<KnowledgeCollection, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.type')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const type = row.original.collection_type as CollectionType;
        return (
          <Badge variant="outline" className={typeColors[type] || ''}>
            {t(`semantic-models:collections.${type}`) || type}
          </Badge>
        );
      },
    },
    {
      accessorKey: 'scope_level',
      header: ({ column }: { column: Column<KnowledgeCollection, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('semantic-models:fields.scope')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const scope = row.original.scope_level as ScopeLevel;
        const icon = scopeIcons[scope];
        const description = scopeDescriptions[scope];
        return (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-2 cursor-help">
                  {icon}
                  <span className="text-sm capitalize">{scope}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-sm">{description}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        );
      },
    },
    {
      accessorKey: 'concept_count',
      header: ({ column }: { column: Column<KnowledgeCollection, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('semantic-models:fields.concepts')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <Badge variant="secondary">
          {row.original.concept_count || 0}
        </Badge>
      ),
    },
    {
      accessorKey: 'source_type',
      header: t('semantic-models:fields.source'),
      cell: ({ row }) => {
        const sourceType = row.original.source_type;
        if (sourceType === 'imported') {
          return <Badge variant="outline">{t('semantic-models:badges.imported')}</Badge>;
        }
        return <Badge variant="outline">{t('semantic-models:badges.custom')}</Badge>;
      },
    },
    {
      id: 'actions',
      cell: ({ row }) => {
        const collection = row.original;
        
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
              <Button variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {canEdit && collection.is_editable && (
                <>
                  <DropdownMenuItem onClick={(e) => {
                    e.stopPropagation();
                    onEditCollection(collection);
                  }}>
                    <Pencil className="h-4 w-4 mr-2" />
                    {t('common:actions.edit')}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem onClick={(e) => {
                e.stopPropagation();
                onExportCollection(collection, 'turtle');
              }}>
                <Download className="h-4 w-4 mr-2" />
                {t('common:actions.exportTurtle')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={(e) => {
                e.stopPropagation();
                onExportCollection(collection, 'rdfxml');
              }}>
                <Download className="h-4 w-4 mr-2" />
                {t('common:actions.exportRdfXml')}
              </DropdownMenuItem>
              {canEdit && collection.is_editable && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteCollection(collection);
                    }}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    {t('common:actions.delete')}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ], [t, canEdit, onEditCollection, onExportCollection, onDeleteCollection]);
  
  return (
    <div className="h-full flex gap-4">
      {/* Table Section */}
      <div className={`flex-1 flex flex-col ${selectedCollection ? 'w-1/2' : 'w-full'}`}>
        <DataTable
          columns={columns}
          data={collections}
          searchColumn="label"
          storageKey="knowledge-collections-sort"
          onRowClick={(row) => onSelectCollection(
            selectedCollection?.iri === row.original.iri ? null : row.original
          )}
        />
      </div>

      {/* Detail Panel */}
      {selectedCollection && (
        <div className="w-1/2 border rounded-lg bg-background flex flex-col">
          {/* Header */}
          <div className="p-4 border-b">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${typeColors[selectedCollection.collection_type as CollectionType] || 'bg-muted'}`}>
                  {typeIcons[selectedCollection.collection_type as CollectionType] || <Layers className="h-5 w-5" />}
                </div>
                <div>
                  <h2 className="text-lg font-semibold">{selectedCollection.label}</h2>
                  <p className="text-sm text-muted-foreground">{selectedCollection.iri}</p>
                </div>
              </div>
              <div className="flex gap-2">
                {canEdit && selectedCollection.is_editable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onEditCollection(selectedCollection)}
                  >
                    <Pencil className="h-4 w-4 mr-2" />
                    {t('common:actions.edit')}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onSelectCollection(null)}
                >
                  ✕
                </Button>
              </div>
            </div>
          </div>

          {/* Content */}
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-6">
              {/* Description */}
              {selectedCollection.description && (
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('common:labels.description')}</h3>
                  <p className="text-sm text-muted-foreground">{selectedCollection.description}</p>
                </div>
              )}

              {/* Properties */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('common:labels.type')}</h3>
                  <Badge variant="outline" className={typeColors[selectedCollection.collection_type as CollectionType] || ''}>
                    {t(`semantic-models:collections.${selectedCollection.collection_type}`) || selectedCollection.collection_type}
                  </Badge>
                </div>
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.scope')}</h3>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-2 cursor-help">
                          {scopeIcons[selectedCollection.scope_level as ScopeLevel]}
                          <span className="text-sm capitalize">{selectedCollection.scope_level}</span>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="text-sm">{scopeDescriptions[selectedCollection.scope_level as ScopeLevel]}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.concepts')}</h3>
                  <Badge variant="secondary">{selectedCollection.concept_count || 0}</Badge>
                </div>
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.source')}</h3>
                  <Badge variant="outline">
                    {selectedCollection.source_type === 'imported' 
                      ? t('semantic-models:badges.imported') 
                      : t('semantic-models:badges.custom')}
                  </Badge>
                </div>
              </div>

              {/* Source URL */}
              {selectedCollection.source_url && (
                <div>
                  <h3 className="text-sm font-medium mb-2">{t('semantic-models:fields.sourceUrl')}</h3>
                  <a
                    href={selectedCollection.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-primary hover:underline flex items-center gap-1"
                  >
                    {selectedCollection.source_url}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}

              {/* Status */}
              <div>
                <h3 className="text-sm font-medium mb-2">{t('common:labels.status')}</h3>
                <div className="flex items-center gap-2">
                  <Badge variant={selectedCollection.status === 'active' ? 'default' : 'secondary'}>
                    {selectedCollection.status || 'active'}
                  </Badge>
                  {!selectedCollection.is_editable && (
                    <Badge variant="outline" className="text-muted-foreground">
                      <Lock className="h-3 w-3 mr-1" />
                      {t('semantic-models:badges.readonly')}
                    </Badge>
                  )}
                </div>
              </div>

              {/* Created Info */}
              {selectedCollection.created_at && (
                <div className="text-sm text-muted-foreground border-t pt-4">
                  <p>Created: {new Date(selectedCollection.created_at).toLocaleDateString()}</p>
                </div>
              )}

              {/* Metadata Panel */}
              <EntityMetadataPanel 
                entityType="collection" 
                entityId={selectedCollection.iri} 
              />
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
};
