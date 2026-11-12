import { useCallback, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { SizeToggle } from '@/components/common/size-toggle';

// ---------------------------------------------------------------------------
// Shared Simple/Advanced mode switch for Concepts views (Explore, Define,
// Enrich, concept-detail).
//
// Reads/writes localStorage key `ontosConceptMode` ('simple'|'advanced').
// Also updates `document.documentElement.setAttribute('data-mode', mode)` so
// CSS can hide/show advanced-only content via `html[data-mode="advanced"] .adv-only`.
//
// The mode lives in a tiny module-level store so EVERY hook instance shares one
// value and re-renders together. Without this, the switch and a consuming view
// (which each call useConceptMode separately) would hold independent state, and
// React-conditional blocks like `{advanced && ...}` would not update on toggle.
// ---------------------------------------------------------------------------

type ConceptMode = 'simple' | 'advanced';
const MODE_STORAGE_KEY = 'ontosConceptMode';

function readStoredMode(): ConceptMode {
  try {
    return localStorage.getItem(MODE_STORAGE_KEY) === 'advanced' ? 'advanced' : 'simple';
  } catch {
    return 'simple';
  }
}

let currentMode: ConceptMode = readStoredMode();
const listeners = new Set<() => void>();

// Reflect the initial value onto the DOM attribute as soon as the module loads,
// so `.adv-only` CSS is correct on first paint (not just after a toggle).
if (typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-mode', currentMode);
}

function setStoredMode(mode: ConceptMode) {
  currentMode = mode;
  try {
    localStorage.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    // ignore — localStorage unavailable
  }
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-mode', mode);
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Hook to read/write the shared concept mode ('simple' | 'advanced').
 * All instances share one module-level value; toggling re-renders every
 * consumer. Syncs with localStorage and the DOM data-mode attribute.
 */
export function useConceptMode(): [mode: ConceptMode, setMode: (m: ConceptMode) => void] {
  const mode = useSyncExternalStore(
    subscribe,
    () => currentMode,
    () => 'simple' as ConceptMode,
  );
  const setMode = useCallback((newMode: ConceptMode) => setStoredMode(newMode), []);
  return [mode, setMode];
}

/**
 * ConceptModeSwitch: compact S | L toggle for the Simple/Advanced concept mode.
 * S = 'simple', L = 'advanced'. Rendered with the shared SizeToggle so it
 * matches the view buttons on the Data Contracts detail page.
 *
 * Usage:
 *   <ConceptModeSwitch />
 */
interface ConceptModeSwitchProps {
  /** @deprecated Unused. Kept so existing call sites keep compiling; the
   *  info tooltip it positioned was replaced by the button titles. */
  tipLeft?: boolean;
}

export function ConceptModeSwitch(_props: ConceptModeSwitchProps = {}) {
  const { t } = useTranslation(['concepts', 'common']);
  const [mode, setMode] = useConceptMode();

  const largeLabel = t('common:tooltips.largeView', 'Large View');
  const description = t(
    'concepts:mode.description',
    'Advanced view reveals the ontology layer: RDF/SKOS, IRIs, property domain & range, and technical delivery settings. Simple hides them. Your choice is remembered.'
  );

  return (
    <SizeToggle<ConceptMode>
      aria-label={t('concepts:mode.label', 'View mode')}
      value={mode}
      onChange={setMode}
      options={[
        { value: 'simple', label: 'S', title: t('common:tooltips.smallView', 'Small View') },
        { value: 'advanced', label: 'L', title: `${largeLabel}: ${description}` },
      ]}
    />
  );
}
