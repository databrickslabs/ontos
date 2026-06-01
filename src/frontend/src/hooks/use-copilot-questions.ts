import { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useCopilotStore } from '@/stores/copilot-store';
import { usePermissions } from '@/stores/permissions-store';
import { getFeatureByPath } from '@/config/features';
import {
  COPILOT_QUESTIONS,
  COPILOT_CATEGORIES,
  type CopilotQuestionDef,
} from '@/config/copilot-questions';
import type { AdoptionMode } from '@/types/llm-search';

export interface CopilotQuestionGroup {
  category: string;
  label: string;
  questions: { key: string; text: string }[];
}

function resolveFeatureId(pathname: string, contextFeatureId?: string): string | null {
  if (contextFeatureId) return contextFeatureId;

  const topSegment = '/' + pathname.split('/').filter(Boolean)[0];
  const feature = getFeatureByPath(topSegment);
  if (feature) return feature.permissionId ?? feature.id;

  const settingsMatch = pathname.match(/^\/settings\/(.+)/);
  if (settingsMatch) return 'settings';

  return null;
}

export function useCopilotQuestions(
  adoptionMode?: AdoptionMode | null,
): CopilotQuestionGroup[] {
  const { t } = useTranslation(['copilot-questions']);
  const { pathname } = useLocation();
  const pageContext = useCopilotStore((s) => s.pageContext);
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();

  const currentFeatureId = useMemo(
    () => resolveFeatureId(pathname, pageContext?.featureId),
    [pathname, pageContext?.featureId],
  );

  const selectedEntityName = pageContext?.selectedEntity?.name;

  return useMemo(() => {
    if (permissionsLoading) return [];

    const matching: CopilotQuestionDef[] = COPILOT_QUESTIONS.filter((q) => {
      // Adoption-mode filter: questions tagged with a specific
      // adoption mode are only shown when it matches. When the
      // backend snapshot is unavailable (`adoptionMode` is null/
      // undefined) we hide blank-mode onboarding prompts and keep
      // the regular catalog visible — same as the pre-PR behavior.
      if (q.adoptionMode && q.adoptionMode !== adoptionMode) return false;

      // Entity-aware filter: questions tagged `requiresEntity` are
      // only surfaced on detail pages where a `selectedEntity` lives
      // in `pageContext`. The localized text uses `{{entityName}}` —
      // see substitution below.
      if (q.requiresEntity === true && !pageContext?.selectedEntity) {
        return false;
      }

      const contextMatch =
        q.contexts.length === 0 ||
        (currentFeatureId !== null && q.contexts.includes(currentFeatureId));
      if (!contextMatch) return false;

      return hasPermission(q.featureId, q.minAccess);
    });

    const groups: CopilotQuestionGroup[] = [];

    for (const cat of COPILOT_CATEGORIES) {
      const catQuestions = matching
        .filter((q) => q.category === cat)
        .map((q) => {
          const raw = t(`copilot-questions:questions.${q.key}`);
          const text = raw.replace(/\{\{entityName\}\}/g, selectedEntityName ?? '');
          return { key: q.key, text };
        });

      if (catQuestions.length > 0) {
        groups.push({
          category: cat,
          label: t(`copilot-questions:categories.${cat}`),
          questions: catQuestions,
        });
      }
    }

    return groups;
  }, [
    currentFeatureId,
    permissionsLoading,
    hasPermission,
    t,
    adoptionMode,
    pageContext?.selectedEntity,
    selectedEntityName,
  ]);
}
