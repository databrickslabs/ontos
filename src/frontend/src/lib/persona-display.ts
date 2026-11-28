import type { TestPersona } from '@/stores/test-persona-store';

/**
 * How a test persona is presented in the header chip, switcher and toast.
 *
 * Personas may carry `display_name`, `title`, `color` and `avatar_url`
 * (test_personas.yaml). Without them, name and title are split from `label`
 * ("Priya Raman — Data Steward, Finance"), the colour is derived from `id`,
 * and the avatar falls back to initials.
 */
export interface PersonaDisplay {
  name: string;
  title: string | null;
  color: string;
  initials: string;
  avatarUrl: string | null;
}

// Mid-tone colours that keep white initials readable in light and dark mode.
const PALETTE = ['#0f7b3f', '#2563eb', '#9333ea', '#d97706', '#db2777', '#0891b2', '#4d7c0f', '#c2410c', '#4f46e5', '#52525b'];
const LABEL_SEPARATOR = /\s+[—–]\s+/;
const HEX_COLOR = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

export function personaColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function personaInitials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  const caps = words.filter((w) => /^\p{Lu}/u.test(w));
  const pick = (caps.length ? caps : words).slice(0, 2);
  return pick.map((w) => w[0].toUpperCase()).join('') || '?';
}

export function personaDisplay(p: TestPersona): PersonaDisplay {
  const [labelName, ...rest] = p.label.split(LABEL_SEPARATOR);
  const name = p.display_name?.trim() || labelName.trim() || p.id;
  const title = p.title?.trim() || (rest.length ? rest.join(' — ').trim() : null);
  const color = p.color && HEX_COLOR.test(p.color) ? p.color : personaColor(p.id);
  return { name, title, color, initials: personaInitials(name), avatarUrl: p.avatar_url || null };
}

// ---------------------------------------------------------------------------
// Presenter size: a larger chip for projectors and recordings. Persisted per
// browser; `?presenter=1` / `?presenter=0` in the URL sets it.
// ---------------------------------------------------------------------------

const PRESENTER_KEY = 'ucapp.personaPresenter';

export function readPresenterMode(): boolean {
  try {
    const param = new URLSearchParams(window.location.search).get('presenter');
    if (param === '1' || param === '0') {
      localStorage.setItem(PRESENTER_KEY, param);
      return param === '1';
    }
    return localStorage.getItem(PRESENTER_KEY) === '1';
  } catch {
    return false;
  }
}

export function writePresenterMode(on: boolean): void {
  try {
    localStorage.setItem(PRESENTER_KEY, on ? '1' : '0');
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// Switch toast: switching personas reloads the page, so the "Now viewing as"
// toast is queued in sessionStorage and shown once by the next page load.
// ---------------------------------------------------------------------------

const SWITCHED_KEY = 'ucapp.personaSwitched';

export function markPersonaSwitched(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(SWITCHED_KEY, id);
    else sessionStorage.removeItem(SWITCHED_KEY);
  } catch {
    /* ignore */
  }
}

/** Returns the persona id queued before the reload (once), or null. */
export function takePersonaSwitched(): string | null {
  try {
    const id = sessionStorage.getItem(SWITCHED_KEY);
    if (id) sessionStorage.removeItem(SWITCHED_KEY);
    return id;
  } catch {
    return null;
  }
}

// Places where Alt+[ / Alt+] belongs to the focused widget, or where the reload
// a switch triggers would throw away unsaved input.
const CYCLE_IGNORED_WITHIN = '[role="dialog"], [role="alertdialog"], .cm-editor, .monaco-editor';

/** Alt+] (next) / Alt+[ (previous): returns the step, or 0 when the event isn't the shortcut. */
export function personaCycleStep(e: KeyboardEvent): -1 | 0 | 1 {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat || e.defaultPrevented) return 0;
  const target = e.target as HTMLElement | null;
  if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return 0;
  if (target?.closest?.(CYCLE_IGNORED_WITHIN)) return 0;
  if (e.code === 'BracketRight') return 1;
  if (e.code === 'BracketLeft') return -1;
  return 0;
}

/** Next persona index when cycling; from "no persona" the first step lands on either end. */
export function cyclePersonaIndex(current: number, step: 1 | -1, count: number): number {
  if (count === 0) return -1;
  if (current < 0) return step > 0 ? 0 : count - 1;
  return (current + step + count) % count;
}

// ---------------------------------------------------------------------------
// Chip density: the header shares its width with the search, the sidebar and
// the Ask Ontos panel, so the chip steps down instead of squeezing the search.
// Thresholds are border-box header widths (px) that leave the search about 380 px,
// below which its placeholder and Advanced button start to overlap.
// ---------------------------------------------------------------------------

export type ChipDensity = 'full' | 'name' | 'avatar';

export function chipDensity(headerWidth: number, presenter: boolean): ChipDensity {
  if (headerWidth >= (presenter ? 1260 : 1180)) return 'full';
  if (headerWidth >= (presenter ? 1180 : 1100)) return 'name';
  return 'avatar';
}
