import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  ChevronRight,
  ChevronDown,
  Filter,
  FolderTree,
  Zap,
  Languages,
  MoreHorizontal,
  List,
  ListTree,
  Share2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { systemRdfNamespaceDisplayLabel } from '@/lib/system-rdf-namespace-labels';
import type { OntologyConcept, KnowledgeCollection } from '@/types/ontology';
import type { GroupByDimension } from '@/stores/glossary-preferences-store';
import { getAvailableLanguages, getLanguageDisplayName } from '@/lib/ontology-utils';

function stripSourcePrefix(iri: string): string {
  const prefixes = ['urn:glossary:', 'urn:taxonomy:', 'urn:ontology:', 'urn:semantic-model:', 'urn:schema:'];
  for (const prefix of prefixes) {
    if (iri.startsWith(prefix)) {
      return iri.slice(prefix.length);
    }
  }
  return iri;
}

interface GlossaryFilterPanelProps {
  // Data for computing counts
  filteredConcepts: OntologyConcept[];
  sourceConceptCounts: Record<string, number>;
  // Source filtering
  availableSources: string[];
  hiddenSources: string[];
  onToggleSource: (source: string) => void;
  onSelectAllSources: () => void;
  onSelectNoneSources: (sources: string[]) => void;
  // Display options
  // The "Group by" lens re-organizes terms under dimension headers. This is a
  // LENS, not a second filter -- filtering stays driven by the source chips above.
  groupByDimension: GroupByDimension;
  onSetGroupByDimension: (dimension: GroupByDimension) => void;
  showProperties: boolean;
  onSetShowProperties: (enabled: boolean) => void;
  // Language selection
  selectedLanguage: string;
  onSetSelectedLanguage: (lang: string) => void;
  // Expansion state
  isFilterExpanded: boolean;
  onSetFilterExpanded: (expanded: boolean) => void;
  // Collections and callbacks for scheme actions (optional for read-only views)
  collections?: KnowledgeCollection[];
  onRenameScheme?: (collection: KnowledgeCollection) => void;
  onDeleteScheme?: (collection: KnowledgeCollection) => void;
}

type SortMode = 'name' | 'size';

export const GlossaryFilterPanel: React.FC<GlossaryFilterPanelProps> = ({
  filteredConcepts,
  sourceConceptCounts,
  availableSources,
  hiddenSources,
  onToggleSource,
  onSelectAllSources,
  onSelectNoneSources,
  groupByDimension,
  onSetGroupByDimension,
  showProperties,
  onSetShowProperties,
  selectedLanguage,
  onSetSelectedLanguage,
  isFilterExpanded,
  onSetFilterExpanded,
  collections,
  onRenameScheme,
  onDeleteScheme,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);

  // Local state for search and sorting
  const [searchText, setSearchText] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('name');
  const [deleteConfirmScheme, setDeleteConfirmScheme] = useState<KnowledgeCollection | null>(null);

  // Flatten collections tree and build a map: stripped source → collection
  const collectionsBySource = useMemo(() => {
    const map = new Map<string, KnowledgeCollection>();
    if (!collections) return map;
    const visit = (c: KnowledgeCollection) => {
      const strippedSource = stripSourcePrefix(c.iri);
      map.set(strippedSource, c);
      if (c.child_collections && c.child_collections.length > 0) {
        c.child_collections.forEach(visit);
      }
    };
    collections.forEach(visit);
    return map;
  }, [collections]);

  // Group sources by collection type (glossary/taxonomy/ontology/other)
  const sourcesByType = useMemo(() => {
    const groups: Record<string, string[]> = {
      glossary: [],
      taxonomy: [],
      ontology: [],
      other: [],
    };

    availableSources.forEach((source) => {
      const collection = collectionsBySource.get(source);
      if (collection) {
        const type = collection.collection_type;
        if (type === 'glossary' || type === 'taxonomy' || type === 'ontology') {
          groups[type].push(source);
        } else {
          groups.other.push(source);
        }
      } else {
        // Source with no collection record
        groups.other.push(source);
      }
    });

    return groups;
  }, [availableSources, collectionsBySource]);

  // Apply search filter to sources
  const filteredSourcesByType = useMemo(() => {
    const filtered: Record<string, string[]> = {};
    const searchLower = searchText.toLowerCase();

    Object.entries(sourcesByType).forEach(([type, sources]) => {
      filtered[type] = sources.filter((source) => {
        const collection = collectionsBySource.get(source);
        const label = collection?.label || systemRdfNamespaceDisplayLabel(source, t);
        return label.toLowerCase().includes(searchLower);
      });
    });

    return filtered;
  }, [sourcesByType, searchText, collectionsBySource, t]);

  // Sort sources within each type
  const sortedSourcesByType = useMemo(() => {
    const sorted: Record<string, string[]> = {};

    Object.entries(filteredSourcesByType).forEach(([type, sources]) => {
      const sorted_sources = [...sources];
      if (sortMode === 'name') {
        sorted_sources.sort((a, b) => {
          const aLabel = (collectionsBySource.get(a)?.label) || systemRdfNamespaceDisplayLabel(a, t);
          const bLabel = (collectionsBySource.get(b)?.label) || systemRdfNamespaceDisplayLabel(b, t);
          return aLabel.localeCompare(bLabel);
        });
      } else if (sortMode === 'size') {
        sorted_sources.sort((a, b) => {
          const aCount = sourceConceptCounts[a] || 0;
          const bCount = sourceConceptCounts[b] || 0;
          return bCount - aCount;
        });
      }
      sorted[type] = sorted_sources;
    });

    return sorted;
  }, [filteredSourcesByType, sortMode, collectionsBySource, sourceConceptCounts, t]);

  // Compute available languages from all concepts
  const availableLanguages = useMemo(() => {
    return getAvailableLanguages(filteredConcepts);
  }, [filteredConcepts]);

  if (availableSources.length === 0) {
    return null;
  }

  return (
    <Collapsible
      open={isFilterExpanded}
      onOpenChange={onSetFilterExpanded}
      className="border rounded-lg bg-card mb-4"
    >
      <div className="px-4 py-2 flex items-center justify-between">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors">
            {isFilterExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            <Filter className="h-4 w-4" />
            {t('semantic-models:filters.bySource')}
            {hiddenSources.length > 0 && (
              <Badge variant="secondary" className="h-5 text-[10px] px-1.5">
                {availableSources.filter(s => !hiddenSources.includes(s)).length}/{availableSources.length}
              </Badge>
            )}
          </button>
        </CollapsibleTrigger>
        <div className="flex gap-1 items-center">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs px-2"
            onClick={onSelectAllSources}
          >
            {t('semantic-models:filters.all')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs px-2"
            onClick={() => onSelectNoneSources(availableSources)}
          >
            {t('semantic-models:filters.none')}
          </Button>
          <div className="flex items-center gap-1 ml-2 pl-2 border-l">
            <Button
              variant={sortMode === 'name' ? 'default' : 'outline'}
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setSortMode('name')}
              title={t('semantic-models:filters.sortName', 'Name')}
            >
              {t('semantic-models:filters.sortName', 'Name')}
            </Button>
            <Button
              variant={sortMode === 'size' ? 'default' : 'outline'}
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setSortMode('size')}
              title={t('semantic-models:filters.sortSize', 'Size')}
            >
              {t('semantic-models:filters.sortSize', 'Size')}
            </Button>
          </div>
        </div>
      </div>
      <CollapsibleContent>
        <div className="px-4 pb-3 space-y-2">
          {/* Search input — narrow, not full width */}
          <Input
            type="text"
            placeholder={t('semantic-models:filters.searchSchemes', 'Search schemes...')}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="h-8 text-xs w-48"
          />

          {/* Source chips grouped by type. Height-bounded scroll area so a large source
              count doesn't explode the panel vertically; multi-select behavior
              is unchanged (each chip is still an independent checkbox).
              Type headers replaced with icons + tooltips (left of each type row). */}
          <div className="max-h-56 overflow-y-auto pr-1 space-y-1.5">
            {(['glossary', 'taxonomy', 'ontology', 'other'] as const).map((type) => {
              const sources = sortedSourcesByType[type] || [];
              if (sources.length === 0) return null;

              const typeLabel = t(`semantic-models:filters.groupType${type.charAt(0).toUpperCase() + type.slice(1)}`,
                type === 'glossary' ? 'GLOSSARIES' : type === 'taxonomy' ? 'TAXONOMIES' : type === 'ontology' ? 'ONTOLOGIES' : 'OTHER'
              );

              // Type icon mapping — reuse the same icons as Define for consistency
              const typeIconMap: Record<string, React.FC<any>> = {
                glossary: List,
                taxonomy: ListTree,
                ontology: Share2,
                other: Filter,
              };
              const TypeIcon = typeIconMap[type] || Filter;

              return (
                <div key={type} className="flex items-start gap-2">
                  {/* Type icon with tooltip + count */}
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-0.5 text-muted-foreground pt-0.5 flex-shrink-0">
                          <TypeIcon className="h-3.5 w-3.5" />
                          <Badge variant="secondary" className="h-4 text-[10px] px-1">
                            {sources.length}
                          </Badge>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{typeLabel}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  {/* Chips wrapping to the right */}
                  <div className="flex flex-wrap gap-2 flex-1">
                    {sources.map((source) => {
                      const isVisible = !hiddenSources.includes(source);
                      const conceptCount = sourceConceptCounts[source] || 0;
                      const collection = collectionsBySource.get(source);
                      const isDeletable = collection && collection.source_type !== 'imported' && collection.is_editable;

                      return (
                        <div
                          key={source}
                          className={cn(
                            "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-colors",
                            "border hover:bg-accent",
                            isVisible ? "bg-accent/50 border-primary/30" : "opacity-60"
                          )}
                        >
                          <label className="flex items-center gap-1.5 cursor-pointer flex-1">
                            <Checkbox
                              checked={isVisible}
                              onCheckedChange={() => onToggleSource(source)}
                              className="h-3.5 w-3.5"
                            />
                            <span title={source}>
                              {collection?.label || systemRdfNamespaceDisplayLabel(source, t)}
                            </span>
                            <Badge variant="secondary" className="h-4 text-[10px] px-1">
                              {conceptCount}
                            </Badge>
                          </label>

                          {/* Actions menu for schemes with a collection record (only if callbacks provided) */}
                          {collection && onRenameScheme && onDeleteScheme && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 ml-1"
                                >
                                  <MoreHorizontal className="h-3.5 w-3.5" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-40">
                                <DropdownMenuItem onClick={(e) => {
                                  e.stopPropagation();
                                  onRenameScheme(collection);
                                }}>
                                  {t('common:actions.rename', 'Rename')}
                                </DropdownMenuItem>
                                {isDeletable ? (
                                  <DropdownMenuItem
                                    className="text-destructive"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDeleteConfirmScheme(collection);
                                    }}
                                  >
                                    {t('common:actions.delete', 'Delete')}
                                  </DropdownMenuItem>
                                ) : (
                                  <TooltipProvider>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-muted-foreground cursor-not-allowed opacity-50">
                                          {t('common:actions.delete', 'Delete')}
                                        </div>
                                      </TooltipTrigger>
                                      <TooltipContent>
                                        {t('semantic-models:filters.importedDisable', 'Imported — cannot delete')}
                                      </TooltipContent>
                                    </Tooltip>
                                  </TooltipProvider>
                                )}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          
          {/* Display toggles. This row lives inside the collapsible advanced
              area, so the "Group by" lens below is only reachable once the
              panel is expanded. */}
          <div className="flex flex-wrap items-center gap-6 pt-2 border-t">
            {/* Group by lens (advanced): re-organizes the same chips/terms under
                dimension headers. It is a LENS, not a second filter.
                TODO: wire visibility to global advanced mode when one exists;
                for now it is gated behind the expanded filter panel. */}
            <div className="flex items-center gap-2">
              <Label htmlFor="group-by-dimension" className="text-sm flex items-center gap-2 cursor-pointer">
                <FolderTree className="h-4 w-4" />
                {t('semantic-models:filters.groupBy', 'Group by')}
              </Label>
              <Select
                value={groupByDimension}
                onValueChange={(value) => onSetGroupByDimension(value as GroupByDimension)}
              >
                <SelectTrigger id="group-by-dimension" className="w-32 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                {/* Option labels are the dimension noun ONLY ("Source",
                    "Domain", …). The "Group by" prefix already lives in the
                    Label beside the select, so full "Group by Source" strings
                    would render "Group by [Group by Source]". */}
                <SelectContent>
                  <SelectItem value="none">{t('semantic-models:filters.groupByNone', 'None')}</SelectItem>
                  <SelectItem value="scheme">{t('semantic-models:filters.groupByScheme', 'Scheme')}</SelectItem>
                  <SelectItem value="source">{t('semantic-models:filters.groupByDimSource', 'Source')}</SelectItem>
                  <SelectItem value="domain">{t('semantic-models:filters.groupByDimDomain', 'Domain')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Show Properties Toggle */}
            <div className="flex items-center gap-2">
              <Label htmlFor="show-properties" className="text-sm flex items-center gap-2 cursor-pointer">
                <Zap className="h-4 w-4" />
                {t('semantic-models:filters.showProperties')}
              </Label>
              <Switch
                id="show-properties"
                checked={showProperties}
                onCheckedChange={onSetShowProperties}
              />
            </div>

            {/* Label Language Selector */}
            {availableLanguages.length > 0 && (
              <div className="flex items-center gap-2">
                <Label htmlFor="label-language" className="text-sm flex items-center gap-2 cursor-pointer">
                  <Languages className="h-4 w-4" />
                  {t('semantic-models:filters.labelLanguage', 'Label Language')}
                </Label>
                <Select value={selectedLanguage} onValueChange={onSetSelectedLanguage}>
                  <SelectTrigger id="label-language" className="w-28 h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availableLanguages.map((lang) => (
                      <SelectItem key={lang} value={lang}>
                        {getLanguageDisplayName(lang)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>
      </CollapsibleContent>

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteConfirmScheme} onOpenChange={(open) => !open && setDeleteConfirmScheme(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('semantic-models:dialogs.deleteScheme.title', 'Delete Scheme')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('semantic-models:dialogs.deleteScheme.description',
                'Are you sure you want to delete "{{label}}"? This will delete all concepts in this scheme and cannot be undone.',
                { label: deleteConfirmScheme?.label || '' }
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex gap-3 justify-end">
            <AlertDialogCancel>
              {t('common:actions.cancel', 'Cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteConfirmScheme && onDeleteScheme) {
                  onDeleteScheme(deleteConfirmScheme);
                  setDeleteConfirmScheme(null);
                }
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t('common:actions.delete', 'Delete')}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </Collapsible>
  );
};
