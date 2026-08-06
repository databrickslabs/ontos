import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
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
  ChevronRight,
  ChevronDown,
  Filter,
  FolderTree,
  Zap,
  Languages,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { systemRdfNamespaceDisplayLabel } from '@/lib/system-rdf-namespace-labels';
import type { OntologyConcept } from '@/types/ontology';
import type { GroupByDimension } from '@/stores/glossary-preferences-store';
import { getAvailableLanguages, getLanguageDisplayName } from '@/lib/ontology-utils';

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
}

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
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);

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
        <div className="flex gap-1">
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
        </div>
      </div>
      <CollapsibleContent>
        <div className="px-4 pb-3 space-y-3">
          {/* Source checkboxes */}
          <div className="flex flex-wrap gap-2">
            {availableSources.map((source) => {
              const isVisible = !hiddenSources.includes(source);
              const conceptCount = sourceConceptCounts[source] || 0;
              return (
                <label
                  key={source}
                  className={cn(
                    "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs cursor-pointer transition-colors",
                    "border hover:bg-accent",
                    isVisible ? "bg-accent/50 border-primary/30" : "opacity-60"
                  )}
                >
                  <Checkbox
                    checked={isVisible}
                    onCheckedChange={() => onToggleSource(source)}
                    className="h-3.5 w-3.5"
                  />
                  <span title={source}>{systemRdfNamespaceDisplayLabel(source, t)}</span>
                  <Badge variant="secondary" className="h-4 text-[10px] px-1">
                    {conceptCount}
                  </Badge>
                </label>
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
                <SelectContent>
                  <SelectItem value="none">{t('semantic-models:filters.groupByNone', 'None')}</SelectItem>
                  <SelectItem value="scheme">{t('semantic-models:filters.groupByScheme', 'Scheme')}</SelectItem>
                  <SelectItem value="source">{t('semantic-models:filters.groupBySource')}</SelectItem>
                  <SelectItem value="domain">{t('semantic-models:filters.groupByDomain')}</SelectItem>
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
    </Collapsible>
  );
};
