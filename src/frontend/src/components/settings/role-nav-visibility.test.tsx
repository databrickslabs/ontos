/** The role editor's "Show in navigation" checkbox (#1325). */
import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';
import { features, NAV_ENTRY_FEATURES } from '@/config/features';
import i18n from '@/i18n/config';
import {
  RoleNavColumnHeader, RoleNavEntryRow, RoleNavVisibilityCell, cleanHiddenNavFeatures,
  navEntriesOf, roleSaveErrorText,
} from './role-nav-visibility';

const renderCell = (props: Partial<Parameters<typeof RoleNavVisibilityCell>[0]> = {}) => {
  const onChange = vi.fn();
  renderWithProviders(
    <RoleNavVisibilityCell
      featureId="data-contracts"
      label="Data Contracts"
      level={FeatureAccessLevel.READ_ONLY}
      isAdminRole={false}
      hidden={[]}
      onChange={onChange}
      {...props}
    />,
  );
  const box = screen.getByRole('checkbox', { name: 'Show Data Contracts in navigation' });
  return { onChange, box };
};

describe('RoleNavVisibilityCell', () => {
  it('is checked and enabled for a shown feature, and unchecking hides it', () => {
    const { box, onChange } = renderCell({ hidden: ['assets'] });
    expect(box).toBeChecked();
    expect(box).toBeEnabled();
    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(['assets', 'data-contracts']);
  });

  it('checking a hidden feature at Read/Write shows it again', () => {
    const { box, onChange } = renderCell({
      level: FeatureAccessLevel.READ_WRITE, hidden: ['data-contracts', 'assets'],
    });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(['assets']);
  });

  it('is disabled and unchecked at None', () => {
    const { box, onChange } = renderCell({ level: FeatureAccessLevel.NONE });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('is disabled on the admin role, which shows every feature', () => {
    const { box } = renderCell({ isAdminRole: true, level: FeatureAccessLevel.ADMIN });
    expect(box).toBeDisabled();
    expect(box).toBeChecked();
  });
});

describe('RoleNavColumnHeader', () => {
  it('says hiding changes only the menus, not access', () => {
    renderWithProviders(<RoleNavColumnHeader />);
    expect(screen.getByTestId('nav-visibility-help')).toHaveTextContent('not permissions');
    expect(screen.getByText('Show in navigation')).toBeInTheDocument();
  });
});

describe('cleanHiddenNavFeatures', () => {
  it('keeps known features with access and drops None, unknown and duplicate ids', () => {
    const perms = {
      'data-contracts': FeatureAccessLevel.READ_ONLY,
      assets: FeatureAccessLevel.READ_WRITE,
      compliance: FeatureAccessLevel.NONE,
    };
    expect(cleanHiddenNavFeatures(
      ['data-contracts', 'assets', 'assets', 'compliance', 'gone'],
      perms,
      ['data-contracts', 'assets', 'compliance'],
    )).toEqual(['data-contracts', 'assets']);
  });

  it('treats a missing list or level as nothing hidden', () => {
    expect(cleanHiddenNavFeatures(undefined, undefined, ['assets'])).toEqual([]);
    expect(cleanHiddenNavFeatures(['assets'], {}, ['assets'])).toEqual([]);
  });
});

describe('cleanHiddenNavFeatures with menu entries', () => {
  const perms = { 'data-products': FeatureAccessLevel.READ_ONLY };

  it('keeps Marketplace and My Products while Products has access', () => {
    expect(cleanHiddenNavFeatures(
      ['marketplace', 'my-products', 'data-products'], perms, ['data-products'],
      NAV_ENTRY_FEATURES,
    )).toEqual(['marketplace', 'my-products', 'data-products']);
  });

  it('drops them when Products is at None or the feature is unknown', () => {
    expect(cleanHiddenNavFeatures(
      ['marketplace', 'my-products'], { 'data-products': FeatureAccessLevel.NONE },
      ['data-products'], NAV_ENTRY_FEATURES,
    )).toEqual([]);
    expect(cleanHiddenNavFeatures(
      ['marketplace'], perms, ['assets'], NAV_ENTRY_FEATURES,
    )).toEqual([]);
  });

  it('refuses the entry ids without the entry map', () => {
    expect(cleanHiddenNavFeatures(['marketplace'], perms, ['data-products'])).toEqual([]);
  });
});

describe('navEntriesOf and RoleNavEntryRow', () => {
  it('lists Marketplace and My Products under Products only', () => {
    expect(navEntriesOf('data-products').map((f) => f.navId))
      .toEqual(['marketplace', 'my-products']);
    expect(navEntriesOf('assets')).toEqual([]);
    expect(navEntriesOf('marketplace')).toEqual([]);
  });

  const renderRow = (props: Partial<Parameters<typeof RoleNavEntryRow>[0]> = {}) => {
    const onChange = vi.fn();
    const entry = features.find((f) => f.navId === 'marketplace')!;
    renderWithProviders(
      <RoleNavEntryRow
        entry={entry}
        level={FeatureAccessLevel.READ_ONLY}
        isAdminRole={false}
        hidden={['data-products']}
        onChange={onChange}
        {...props}
      />,
    );
    const name = 'Show Marketplace in navigation';
    return { onChange, box: screen.getByRole('checkbox', { name }) };
  };

  it('has its own checkbox that is independent from the Products flag', () => {
    const { box, onChange } = renderRow();
    expect(screen.getByTestId('nav-entry-row-marketplace')).toBeInTheDocument();
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(['data-products', 'marketplace']);
  });

  it('is unchecked when its own flag is set', () => {
    expect(renderRow({ hidden: ['marketplace'] }).box).not.toBeChecked();
  });

  it('is disabled at None and on the admin role', () => {
    expect(renderRow({ level: FeatureAccessLevel.NONE }).box).toBeDisabled();
  });
});

describe('roleSaveErrorText', () => {
  const t = i18n.getFixedT('en');

  it('translates the unknown-feature refusal with its ids', () => {
    expect(roleSaveErrorText({
      error: 'Unknown feature ids in hidden_nav_features: search, x',
      errorCode: 'role_nav_feature_unknown',
      errorParams: { feature_ids: ['search', 'x'] },
    }, t)).toBe("Unknown features can't be hidden from the navigation: search, x");
  });

  it('falls back to the API text, and is null on success', () => {
    expect(roleSaveErrorText({ error: 'Invalid role data', errorCode: null }, t))
      .toBe('Invalid role data');
    expect(roleSaveErrorText({ error: null }, t)).toBeNull();
  });
});
