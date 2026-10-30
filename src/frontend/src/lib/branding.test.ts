import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_APP_NAME,
  resolveAppName,
  resolveShortName,
  applyBranding,
  applyThemeColors,
  buildThemeCss,
  hexToHslTriplet,
  pickForeground,
  resolveBrandingAssetUrl,
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

describe('branding assets and theme colors', () => {
  it('resolves app asset paths and keeps URLs as given', () => {
    expect(resolveBrandingAssetUrl('  ')).toBeNull();
    expect(resolveBrandingAssetUrl(null)).toBeNull();
    // Vitest runs in dev mode, where public assets are served from the root
    expect(resolveBrandingAssetUrl('/branding/acme/mark.svg')).toBe('/branding/acme/mark.svg');
    expect(resolveBrandingAssetUrl('/api/branding/logo')).toBe('/api/branding/logo');
    expect(resolveBrandingAssetUrl('https://cdn.example/x.svg')).toBe('https://cdn.example/x.svg');
  });

  it('converts hex colors to HSL triplets and rejects anything else', () => {
    expect(hexToHslTriplet('#ff0000')).toBe('0 100% 50%');
    expect(hexToHslTriplet('#fff')).toBe('0 0% 100%');
    expect(hexToHslTriplet('#2563eb')).toBe('4 67% 51%');
    expect(hexToHslTriplet('red')).toBeNull();
    expect(hexToHslTriplet('#fff;}body{')).toBeNull();
  });

  it('picks a readable foreground', () => {
    expect(pickForeground('#2563eb')).toBe('0 0% 98%');
    expect(pickForeground('#93c5fd')).toBe('0 0% 9%');
    expect(pickForeground('#ffffff')).toBe('0 0% 9%');
  });

  it('builds no CSS when unset and falls back to light colors in dark mode', () => {
    expect(buildThemeCss(null)).toBe('');
    expect(buildThemeCss({ primary: 'nope' })).toBe('');
    const css = buildThemeCss({ primary: '#2563eb', accentDark: '#1e293b' });
    expect(css).toContain(':root {\n  --primary: 4 67% 51%;');
    expect(css).toMatch(/\.dark \{\n {2}--primary: 4 67% 51%;[\s\S]*--accent: 14 17% 20%;/);
  });

  it('injects the theme style before custom CSS and removes it when cleared', () => {
    document.head.innerHTML = '<style id="custom-user-css"></style>';
    applyThemeColors({ primary: '#2563eb' });
    const styles = Array.from(document.head.querySelectorAll('style')).map((el) => el.id);
    expect(styles).toEqual(['branding-theme', 'custom-user-css']);
    applyThemeColors({});
    expect(document.getElementById('branding-theme')).toBeNull();
  });
});
