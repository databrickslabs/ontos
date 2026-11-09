/**
 * Industry Ontology Library Dialog.
 * 
 * A modal dialog for browsing and importing industry-standard ontologies.
 * Organized by industry verticals (Healthcare, Finance, Manufacturing, etc.).
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Input } from '@/components/ui/input';
import {
  ChevronRight,
  ChevronDown,
  Loader2,
  Library,
  ExternalLink,
  Search,
} from 'lucide-react';
import {
  VerticalSummary,
  OntologySummary,
  ModuleTreeNode,
  ImportRequest,
  ImportResult,
  OntologyLibraryDialogProps,
  maturityColors,
  MaturityLevel,
} from '@/types/industry-ontology';
import { cn } from '@/lib/utils';

/**
 * Main dialog component for the Industry Ontology Library.
 */
export default function OntologyLibraryDialog({
  isOpen,
  onOpenChange,
  onImportSuccess,
}: OntologyLibraryDialogProps) {
  const { t } = useTranslation(['settings', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();

  // Data state
  const [verticals, setVerticals] = useState<VerticalSummary[]>([]);
  const [selectedVertical, setSelectedVertical] = useState<string | null>(null);
  const [ontologies, setOntologies] = useState<OntologySummary[]>([]);
  const [selectedOntology, setSelectedOntology] = useState<OntologySummary | null>(null);
  const [moduleTree, setModuleTree] = useState<ModuleTreeNode[]>([]);

  // Selection state
  const [selectedModules, setSelectedModules] = useState<Set<string>>(new Set());
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [acceptLicense, setAcceptLicense] = useState(false);

  // Loading state
  const [isLoadingVerticals, setIsLoadingVerticals] = useState(false);
  const [isLoadingOntologies, setIsLoadingOntologies] = useState(false);
  const [isLoadingModules, setIsLoadingModules] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  // Search/filter
  const [searchQuery, setSearchQuery] = useState('');

  // Load verticals on mount
  useEffect(() => {
    if (isOpen && verticals.length === 0) {
      loadVerticals();
    }
  }, [isOpen]);

  // Load ontologies when vertical changes
  useEffect(() => {
    if (selectedVertical) {
      loadOntologies(selectedVertical);
    } else {
      setOntologies([]);
    }
    setSelectedOntology(null);
    setModuleTree([]);
    setSelectedModules(new Set());
  }, [selectedVertical]);

  // Load modules when ontology changes
  useEffect(() => {
    if (selectedVertical && selectedOntology) {
      loadModules(selectedVertical, selectedOntology.id);
    } else {
      setModuleTree([]);
    }
    setSelectedModules(new Set());
    setAcceptLicense(false);
  }, [selectedOntology]);

  const loadVerticals = async () => {
    setIsLoadingVerticals(true);
    try {
      const res = await get<VerticalSummary[]>('/api/industry-ontologies/verticals');
      if (res.data) {
        setVerticals(res.data);
        // Auto-select first vertical
        if (res.data.length > 0) {
          setSelectedVertical(res.data[0].id);
        }
      }
    } catch (e: any) {
      toast({
        title: t('common:status.error'),
        description: e.message || t('settings:ontologyLibrary.messages.loadVerticalsFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsLoadingVerticals(false);
    }
  };

  const loadOntologies = async (verticalId: string) => {
    setIsLoadingOntologies(true);
    try {
      const res = await get<OntologySummary[]>(
        `/api/industry-ontologies/verticals/${verticalId}/ontologies`
      );
      if (res.data) {
        setOntologies(res.data);
      }
    } catch (e: any) {
      toast({
        title: t('common:status.error'),
        description: e.message || t('settings:ontologyLibrary.messages.loadOntologiesFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsLoadingOntologies(false);
    }
  };

  const loadModules = async (verticalId: string, ontologyId: string) => {
    setIsLoadingModules(true);
    try {
      const res = await get<ModuleTreeNode[]>(
        `/api/industry-ontologies/verticals/${verticalId}/ontologies/${ontologyId}/modules`
      );
      if (res.data) {
        setModuleTree(res.data);
      }
    } catch (e: any) {
      toast({
        title: t('common:status.error'),
        description: e.message || t('settings:ontologyLibrary.messages.loadModulesFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsLoadingModules(false);
    }
  };

  // Get all descendant IDs for a node
  const getDescendantIds = useCallback((node: ModuleTreeNode): string[] => {
    const ids = [node.id];
    for (const child of node.children) {
      ids.push(...getDescendantIds(child));
    }
    return ids;
  }, []);

  // Toggle module selection
  const toggleModuleSelection = useCallback(
    (nodeId: string, node: ModuleTreeNode) => {
      setSelectedModules((prev) => {
        const next = new Set(prev);
        const descendantIds = getDescendantIds(node);

        if (next.has(nodeId)) {
          // Deselect this node and all descendants
          descendantIds.forEach((id) => next.delete(id));
        } else {
          // Select this node and all descendants
          descendantIds.forEach((id) => next.add(id));
        }
        return next;
      });
    },
    [getDescendantIds]
  );

  // Toggle node expansion
  const toggleNodeExpansion = useCallback((nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  // Check if a node is partially selected (some but not all children selected)
  const isPartiallySelected = useCallback(
    (node: ModuleTreeNode): boolean => {
      if (node.children.length === 0) return false;

      const descendantIds = getDescendantIds(node).slice(1); // Exclude the node itself
      const selectedCount = descendantIds.filter((id) => selectedModules.has(id)).length;

      return selectedCount > 0 && selectedCount < descendantIds.length;
    },
    [selectedModules, getDescendantIds]
  );

  // Handle import
  const handleImport = async () => {
    if (!selectedVertical || !selectedOntology || selectedModules.size === 0) {
      toast({
        title: t('settings:ontologyLibrary.messages.noModulesTitle'),
        description: t('settings:ontologyLibrary.messages.noModulesDescription'),
        variant: 'destructive',
      });
      return;
    }

    if (selectedOntology.requires_license_agreement && !acceptLicense) {
      toast({
        title: t('settings:ontologyLibrary.messages.licenseRequiredTitle'),
        description: t('settings:ontologyLibrary.messages.licenseRequiredDescription'),
        variant: 'destructive',
      });
      return;
    }

    setIsImporting(true);
    try {
      const request: ImportRequest = {
        ontology_id: selectedOntology.id,
        vertical_id: selectedVertical,
        module_ids: Array.from(selectedModules),
        include_dependencies: true,
        accept_license: acceptLicense,
      };

      const res = await post<ImportResult>('/api/industry-ontologies/import', request);

      if (res.error) {
        toast({
          title: t('settings:ontologyLibrary.messages.importFailed'),
          description: res.error,
          variant: 'destructive',
        });
        return;
      }

      if (res.data?.success) {
        toast({
          title: t('settings:ontologyLibrary.messages.importSuccessTitle'),
          description: t('settings:ontologyLibrary.messages.importSuccessDescription', {
            count: res.data.triple_count.toLocaleString(),
            name: res.data.semantic_model_name,
          }),
        });

        // Show warnings if any
        if (res.data.warnings.length > 0) {
          res.data.warnings.forEach((warning) => {
            toast({
              title: t('settings:ontologyLibrary.messages.warningTitle'),
              description: warning,
            });
          });
        }

        onImportSuccess?.(res.data);
        onOpenChange(false);
      } else {
        toast({
          title: t('settings:ontologyLibrary.messages.importFailed'),
          description: res.data?.error || t('common:errors.unknownError'),
          variant: 'destructive',
        });
      }
    } catch (e: any) {
      toast({
        title: t('settings:ontologyLibrary.messages.importErrorTitle'),
        description: e.message || t('settings:ontologyLibrary.messages.importErrorDescription'),
        variant: 'destructive',
      });
    } finally {
      setIsImporting(false);
    }
  };

  // Filter ontologies by search
  const filteredOntologies = useMemo(() => {
    if (!searchQuery.trim()) return ontologies;
    const q = searchQuery.toLowerCase();
    return ontologies.filter(
      (o) =>
        o.name.toLowerCase().includes(q) ||
        o.full_name?.toLowerCase().includes(q) ||
        o.description?.toLowerCase().includes(q)
    );
  }, [ontologies, searchQuery]);

  // Render a module tree node
  const renderTreeNode = (node: ModuleTreeNode, level: number = 0) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expandedNodes.has(node.id);
    const isSelected = selectedModules.has(node.id);
    const isPartial = isPartiallySelected(node);
    const maturity = node.maturity as MaturityLevel | undefined;

    return (
      <div key={node.id}>
        <div
          className={cn(
            'flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-muted cursor-pointer',
            isSelected && 'bg-primary/10'
          )}
          style={{ paddingLeft: `${level * 16 + 8}px` }}
        >
          {/* Expand/collapse button */}
          <div className="w-4 flex-shrink-0">
            {hasChildren && (
              <button
                className="p-0.5 hover:bg-muted rounded"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleNodeExpansion(node.id);
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

          {/* Checkbox */}
          {node.selectable && (
            <Checkbox
              checked={isSelected}
              // @ts-ignore - indeterminate is valid but not in types
              data-state={isPartial ? 'indeterminate' : isSelected ? 'checked' : 'unchecked'}
              onCheckedChange={() => toggleModuleSelection(node.id, node)}
              className={cn(isPartial && 'opacity-60')}
            />
          )}

          {/* Node label */}
          <div
            className="flex-1 min-w-0 flex items-center gap-2"
            onClick={() => node.selectable && toggleModuleSelection(node.id, node)}
          >
            <span className="truncate text-sm">{node.name}</span>

            {/* Maturity badge */}
            {maturity && (
              <span className="text-xs" title={maturityColors[maturity].label}>
                {maturityColors[maturity].icon}
              </span>
            )}

            {/* Node type badge */}
            <Badge variant="outline" className="text-xs px-1 py-0">
              {node.node_type}
            </Badge>
          </div>
        </div>

        {/* Children */}
        {hasChildren && isExpanded && (
          <div>{node.children.map((child) => renderTreeNode(child, level + 1))}</div>
        )}
      </div>
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[90vw] h-[80vh] flex flex-col p-0">
        <DialogHeader className="px-6 pt-6 pb-0">
          <DialogTitle className="flex items-center gap-2">
            <Library className="h-5 w-5" />
            {t('settings:ontologyLibrary.title')}
          </DialogTitle>
          <DialogDescription>
            {t('settings:ontologyLibrary.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 flex min-h-0 px-6 py-4 gap-4">
          {/* Left sidebar - Verticals */}
          <div className="w-64 flex-shrink-0 flex flex-col border rounded-lg overflow-hidden">
            <div className="p-2 border-b bg-muted/50">
              <span className="text-xs font-medium text-muted-foreground uppercase">
                {t('settings:ontologyLibrary.verticalsHeading')}
              </span>
            </div>
            <ScrollArea className="flex-1">
              {isLoadingVerticals ? (
                <div className="p-4 flex justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="p-1">
                  {verticals.map((v) => (
                    <button
                      key={v.id}
                      className={cn(
                        'w-full flex items-center gap-2 px-3 py-2 rounded-md text-left text-sm',
                        'hover:bg-muted transition-colors',
                        selectedVertical === v.id && 'bg-primary/10 font-medium'
                      )}
                      onClick={() => setSelectedVertical(v.id)}
                      title={v.name}
                    >
                      <span className="text-lg flex-shrink-0">{v.icon}</span>
                      <span className="truncate flex-1 min-w-0">{v.name}</span>
                      <Badge variant="secondary" className="flex-shrink-0 text-xs">
                        {v.ontology_count}
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>

          {/* Middle section - Ontologies list */}
          <div className="w-72 flex-shrink-0 flex flex-col border rounded-lg">
            <div className="p-2 border-b bg-muted/50 flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground uppercase flex-1">
                {t('settings:ontologyLibrary.ontologiesHeading')}
              </span>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  placeholder={t('settings:ontologyLibrary.filterPlaceholder')}
                  className="h-7 w-32 pl-7 text-xs"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>
            <ScrollArea className="flex-1">
              {isLoadingOntologies ? (
                <div className="p-4 flex justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : filteredOntologies.length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  {selectedVertical ? t('settings:ontologyLibrary.noOntologiesFound') : t('settings:ontologyLibrary.selectVertical')}
                </div>
              ) : (
                <div className="p-1">
                  {filteredOntologies.map((o) => (
                    <button
                      key={o.id}
                      className={cn(
                        'w-full flex flex-col gap-1 px-3 py-2 rounded-md text-left',
                        'hover:bg-muted transition-colors',
                        selectedOntology?.id === o.id && 'bg-primary/10'
                      )}
                      onClick={() => setSelectedOntology(o)}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{o.name}</span>
                        {o.recommended_foundation && (
                          <Badge variant="outline" className="text-xs px-1 py-0">
                            {t('settings:ontologyLibrary.foundationBadge')}
                          </Badge>
                        )}
                      </div>
                      {o.description && (
                        <span className="text-xs text-muted-foreground line-clamp-2">
                          {o.description}
                        </span>
                      )}
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant="secondary" className="text-xs">
                          {t('settings:ontologyLibrary.moduleCount', { count: o.module_count })}
                        </Badge>
                        {o.requires_license_agreement && (
                          <Badge variant="outline" className="text-xs text-yellow-600">
                            {t('settings:ontologyLibrary.licenseBadge')}
                          </Badge>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>

          {/* Right section - Module tree */}
          <div className="flex-1 flex flex-col border rounded-lg min-w-0">
            <div className="p-2 border-b bg-muted/50 flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground uppercase">
                {t('settings:ontologyLibrary.modulesHeading')}
              </span>
              {selectedOntology && (
                <div className="flex items-center gap-2">
                  {selectedOntology.website && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={() => window.open(selectedOntology.website, '_blank')}
                    >
                      <ExternalLink className="h-3 w-3 mr-1" />
                      {t('settings:ontologyLibrary.website')}
                    </Button>
                  )}
                  {selectedOntology.version && (
                    <Badge variant="outline" className="text-xs">
                      v{selectedOntology.version}
                    </Badge>
                  )}
                </div>
              )}
            </div>
            <ScrollArea className="flex-1">
              {isLoadingModules ? (
                <div className="p-4 flex justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : !selectedOntology ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  {t('settings:ontologyLibrary.selectOntologyPrompt')}
                </div>
              ) : moduleTree.length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  {t('settings:ontologyLibrary.noModulesAvailable')}
                </div>
              ) : (
                <div className="p-2">{moduleTree.map((node) => renderTreeNode(node))}</div>
              )}
            </ScrollArea>

            {/* License agreement */}
            {selectedOntology?.requires_license_agreement && (
              <div className="p-3 border-t bg-yellow-50 dark:bg-yellow-950">
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="accept-license"
                    checked={acceptLicense}
                    onCheckedChange={(checked) => setAcceptLicense(!!checked)}
                  />
                  <label htmlFor="accept-license" className="text-sm">
                    <Trans
                      i18nKey="settings:ontologyLibrary.license.acceptLabel"
                      values={{
                        name: selectedOntology.name,
                        license: selectedOntology.license ? ` (${selectedOntology.license})` : '',
                      }}
                      components={{
                        terms: (
                          <a
                            href={selectedOntology.website}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline text-primary"
                          />
                        ),
                      }}
                    />
                  </label>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <Separator />
        <DialogFooter className="px-6 py-4 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            {selectedModules.size > 0 ? (
              <span>
                <Trans
                  i18nKey={selectedOntology ? 'settings:ontologyLibrary.footer.selectedFrom' : 'settings:ontologyLibrary.footer.selected'}
                  count={selectedModules.size}
                  values={{ count: selectedModules.size, ontology: selectedOntology?.name }}
                  components={{ strong: <strong /> }}
                />
              </span>
            ) : (
              <span>{t('settings:ontologyLibrary.footer.selectPrompt')}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button
              onClick={handleImport}
              disabled={
                isImporting ||
                selectedModules.size === 0 ||
                (selectedOntology?.requires_license_agreement && !acceptLicense)
              }
            >
              {isImporting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t('settings:ontologyLibrary.buttons.importing')}
                </>
              ) : (
                t('settings:ontologyLibrary.buttons.import')
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
