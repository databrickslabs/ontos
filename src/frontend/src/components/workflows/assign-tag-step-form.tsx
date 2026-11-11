/**
 * Config form of the assign_tag workflow step (#1423, designer part).
 *
 * The value is one of:
 * - a fixed value (a select when the tag defines `possible_values`),
 * - a value taken from the run (`value_source`),
 * - no value: the tag is assigned key-only, and a value the entity already has
 *   for the tag is kept.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import type { AssignTagStepConfig } from '@/types/process-workflow';

export type AssignTagValueMode = 'fixed' | 'source' | 'none';

export const VALUE_SOURCES = ['current_user', 'project_name', 'entity_name', 'timestamp'] as const;

const SOURCE_LABEL_KEYS: Record<(typeof VALUE_SOURCES)[number], string> = {
  current_user: 'sourceCurrentUser',
  project_name: 'sourceProjectName',
  entity_name: 'sourceEntityName',
  timestamp: 'sourceTimestamp',
};

/** The value mode a stored config stands for. */
export function valueModeOf(config: Partial<AssignTagStepConfig>): AssignTagValueMode {
  if (config.value_source) return 'source';
  if (config.value) return 'fixed';
  return 'none';
}

/** The config for a value mode: only the fields of that mode are kept. */
export function configForMode(
  config: Partial<AssignTagStepConfig>, mode: AssignTagValueMode,
): Partial<AssignTagStepConfig> {
  const { value: _value, value_source: _source, ...rest } = config;
  if (mode === 'fixed') return { ...rest, value: config.value ?? '' };
  if (mode === 'source') return { ...rest, value_source: config.value_source || 'current_user' };
  return rest;
}

interface TagInfo {
  fully_qualified_name: string;
  possible_values?: string[] | null;
}

interface AssignTagStepFormProps {
  config: Partial<AssignTagStepConfig>;
  onChange: (config: Partial<AssignTagStepConfig>) => void;
}

const LOOKUP_DELAY_MS = 300;

export default function AssignTagStepForm({ config, onChange }: AssignTagStepFormProps) {
  const { t } = useTranslation(['workflows']);
  const { get } = useApi();
  // A fixed value being typed is '' for a moment: keep the mode the user chose.
  const [mode, setMode] = useState<AssignTagValueMode>(() => valueModeOf(config));
  const [tag, setTag] = useState<TagInfo | null | undefined>(undefined);
  const key = (config.key || '').trim();

  useEffect(() => {
    if (!key) {
      setTag(undefined);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const path = key.split('/').map(encodeURIComponent).join('/');
      const response = await get<TagInfo>(`/api/tags/fqn/${path}`);
      if (!cancelled) setTag(response.data && !response.error ? response.data : null);
    }, LOOKUP_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [key, get]);

  const possibleValues = tag?.possible_values?.filter(v => v !== '') ?? [];
  const fixedValue = config.value ?? '';

  const changeMode = (next: AssignTagValueMode) => {
    setMode(next);
    onChange(configForMode(config, next));
  };

  return (
    <>
      <div>
        <Label htmlFor="assign-tag-key">{t('workflows:designer.assignTag.tagKey')}</Label>
        <Input
          id="assign-tag-key"
          value={config.key || ''}
          onChange={(e) => onChange({ ...config, key: e.target.value })}
          placeholder={t('workflows:designer.assignTag.tagKeyPlaceholder')}
        />
        {tag === null && (
          <p className="text-xs text-muted-foreground mt-1">{t('workflows:designer.assignTag.tagNotFound')}</p>
        )}
      </div>
      <div>
        <Label>{t('workflows:designer.assignTag.valueMode')}</Label>
        <Select value={mode} onValueChange={(v) => changeMode(v as AssignTagValueMode)}>
          <SelectTrigger aria-label={t('workflows:designer.assignTag.valueMode')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">{t('workflows:designer.assignTag.modeFixed')}</SelectItem>
            <SelectItem value="source">{t('workflows:designer.assignTag.modeSource')}</SelectItem>
            <SelectItem value="none">{t('workflows:designer.assignTag.modeNone')}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {mode === 'fixed' && (
        <div>
          <Label htmlFor="assign-tag-value">{t('workflows:designer.assignTag.fixedValue')}</Label>
          {possibleValues.length > 0 ? (
            <Select value={fixedValue || undefined} onValueChange={(v) => onChange({ ...config, value: v })}>
              <SelectTrigger id="assign-tag-value" aria-label={t('workflows:designer.assignTag.fixedValue')}>
                <SelectValue placeholder={t('workflows:designer.assignTag.selectValue')} />
              </SelectTrigger>
              <SelectContent>
                {/* A stored value outside the list stays selectable, so opening the step doesn't drop it. */}
                {[...possibleValues, ...(fixedValue && !possibleValues.includes(fixedValue) ? [fixedValue] : [])]
                  .map(v => <SelectItem key={v} value={v}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          ) : (
            <Input
              id="assign-tag-value"
              value={fixedValue}
              onChange={(e) => onChange({ ...config, value: e.target.value })}
              placeholder={t('workflows:designer.assignTag.fixedValuePlaceholder')}
            />
          )}
        </div>
      )}
      {mode === 'source' && (
        <div>
          <Label>{t('workflows:designer.assignTag.valueSource')}</Label>
          <Select
            value={config.value_source || 'current_user'}
            onValueChange={(v) => onChange({ ...config, value_source: v })}
          >
            <SelectTrigger aria-label={t('workflows:designer.assignTag.valueSource')}>
              <SelectValue placeholder={t('workflows:designer.assignTag.selectSource')} />
            </SelectTrigger>
            <SelectContent>
              {VALUE_SOURCES.map(source => (
                <SelectItem key={source} value={source}>
                  {t(`workflows:designer.assignTag.${SOURCE_LABEL_KEYS[source]}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {mode === 'none' && (
        <p className="text-xs text-muted-foreground">{t('workflows:designer.assignTag.noValueHelp')}</p>
      )}
    </>
  );
}
