import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProductDomainBadges from './product-domain-badges';

const domainNames: Record<string, string> = {
  'domain-primary': 'Primary domain',
  'domain-secondary': 'Secondary domain',
  ...Object.fromEntries(
    Array.from({ length: 10 }, (_, index) => [
      `domain-${index + 1}`,
      index < 2
        ? `Domain ${index + 1} with a very long name that must be truncated`
        : `Domain ${index + 1}`,
    ])
  ),
};

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({
    getDomainName: (id: string) => domainNames[id],
    getDomainIdByName: (name: string) =>
      Object.entries(domainNames).find(([, domainName]) => domainName === name)?.[0],
  }),
}));

describe('ProductDomainBadges', () => {
  const onDomainClick = vi.fn();

  beforeEach(() => onDomainClick.mockReset());

  it('shows the plural label and an empty value when no domains are assigned', () => {
    render(<ProductDomainBadges product={{}} onDomainClick={onDomainClick} />);

    expect(screen.getByText('Domains:')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('marks a single assigned domain as primary', () => {
    render(
      <ProductDomainBadges
        product={{ domain_ids: ['domain-primary'], primary_domain_id: 'domain-primary' }}
        onDomainClick={onDomainClick}
      />
    );

    expect(screen.getByTitle('Primary domain (Primary domain)')).toBeInTheDocument();
  });

  it('renders every assigned domain and keeps the primary domain visually distinct', () => {
    render(
      <ProductDomainBadges
        product={{
          domain_ids: ['domain-secondary', 'domain-primary'],
          primary_domain_id: 'domain-primary',
        }}
        onDomainClick={onDomainClick}
      />
    );

    expect(screen.getByTitle('Primary domain (Primary domain)')).toBeInTheDocument();
    expect(screen.getByTitle('Secondary domain')).toBeInTheDocument();
  });

  it('allows navigation from each domain badge', async () => {
    const user = userEvent.setup();
    render(
      <ProductDomainBadges
        product={{
          domain_ids: ['domain-primary', 'domain-secondary'],
          primary_domain_id: 'domain-primary',
        }}
        onDomainClick={onDomainClick}
      />
    );

    await user.click(screen.getByText('Primary domain'));
    await user.click(screen.getByText('Secondary domain'));

    expect(onDomainClick).toHaveBeenNthCalledWith(1, 'domain-primary');
    expect(onDomainClick).toHaveBeenNthCalledWith(2, 'domain-secondary');
  });

  it('bounds many domains to two rows and exposes the remaining domains', async () => {
    const user = userEvent.setup();
    const domainIds = Array.from({ length: 10 }, (_, index) => `domain-${index + 1}`);
    render(
      <ProductDomainBadges
        product={{ domain_ids: domainIds, primary_domain_id: 'domain-1' }}
        onDomainClick={onDomainClick}
      />
    );

    expect(
      screen.getByTitle('Domain 1 with a very long name that must be truncated (Primary domain)')
    ).toBeInTheDocument();
    expect(screen.getByText('Domain 2 with a very long name that must be truncated')).toHaveClass(
      'truncate'
    );
    expect(screen.getByRole('button', { name: '+7' })).toHaveAttribute(
      'title',
      expect.stringContaining('Domain 9')
    );
    expect(screen.queryByText('Domain 9')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '+7' }));
    await user.click(await screen.findByText('Domain 9'));

    expect(onDomainClick).toHaveBeenCalledWith('domain-9');
  });

  it('preserves navigation for products that only carry the legacy primary-domain name', async () => {
    const user = userEvent.setup();
    render(
      <ProductDomainBadges product={{ domain: 'Primary domain' }} onDomainClick={onDomainClick} />
    );

    await user.click(screen.getByText('Primary domain'));
    expect(onDomainClick).toHaveBeenCalledWith('domain-primary');
  });

  it('preserves an unresolved legacy domain name as read-only text', () => {
    render(
      <ProductDomainBadges product={{ domain: 'Legacy domain' }} onDomainClick={onDomainClick} />
    );

    expect(screen.getByText('Legacy domain')).toBeInTheDocument();
    expect(onDomainClick).not.toHaveBeenCalled();
  });

  it('renders unresolved domain ids without navigation', async () => {
    const user = userEvent.setup();
    render(
      <ProductDomainBadges
        product={{ domain_ids: ['missing-domain'], primary_domain_id: 'missing-domain' }}
        onDomainClick={onDomainClick}
      />
    );

    const unresolved = screen.getByText('missing-domain');
    expect(unresolved.closest('[role="button"]')).toBeNull();

    await user.click(unresolved);
    expect(onDomainClick).not.toHaveBeenCalled();
  });
});
