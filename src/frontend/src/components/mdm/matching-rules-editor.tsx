import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Plus, Trash2, GripVertical, Save } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { MatchingRule, SurvivorshipRule, MdmConfig, MatchRuleType, SurvivorshipStrategy } from '@/types/mdm';

interface MatchingRulesEditorProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  config: MdmConfig;
}

export default function MatchingRulesEditor({
  isOpen,
  onClose,
  onSuccess,
  config,
}: MatchingRulesEditorProps) {
  const [matchingRules, setMatchingRules] = useState<MatchingRule[]>(
    config.matching_rules || []
  );
  const [survivorshipRules, setSurvivorshipRules] = useState<SurvivorshipRule[]>(
    config.survivorship_rules || []
  );
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState<'matching' | 'survivorship'>('matching');

  const { t } = useTranslation(['mdm', 'common']);
  const { put } = useApi();
  const { toast } = useToast();

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await put(`/api/mdm/configs/${config.id}`, {
        matching_rules: matchingRules,
        survivorship_rules: survivorshipRules,
      });

      if (response.data) {
        toast({ title: t('common:status.success'), description: t('mdm:editor.saveSuccess') });
        onSuccess();
        onClose();
      }
    } catch (err: any) {
      toast({
        title: t('common:status.error'),
        description: err.message || t('mdm:editor.saveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  const addMatchingRule = () => {
    setMatchingRules([
      ...matchingRules,
      {
        name: `rule_${matchingRules.length + 1}`,
        type: MatchRuleType.DETERMINISTIC,
        fields: [],
        weight: 1.0,
        threshold: 0.8,
      },
    ]);
  };

  const updateMatchingRule = (index: number, updates: Partial<MatchingRule>) => {
    const updated = [...matchingRules];
    updated[index] = { ...updated[index], ...updates };
    setMatchingRules(updated);
  };

  const removeMatchingRule = (index: number) => {
    setMatchingRules(matchingRules.filter((_, i) => i !== index));
  };

  const addSurvivorshipRule = () => {
    setSurvivorshipRules([
      ...survivorshipRules,
      {
        field: '',
        strategy: SurvivorshipStrategy.MOST_RECENT,
      },
    ]);
  };

  const updateSurvivorshipRule = (index: number, updates: Partial<SurvivorshipRule>) => {
    const updated = [...survivorshipRules];
    updated[index] = { ...updated[index], ...updates };
    setSurvivorshipRules(updated);
  };

  const removeSurvivorshipRule = (index: number) => {
    setSurvivorshipRules(survivorshipRules.filter((_, i) => i !== index));
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('mdm:configDetails.editRules')}</DialogTitle>
          <DialogDescription>
            {t('mdm:editor.dialogDescription', { name: config.name })}
          </DialogDescription>
        </DialogHeader>

        {/* Section Tabs */}
        <div className="flex gap-2 border-b pb-2">
          <Button
            variant={activeSection === 'matching' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setActiveSection('matching')}
          >
            {t('mdm:rulesTab.title')} ({matchingRules.length})
          </Button>
          <Button
            variant={activeSection === 'survivorship' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setActiveSection('survivorship')}
          >
            {t('mdm:survivorship.title')} ({survivorshipRules.length})
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto py-4 space-y-4">
          {/* Matching Rules Section */}
          {activeSection === 'matching' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-muted-foreground">
                  {t('mdm:editor.matchingHint')}
                </p>
                <Button size="sm" onClick={addMatchingRule}>
                  <Plus className="h-4 w-4 mr-1" />
                  {t('mdm:editor.addRule')}
                </Button>
              </div>

              {matchingRules.length === 0 ? (
                <p className="text-center text-muted-foreground py-8">
                  {t('mdm:editor.noMatchingRules')}
                </p>
              ) : (
                <div className="space-y-3">
                  {matchingRules.map((rule, idx) => (
                    <div key={idx} className="p-4 border rounded-lg space-y-3 bg-muted/30">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <GripVertical className="h-4 w-4 text-muted-foreground" />
                          <Input
                            value={rule.name}
                            onChange={(e) => updateMatchingRule(idx, { name: e.target.value })}
                            className="w-48 h-8"
                            placeholder={t('mdm:editor.ruleNamePlaceholder')}
                          />
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeMatchingRule(idx)}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                          <Label className="text-xs">{t('common:labels.type')}</Label>
                          <Select
                            value={rule.type}
                            onValueChange={(value) =>
                              updateMatchingRule(idx, { type: value as any })
                            }
                          >
                            <SelectTrigger className="h-8">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="deterministic">{t('mdm:editor.deterministic')}</SelectItem>
                              <SelectItem value="probabilistic">{t('mdm:editor.probabilistic')}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        <div className="space-y-1">
                          <Label className="text-xs">{t('mdm:editor.fieldsLabel')}</Label>
                          <Input
                            value={rule.fields.join(', ')}
                            onChange={(e) =>
                              updateMatchingRule(idx, {
                                fields: e.target.value.split(',').map((f) => f.trim()).filter(Boolean),
                              })
                            }
                            className="h-8"
                            placeholder={t('mdm:editor.fieldsPlaceholder')}
                          />
                        </div>

                        <div className="space-y-1">
                          <Label className="text-xs">{t('mdm:editor.weightLabel')}</Label>
                          <Input
                            type="number"
                            min="0"
                            max="1"
                            step="0.1"
                            value={rule.weight}
                            onChange={(e) =>
                              updateMatchingRule(idx, { weight: parseFloat(e.target.value) || 1.0 })
                            }
                            className="h-8"
                          />
                        </div>

                        <div className="space-y-1">
                          <Label className="text-xs">{t('mdm:editor.thresholdLabel')}</Label>
                          <Input
                            type="number"
                            min="0"
                            max="1"
                            step="0.1"
                            value={rule.threshold}
                            onChange={(e) =>
                              updateMatchingRule(idx, { threshold: parseFloat(e.target.value) || 0.8 })
                            }
                            className="h-8"
                          />
                        </div>

                        {rule.type === 'probabilistic' && (
                          <div className="space-y-1 col-span-2">
                            <Label className="text-xs">{t('mdm:rulesTab.algorithm')}</Label>
                            <Select
                              value={rule.algorithm || 'jaro_winkler'}
                              onValueChange={(value) => updateMatchingRule(idx, { algorithm: value })}
                            >
                              <SelectTrigger className="h-8">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="jaro_winkler">{t('mdm:editor.algoJaroWinkler')}</SelectItem>
                                <SelectItem value="levenshtein">{t('mdm:editor.algoLevenshtein')}</SelectItem>
                                <SelectItem value="token_sort">{t('mdm:editor.algoTokenSort')}</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Survivorship Rules Section */}
          {activeSection === 'survivorship' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-muted-foreground">
                  {t('mdm:editor.survivorshipHint')}
                </p>
                <Button size="sm" onClick={addSurvivorshipRule}>
                  <Plus className="h-4 w-4 mr-1" />
                  {t('mdm:editor.addRule')}
                </Button>
              </div>

              {survivorshipRules.length === 0 ? (
                <p className="text-center text-muted-foreground py-8">
                  {t('mdm:editor.noSurvivorshipRules')}
                </p>
              ) : (
                <div className="space-y-3">
                  {survivorshipRules.map((rule, idx) => (
                    <div key={idx} className="p-4 border rounded-lg space-y-3 bg-muted/30">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <GripVertical className="h-4 w-4 text-muted-foreground" />
                          <Badge variant="outline">{rule.field || t('mdm:editor.unnamedField')}</Badge>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeSurvivorshipRule(idx)}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                          <Label className="text-xs">{t('mdm:editor.fieldNameLabel')}</Label>
                          <Input
                            value={rule.field}
                            onChange={(e) =>
                              updateSurvivorshipRule(idx, { field: e.target.value })
                            }
                            className="h-8"
                            placeholder={t('mdm:editor.fieldNamePlaceholder')}
                          />
                        </div>

                        <div className="space-y-1">
                          <Label className="text-xs">{t('mdm:editor.strategyLabel')}</Label>
                          <Select
                            value={rule.strategy}
                            onValueChange={(value) =>
                              updateSurvivorshipRule(idx, { strategy: value as any })
                            }
                          >
                            <SelectTrigger className="h-8">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="most_recent">{t('mdm:editor.stratMostRecent')}</SelectItem>
                              <SelectItem value="most_trusted">{t('mdm:editor.stratMostTrusted')}</SelectItem>
                              <SelectItem value="most_complete">{t('mdm:editor.stratMostComplete')}</SelectItem>
                              <SelectItem value="source_priority">{t('mdm:editor.stratSourcePriority')}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        {rule.strategy === 'most_trusted' && (
                          <div className="space-y-1 col-span-2">
                            <Label className="text-xs">{t('mdm:editor.priorityLabel')}</Label>
                            <Input
                              value={(rule.priority || []).join(', ')}
                              onChange={(e) =>
                                updateSurvivorshipRule(idx, {
                                  priority: e.target.value.split(',').map((p) => p.trim()).filter(Boolean),
                                })
                              }
                              className="h-8"
                              placeholder={t('mdm:editor.priorityPlaceholder')}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {t('common:actions.saving')}
              </>
            ) : (
              <>
                <Save className="h-4 w-4 mr-2" />
                {t('mdm:editor.saveButton')}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

