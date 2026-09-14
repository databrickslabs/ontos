import { useCallback, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { Info } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

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
 * ConceptModeSwitch — UI component for toggling between Simple and Advanced views.
 * Shows mode buttons + info tooltip explaining the difference.
 *
 * Usage:
 *   <ConceptModeSwitch />
 *
 * Tip positioning:
 *   - Default: tooltip appears to the right (good for left-aligned switches)
 *   - Pass tipLeft=true to anchor it on the left (good for right-aligned switches)
 */
interface ConceptModeSwitchProps {
  tipLeft?: boolean;
}

export function ConceptModeSwitch({ tipLeft = false }: ConceptModeSwitchProps) {
  const { t } = useTranslation(['concepts']);
  const [mode, setMode] = useConceptMode();

  return (
    <div className="inline-flex items-center gap-2 flex-shrink-0">
      <div
        role="tablist"
        aria-label={t('concepts:mode.label', 'View mode')}
        className="inline-flex items-center gap-1 rounded-lg bg-muted p-1"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'simple'}
          onClick={() => setMode('simple')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'simple'
              ? 'bg-background text-foreground shadow'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {t('concepts:mode.simple', 'Simple')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'advanced'}
          onClick={() => setMode('advanced')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'advanced'
              ? 'bg-background text-foreground shadow'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {t('concepts:mode.advanced', 'Advanced view')}
        </button>
      </div>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={t(
                'concepts:mode.info',
                'Advanced view reveals the ontology layer'
              )}
              className="inline-flex items-center justify-center h-4 w-4 rounded-full border border-border text-muted-foreground hover:text-foreground"
            >
              <Info className="h-3 w-3" />
            </button>
          </TooltipTrigger>
          <TooltipContent side={tipLeft ? 'left' : 'right'} className="max-w-[240px]">
            {t(
              'concepts:mode.description',
              'Advanced view reveals the ontology layer: RDF/SKOS, IRIs, property domain & range, and technical delivery settings. Simple hides them. Your choice is remembered.'
            )}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
