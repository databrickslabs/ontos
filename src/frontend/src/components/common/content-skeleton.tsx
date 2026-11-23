import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { SkeletonLine } from '@/components/common/list-view-skeleton';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

/**
 * Loading state that has the shape of the content: while loading, the real
 * component is laid out with sample data but not shown (`[data-skeleton]` in
 * index.css), and skeleton bones in the shared Skeleton style are drawn over
 * each of its text lines (as wide as the text), icons and controls. Frames
 * and spacing stay as they are. Nothing in it can be focused or clicked.
 *
 * Wrap only the part that depends on the data (e.g. a card's content, not its
 * title), so static labels stay readable.
 *
 *   <ContentSkeleton data={owners} sample={SAMPLE_OWNERS}>
 *     {(owners) => <OwnerList owners={owners} />}
 *   </ContentSkeleton>
 *
 *   <ContentSkeleton loading={isLoading} empty={!rows.length} emptyMessage={<Empty />}>
 *     <Rows rows={rows} />
 *   </ContentSkeleton>
 */
interface BaseProps {
  /** Shown instead of the content when set (e.g. a load error) */
  error?: ReactNode;
  /** With emptyMessage: shown instead of the content once loaded */
  empty?: boolean;
  emptyMessage?: ReactNode;
  /** Read to screen readers while loading; defaults to "Loading…" */
  label?: string;
  /** Classes of the wrapping div, which is the same loading or not */
  className?: string;
  /** Classes of the inner div around the content, e.g. to continue a flex layout */
  contentClassName?: string;
}

interface DataProps<T> extends BaseProps {
  /** Loading while null/undefined (unless `loading` says otherwise) */
  data: T | null | undefined;
  /** Stands in for `data` while loading */
  sample: T;
  /** Shows the skeleton even with data, e.g. while reloading */
  loading?: boolean;
  children: (data: T) => ReactNode;
}

interface ChildrenProps extends BaseProps {
  loading: boolean;
  data?: never;
  sample?: never;
  children: ReactNode;
}

export type ContentSkeletonProps<T> = DataProps<T> | ChildrenProps;

interface Bone { left: number; top: number; width: number; height: number }

// Elements drawn as one block instead of their text
const BLOCK_SELECTOR = 'svg, img, video, canvas, input, textarea, select, [role="img"], [data-skeleton-block]';

/** Rectangles of the sample's text lines and blocks, relative to `origin`. */
function measureBones(root: HTMLElement, origin: HTMLElement): Bone[] {
  const base = origin.getBoundingClientRect();
  const bones: Bone[] = [];
  const add = (r: DOMRect, textLine: boolean) => {
    if (r.width < 2 || r.height < 2) return;
    // A text bone is a bar inside the line box, like the shared SkeletonLine
    const height = textLine ? Math.max(8, Math.min(r.height * 0.7, 16)) : r.height;
    bones.push({
      left: r.left - base.left,
      top: r.top - base.top + (r.height - height) / 2,
      width: r.width,
      height,
    });
  };
  const blocks = Array.from(root.querySelectorAll<HTMLElement>(BLOCK_SELECTOR))
    .filter((el) => !el.parentElement?.closest(BLOCK_SELECTOR));
  blocks.forEach((el) => add(el.getBoundingClientRect(), false));
  if (typeof document.createRange !== 'function') return bones;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent?.trim() || node.parentElement?.closest(BLOCK_SELECTOR)) continue;
    range.selectNodeContents(node);
    if (typeof range.getClientRects !== 'function') continue;
    Array.from(range.getClientRects()).forEach((r) => add(r, true));
  }
  return bones;
}

export function ContentSkeleton<T>(props: ContentSkeletonProps<T>) {
  const { t } = useTranslation('common');
  const { error, empty, emptyMessage, label, className, contentClassName } = props;
  const isLoading = props.loading ?? props.data == null;
  const ref = useRef<HTMLDivElement>(null);
  const outerRef = useRef<HTMLDivElement>(null);
  const [bones, setBones] = useState<Bone[]>([]);

  // Measure the laid-out sample, and again when its size changes
  useLayoutEffect(() => {
    const el = ref.current;
    const outer = outerRef.current;
    if (!isLoading || !el || !outer) {
      setBones([]);
      return;
    }
    const measure = () => setBones(measureBones(el, outer));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [isLoading]);

  // React 18 has no `inert` prop; set the attribute so the sample can't be
  // focused, clicked or read while loading
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (isLoading) el.setAttribute('inert', '');
    else el.removeAttribute('inert');
  }, [isLoading]);

  if (error) return <div className={className}>{error}</div>;

  if (empty && emptyMessage && !isLoading) return <div className={className}>{emptyMessage}</div>;

  const render = props.children;
  const content =
    typeof render === 'function'
      ? (render as (d: T) => ReactNode)(isLoading ? (props as DataProps<T>).sample : (props.data as T))
      : render;

  // One tree for both states, so the content isn't remounted when loading ends
  return (
    <div ref={outerRef} className={cn('relative', className)} aria-busy={isLoading || undefined}>
      <span className="sr-only" role="status">{isLoading ? label ?? t('states.loading') : ''}</span>
      <div
        ref={ref}
        className={contentClassName}
        data-skeleton={isLoading ? '' : undefined}
        aria-hidden={isLoading || undefined}
      >
        {content}
      </div>
      {isLoading && bones.length > 0 && (
        <div className="pointer-events-none absolute inset-0" aria-hidden="true" data-skeleton-bones="">
          {bones.map((b, i) => (
            <SkeletonLine
              key={i}
              width=""
              height=""
              className="absolute"
              style={{ left: b.left, top: b.top, width: b.width, height: b.height }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default ContentSkeleton;
