import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_APP_NAME,
  resolveAppName,
  resolveShortName,
  applyBranding,
} from './branding';

describe('branding', () => {
  describe('resolveAppName', () => {
    it('returns the default for non-strings and blank input', () => {
      expect(resolveAppName(undefined)).toBe(DEFAULT_APP_NAME);
      expect(resolveAppName(null)).toBe(DEFAULT_APP_NAME);
      expect(resolveAppName('   ')).toBe(DEFAULT_APP_NAME);
    });

    it('trims and returns a provided name', () => {
      expect(resolveAppName('  Acme Data  ')).toBe('Acme Data');
    });
  });

  describe('resolveShortName', () => {
    it('prefers a non-blank short name', () => {
      expect(resolveShortName('  AD ', 'Acme Data')).toBe('AD');
    });

    it('falls back to the resolved app name', () => {
      expect(resolveShortName('   ', 'Acme Data')).toBe('Acme Data');
      expect(resolveShortName(null, null)).toBe(DEFAULT_APP_NAME);
    });
  });

  describe('applyBranding', () => {
    beforeEach(() => {
      document.head.innerHTML = '';
      document.title = '';
    });

    it('sets the document title from the display name', () => {
      applyBranding({ displayName: 'My Catalog' });
      expect(document.title).toBe('My Catalog');
    });

    it('creates a favicon link and sets a custom href', () => {
      applyBranding({ displayName: 'X', faviconUrl: 'https://cdn/x.png' });
      const link = document.querySelector<HTMLLinkElement>('link#app-favicon');
      expect(link).not.toBeNull();
      expect(link?.getAttribute('href')).toBe('https://cdn/x.png');
    });

    it('reuses an existing icon link and falls back to a non-empty href when cleared', () => {
      const existing = document.createElement('link');
      existing.rel = 'icon';
      existing.setAttribute('href', '/original.svg');
      document.head.appendChild(existing);

      // A blank favicon URL must never leave the href empty; it falls back to
      // the captured original (module-level, captured on first apply) or the
      // shipped default. Either way the href stays a usable, non-empty path.
      applyBranding({ displayName: 'X', faviconUrl: '   ' });
      expect(existing.id).toBe('app-favicon');
      expect(existing.getAttribute('href')).toBeTruthy();
      expect(existing.getAttribute('href')).not.toBe('');
    });
  });
});
