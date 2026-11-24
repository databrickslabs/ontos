import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { ProjectChooser } from './project-chooser';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null,
    availableProjects: [{ id: 'project-1', name: 'Project 1', team_count: 0 }],
    allProjects: [],
    isLoading: false,
    error: null,
    hasProjectContext: false,
    fetchUserProjects: vi.fn(),
    fetchAllProjects: vi.fn(),
    switchProject: vi.fn(),
    requestProjectAccess: vi.fn(),
    clearProject: vi.fn(),
  }),
}));

describe('ProjectChooser localization', () => {
  it.each([
    ['pt', 'Todos os projetos'],
    ['nl', 'Alle Projecten'],
  ])('uses the translated all-projects label in %s', async (locale, label) => {
    await i18n.changeLanguage(locale);
    renderWithProviders(<ProjectChooser />);

    expect(screen.getByRole('button')).toHaveTextContent(label);
  });
});
