import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

// Plain stand-ins for the Radix Select parts (driving Radix in jsdom hung CI).
vi.mock('@/components/ui/select', () => ({
  SelectGroup: ({ children }: { children?: React.ReactNode }) => (
    <div role="group">{children}</div>
  ),
  SelectLabel: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="group-label">{children}</div>
  ),
  SelectSeparator: () => <hr data-testid="separator" />,
  SelectItem: ({
    value,
    children,
    description,
  }: {
    value: string;
    children?: React.ReactNode;
    description?: React.ReactNode;
  }) => (
    <div role="option" aria-selected={false} data-value={value}>
      <span data-testid="item-text">{children}</span>
      {description && <span data-testid="item-description">{description}</span>}
    </div>
  ),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (typeof options === 'string') return options;
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return (options.defaultValue as string).replace('{{parent}}', String(options.parent ?? ''));
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

import { SchemeSelectItems } from './scheme-select-items';

describe('SchemeSelectItems', () => {
  it('renders a labelled group per type with separators between groups', () => {
    render(
      <SchemeSelectItems
        groups={[
          { type: 'glossary', options: [{ iri: 'g', label: 'Gloss' }] },
          { type: 'taxonomy', options: [{ iri: 't', label: 'Tax' }] },
          { type: 'ontology', options: [{ iri: 'o', label: 'Onto' }] },
        ]}
      />,
    );
    expect(screen.getAllByTestId('group-label').map((el) => el.textContent)).toEqual([
      'Glossaries',
      'Taxonomies',
      'Ontologies',
    ]);
    expect(screen.getAllByTestId('separator')).toHaveLength(2);
  });

  it('uses the iri as value and shows the parent as a separate description', () => {
    render(
      <SchemeSelectItems
        groups={[{ type: 'glossary', options: [{ iri: 'urn:c', label: 'Child', parentLabel: 'Parent' }] }]}
      />,
    );
    const item = screen.getByRole('option');
    expect(item).toHaveAttribute('data-value', 'urn:c');
    // Item text (what the closed trigger shows) is the label only.
    expect(within(item).getByTestId('item-text').textContent).toBe('Child');
    expect(within(item).getByTestId('item-description').textContent).toBe('in Parent');
  });

  it('omits the description for root schemes and falls back to the raw type heading', () => {
    render(<SchemeSelectItems groups={[{ type: 'vocabulary', options: [{ iri: 'v', label: 'Voc' }] }]} />);
    expect(screen.getByTestId('group-label').textContent).toBe('vocabulary');
    expect(screen.queryByTestId('item-description')).toBeNull();
    expect(screen.queryByTestId('separator')).toBeNull();
  });

  it('renders a suffix next to the parent text', () => {
    render(
      <SchemeSelectItems
        groups={[{ type: 'glossary', options: [{ iri: 'g', label: 'Gloss' }] }]}
        renderSuffix={() => <span>enterprise</span>}
      />,
    );
    expect(screen.getByTestId('item-description').textContent).toBe('enterprise');
  });
});
