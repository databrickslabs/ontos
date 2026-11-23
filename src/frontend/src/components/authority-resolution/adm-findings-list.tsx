import { useTranslation } from 'react-i18next';
import type { AdmConformanceFinding } from '@/types/authority-resolution';

/** The conformance findings of an ADM schema: what is missing or mistyped, per table and column. */
export default function AdmFindingsList({ findings }: { findings: AdmConformanceFinding[] }) {
  const { t } = useTranslation('authority-resolution');
  if (findings.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs" aria-label={t('adm.findings.title')}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${f.table}-${f.column ?? ''}-${i}`} className="rounded border p-2">
          <span className="font-medium">{t(`adm.findings.${f.code}`, { defaultValue: f.code })}</span>
          <span className="ml-2 font-mono break-all">
            {f.table}{f.column ? `.${f.column}` : ''}
          </span>
          {(f.expected || f.actual) && (
            <span className="ml-2 text-muted-foreground">
              {f.expected ? t('adm.findings.expected', { value: f.expected }) : ''}
              {f.expected && f.actual ? ' ' : ''}
              {f.actual ? t('adm.findings.actual', { value: f.actual }) : ''}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
