import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { OdrlProfile, ProfileLeftOperand } from '@/types/access-policy';
import { LIST_OPERATORS, type FormConstraint } from './odrl-helpers';

interface ConstraintEditorProps {
  profile: OdrlProfile | null;
  value: FormConstraint[];
  onChange: (next: FormConstraint[]) => void;
  /** Restrict left operands to these subjects (rule context/asset/party). */
  subjects?: ProfileLeftOperand['subject'][];
  disabled?: boolean;
  emptyLabel?: string;
}

export const ENFORCEMENT_VARIANT: Record<string, 'default' | 'secondary' | 'outline'> = {
  platform: 'default',
  workflow: 'secondary',
  advisory: 'outline',
};

/** Edits a conjunction of ODRL constraints (all must be satisfied). */
export default function ConstraintEditor({ profile, value, onChange, subjects, disabled, emptyLabel }: ConstraintEditorProps) {
  const { t } = useTranslation(['access-policies']);
  const operands = (profile?.left_operands || []).filter((o) => !subjects || subjects.includes(o.subject));
  const operators = profile?.operators || [];

  const update = (i: number, patch: Partial<FormConstraint>) =>
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  return (
    <div className="space-y-2">
      {value.length === 0 && (
        <p className="text-xs text-muted-foreground">{emptyLabel || t('access-policies:constraints.none')}</p>
      )}
      {value.map((c, i) => {
        const op = operands.find((o) => o.key === c.leftOperand);
        return (
          <div key={i} className="flex flex-wrap items-center gap-2">
            {i > 0 && <span className="text-xs font-medium text-muted-foreground">{t('access-policies:constraints.and')}</span>}
            <Select value={c.leftOperand} onValueChange={(v) => update(i, { leftOperand: v })} disabled={disabled}>
              <SelectTrigger className="h-8 w-48" aria-label={t('access-policies:constraints.leftOperand')}>
                <SelectValue placeholder={t('access-policies:constraints.leftOperand')} />
              </SelectTrigger>
              <SelectContent>
                {operands.map((o) => (
                  <SelectItem key={o.key} value={o.key}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={c.operator} onValueChange={(v) => update(i, { operator: v })} disabled={disabled}>
              <SelectTrigger className="h-8 w-40" aria-label={t('access-policies:constraints.operator')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {operators.map((o) => (
                  <SelectItem key={o.key} value={o.key}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              className="h-8 w-56"
              value={c.value}
              disabled={disabled}
              aria-label={t('access-policies:constraints.value')}
              placeholder={
                LIST_OPERATORS.includes(c.operator)
                  ? t('access-policies:constraints.listPlaceholder')
                  : op?.datatype === 'xsd:dateTime'
                    ? 'YYYY-MM-DD'
                    : t('access-policies:constraints.value')
              }
              onChange={(e) => update(i, { value: e.target.value })}
            />
            {op && (
              <Badge variant={ENFORCEMENT_VARIANT[op.enforcement]} title={op.description} className="text-[10px]">
                {t(`access-policies:enforcement.${op.enforcement}`)}
              </Badge>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              disabled={disabled}
              aria-label={t('access-policies:constraints.remove')}
              onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || operands.length === 0}
        onClick={() => onChange([...value, { leftOperand: operands[0]?.key || '', operator: 'eq', value: '' }])}
      >
        <Plus className="mr-1 h-3 w-3" /> {t('access-policies:constraints.add')}
      </Button>
    </div>
  );
}
