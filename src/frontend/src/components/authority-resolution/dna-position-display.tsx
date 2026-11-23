import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { dnaDimensionRows, type DnaDimensionRow, type DnaDimensionValue } from '@/types/authority-resolution';

interface Props {
  /** Overall magnitude 0..1; the ceiling gates on it. */
  magnitude: number | null | undefined;
  /** Combined signed position -1..+1. */
  position: number | null | undefined;
  /** The magnitude ceiling (dna_max_threshold). */
  ceiling: number | null | undefined;
  dimensions: Record<string, DnaDimensionValue> | null | undefined;
  loading?: boolean;
}

const fmt = (x: number) => x.toFixed(2);
const fmtSigned = (x: number) => `${x > 0 ? '+' : ''}${x.toFixed(2)}`;
// Position on the -1..+1 axis as a percentage across the track.
const leftPct = (pos: number) => ((pos + 1) / 2) * 100;

function CeilingBar({ magnitude, ceiling }: { magnitude: number; ceiling: number | null }) {
  const over = ceiling != null && magnitude > ceiling;
  return (
    <div className="relative h-2 w-full rounded bg-muted" data-testid="dna-ceiling-bar">
      <div
        className={`absolute inset-y-0 left-0 rounded ${over ? 'bg-destructive' : 'bg-primary'}`}
        style={{ width: `${Math.min(100, magnitude * 100)}%` }}
      />
      {ceiling != null && (
        <div
          className="absolute -top-1 -bottom-1 w-0.5 bg-foreground"
          style={{ left: `${Math.min(100, ceiling * 100)}%` }}
          data-testid="dna-ceiling-marker"
        />
      )}
    </div>
  );
}

/** Unsigned magnitude bar: legacy dimensions and the structural definition entry. */
function MagnitudeBar({ row, testId }: { row: DnaDimensionRow; testId: string }) {
  return (
    <div className="flex items-center gap-3 text-xs" data-testid={testId}>
      <span className="w-32 truncate font-mono" title={row.name}>{row.name}</span>
      <div className="relative h-2 flex-1 rounded bg-muted">
        <div className="absolute inset-y-0 left-0 rounded bg-primary" style={{ width: `${row.magnitude * 100}%` }} />
      </div>
      <span className="w-10 text-right tabular-nums">{fmt(row.magnitude)}</span>
    </div>
  );
}

/** Two dimensions on one -1..+1 line: a labelled marker each, plus the combined position. */
function PositionLine({ rows, position }: { rows: DnaDimensionRow[]; position: number | null }) {
  const { t } = useTranslation('authority-resolution');
  return (
    <div className="space-y-2">
      <div className="relative h-14 mx-4">
        <div className="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded bg-muted" />
        <div className="absolute left-1/2 top-1/2 h-3 w-px -translate-y-1/2 bg-muted-foreground" />
        {rows.map((r, i) => (
          <div
            key={r.name}
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${leftPct(r.position ?? 0)}%` }}
            data-testid={`dna-line-marker-${r.name}`}
            title={`${r.name}: ${fmtSigned(r.position ?? 0)}`}
          >
            <div className="h-3 w-3 rounded-full bg-primary" />
            <div className={`absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] ${i % 2 === 0 ? '-top-5' : 'top-4'}`}>
              {r.name} {fmtSigned(r.position ?? 0)}
            </div>
          </div>
        ))}
        {position != null && (
          <div
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${leftPct(position)}%` }}
            data-testid="dna-line-combined"
            title={t('dna.combinedPosition', { position: fmtSigned(position) })}
          >
            <div className="h-5 w-5 rounded-full border-2 border-foreground bg-background" />
          </div>
        )}
      </div>
      <div className="flex justify-between px-4 text-[10px] text-muted-foreground">
        <span>-1</span>
        <span>0</span>
        <span>+1</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {rows.map((r) => (
          <span key={r.name}>
            <span className="font-mono">{r.name}</span>: {fmtSigned(r.position ?? 0)} · {t('dna.dimensionMagnitude', { value: fmt(r.magnitude) })}
          </span>
        ))}
        {position != null && <span>{t('dna.combinedPosition', { position: fmtSigned(position) })}</span>}
      </div>
    </div>
  );
}

/** Three or more dimensions: one signed bar per dimension, around a centre line. */
function PositionBars({ rows }: { rows: DnaDimensionRow[] }) {
  const { t } = useTranslation('authority-resolution');
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        if (r.definition) {
          return (
            <div key={r.name} className="space-y-1">
              <MagnitudeBar row={r} testId={`dna-definition-bar-${r.name}`} />
              <p className="text-[11px] text-muted-foreground">{t('dna.definitionNote')}</p>
            </div>
          );
        }
        const pos = r.position ?? 0;
        const width = Math.abs(pos) * 50;
        const left = pos >= 0 ? 50 : 50 - width;
        return (
          <div key={r.name} className="flex items-center gap-3 text-xs" data-testid={`dna-bar-${r.name}`}>
            <span className="w-32 truncate font-mono" title={r.name}>{r.name}</span>
            <div className="relative h-2 flex-1 rounded bg-muted">
              <div className="absolute inset-y-0 w-px bg-muted-foreground" style={{ left: '50%' }} />
              <div
                className={`absolute inset-y-0 rounded ${pos >= 0 ? 'bg-primary' : 'bg-amber-500'}`}
                style={{ left: `${left}%`, width: `${width}%` }}
              />
            </div>
            <span className="w-12 text-right tabular-nums">{fmtSigned(pos)}</span>
            <span className="w-20 text-right text-muted-foreground tabular-nums">{t('dna.dimensionMagnitude', { value: fmt(r.magnitude) })}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * The DNA-Coefficient of an Authority Relation: the signed position per dimension, the
 * combined position, and the magnitude against its ceiling. Legacy runs (bare numbers
 * per dimension, before ADM evidence) show magnitude only and say so.
 */
export default function DnaPositionDisplay({ magnitude, position, ceiling, dimensions, loading }: Props) {
  const { t } = useTranslation('authority-resolution');

  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label={t('dna.loading')}>
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }

  const rows = dnaDimensionRows(dimensions);
  const measured = magnitude != null || rows.length > 0;
  if (!measured) {
    return <p className="text-sm text-muted-foreground">{t('dna.empty')}</p>;
  }

  // The structural (definition) entry is not a signed dimension: it never sits on the line.
  const signedRows = rows.filter((r) => !r.definition);
  const legacy = rows.some((r) => r.legacy);
  const hasMagnitude = magnitude != null;
  const over = hasMagnitude && ceiling != null && magnitude > ceiling;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {t('dna.magnitudeOfCeiling', {
            magnitude: hasMagnitude ? fmt(magnitude) : '—',
            ceiling: ceiling != null ? fmt(ceiling) : '—',
          })}
        </span>
        {hasMagnitude && ceiling != null && (
          <Badge variant={over ? 'destructive' : 'outline'}>
            {over ? t('dna.overCeiling') : t('dna.withinCeiling')}
          </Badge>
        )}
      </div>
      {hasMagnitude && <CeilingBar magnitude={magnitude} ceiling={ceiling ?? null} />}

      {legacy ? (
        <div className="space-y-2">
          <p className="text-xs text-amber-600" data-testid="dna-legacy-note">{t('dna.legacyNote')}</p>
          {rows.map((r) => (
            <MagnitudeBar key={r.name} row={r} testId={`dna-legacy-bar-${r.name}`} />
          ))}
        </div>
      ) : signedRows.length === 2 ? (
        <div className="space-y-4">
          <PositionLine rows={signedRows} position={position ?? null} />
          {rows.filter((r) => r.definition).map((r) => (
            <div key={r.name} className="space-y-1">
              <MagnitudeBar row={r} testId={`dna-definition-bar-${r.name}`} />
              <p className="text-[11px] text-muted-foreground">{t('dna.definitionNote')}</p>
            </div>
          ))}
        </div>
      ) : rows.length > 0 ? (
        <PositionBars rows={rows} />
      ) : null}
    </div>
  );
}
