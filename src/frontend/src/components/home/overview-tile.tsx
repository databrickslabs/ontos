import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardTitle } from '@/components/ui/card';
import { SkeletonLine } from '@/components/common/list-view-skeleton';

interface OverviewTileProps {
  icon: ReactNode;
  title: string;
  value: string | number;
  loading: boolean;
  error: string | null;
  link: string;
  description: string;
  children?: ReactNode; // For embedded charts/custom content
}

/**
 * Reusable Overview Tile component with responsive design.
 *
 * Formatting constraints:
 * - Container: Card with transition-colors h-full
 * - Padding: p-6
 * - Header Row: flex items-center justify-between with responsive gaps
 * - Icon: Responsive sizing (h-3 w-3 on mobile to h-4 w-4 on desktop)
 * - Title: Responsive text (text-[11px] on mobile to text-base on lg+)
 * - Value: Responsive text (text-sm on mobile to text-3xl on xl+)
 * - Description: text-xs text-muted-foreground mt-1
 * - Custom content: -mx-2 mt-2 for edge alignment
 *
 * Responsive breakpoints:
 * - Mobile: < 640px (text-[11px], h-3, text-sm)
 * - Small: 640px+ (sm:text-xs, sm:h-3.5, sm:text-lg)
 * - Medium: 768px+ (md:text-sm, md:h-4, md:text-xl)
 * - Large: 1024px+ (lg:text-base, lg:text-2xl)
 * - XLarge: 1280px+ (xl:text-3xl)
 */
export default function OverviewTile({
  icon,
  title,
  value,
  loading,
  error,
  link,
  description,
  children
}: OverviewTileProps) {
  return (
    <Card className="transition-colors h-full">
      <CardContent className="p-6 flex flex-col justify-between h-full">
        <div>
          {/* Icon, Title, and Value in one row */}
          <div className="flex items-center justify-between gap-1.5 sm:gap-2 md:gap-3">
            <div className="flex items-center gap-1 sm:gap-1.5 md:gap-2 flex-1 min-w-0">
              <div className="h-3 w-3 sm:h-3.5 sm:w-3.5 md:h-4 md:w-4 text-muted-foreground flex-shrink-0">
                {icon}
              </div>
              <CardTitle className="text-[11px] sm:text-xs md:text-sm lg:text-base font-medium min-w-0 flex-1">
                <Link to={link} className="hover:underline block truncate">
                  {title}
                </Link>
              </CardTitle>
            </div>
            <div className="flex-shrink-0 ml-auto">
              {loading ? (
                <SkeletonLine height="h-6 md:h-8" width="w-12 md:w-16" />
              ) : error ? (
                <span className="text-xs text-destructive">Error</span>
              ) : (
                <Link
                  to={link}
                  className="text-sm sm:text-lg md:text-xl lg:text-2xl xl:text-3xl font-bold hover:underline tabular-nums"
                >
                  {value}
                </Link>
              )}
            </div>
          </div>

          {/* Description below */}
          <p className="text-xs text-muted-foreground mt-1">
            {description}
          </p>

          {/* Custom content (charts, breakdowns) */}
          {children && !loading && !error && (
            <div className="-mx-2 mt-2">
              {children}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
