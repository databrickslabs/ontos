import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface ComplianceTrendMiniProps {
  // null: a day without a scored run ("No score"), not 0 %
  data?: (number | null)[];
  className?: string;
}

export default function ComplianceTrendMini({
  data,
  className = ''
}: ComplianceTrendMiniProps) {
  const { t } = useTranslation('compliance');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // Don't render if no data is provided
  if (!data || data.length === 0) {
    return null;
  }

  const chartData = data;
  const scored = chartData.filter((v): v is number => v !== null && v !== undefined);
  if (scored.length === 0) {
    return (
      <div className={`text-xs text-muted-foreground ${className}`}>
        {t('runScoreCoverage.noScore')}
      </div>
    );
  }

  const width = 280;
  const height = 110;
  const padding = { top: 5, right: 10, bottom: 15, left: 28 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Calculate min/max for better scaling - ensure minimum range
  const dataMin = Math.min(...scored);
  const dataMax = Math.max(...scored);
  const minValue = Math.max(0, Math.floor(dataMin / 10) * 10 - 10); // Add padding below, but not below 0
  const maxValue = Math.min(100, Math.ceil(dataMax / 10) * 10 + 10); // Add padding above, but not above 100
  const range = Math.max(maxValue - minValue, 20); // Ensure minimum range of 20 for visibility

  // Calculate SVG path for the line chart
  // Days without a score have no point: the line breaks there instead of dropping to 0
  const slots = chartData.map((value, index) => {
    if (value === null || value === undefined) return null;
    const x = padding.left + (index / Math.max(chartData.length - 1, 1)) * chartWidth;
    const y = padding.top + chartHeight - ((value - minValue) / range) * chartHeight;
    return { x, y, value, index };
  });
  const points = slots.filter((p): p is NonNullable<typeof p> => p !== null);

  const segments: (typeof points)[] = [];
  slots.forEach((p) => {
    if (p === null) {
      segments.push([]);
    } else {
      if (segments.length === 0) segments.push([]);
      segments[segments.length - 1].push(p);
    }
  });
  const runs = segments.filter((seg) => seg.length > 0);
  const baseY = height - padding.bottom;
  const pathD = runs
    .map((seg) => `M ${seg.map((p) => `${p.x},${p.y}`).join(' L ')}`)
    .join(' ');
  const areaD = runs
    .map((seg) => {
      const line = `M ${seg.map((p) => `${p.x},${p.y}`).join(' L ')}`;
      return `${line} L ${seg[seg.length - 1].x},${baseY} L ${seg[0].x},${baseY} Z`;
    })
    .join(' ');

  // Calculate day label for hover
  const getDayLabel = (index: number) => {
    const daysAgo = chartData.length - 1 - index;
    if (daysAgo === 0) return 'Today';
    if (daysAgo === 1) return 'Yesterday';
    return `${daysAgo} days ago`;
  };

  return (
    <div className={`relative ${className}`}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        className="overflow-visible"
      >
        {/* Area fill with gradient */}
        <defs>
          <linearGradient id="areaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.2" />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        <path
          d={areaD}
          fill="url(#areaGradient)"
        />

        {/* Line */}
        <path
          d={pathD}
          fill="none"
          stroke="hsl(var(--primary))"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Interactive hover points */}
        {points.map((point) => (
          <g key={point.index}>
            {/* Invisible larger hit area for better hover */}
            <circle
              cx={point.x}
              cy={point.y}
              r="8"
              fill="transparent"
              className="cursor-pointer"
              onMouseEnter={() => setHoveredIndex(point.index)}
              onMouseLeave={() => setHoveredIndex(null)}
            />
            {/* Visible dot */}
            <circle
              cx={point.x}
              cy={point.y}
              r={hoveredIndex === point.index ? "4" : "2"}
              fill="hsl(var(--primary))"
              className={`transition-all ${hoveredIndex === point.index ? 'opacity-100' : 'opacity-50'}`}
              pointerEvents="none"
            />
          </g>
        ))}

        {/* X-axis labels */}
        <text
          x={padding.left}
          y={height - 3}
          textAnchor="start"
          className="text-[9px] fill-muted-foreground"
        >
          30d ago
        </text>
        <text
          x={width - padding.right}
          y={height - 3}
          textAnchor="end"
          className="text-[9px] fill-muted-foreground"
        >
          Today
        </text>

        {/* Y-axis labels */}
        <text
          x={3}
          y={padding.top + 3}
          textAnchor="start"
          className="text-[9px] fill-muted-foreground"
        >
          100%
        </text>
        <text
          x={3}
          y={height - padding.bottom - 2}
          textAnchor="start"
          className="text-[9px] fill-muted-foreground"
        >
          0%
        </text>
      </svg>

      {/* Hover tooltip */}
      {hoveredIndex !== null && (
        <div
          className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded shadow-lg border whitespace-nowrap z-10"
          style={{
            pointerEvents: 'none',
          }}
        >
          <div className="font-semibold">{chartData[hoveredIndex]}% compliance</div>
          <div className="text-muted-foreground">{getDayLabel(hoveredIndex)}</div>
        </div>
      )}
    </div>
  );
}
