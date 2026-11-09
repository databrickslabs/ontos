/** The role editor's "Show in navigation" checkbox (#1325). */
import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';
import {
  RoleNavColumnHeader, RoleNavVisibilityCell, cleanHiddenNavFeatures,
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
  return { onChange, box: screen.getByRole('checkbox', { name: 'Show Data Contracts in navigation' }) };
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
