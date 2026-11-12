import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import {
  operandKey,
  type ArfRule, type DomainContext, type OdrlConstraint, type RuleConstraint,
} from '@/types/authority-resolution';

const show = (v: unknown) => (Array.isArray(v) ? v.join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v));

/** Scope chips (`market ∈ DE, AT`) and a parameters table. */
export function DomainContextView({ value }: { value?: DomainContext | null }) {
  const { t } = useTranslation(['authority-resolution']);
  const scope = value?.scope || [];
  const params = Object.entries(value?.params || {});
  if (!scope.length && !params.length) return <div className="text-xs text-muted-foreground">—</div>;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-xs text-muted-foreground mr-1">{t('domainContext.scope.label')}:</span>
        {scope.length ? scope.map((c, i) => (
          <Badge key={i} variant="outline" className="font-mono text-xs" title={c.leftOperand}>
            {operandKey(c.leftOperand)} {t(`rule.operatorSymbol.${c.operator}`)} {show(c.rightOperand)}
          </Badge>
        )) : <span className="text-xs text-muted-foreground">{t('domainContext.scope.unscoped')}</span>}
      </div>
      {params.length > 0 && (
        <table className="text-xs">
          <tbody>
            {params.map(([k, v]) => (
              <tr key={k}>
                <td className="pr-3 font-mono text-muted-foreground">ctx.{k}</td>
                <td className="font-mono">{show(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function describe(c: RuleConstraint, t: (k: string) => string): string {
  if ('or' in c || 'and' in c) {
    const join = 'or' in c ? 'or' : 'and';
    return ((c as any)[join] as OdrlConstraint[]).map((p) => describe(p, t)).join(` ${t(`rule.join.${join}Word`)} `);
  }
  const o = c as OdrlConstraint;
  return `${o.leftOperand} ${t(`rule.operatorSymbol.${o.operator}`)} ${o.rightOperandReference ?? show(o.rightOperand)}`;
}

/** The rule's constraints, duties and prohibitions, one line each. */
export function RuleView({ rule }: { rule?: ArfRule | null }) {
  const { t } = useTranslation(['authority-resolution']);
  const lines: { kind: 'constraint' | 'duty' | 'prohibition'; text: string; name?: string; message?: string; action?: string; clause?: string }[] = [];
  for (const c of rule?.permission?.constraint || []) lines.push({ kind: 'constraint', text: describe(c, t), name: c.name, message: c.message, clause: c.clause });
  for (const d of rule?.permission?.duty || []) {
    lines.push({ kind: 'duty', action: d.action, text: (d.constraint || []).map((c) => describe(c, t)).join(` ${t('rule.join.andWord')} `), name: d.name, message: d.message, clause: d.clause });
  }
  for (const p of rule?.prohibition || []) {
    lines.push({ kind: 'prohibition', text: (p.constraint || []).map((c) => describe(c, t)).join(` ${t('rule.join.andWord')} `), name: p.name, message: p.message, clause: p.clause });
  }
  if (!lines.length) return <div className="text-muted-foreground text-xs">{t('rule.none')}</div>;
  return (
    <div className="space-y-2">
      {lines.map((l, i) => (
        <div key={i} className="rounded border p-2 space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant={l.kind === 'prohibition' ? 'destructive' : l.kind === 'duty' ? 'secondary' : 'default'} className="text-xs">
              {t(`rule.kind.${l.kind}`)}
            </Badge>
            {l.action && <span className="font-mono text-xs">{l.action}</span>}
            {l.name && <span className="font-medium">{l.name}</span>}
            {l.clause && <Badge variant="secondary" className="font-mono text-xs ml-auto">{l.clause}</Badge>}
          </div>
          <div className="font-mono text-xs break-all">
            {l.kind === 'duty' ? `${t('rule.fulfilledWhen')} ` : l.kind === 'prohibition' ? `${t('rule.prohibitedWhen')} ` : ''}{l.text}
          </div>
          {l.message && <div className="text-xs text-muted-foreground">↳ {l.message}</div>}
        </div>
      ))}
    </div>
  );
}
