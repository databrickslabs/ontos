import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import type { PolicyClause } from '@/types/authority-resolution';

/**
 * The labels still valid after the reference changed: a label survives only if the new
 * reference suggests it. A cleared reference (no suggestions) clears them all.
 */
export const pruneClauseLabels = (labels: string[], suggestedRefs: string[]): string[] =>
  labels.filter((label) => suggestedRefs.includes(label));

/** Comma-separated labels, trimmed, without empties or repeats. */
export const parseClauseLabels = (text: string): string[] =>
  [...new Set(text.split(',').map((s) => s.trim()).filter(Boolean))];

/**
 * Free-text clause labels an AR cites (ARF 1.2.0). The reference's suggested clauses
 * are offered in a datalist; any label can still be typed.
 */
export default function ClauseLabelsInput({ value, onChange, suggestions = [] }: {
  value: string[];
  onChange: (labels: string[]) => void;
  suggestions?: PolicyClause[];
}) {
  const { t } = useTranslation(['authority-resolution']);
  const listId = useId();
  const [text, setText] = useState(value.join(', '));
  // Re-sync only when the stored labels change from outside (a loaded AR), not while typing.
  useEffect(() => {
    setText((current) => (parseClauseLabels(current).join('\n') === value.join('\n') ? current : value.join(', ')));
  }, [value]);
  return (
    <div className="space-y-1">
      <Input
        value={text}
        list={suggestions.length ? listId : undefined}
        placeholder={t('policy.citation.clausesPlaceholder')}
        aria-label={t('policy.citation.clauses')}
        className="font-mono text-xs"
        onChange={(e) => {
          setText(e.target.value);
          onChange(parseClauseLabels(e.target.value));
        }}
      />
      {suggestions.length > 0 && (
        <datalist id={listId}>
          {suggestions.map((c) => <option key={c.ref} value={c.ref}>{c.title || ''}</option>)}
        </datalist>
      )}
      <p className="text-xs text-muted-foreground">{t('policy.citation.clausesHint')}</p>
    </div>
  );
}
