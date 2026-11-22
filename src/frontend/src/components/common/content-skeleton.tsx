import { useEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

/**
 * Loading state that has the shape of the content: while loading, the real
 * component is rendered with sample data in skeleton mode (see
 * `[data-skeleton]` in index.css): every line of text becomes a bar as wide
 * as the text, icons and images become blocks, and frames stay as they are.
 * Nothing in it can be focused or clicked.
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

export function ContentSkeleton<T>(props: ContentSkeletonProps<T>) {
  const { t } = useTranslation('common');
  const { error, empty, emptyMessage, label, className, contentClassName } = props;
  const isLoading = props.loading ?? props.data == null;
  const ref = useRef<HTMLDivElement>(null);

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
    <div className={cn('relative', className)} aria-busy={isLoading || undefined}>
      <span className="sr-only" role="status">{isLoading ? label ?? t('states.loading') : ''}</span>
      <div
        ref={ref}
        className={contentClassName}
        data-skeleton={isLoading ? '' : undefined}
        aria-hidden={isLoading || undefined}
      >
        {content}
      </div>
    </div>
  );
}

export default ContentSkeleton;
