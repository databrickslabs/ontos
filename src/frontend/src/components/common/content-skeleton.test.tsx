import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { describe, it, expect } from 'vitest';
import '@/i18n/config';
import { ContentSkeleton } from './content-skeleton';

const Owners = ({ names }: { names: string[] }) => (
  <ul>
    {names.map((n) => (
      <li key={n}>
        {n} <button type="button">Remove</button>
      </li>
    ))}
  </ul>
);

describe('ContentSkeleton', () => {
  it('renders the sample in skeleton mode while data is missing', () => {
    const { container } = render(
      <ContentSkeleton data={null} sample={['Sample Owner']}>
        {(names: string[]) => <Owners names={names} />}
      </ContentSkeleton>,
    );
    const bones = container.querySelector('[data-skeleton]') as HTMLElement;
    expect(bones).not.toBeNull();
    expect(bones).toHaveAttribute('inert');
    expect(bones).toHaveAttribute('aria-hidden', 'true');
    expect(bones).toHaveTextContent('Sample Owner');
    expect(container.firstElementChild).toHaveAttribute('aria-busy', 'true');
    // The sample's controls are out of reach; only the status is announced
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i);
  });

  it('renders the data, not the sample, once loaded', () => {
    const { container } = render(
      <ContentSkeleton data={['Ada']} sample={['Sample Owner']}>
        {(names: string[]) => <Owners names={names} />}
      </ContentSkeleton>,
    );
    expect(container.querySelector('[data-skeleton]')).toBeNull();
    expect(container.querySelector('[inert]')).toBeNull();
    expect(screen.getByText('Ada')).toBeInTheDocument();
    expect(screen.queryByText('Sample Owner')).toBeNull();
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument();
  });

  it('keeps showing the skeleton over data while loading is set', () => {
    const { container } = render(
      <ContentSkeleton data={['Ada']} sample={['Sample Owner']} loading>
        {(names: string[]) => <Owners names={names} />}
      </ContentSkeleton>,
    );
    expect(container.querySelector('[data-skeleton]')).toHaveTextContent('Sample Owner');
  });

  it('drops inert when loading ends', () => {
    const { container, rerender } = render(
      <ContentSkeleton loading>
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(container.querySelector('[inert]')).not.toBeNull();
    rerender(
      <ContentSkeleton loading={false}>
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(container.querySelector('[inert]')).toBeNull();
    expect(container.querySelector('[data-skeleton]')).toBeNull();
  });

  it('shows the empty message once loaded and empty', () => {
    render(
      <ContentSkeleton loading={false} empty emptyMessage={<p>No owners yet</p>}>
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(screen.getByText('No owners yet')).toBeInTheDocument();
    expect(screen.queryByText('Rows')).toBeNull();
  });

  it('does not show the empty message while loading', () => {
    render(
      <ContentSkeleton loading empty emptyMessage={<p>No owners yet</p>}>
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(screen.queryByText('No owners yet')).toBeNull();
  });

  it('shows the error instead of the content', () => {
    render(
      <ContentSkeleton data={null} sample={['x']} error={<p>Could not load</p>}>
        {(names: string[]) => <Owners names={names} />}
      </ContentSkeleton>,
    );
    expect(screen.getByText('Could not load')).toBeInTheDocument();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('keeps the same wrapper classes loading or not', () => {
    const { container, rerender } = render(
      <ContentSkeleton loading className="space-y-2">
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(container.firstElementChild).toHaveClass('space-y-2');
    rerender(
      <ContentSkeleton loading={false} className="space-y-2">
        <p>Rows</p>
      </ContentSkeleton>,
    );
    expect(container.firstElementChild).toHaveClass('space-y-2');
  });

  it('keeps the content mounted when loading ends (local state survives)', () => {
    const Counter = () => {
      const [n, setN] = useState(0);
      return <button type="button" onClick={() => setN(n + 1)}>count {n}</button>;
    };
    const { rerender } = render(<ContentSkeleton loading={false}><Counter /></ContentSkeleton>);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('count 1');
    rerender(<ContentSkeleton loading><Counter /></ContentSkeleton>);
    rerender(<ContentSkeleton loading={false}><Counter /></ContentSkeleton>);
    expect(screen.getByRole('button')).toHaveTextContent('count 1');
  });
});
