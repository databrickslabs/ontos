import { useTranslation } from 'react-i18next';
import { stageLabel } from '@/lib/lifecycle-stages';
import type { LifecycleStage, LifecycleStageTransition } from '@/types/lifecycle-stage-groups';

const NODE_W = 104;
const NODE_H = 30;
const GAP = 40;
const PAD = 12;

/** Stroke and fill per stage colour (SVG has no Tailwind badge classes). */
const FILL: Record<string, [string, string]> = {
  gray: ['#f3f4f6', '#6b7280'], slate: ['#f1f5f9', '#64748b'],
  purple: ['#f3e8ff', '#9333ea'], indigo: ['#e0e7ff', '#4f46e5'],
  blue: ['#dbeafe', '#2563eb'], sky: ['#e0f2fe', '#0284c7'],
  teal: ['#ccfbf1', '#0d9488'], emerald: ['#d1fae5', '#059669'],
  green: ['#dcfce7', '#16a34a'], yellow: ['#fef9c3', '#ca8a04'],
  amber: ['#fef3c7', '#d97706'], orange: ['#ffedd5', '#ea580c'],
  red: ['#fee2e2', '#dc2626'], pink: ['#fce7f3', '#db2777'],
};

interface StageGraphPreviewProps {
  stages: Pick<LifecycleStage, 'key' | 'label' | 'color' | 'is_initial'>[];
  transitions: LifecycleStageTransition[];
  /** The entity's current stage, outlined. */
  currentKey?: string | null;
}

/**
 * A read-only graph of a group: the stages left to right in their order, a
 * forward move as an arc above them and a backward one (a loop, such as
 * Active -> Needs Review -> Active) as an arc below.
 */
export default function StageGraphPreview(
  { stages, transitions, currentKey }: StageGraphPreviewProps,
) {
  const { t } = useTranslation(['lifecycle']);
  const index = new Map(stages.map((s, i) => [s.key, i]));
  const edges = transitions.filter(
    (e) => index.has(e.from_key) && index.has(e.to_key) && e.from_key !== e.to_key,
  );
  const spanOf = (e: LifecycleStageTransition) =>
    Math.abs(index.get(e.to_key)! - index.get(e.from_key)!);
  const maxSpan = Math.max(1, ...edges.map(spanOf));
  const arc = (span: number) => 14 + (span / maxSpan) * 46;
  const top = PAD + arc(maxSpan);
  const width = PAD * 2 + stages.length * NODE_W + Math.max(0, stages.length - 1) * GAP;
  const height = top + NODE_H + arc(maxSpan) + PAD;
  const cx = (i: number) => PAD + i * (NODE_W + GAP) + NODE_W / 2;
  const name = (s: StageGraphPreviewProps['stages'][number]) =>
    s.label ? stageLabel(s, t) : s.key;

  return (
    <div className="overflow-x-auto rounded-md border bg-muted/20 p-2">
      <svg
        role="img"
        aria-label={t('lifecycle:editor.graphLabel')}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
      >
        <defs>
          <marker id="lifecycle-arrow" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
          </marker>
        </defs>
        {edges.map((e) => {
          const a = index.get(e.from_key)!;
          const b = index.get(e.to_key)!;
          const forward = b > a;
          const span = Math.abs(b - a);
          const y = forward ? top : top + NODE_H;
          const bend = forward ? y - arc(span) : y + arc(span);
          const x1 = cx(a) + (forward ? 8 : -8);
          const x2 = cx(b) + (forward ? -8 : 8);
          return (
            <path
              key={`${e.from_key}>${e.to_key}`}
              data-edge={`${e.from_key}->${e.to_key}`}
              data-direction={forward ? 'forward' : 'back'}
              d={`M ${x1} ${y} Q ${(x1 + x2) / 2} ${bend} ${x2} ${y}`}
              fill="none"
              stroke={forward ? '#64748b' : '#d97706'}
              strokeWidth={1.5}
              strokeDasharray={forward ? undefined : '4 3'}
              markerEnd="url(#lifecycle-arrow)"
            >
              <title>{`${e.from_key} → ${e.to_key}`}</title>
            </path>
          );
        })}
        {stages.map((s, i) => {
          const [fill, stroke] = FILL[s.color ?? 'gray'] ?? FILL.gray;
          const x = PAD + i * (NODE_W + GAP);
          return (
            <g key={s.key || i} data-node={s.key}
              data-current={s.key === currentKey ? 'true' : undefined}>
              {s.key === currentKey && (
                <rect x={x - 3} y={top - 3} width={NODE_W + 6} height={NODE_H + 6} rx={8}
                  fill="none" stroke="#2563eb" strokeWidth={2} />
              )}
              <rect x={x} y={top} width={NODE_W} height={NODE_H} rx={6}
                fill={fill} stroke={stroke} strokeWidth={s.is_initial ? 2.5 : 1} />
              <text x={x + NODE_W / 2} y={top + NODE_H / 2 + 4} textAnchor="middle"
                fontSize={11} fill="#111827">
                {name(s).length > 16 ? `${name(s).slice(0, 15)}…` : name(s)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
