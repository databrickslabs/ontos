import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import NativeSelect from '@/components/ui/native-select';
import { Plus, Trash2 } from 'lucide-react';
import { InfoHint } from '@/components/authority-resolution/info-hint';
import {
  operandForKey, operandKey,
  type DomainContext, type OdrlConstraint, type OdrlOperator,
} from '@/types/authority-resolution';

/**
 * Domain context = the scope the authority holds in (ODRL constraints the
 * request context must match, else the resolve returns no_authority) plus the
 * AR's parameters (read by rules and checks as `ctx.<key>`).
 */

export type ScopeMatch = 'in' | 'notIn' | 'lt' | 'lteq' | 'gt' | 'gteq';

export interface ScopeRow { key: string; match: ScopeMatch; values: string }
export type ParamType = 'string' | 'number' | 'boolean' | 'list' | 'json';
export interface ParamRow { key: string; type: ParamType; value: string }

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

const matchOf = (op: OdrlOperator): ScopeMatch =>
  op === 'eq' || op === 'isAnyOf' ? 'in'
    : op === 'neq' || op === 'isNoneOf' ? 'notIn'
      : op;

export function scopeRowsFrom(dc?: DomainContext | null): ScopeRow[] {
  return (dc?.scope || []).map((c) => ({
    key: operandKey(c.leftOperand),
    match: matchOf(c.operator),
    values: Array.isArray(c.rightOperand) ? c.rightOperand.join(', ') : String(c.rightOperand ?? ''),
  }));
}

export function paramRowsFrom(dc?: DomainContext | null): ParamRow[] {
  return Object.entries(dc?.params || {}).map(([key, v]): ParamRow => {
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return { key, type: 'list', value: v.join(', ') };
    if (typeof v === 'number') return { key, type: 'number', value: String(v) };
    if (typeof v === 'boolean') return { key, type: 'boolean', value: String(v) };
    if (typeof v === 'string') return { key, type: 'string', value: v };
    // Objects, mixed lists, null: kept as JSON so a save doesn't change them.
    return { key, type: 'json', value: JSON.stringify(v) };
  });
}

const splitList = (s: string) => s.split(',').map((v) => v.trim()).filter(Boolean);

/** Build the payload, or return an i18n error key (+ the offending key). */
export function toDomainContext(
  scope: ScopeRow[], params: ParamRow[],
): { value?: DomainContext; error?: { key: string; field: string } } {
  const out: DomainContext = { scope: [], params: {} };
  for (const r of scope) {
    const key = r.key.trim();
    if (!key && !r.values.trim()) continue;
    if (!IDENT.test(key)) return { error: { key: 'domainContext.validation.invalidKey', field: key } };
    const values = splitList(r.values);
    if (!values.length) return { error: { key: 'domainContext.validation.missingValue', field: key } };
    let constraint: OdrlConstraint;
    if (r.match === 'in' || r.match === 'notIn') {
      const many = values.length > 1;
      const operator: OdrlOperator = r.match === 'in' ? (many ? 'isAnyOf' : 'eq') : (many ? 'isNoneOf' : 'neq');
      constraint = { leftOperand: operandForKey(key), operator, rightOperand: many ? values : values[0] };
    } else {
      constraint = { leftOperand: operandForKey(key), operator: r.match, rightOperand: values[0] };
    }
    out.scope.push(constraint);
  }
  for (const p of params) {
    const key = p.key.trim();
    if (!key && !p.value.trim()) continue;
    if (!IDENT.test(key)) return { error: { key: 'domainContext.validation.invalidKey', field: key } };
    if (p.type === 'number') {
      const n = Number(p.value);
      if (!p.value.trim() || !Number.isFinite(n)) return { error: { key: 'domainContext.validation.notANumber', field: key } };
      out.params[key] = n;
    } else if (p.type === 'boolean') {
      out.params[key] = p.value === 'true';
    } else if (p.type === 'list') {
      out.params[key] = splitList(p.value);
    } else if (p.type === 'json') {
      try {
        out.params[key] = JSON.parse(p.value);
      } catch {
        return { error: { key: 'domainContext.validation.badJson', field: key } };
      }
    } else {
      out.params[key] = p.value;
    }
  }
  return { value: out };
}

interface Props {
  scope: ScopeRow[];
  params: ParamRow[];
  onScopeChange: (rows: ScopeRow[]) => void;
  onParamsChange: (rows: ParamRow[]) => void;
}

export default function DomainContextEditor({ scope, params, onScopeChange, onParamsChange }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  const patchScope = (i: number, p: Partial<ScopeRow>) => onScopeChange(scope.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const patchParam = (i: number, p: Partial<ParamRow>) => onParamsChange(params.map((r, j) => (j === i ? { ...r, ...p } : r)));

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="space-y-2">
        <Label className="text-xs flex items-center gap-1.5">
          {t('domainContext.scope.label')} <InfoHint>{t('domainContext.scope.hint')}</InfoHint>
        </Label>
        {scope.map((r, i) => (
          <div key={i} className="grid grid-cols-[1.3fr_auto_1fr_auto] gap-1.5 items-center">
            <Input value={r.key} onChange={(e) => patchScope(i, { key: e.target.value })}
                   placeholder={t('domainContext.scope.keyPlaceholder')} className="h-8 text-xs font-mono" />
            <NativeSelect className="w-28" selectClassName="h-8 text-xs" value={r.match}
                          onChange={(e) => patchScope(i, { match: e.target.value as ScopeMatch })}>
              {(['in', 'notIn', 'lt', 'lteq', 'gt', 'gteq'] as ScopeMatch[]).map((m) => (
                <option key={m} value={m}>{t(`domainContext.scope.match.${m}`)}</option>
              ))}
            </NativeSelect>
            <Input value={r.values} onChange={(e) => patchScope(i, { values: e.target.value })}
                   placeholder={t('domainContext.scope.valuesPlaceholder')} className="h-8 text-xs" />
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onScopeChange(scope.filter((_, j) => j !== i))}
                    aria-label={t('domainContext.remove')}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" className="h-7 text-xs"
                onClick={() => onScopeChange([...scope, { key: '', match: 'in', values: '' }])}>
          <Plus className="h-3.5 w-3.5 mr-1" /> {t('domainContext.scope.add')}
        </Button>
      </div>

      <div className="space-y-2">
        <Label className="text-xs flex items-center gap-1.5">
          {t('domainContext.params.label')} <InfoHint>{t('domainContext.params.hint')}</InfoHint>
        </Label>
        {params.map((p, i) => (
          <div key={i} className="grid grid-cols-[1.3fr_auto_1fr_auto] gap-1.5 items-center">
            <Input value={p.key} onChange={(e) => patchParam(i, { key: e.target.value })}
                   placeholder={t('domainContext.params.keyPlaceholder')} className="h-8 text-xs font-mono" />
            <NativeSelect className="w-28" selectClassName="h-8 text-xs" value={p.type}
                          onChange={(e) => patchParam(i, { type: e.target.value as ParamType, value: e.target.value === 'boolean' ? 'true' : p.value })}>
              {(['string', 'number', 'boolean', 'list', 'json'] as ParamType[]).map((ty) => (
                <option key={ty} value={ty}>{t(`domainContext.params.type.${ty}`)}</option>
              ))}
            </NativeSelect>
            {p.type === 'boolean' ? (
              <NativeSelect selectClassName="h-8 text-xs" value={p.value} onChange={(e) => patchParam(i, { value: e.target.value })}>
                <option value="true">true</option>
                <option value="false">false</option>
              </NativeSelect>
            ) : (
              <Input value={p.value} onChange={(e) => patchParam(i, { value: e.target.value })}
                     placeholder={t(p.type === 'list' ? 'domainContext.params.listPlaceholder' : 'domainContext.params.valuePlaceholder')}
                     className="h-8 text-xs" />
            )}
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onParamsChange(params.filter((_, j) => j !== i))}
                    aria-label={t('domainContext.remove')}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" className="h-7 text-xs"
                onClick={() => onParamsChange([...params, { key: '', type: 'string', value: '' }])}>
          <Plus className="h-3.5 w-3.5 mr-1" /> {t('domainContext.params.add')}
        </Button>
      </div>
    </div>
  );
}
