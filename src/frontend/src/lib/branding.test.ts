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
  contrastRatio,
  describeContrast,
  deriveDarkColor,
  normalizeHexColor,
  resolveDarkTheme,
  formatContrastRatio,
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
    expect(hexToHslTriplet('#2563eb')).toBe('221 83% 53%');
    expect(hexToHslTriplet('red')).toBeNull();
    expect(hexToHslTriplet('#fff;}body{')).toBeNull();
  });

  it('picks a readable foreground', () => {
    expect(pickForeground('#2563eb')).toBe('0 0% 98%');
    expect(pickForeground('#93c5fd')).toBe('0 0% 9%');
    expect(pickForeground('#ffffff')).toBe('0 0% 9%');
  });

  it('builds no CSS when unset and derives missing dark colors from the light ones', () => {
    expect(buildThemeCss(null)).toBe('');
    expect(buildThemeCss({ primary: 'nope' })).toBe('');
    const css = buildThemeCss({ primary: '#2563eb', accentDark: '#1e293b' });
    expect(css).toContain(':root {\n  --primary: 221 83% 53%;');
    const derived = hexToHslTriplet(deriveDarkColor('#2563eb', 'primary'));
    expect(derived).not.toBe('221 83% 53%');
    expect(css).toContain(`.dark {\n  --primary: ${derived};`);
    expect(css).toMatch(/\.dark \{[\s\S]*--accent: 217 33% 17%;/);
    // A configured dark color wins over the derived one
    expect(buildThemeCss({ primary: '#2563eb', primaryDark: '#93c5fd' }))
      .toContain('.dark {\n  --primary: 212 96% 78%;');
  });

  it('computes WCAG contrast and the text color for a background', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#fff', '#fff')).toBeCloseTo(1, 5);
    expect(contrastRatio('red', '#fff')).toBeNull();
    const darkBlue = describeContrast('#1d4ed8');
    expect(darkBlue).toMatchObject({ foreground: 'light', foregroundHex: '#fafafa', meetsAA: true });
    // Light text still reads best on this blue, but it falls just short of AA
    const blue = describeContrast('#2f6fed');
    expect(blue).toMatchObject({ foreground: 'light', meetsAA: false });
    expect(blue!.ratio).toBeGreaterThan(4.3);
    // Mid-tone yellow: neither text color reaches AA with the light one; dark text wins
    const yellow = describeContrast('#f5b400');
    expect(yellow).toMatchObject({ foreground: 'dark', meetsAA: true });
    const mid = describeContrast('#777777');
    expect(mid!.meetsAA).toBe(false);
    expect(describeContrast('')).toBeNull();
    expect(formatContrastRatio(4.49)).toBe('4.4');
    expect(formatContrastRatio(4.5)).toBe('4.5');
  });

  it('derives dark-mode colors that read on the dark background', () => {
    const darkBackground = '#11171d';
    const primary = deriveDarkColor('#2563eb', 'primary')!;
    expect(primary).toMatch(/^#[0-9a-f]{6}$/);
    expect(contrastRatio(primary, darkBackground)!).toBeGreaterThanOrEqual(4.5);
    // Same hue, only lighter
    expect(hexToHslTriplet(primary)!.split(' ')[0]).toBe('221');
    // An already light primary is kept
    expect(deriveDarkColor('#93c5fd', 'primary')).toBe('#93c5fd');
    // Accent becomes a dark, muted surface of the same hue
    const accent = deriveDarkColor('#dbeafe', 'accent')!;
    // (hex rounding moves hue/saturation by a point)
    expect(hexToHslTriplet(accent)).toMatch(/^21[34] (29|30)% 20%$/);
    expect(deriveDarkColor('nope', 'accent')).toBeNull();
    expect(resolveDarkTheme({ primary: '#2563eb', accentDark: '#ABC' })).toEqual({
      primary,
      accent: '#aabbcc',
    });
    expect(normalizeHexColor(' #ABC ')).toBe('#aabbcc');
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
