import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  Search, Loader2, Check, X, Database, Table2, Eye, Radio,
  LayoutDashboard, BookOpen, BrainCircuit, Globe, Zap,
  Box, Server, Shapes, FolderTree, Columns2, FileCode, Brain,
  Activity, Shield, FolderOpen,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { useApi } from '@/hooks/use-api';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { AssetTypeRead } from '@/types/asset';

export interface AssetSearchResult {
  id: string;
  name: string;
  description?: string;
  asset_type_name?: string;
  platform?: string;
  location?: string;
  status?: string;
}

export interface SelectedAsset extends AssetSearchResult {
  relationshipType: string;
}

interface AssetSelectorProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (assets: SelectedAsset[]) => void;
  relationshipType?: string;
  relationshipLabel?: string;
  targetAssetTypes?: string[];
  excludeAssetIds?: string[];
  title?: string;
  description?: string;
  confirmLabel?: string;
  /** When false, the dialog stays open after confirm (caller must close it). Default true. */
  closeOnConfirm?: boolean;
  /** Additional disable condition for the confirm button (ORed with empty selection). */
  confirmDisabled?: boolean;
}

const ASSET_TYPE_ICONS: Record<string, React.ElementType> = {
  Dataset: Database,
  Table: Table2,
  View: Eye,
  'Delivery Channel': Radio,
  Dashboard: LayoutDashboard,
  Notebook: BookOpen,
  'ML Model': BrainCircuit,
  'API Endpoint': Globe,
  Stream: Zap,
};

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box,
};

const CATEGORY_META: Record<string, { labelKey: string; icon: React.ElementType; order: number }> = {
  data: { labelKey: 'assetSelector.categories.data', icon: Database, order: 1 },
  analytics: { labelKey: 'assetSelector.categories.analytics', icon: LayoutDashboard, order: 2 },
  integration: { labelKey: 'assetSelector.categories.integration', icon: Globe, order: 3 },
  system: { labelKey: 'assetSelector.categories.system', icon: Server, order: 4 },
  custom: { labelKey: 'assetSelector.categories.custom', icon: Shapes, order: 5 },
};

function getAssetIcon(typeName?: string) {
  if (!typeName) return Database;
  return ASSET_TYPE_ICONS[typeName] || Database;
}

function getIconComponent(iconName?: string | null): React.ElementType {
  if (!iconName) return Box;
  return ICON_MAP[iconName] || Box;
}

// --- Reusable sub-components ---

function AssetResultRow({ asset, isSelected, onToggle }: {
  asset: AssetSearchResult;
  isSelected: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation('common');
  const Icon = getAssetIcon(asset.asset_type_name);
  return (
    <button
      onClick={onToggle}
      className={cn(
        'w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-colors overflow-hidden',
        isSelected ? 'bg-primary/10 border border-primary/20' : 'hover:bg-muted'
      )}
    >
      <Checkbox checked={isSelected} className="pointer-events-none" />
      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{asset.name}</div>
        {asset.location && (
          <div className="text-xs text-muted-foreground truncate">{asset.location}</div>
        )}
      </div>
      <Badge variant="outline" className="text-xs flex-shrink-0">
        {asset.asset_type_name || t('common:assetSelector.assetFallback')}
      </Badge>
      {isSelected && <Check className="h-4 w-4 text-primary flex-shrink-0" />}
    </button>
  );
}

function AssetResultsList({ results, loading, selected, onToggle, emptyMessage }: {
  results: AssetSearchResult[];
  loading: boolean;
  selected: Map<string, AssetSearchResult>;
  onToggle: (asset: AssetSearchResult) => void;
  emptyMessage?: string;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (results.length === 0 && emptyMessage) {
    return <p className="text-sm text-muted-foreground text-center py-6">{emptyMessage}</p>;
  }
  return (
    <div className="space-y-0.5">
      {results.map(asset => (
        <AssetResultRow
          key={asset.id}
          asset={asset}
          isSelected={selected.has(asset.id)}
          onToggle={() => onToggle(asset)}
        />
      ))}
    </div>
  );
}

// --- Main component ---

export function AssetSelector({
  isOpen,
  onOpenChange,
  onConfirm,
  relationshipType = '',
  relationshipLabel,
  targetAssetTypes,
  excludeAssetIds = [],
  title,
  description,
  confirmLabel,
  closeOnConfirm = true,
  confirmDisabled = false,
}: AssetSelectorProps) {
  const hasNarrowTypeFilter = !!targetAssetTypes && targetAssetTypes.length > 0 && targetAssetTypes.length <= 2;

  const { t } = useTranslation('common');
  const [mode, setMode] = useState<'search' | 'browse'>(hasNarrowTypeFilter ? 'search' : 'browse');
  const [selected, setSelected] = useState<Map<string, AssetSearchResult>>(new Map());
  const { get: apiGet } = useApi();

  // Search mode state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<AssetSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Browse mode state
  const [assetTypes, setAssetTypes] = useState<AssetTypeRead[]>([]);
  const [typesLoading, setTypesLoading] = useState(false);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [browseResults, setBrowseResults] = useState<AssetSearchResult[]>([]);
  const [browseTotal, setBrowseTotal] = useState(0);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseFilter, setBrowseFilter] = useState('');
  const browseFilterRef = useRef<HTMLInputElement>(null);
  const browseDebounceRef = useRef<ReturnType<typeof setTimeout>>();

  const groupedTypes = useMemo(() => {
    const filtered = targetAssetTypes && targetAssetTypes.length > 0
      ? assetTypes.filter(t => targetAssetTypes.includes(t.name))
      : assetTypes;
    const groups: Record<string, AssetTypeRead[]> = {};
    for (const t of filtered) {
      const cat = t.category || 'custom';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    }
    return Object.entries(groups)
      .map(([cat, types]) => ({
        category: cat,
        label: CATEGORY_META[cat]?.labelKey ? t(`common:${CATEGORY_META[cat].labelKey}`) : cat,
        icon: CATEGORY_META[cat]?.icon || Shapes,
        order: CATEGORY_META[cat]?.order || 99,
        types: types.sort((a, b) => a.name.localeCompare(b.name)),
      }))
      .sort((a, b) => a.order - b.order);
  }, [assetTypes, targetAssetTypes, t]);

  // --- Search mode ---

  const doSearch = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    try {
      let url = `/api/assets?name=${encodeURIComponent(query)}&limit=20`;
      if (targetAssetTypes && targetAssetTypes.length > 0) {
        url += `&asset_type_names=${encodeURIComponent(targetAssetTypes.join(','))}`;
      }
      const response = await apiGet<{ items: AssetSearchResult[]; total: number }>(url);
      const items = response.data?.items;
      if (!response.error && Array.isArray(items)) {
        setSearchResults(items.filter(a => !excludeAssetIds.includes(a.id)));
      } else {
        setSearchResults([]);
      }
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }, [apiGet, targetAssetTypes, excludeAssetIds]);

  const handleSearchQueryChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 300);
  };

  // --- Browse mode ---

  const fetchAssetTypes = useCallback(async () => {
    setTypesLoading(true);
    try {
      const response = await apiGet<AssetTypeRead[]>('/api/asset-types?limit=100');
      if (!response.error && Array.isArray(response.data)) {
        setAssetTypes(response.data.filter(t => t.status === 'active'));
      }
    } catch {
      // silently fail
    } finally {
      setTypesLoading(false);
    }
  }, [apiGet]);

  const fetchBrowseAssets = useCallback(async (typeId: string, nameFilter?: string) => {
    setBrowseLoading(true);
    try {
      let url = `/api/assets?asset_type_id=${typeId}&limit=50`;
      if (nameFilter && nameFilter.length >= 2) {
        url += `&name=${encodeURIComponent(nameFilter)}`;
      }
      const response = await apiGet<{ items: AssetSearchResult[]; total: number }>(url);
      const items = response.data?.items;
      if (!response.error && Array.isArray(items)) {
        setBrowseResults(items.filter(a => !excludeAssetIds.includes(a.id)));
        setBrowseTotal(response.data?.total ?? 0);
      } else {
        setBrowseResults([]);
        setBrowseTotal(0);
      }
    } catch {
      setBrowseResults([]);
      setBrowseTotal(0);
    } finally {
      setBrowseLoading(false);
    }
  }, [apiGet, excludeAssetIds]);

  const handleTypeSelect = (typeId: string) => {
    setSelectedTypeId(typeId);
    setBrowseFilter('');
    fetchBrowseAssets(typeId);
  };

  const handleBrowseFilterChange = (value: string) => {
    setBrowseFilter(value);
    if (browseDebounceRef.current) clearTimeout(browseDebounceRef.current);
    if (selectedTypeId) {
      if (value.length === 0) {
        fetchBrowseAssets(selectedTypeId);
      } else {
        browseDebounceRef.current = setTimeout(() => {
          fetchBrowseAssets(selectedTypeId, value);
        }, 300);
      }
    }
  };

  // --- Shared ---

  const toggleSelect = (asset: AssetSearchResult) => {
    setSelected(prev => {
      const next = new Map(prev);
      if (next.has(asset.id)) {
        next.delete(asset.id);
      } else {
        next.set(asset.id, asset);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    const assets: SelectedAsset[] = Array.from(selected.values()).map(a => ({
      ...a,
      relationshipType,
    }));
    onConfirm(assets);
    if (closeOnConfirm) onOpenChange(false);
  };

  const resetState = () => {
    setSearchQuery('');
    setSearchResults([]);
    setSelected(new Map());
    setSelectedTypeId(null);
    setBrowseResults([]);
    setBrowseTotal(0);
    setBrowseFilter('');
    setMode(hasNarrowTypeFilter ? 'search' : 'browse');
  };

  useEffect(() => {
    if (isOpen) {
      resetState();
      fetchAssetTypes();
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  useEffect(() => {
    if (mode === 'search') {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    }
  }, [mode]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (browseDebounceRef.current) clearTimeout(browseDebounceRef.current);
    };
  }, []);

  const descText = description || (relationshipLabel || relationshipType
    ? t('common:assetSelector.descWithRel', { rel: relationshipLabel || relationshipType })
    : t('common:assetSelector.descDefault'));
  const selectedTypeName = assetTypes.find(t => t.id === selectedTypeId)?.name;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { onOpenChange(open); if (!open) resetState(); }}>
      <DialogContent className="max-w-2xl p-0 overflow-hidden">
        <div className="flex flex-col max-h-[80vh] overflow-hidden">
          {/* Header */}
          <div className="px-6 pt-6 pb-2">
            <DialogHeader>
              <DialogTitle>{title || t('common:assetSelector.title')}</DialogTitle>
              <DialogDescription>{descText}</DialogDescription>
            </DialogHeader>
          </div>

          {/* Mode toggle */}
          <div className="px-6 pb-3">
            <Tabs value={mode} onValueChange={(v) => setMode(v as 'search' | 'browse')}>
              <TabsList className="w-fit">
                <TabsTrigger value="search" className="gap-1.5">
                  <Search className="h-3.5 w-3.5" />
                  {t('common:actions.search')}
                </TabsTrigger>
                <TabsTrigger value="browse" className="gap-1.5">
                  <FolderTree className="h-3.5 w-3.5" />
                  {t('common:actions.browse')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {/* Content area */}
          <div className="flex-1 min-h-0 px-6 overflow-hidden">
            {mode === 'search' ? (
              <div className="flex flex-col h-full min-h-[250px] overflow-hidden">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    ref={searchInputRef}
                    placeholder={t('common:assetSelector.searchPlaceholder')}
                    value={searchQuery}
                    onChange={(e) => handleSearchQueryChange(e.target.value)}
                    className="pl-9"
                  />
                  {searchLoading && (
                    <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                </div>
                <ScrollArea className="flex-1 min-h-0">
                  <AssetResultsList
                    results={searchResults}
                    loading={false}
                    selected={selected}
                    onToggle={toggleSelect}
                    emptyMessage={
                      searchQuery.length >= 2
                        ? (searchLoading ? undefined : t('common:assetSelector.noAssetsFound'))
                        : t('common:assetSelector.typeToSearchHint')
                    }
                  />
                </ScrollArea>
              </div>
            ) : (
              <div className="flex gap-3 h-full min-h-[300px] overflow-hidden">
                {/* Type sidebar */}
                <ScrollArea className="w-48 flex-shrink-0 border rounded-md">
                  <div className="p-1">
                    {typesLoading ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    ) : groupedTypes.length === 0 ? (
                      <p className="text-xs text-muted-foreground text-center py-4">{t('common:assetSelector.noAssetTypes')}</p>
                    ) : (
                      groupedTypes.map(group => (
                        <div key={group.category} className="mb-2">
                          <div className="flex items-center gap-1.5 px-2 py-1">
                            <group.icon className="h-3.5 w-3.5 text-muted-foreground" />
                            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                              {group.label}
                            </span>
                          </div>
                          {group.types.map(t => {
                            const TypeIcon = getIconComponent(t.icon);
                            return (
                              <button
                                key={t.id}
                                onClick={() => handleTypeSelect(t.id)}
                                className={cn(
                                  'w-full flex items-center gap-2 px-2 py-1.5 rounded-sm text-left text-sm transition-colors',
                                  selectedTypeId === t.id
                                    ? 'bg-primary/10 text-primary font-medium'
                                    : 'hover:bg-muted text-foreground'
                                )}
                              >
                                <TypeIcon className="h-3.5 w-3.5 flex-shrink-0" />
                                <span className="truncate flex-1">{t.name}</span>
                                <span className="text-xs text-muted-foreground flex-shrink-0">
                                  {t.asset_count}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      ))
                    )}
                  </div>
                </ScrollArea>

                {/* Results panel */}
                <div className="flex-1 min-w-0 flex flex-col border rounded-md overflow-hidden">
                  {selectedTypeId ? (
                    <>
                      <div className="relative px-3 py-2 border-b">
                        <Search className="absolute left-5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                        <Input
                          ref={browseFilterRef}
                          placeholder={t('common:assetSelector.filterPlaceholder', { type: selectedTypeName || t('common:assetSelector.assetsFallback') })}
                          value={browseFilter}
                          onChange={(e) => handleBrowseFilterChange(e.target.value)}
                          className="pl-8 h-8 text-sm"
                        />
                      </div>
                      <ScrollArea className="flex-1">
                        <div className="p-1">
                          <AssetResultsList
                            results={browseResults}
                            loading={browseLoading}
                            selected={selected}
                            onToggle={toggleSelect}
                            emptyMessage={
                              browseFilter.length >= 2
                                ? t('common:assetSelector.noMatchingAssets')
                                : t('common:assetSelector.noAssetsOfType')
                            }
                          />
                        </div>
                        {browseTotal > 50 && !browseLoading && (
                          <p className="text-xs text-muted-foreground text-center py-2">
                            {t('common:assetSelector.showingLimit', { total: browseTotal })}
                          </p>
                        )}
                      </ScrollArea>
                    </>
                  ) : (
                    <div className="flex-1 flex items-center justify-center">
                      <div className="text-center text-muted-foreground">
                        <FolderTree className="h-8 w-8 mx-auto mb-2 opacity-40" />
                        <p className="text-sm">{t('common:assetSelector.selectTypeToBrowse')}</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Selected items bar */}
          {selected.size > 0 && (
            <div className="px-6 pt-2">
              <Separator className="mb-2" />
              <div className="max-h-16 overflow-y-auto">
                <div className="flex flex-wrap gap-1.5">
                  {Array.from(selected.values()).map(a => {
                    const Icon = getAssetIcon(a.asset_type_name);
                    return (
                      <Badge key={a.id} variant="secondary" className="gap-1 pr-1">
                        <Icon className="h-3 w-3" />
                        <span className="text-xs max-w-32 truncate">{a.name}</span>
                        <button
                          onClick={() => toggleSelect(a)}
                          className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="px-6 pb-6 pt-3">
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common:actions.cancel')}</Button>
              <Button onClick={handleConfirm} disabled={selected.size === 0 || confirmDisabled}>
                {confirmLabel || (selected.size > 0 ? t('common:assetSelector.linkCount', { count: selected.size }) : t('common:assetSelector.linkEmpty'))}
              </Button>
            </DialogFooter>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
