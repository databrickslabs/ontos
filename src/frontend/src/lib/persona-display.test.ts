import { describe, it, expect, beforeEach } from 'vitest';
import {
  personaDisplay,
  personaColor,
  personaInitials,
  readPresenterMode,
  writePresenterMode,
  markPersonaSwitched,
  takePersonaSwitched,
  personaCycleStep,
  cyclePersonaIndex,
  chipDensity,
} from './persona-display';

const base = { email: 'p@test.local', groups: null };

describe('personaDisplay', () => {
  it('splits name and title from the label when no explicit fields are set', () => {
    const d = personaDisplay({ ...base, id: 'priya', label: 'Priya Raman — Data Contract Engineer, Data Foundations' });
    expect(d.name).toBe('Priya Raman');
    expect(d.title).toBe('Data Contract Engineer, Data Foundations');
    expect(d.initials).toBe('PR');
    expect(d.avatarUrl).toBeNull();
  });

  it('prefers display_name, title, color and avatar_url', () => {
    const d = personaDisplay({
      ...base,
      id: 'x',
      label: 'Ignored — Ignored',
      display_name: 'Joost de Vries',
      title: 'Data Steward',
      color: '#2563eb',
      avatar_url: '/api/test/personas/x/avatar',
    });
    expect(d).toMatchObject({ name: 'Joost de Vries', title: 'Data Steward', color: '#2563eb', initials: 'JV' });
    expect(d.avatarUrl).toBe('/api/test/personas/x/avatar');
  });

  it('has no title for a plain label and ignores a non-hex colour', () => {
    const d = personaDisplay({ ...base, id: 'steward', label: 'Data Steward', color: 'red; x' });
    expect(d.name).toBe('Data Steward');
    expect(d.title).toBeNull();
    expect(d.color).toBe(personaColor('steward'));
  });
});

describe('personaColor / personaInitials', () => {
  it('derives a stable colour from the id', () => {
    expect(personaColor('priya')).toBe(personaColor('priya'));
    expect(personaColor('priya')).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('uses capitalised words for initials, skipping particles', () => {
    expect(personaInitials('Joost de Vries')).toBe('JV');
    expect(personaInitials('admin')).toBe('A');
    expect(personaInitials('')).toBe('?');
  });
});

describe('presenter mode', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('persists the toggle', () => {
    expect(readPresenterMode()).toBe(false);
    writePresenterMode(true);
    expect(readPresenterMode()).toBe(true);
  });

  it('lets ?presenter=1 / ?presenter=0 set and persist it', () => {
    window.history.replaceState({}, '', '/?presenter=1');
    expect(readPresenterMode()).toBe(true);
    window.history.replaceState({}, '', '/');
    expect(readPresenterMode()).toBe(true);
    window.history.replaceState({}, '', '/?presenter=0');
    expect(readPresenterMode()).toBe(false);
  });
});

describe('switch toast handoff', () => {
  it('hands the switched persona to the next page load exactly once', () => {
    markPersonaSwitched('priya');
    expect(takePersonaSwitched()).toBe('priya');
    expect(takePersonaSwitched()).toBeNull();
  });

  it('clears the handoff when switching back to the real identity', () => {
    markPersonaSwitched('priya');
    markPersonaSwitched(null);
    expect(takePersonaSwitched()).toBeNull();
  });
});

describe('persona cycling', () => {
  const key = (code: string, init: KeyboardEventInit = {}, target?: HTMLElement) => {
    const e = new KeyboardEvent('keydown', { code, altKey: true, ...init });
    if (target) Object.defineProperty(e, 'target', { value: target });
    return e;
  };

  it('maps Alt+] / Alt+[ and ignores other combinations and text fields', () => {
    expect(personaCycleStep(key('BracketRight'))).toBe(1);
    expect(personaCycleStep(key('BracketLeft'))).toBe(-1);
    expect(personaCycleStep(key('BracketRight', { altKey: false }))).toBe(0);
    expect(personaCycleStep(key('BracketRight', { metaKey: true }))).toBe(0);
    expect(personaCycleStep(key('KeyA'))).toBe(0);
    expect(personaCycleStep(key('BracketRight', {}, document.createElement('input')))).toBe(0);
    expect(personaCycleStep(key('BracketRight', { shiftKey: true }))).toBe(0);
    expect(personaCycleStep(key('BracketRight', { repeat: true }))).toBe(0);
  });

  it('leaves dialogs and code editors alone', () => {
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    const inner = document.createElement('button');
    dialog.appendChild(inner);
    expect(personaCycleStep(key('BracketRight', {}, inner))).toBe(0);
    const editor = document.createElement('div');
    editor.className = 'cm-editor';
    const line = document.createElement('div');
    editor.appendChild(line);
    expect(personaCycleStep(key('BracketRight', {}, line))).toBe(0);
  });

  it('wraps around and starts at either end from no persona', () => {
    expect(cyclePersonaIndex(-1, 1, 3)).toBe(0);
    expect(cyclePersonaIndex(-1, -1, 3)).toBe(2);
    expect(cyclePersonaIndex(2, 1, 3)).toBe(0);
    expect(cyclePersonaIndex(0, -1, 3)).toBe(2);
    expect(cyclePersonaIndex(-1, 1, 0)).toBe(-1);
  });
});

describe('chipDensity', () => {
  it('steps down as the header narrows, with more room needed in presenter size', () => {
    expect(chipDensity(1180, false)).toBe('full');
    expect(chipDensity(1180, true)).toBe('name');
    expect(chipDensity(1260, true)).toBe('full');
    expect(chipDensity(1100, false)).toBe('name');
    expect(chipDensity(1100, true)).toBe('avatar');
    expect(chipDensity(760, false)).toBe('avatar');
  });
});
