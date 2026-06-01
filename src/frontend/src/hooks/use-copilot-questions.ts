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

// Specificity ranking: lower numbers sort first. Entity-templated
// questions (`requiresEntity`) are the most specific because they
// embed the current detail-page entity in the prompt; page-scoped
// questions come next; global ones are last.
function specificityRank(q: CopilotQuestionDef): number {
  if (q.requiresEntity === true) return 0;
  if (q.contexts.length > 0) return 1;
  return 2;
}

export function useCopilotQuestions(
  adoptionMode?: AdoptionMode | null,
): CopilotQuestionGroup[] {
  const { t } = useTranslation(['copilot-questions']);
  const { pathname } = useLocation();
  const pageContext = useCopilotStore((s) => s.pageContext);
  const contextScope = useCopilotStore((s) => s.contextScope);
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();

  const currentFeatureId = useMemo(
    () => resolveFeatureId(pathname, pageContext?.featureId),
    [pathname, pageContext?.featureId],
  );

  const selectedEntityName = pageContext?.selectedEntity?.name;

  return useMemo(() => {
    if (permissionsLoading) return [];

    // When the user flips the chip to "Ontos (general)" we drop every
    // page-scoped or entity-templated question and keep only globals.
    // The cap also widens to the main-page bucket (15) so the panel
    // doesn't shrink unexpectedly.
    const generalScope = contextScope === 'general';

    const matching: CopilotQuestionDef[] = COPILOT_QUESTIONS.filter((q) => {
      // Adoption-mode filter: questions tagged with a specific
      // adoption mode are only shown when it matches. When the
      // backend snapshot is unavailable (`adoptionMode` is null/
      // undefined) we hide blank-mode onboarding prompts and keep
      // the regular catalog visible — same as the pre-PR behavior.
      if (q.adoptionMode && q.adoptionMode !== adoptionMode) return false;

      if (generalScope) {
        // General scope: only globals (no contexts, no entity binding).
        if (q.requiresEntity === true) return false;
        if (q.contexts.length > 0) return false;
        return hasPermission(q.featureId, q.minAccess);
      }

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

    // Sort by specificity so the most-context-bound questions surface
    // first: entity-templated → page-scoped → global. Keeps relative
    // order stable within a tier (definition order in COPILOT_QUESTIONS).
    matching.sort((a, b) => specificityRank(a) - specificityRank(b));

    // Cap by page scope. Detail pages (selectedEntity present) and
    // type-scoped list pages get a tight cap so the most specific
    // questions dominate; main/marketplace/search and general-scope
    // get a wider cap.
    const onDetailPage = !generalScope && !!pageContext?.selectedEntity;
    const onListScope = !generalScope && !onDetailPage && currentFeatureId !== null;
    const cap = onDetailPage ? 6 : onListScope ? 6 : 15;
    const capped = matching.slice(0, cap);

    const groups: CopilotQuestionGroup[] = [];

    for (const cat of COPILOT_CATEGORIES) {
      const catQuestions = capped
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
    contextScope,
  ]);
}
