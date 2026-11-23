import { useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import {
  EVIDENCE_BOUNDS, evidenceSliceErrors, type EvidenceSliceDraft, type EvidenceSliceError,
} from '@/types/authority-resolution';

interface Props {
  value: EvidenceSliceDraft;
  onChange: (next: EvidenceSliceDraft) => void;
  disabled?: boolean;
}

interface ChipInputProps {
  id: string;
  values: string[];
  placeholder: string;
  disabled?: boolean;
  /** Normalises and validates a typed entry; returns the value to add, or null to ignore it. */
  normalize: (raw: string) => string | null;
  onChange: (next: string[]) => void;
  removeLabel: (value: string) => string;
}

// Tag-style input: Enter or comma adds the typed value, Backspace on an empty field removes the last one.
function ChipInput({ id, values, placeholder, disabled, normalize, onChange, removeLabel }: ChipInputProps) {
  const [text, setText] = useState('');
  const commit = () => {
    const next = normalize(text);
    setText('');
    if (next && !values.includes(next)) onChange([...values, next]);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (text.trim()) commit();
    } else if (e.key === 'Backspace' && !text && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div className="space-y-2">
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <Badge key={v} variant="secondary" className="font-mono text-xs gap-1 pr-1">
              {v}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-4 w-4 p-0"
                disabled={disabled}
                aria-label={removeLabel(v)}
                onClick={() => onChange(values.filter((x) => x !== v))}
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        value={text}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => { if (text.trim()) commit(); }}
      />
    </div>
  );
}

/**
 * The AR's evidence slice: which ADM action codes (and optionally which objects) it reads,
 * over what window and sample. Replaces the old table + column-map binding (ARF 1.2.0 slice 4).
 */
export default function EvidenceSliceEditor({ value, onChange, disabled }: Props) {
  const { t } = useTranslation('authority-resolution');
  const errors = evidenceSliceErrors(value);
  const errorText = (key: EvidenceSliceError) => t(`editor.evidenceSlice.errors.${key}`, {
    min: EVIDENCE_BOUNDS.windowDaysMin,
    max: key === 'sampleSizeRange' ? EVIDENCE_BOUNDS.sampleSizeMax : EVIDENCE_BOUNDS.windowDaysMax,
  });
  const has = (key: EvidenceSliceError) => errors.includes(key);
  const patch = (p: Partial<EvidenceSliceDraft>) => onChange({ ...value, ...p });

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <Label htmlFor="evidence-action-codes">{t('editor.evidenceSlice.actionCodes')}</Label>
        <ChipInput
          id="evidence-action-codes"
          values={value.action_codes}
          disabled={disabled}
          placeholder={t('editor.evidenceSlice.actionCodePlaceholder')}
          normalize={(raw) => {
            const v = raw.trim().toLowerCase().replace(/,$/, '');
            return v || null;
          }}
          onChange={(action_codes) => patch({ action_codes })}
          removeLabel={(v) => t('editor.evidenceSlice.removeChip', { value: v })}
        />
        <p className="text-xs text-muted-foreground">{t('editor.evidenceSlice.actionCodesHint', { max: EVIDENCE_BOUNDS.actionCodesMax })}</p>
        {(has('actionCodesRequired') || has('actionCodesTooMany') || has('actionCodeInvalid')) && (
          <p className="text-xs text-destructive" role="alert">
            {has('actionCodesRequired') ? errorText('actionCodesRequired')
              : has('actionCodesTooMany') ? errorText('actionCodesTooMany')
                : errorText('actionCodeInvalid')}
          </p>
        )}
      </div>

      <div className="space-y-1">
        <Label htmlFor="evidence-object-refs">{t('editor.evidenceSlice.objectRefs')}</Label>
        <ChipInput
          id="evidence-object-refs"
          values={value.object_refs}
          disabled={disabled}
          placeholder={t('editor.evidenceSlice.objectRefPlaceholder')}
          normalize={(raw) => raw.trim().replace(/,$/, '') || null}
          onChange={(object_refs) => patch({ object_refs })}
          removeLabel={(v) => t('editor.evidenceSlice.removeChip', { value: v })}
        />
        <p className="text-xs text-muted-foreground">{t('editor.evidenceSlice.objectRefsHint', { max: EVIDENCE_BOUNDS.objectRefsMax })}</p>
        {has('objectRefsTooMany') && <p className="text-xs text-destructive" role="alert">{errorText('objectRefsTooMany')}</p>}
      </div>

      <div className="flex items-center gap-3">
        <Switch
          id="evidence-domain-scope"
          checked={value.domain_scope}
          disabled={disabled}
          onCheckedChange={(domain_scope) => patch({ domain_scope })}
        />
        <Label htmlFor="evidence-domain-scope">{t('editor.evidenceSlice.domainScope')}</Label>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="evidence-window-days">{t('editor.evidenceSlice.windowDays')}</Label>
          <Input
            id="evidence-window-days"
            type="number"
            inputMode="numeric"
            min={EVIDENCE_BOUNDS.windowDaysMin}
            max={EVIDENCE_BOUNDS.windowDaysMax}
            value={value.window_days}
            disabled={disabled}
            aria-invalid={has('windowDaysRange') || undefined}
            onChange={(e) => patch({ window_days: e.target.value })}
          />
          {has('windowDaysRange') && <p className="text-xs text-destructive" role="alert">{errorText('windowDaysRange')}</p>}
        </div>
        <div className="space-y-1">
          <Label htmlFor="evidence-sample-size">{t('editor.evidenceSlice.sampleSize')}</Label>
          <Input
            id="evidence-sample-size"
            type="number"
            inputMode="numeric"
            min={EVIDENCE_BOUNDS.sampleSizeMin}
            max={EVIDENCE_BOUNDS.sampleSizeMax}
            value={value.sample_size}
            disabled={disabled}
            aria-invalid={has('sampleSizeRange') || undefined}
            onChange={(e) => patch({ sample_size: e.target.value })}
          />
          {has('sampleSizeRange') && <p className="text-xs text-destructive" role="alert">{errorText('sampleSizeRange')}</p>}
        </div>
      </div>
    </div>
  );
}
