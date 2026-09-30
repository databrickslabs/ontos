import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Loader2, Plus, Check, Search, ChevronRight, ChevronLeft,
  Link2, Database, Package, Shield, Send, BookOpen, Tag,
  Shapes, AlertCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useToast } from '@/hooks/use-toast';
import { useFormatLabel } from '@/lib/format-label';
import type { RelationshipDefinition, EntityRelationships } from '@/types/ontology-schema';

interface LinkCandidate {
  id: string;
  name: string;
  entity_type: string;
  description?: string | null;
  status?: string | null;
  score: number;
}

interface PendingRelationship {
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  relationship_type: string;
  target_name: string;
}

const TARGET_TYPE_ICONS: Record<string, React.ElementType> = {
  Dataset: Database,
  DataProduct: Package,
  Policy: Shield,
  DeliveryChannel: Send,
  LogicalEntity: Shapes,
  LogicalAttribute: Shapes,
  BusinessTerm: Tag,
};

function getIconForRelationship(rel: RelationshipDefinition): React.ElementType {
  const typeName = rel.target_type_label || rel.target_type_iri.split('#').pop() || '';
  return TARGET_TYPE_ICONS[typeName] || Link2;
}

interface LineageEditorProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: string;
  entityId: string;
  entityName: string;
  onSuccess?: () => void;
}

export function LineageEditor({
  isOpen,
  onOpenChange,
  entityType,
  entityId,
  entityName,
  onSuccess,
}: LineageEditorProps) {
  const { toast } = useToast();
  const { t, i18n } = useTranslation('common');
  const formatLabel = useFormatLabel();
  const [currentStep, setCurrentStep] = useState(0);
  const [pendingRelationships, setPendingRelationships] = useState<PendingRelationship[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [relationships, setRelationships] = useState<RelationshipDefinition[]>([]);
  const [isLoadingSchema, setIsLoadingSchema] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const steps = useMemo(() => [
    ...relationships.map(rel => ({
      id: rel.property_name,
      label: formatLabel(rel.label),
      relationship: rel,
    })),
    { id: 'review', label: t('common:lineageEditor.reviewStep'), relationship: null },
  ], [relationships, formatLabel, t]);

  const isReviewStep = currentStep === steps.length - 1;

  useEffect(() => {
    if (!isOpen) return;
    setCurrentStep(0);
    setPendingRelationships([]);
    setSchemaError(null);

    const fetchSchema = async () => {
      setIsLoadingSchema(true);
      try {
        const iri = `http://ontos.app/ontology#${entityType}`;
        const res = await fetch(`/api/ontology/entity-types/relationships?type_iri=${encodeURIComponent(iri)}&lang=${encodeURIComponent(i18n.language)}`);
        if (!res.ok) throw new Error(t('common:lineageEditor.failedLoadRelationships', { status: res.status }));
        const data: EntityRelationships = await res.json();
        setRelationships([...data.outgoing, ...data.incoming]);
      } catch (err: any) {
        setSchemaError(err.message || t('common:lineageEditor.failedLoadOntology'));
        setRelationships([]);
      } finally {
        setIsLoadingSchema(false);
      }
    };
    fetchSchema();
  }, [isOpen, entityType]);

  const addRelationship = useCallback((rel: PendingRelationship) => {
    setPendingRelationships(prev => {
      const exists = prev.some(
        p => p.source_type === rel.source_type && p.source_id === rel.source_id &&
             p.target_type === rel.target_type && p.target_id === rel.target_id &&
             p.relationship_type === rel.relationship_type
      );
      if (exists) return prev;
      return [...prev, rel];
    });
  }, []);

  const removeRelationship = useCallback((index: number) => {
    setPendingRelationships(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleSave = async () => {
    if (pendingRelationships.length === 0) {
      onOpenChange(false);
      return;
    }
    setIsSaving(true);
    let successCount = 0;
    let errorCount = 0;
    for (const rel of pendingRelationships) {
      try {
        const res = await fetch('/api/entity-relationships', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_type: rel.source_type,
            source_id: rel.source_id,
            target_type: rel.target_type,
            target_id: rel.target_id,
            relationship_type: rel.relationship_type,
          }),
        });
        if (res.ok) {
          successCount++;
        } else {
          errorCount++;
        }
      } catch {
        errorCount++;
      }
    }
    setIsSaving(false);
    toast({
      title: errorCount === 0 ? t('common:lineageEditor.lineageSaved') : t('common:lineageEditor.partiallySaved'),
      description: errorCount > 0
        ? t('common:lineageEditor.saveResultWithFailed', { count: successCount, failed: errorCount })
        : t('common:lineageEditor.saveResult', { count: successCount }),
      variant: errorCount > 0 ? 'destructive' : 'default',
    });
    onOpenChange(false);
    onSuccess?.();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {t('common:lineageEditor.title')}
            <Badge variant="outline" className="text-xs font-normal">{entityName}</Badge>
          </DialogTitle>
          <DialogDescription>
            {t('common:lineageEditor.description')}
          </DialogDescription>
        </DialogHeader>

        {isLoadingSchema ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground mr-2" />
            <span className="text-sm text-muted-foreground">{t('common:lineageEditor.loadingTypes')}</span>
          </div>
        ) : schemaError ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-destructive">{schemaError}</p>
          </div>
        ) : relationships.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <Link2 className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {t('common:lineageEditor.noRelationshipsDefinedBefore')} <span className="font-medium">{entityType}</span> {t('common:lineageEditor.noRelationshipsDefinedAfter')}
            </p>
          </div>
        ) : (
          <>
            {/* Step indicator */}
            <div className="flex items-center gap-1 overflow-x-auto pb-2">
              {steps.map((s, i) => {
                const Icon = s.relationship ? getIconForRelationship(s.relationship) : Check;
                const isActive = i === currentStep;
                const isDone = i < currentStep;
                return (
                  <button
                    key={s.id}
                    onClick={() => setCurrentStep(i)}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-xs whitespace-nowrap transition-colors ${
                      isActive ? 'bg-primary text-primary-foreground' :
                      isDone ? 'bg-primary/10 text-primary' :
                      'bg-muted text-muted-foreground hover:bg-accent'
                    }`}
                  >
                    <Icon className="h-3 w-3" />
                    {s.label}
                  </button>
                );
              })}
            </div>

            <Separator />

            {/* Step content */}
            <ScrollArea className="flex-1 min-h-0">
              <div className="py-3">
                {!isReviewStep && steps[currentStep]?.relationship ? (
                  <CandidateSearchStep
                    entityType={entityType}
                    entityId={entityId}
                    relationship={steps[currentStep].relationship!}
                    onAddRelationship={addRelationship}
                    pendingRelationships={pendingRelationships}
                  />
                ) : (
                  <ReviewStep
                    pendingRelationships={pendingRelationships}
                    onRemove={removeRelationship}
                  />
                )}
              </div>
            </ScrollArea>

            <Separator />

            <DialogFooter className="flex items-center justify-between sm:justify-between">
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentStep === 0}
                  onClick={() => setCurrentStep(s => s - 1)}
                >
                  <ChevronLeft className="mr-1 h-3.5 w-3.5" /> {t('common:actions.back')}
                </Button>
                {currentStep < steps.length - 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentStep(s => s + 1)}
                  >
                    {t('common:actions.next')} <ChevronRight className="ml-1 h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
              <div className="flex gap-2 items-center">
                <span className="text-xs text-muted-foreground">
                  {t('common:lineageEditor.queuedCount', { count: pendingRelationships.length })}
                </span>
                {isReviewStep && (
                  <Button size="sm" onClick={handleSave} disabled={isSaving}>
                    {isSaving && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
                    {t('common:lineageEditor.saveAll')}
                  </Button>
                )}
              </div>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface CandidateSearchStepProps {
  entityType: string;
  entityId: string;
  relationship: RelationshipDefinition;
  onAddRelationship: (rel: PendingRelationship) => void;
  pendingRelationships: PendingRelationship[];
}

function CandidateSearchStep({
  entityType,
  entityId,
  relationship,
  onAddRelationship,
  pendingRelationships,
}: CandidateSearchStepProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [candidates, setCandidates] = useState<LinkCandidate[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const { t } = useTranslation('common');
  const formatLabel = useFormatLabel();
  const targetType = relationship.target_type_label || relationship.target_type_iri.split('#').pop() || '';

  useEffect(() => {
    const search = async () => {
      setIsSearching(true);
      try {
        const params = new URLSearchParams({
          target_type: targetType,
          limit: '20',
        });
        if (searchQuery) params.set('query', searchQuery);

        const res = await fetch(`/api/suggestions/link-candidates?${params}`);
        if (res.ok) {
          const data = await res.json();
          setCandidates(data.candidates || []);
        }
      } catch {
        setCandidates([]);
      } finally {
        setIsSearching(false);
      }
    };

    const timer = setTimeout(search, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, targetType]);

  const isAlreadyAdded = (candidateId: string) => {
    return pendingRelationships.some(r => {
      if (relationship.direction === 'outgoing') {
        return r.target_id === candidateId && r.relationship_type === relationship.property_name;
      }
      return r.source_id === candidateId && r.relationship_type === relationship.property_name;
    });
  };

  const handleAdd = (candidate: LinkCandidate) => {
    const rel: PendingRelationship = relationship.direction === 'outgoing'
      ? {
          source_type: entityType,
          source_id: entityId,
          target_type: targetType,
          target_id: candidate.id,
          relationship_type: relationship.property_name,
          target_name: candidate.name,
        }
      : {
          source_type: targetType,
          source_id: candidate.id,
          target_type: entityType,
          target_id: entityId,
          relationship_type: relationship.property_name,
          target_name: candidate.name,
        };
    onAddRelationship(rel);
  };

  const searchLabel = formatLabel(relationship.label) || targetType;

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-sm">{t('common:lineageEditor.searchLabel', { label: searchLabel })}</Label>
        <div className="relative mt-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('common:lineageEditor.searchPlaceholder', { label: searchLabel.toLowerCase() })}
            className="pl-9 h-9"
          />
        </div>
      </div>

      <div className="space-y-1.5">
        {isSearching ? (
          <div className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> {t('common:lineageEditor.searching')}
          </div>
        ) : candidates.length === 0 ? (
          <div className="text-sm text-muted-foreground p-3">
            {t('common:lineageEditor.noCandidates')}
          </div>
        ) : (
          candidates.map((c) => {
            const added = isAlreadyAdded(c.id);
            return (
              <div
                key={c.id}
                className="flex items-center justify-between p-2 rounded-md border hover:bg-accent/50 transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{c.name}</div>
                  {c.description && (
                    <div className="text-xs text-muted-foreground truncate">{c.description}</div>
                  )}
                  <div className="flex items-center gap-1 mt-0.5">
                    <Badge variant="outline" className="text-[9px] h-3.5">{c.entity_type}</Badge>
                    {c.status && (
                      <Badge variant="secondary" className="text-[9px] h-3.5">{c.status}</Badge>
                    )}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant={added ? 'secondary' : 'outline'}
                  className="ml-2 h-7 text-xs"
                  disabled={added}
                  onClick={() => handleAdd(c)}
                >
                  {added ? (
                    <><Check className="mr-1 h-3 w-3" /> {t('common:lineageEditor.added')}</>
                  ) : (
                    <><Plus className="mr-1 h-3 w-3" /> {t('common:actions.add')}</>
                  )}
                </Button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

interface ReviewStepProps {
  pendingRelationships: PendingRelationship[];
  onRemove: (index: number) => void;
}

function ReviewStep({ pendingRelationships, onRemove }: ReviewStepProps) {
  const { t } = useTranslation('common');
  if (pendingRelationships.length === 0) {
    return (
      <div className="text-center py-8">
        <BookOpen className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">
          {t('common:lineageEditor.noneQueued')}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground mb-3">
        {t('common:lineageEditor.willBeCreated', { count: pendingRelationships.length })}
      </p>
      {pendingRelationships.map((rel, i) => (
        <Card key={i}>
          <CardContent className="p-3 flex items-center justify-between">
            <div className="text-sm">
              <span className="font-medium">{rel.source_type}</span>
              <span className="mx-2 text-muted-foreground">
                —[{rel.relationship_type}]→
              </span>
              <span className="font-medium">{rel.target_name}</span>
              <Badge variant="outline" className="ml-2 text-[9px]">{rel.target_type}</Badge>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-destructive hover:text-destructive"
              onClick={() => onRemove(i)}
            >
              {t('common:actions.remove')}
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
