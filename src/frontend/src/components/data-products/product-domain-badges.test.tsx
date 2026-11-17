import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProductDomainBadges from './product-domain-badges';

const domainNames: Record<string, string> = {
  'domain-primary': 'Primary domain',
  'domain-secondary': 'Secondary domain',
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

    expect(screen.getByTitle('Primary domain (primary domain)')).toBeInTheDocument();
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

    expect(screen.getByTitle('Primary domain (primary domain)')).toBeInTheDocument();
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
});
