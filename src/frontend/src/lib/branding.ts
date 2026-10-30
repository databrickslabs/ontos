/**
 * Branding side-effects module (issue #240).
 *
 * Single owner of runtime DOM mutations for product branding:
 *  - document.title
 *  - <link rel="icon"> in <head>
 *  - theme color overrides (<style id="branding-theme">)
 *
 * Custom CSS injection lives in the UI customization store; both are invoked
 * from the same fetch path so views never duplicate DOM manipulation.
 */

import { getAssetPath } from '@/utils/asset-path';

/** Canonical fallback product name. Single source of truth for the client. */
export const DEFAULT_APP_NAME = 'Ontos';

/** Filesystem path of the shipped favicon, kept in sync with `index.html`. */
const DEFAULT_FAVICON_HREF = '/ontos-logo.svg';

const FAVICON_LINK_ID = 'app-favicon';

let originalFaviconHref: string | null = null;

export interface BrandingInput {
  displayName?: string | null;
  faviconUrl?: string | null;
}

/**
 * Resolve the effective application name with safe fallback.
 * Treats whitespace-only strings as unset.
 */
export function resolveAppName(displayName?: string | null): string {
  if (typeof displayName !== 'string') return DEFAULT_APP_NAME;
  const trimmed = displayName.trim();
  return trimmed || DEFAULT_APP_NAME;
}

/**
 * Resolve the effective short name, falling back to the (full) display name.
 */
export function resolveShortName(
  shortName?: string | null,
  displayName?: string | null,
): string {
  if (typeof shortName === 'string') {
    const trimmed = shortName.trim();
    if (trimmed) return trimmed;
  }
  return resolveAppName(displayName);
}

/**
 * Apply branding side effects to the document. Idempotent.
 * Called from the UI customization store after fetch and after admin save.
 */
export function applyBranding({ displayName, faviconUrl }: BrandingInput): void {
  if (typeof document === 'undefined') return;

  document.title = resolveAppName(displayName);

  const link = ensureFaviconLink();
  if (link) {
    if (originalFaviconHref === null) {
      originalFaviconHref = link.getAttribute('href') || DEFAULT_FAVICON_HREF;
    }
    const cleaned = typeof faviconUrl === 'string' ? faviconUrl.trim() : '';
    const href = cleaned ? resolveBrandingAssetUrl(cleaned) : '';
    link.setAttribute('href', href || originalFaviconHref || DEFAULT_FAVICON_HREF);
  }
}

function ensureFaviconLink(): HTMLLinkElement | null {
  if (typeof document === 'undefined') return null;
  let link = document.querySelector<HTMLLinkElement>(`link#${FAVICON_LINK_ID}`);
  if (link) return link;

  link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
  if (link) {
    link.id = FAVICON_LINK_ID;
    return link;
  }

  link = document.createElement('link');
  link.id = FAVICON_LINK_ID;
  link.rel = 'icon';
  document.head.appendChild(link);
  return link;
}

/**
 * Resolve a configured branding image (logo, favicon).
 *
 * A root-relative path such as `/branding/acme/logo.svg` names a file shipped
 * in the frontend `public/` dir, so it goes through `getAssetPath` (prod serves
 * those under `/static`). `/api/...` and `/static/...` paths and absolute URLs
 * are used as given. Returns null for blank input.
 */
export function resolveBrandingAssetUrl(url?: string | null): string | null {
  if (typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (!trimmed) return null;
  const isAppAsset = trimmed.startsWith('/') && !trimmed.startsWith('//');
  if (!isAppAsset || /^\/(api|static)\//.test(trimmed)) return trimmed;
  return getAssetPath(trimmed);
}

/**
 * Image URL the backend accepts for branding images: an http(s) URL or a
 * root-relative app asset path (no `//host`, whitespace or backslashes).
 * Empty input is valid (unset).
 */
export function isValidImageUrl(url: string): boolean {
  if (!url) return true;
  if (url.startsWith('/') && !url.startsWith('//')) return !/[\s\\]/.test(url);
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Theme colors from the branding config, each `#rgb`/`#rrggbb` or unset. */
export interface BrandingTheme {
  primary?: string | null;
  primaryDark?: string | null;
  accent?: string | null;
  accentDark?: string | null;
}

const THEME_STYLE_ID = 'branding-theme';
const CUSTOM_CSS_STYLE_ID = 'custom-user-css';
const HEX_COLOR_RE = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
// Foregrounds used by the shipped theme (index.css), as HSL triplets and hex
const LIGHT_FOREGROUND = '0 0% 98%';
const DARK_FOREGROUND = '0 0% 9%';
const LIGHT_FOREGROUND_HEX = '#fafafa';
const DARK_FOREGROUND_HEX = '#171717';
/** WCAG AA contrast for normal text. */
export const WCAG_AA_CONTRAST = 4.5;

function parseHex(hex?: string | null): [number, number, number] | null {
  if (typeof hex !== 'string' || !HEX_COLOR_RE.test(hex.trim())) return null;
  let h = hex.trim().slice(1);
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** RGB (0-255) -> unrounded [hue 0-360, saturation 0-100, lightness 0-100]. */
function rgbToHsl(rgb: [number, number, number]): [number, number, number] {
  const [r, g, b] = rgb.map((v) => v / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  let s = 0;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return [h, s * 100, l * 100];
}

function hslToHex(h: number, s: number, l: number): string {
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const channel = (n: number) =>
    Math.round(255 * (light - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))));
  return `#${[0, 8, 4].map((n) => channel(n).toString(16).padStart(2, '0')).join('')}`;
}

/** `#2563eb` -> `"221 83% 53%"` (the `H S% L%` form the theme variables use). */
export function hexToHslTriplet(hex?: string | null): string | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const [h, s, l] = rgbToHsl(rgb);
  return `${Math.round(h) % 360} ${Math.round(s)}% ${Math.round(l)}%`;
}

function relativeLuminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two hex colors (1-21), or null when one is invalid. */
export function contrastRatio(a?: string | null, b?: string | null): number | null {
  const ra = parseHex(a);
  const rb = parseHex(b);
  if (!ra || !rb) return null;
  const [hi, lo] = [relativeLuminance(ra), relativeLuminance(rb)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Text color picked for a background color and how well it reads on it. */
export interface ContrastInfo {
  foreground: 'light' | 'dark';
  foregroundHex: string;
  ratio: number;
  meetsAA: boolean;
}

/**
 * Pick a readable foreground for a background color: the light one when it
 * reaches WCAG AA (4.5:1) against the color, otherwise the higher-contrast one.
 */
export function describeContrast(hex?: string | null): ContrastInfo | null {
  if (!parseHex(hex)) return null;
  const vsLight = contrastRatio(hex, LIGHT_FOREGROUND_HEX) as number;
  const vsDark = contrastRatio(hex, DARK_FOREGROUND_HEX) as number;
  const light = vsLight >= WCAG_AA_CONTRAST || vsLight >= vsDark;
  const ratio = light ? vsLight : vsDark;
  return {
    foreground: light ? 'light' : 'dark',
    foregroundHex: light ? LIGHT_FOREGROUND_HEX : DARK_FOREGROUND_HEX,
    ratio,
    meetsAA: ratio >= WCAG_AA_CONTRAST,
  };
}

/** One decimal, rounded down so a ratio just under 4.5 never reads as "4.5". */
export function formatContrastRatio(ratio: number): string {
  return (Math.floor(ratio * 10) / 10).toFixed(1);
}

/** Foreground HSL triplet for a background color (see `describeContrast`). */
export function pickForeground(hex?: string | null): string | null {
  const info = describeContrast(hex);
  if (!info) return null;
  return info.foreground === 'light' ? LIGHT_FOREGROUND : DARK_FOREGROUND;
}

export type ThemeColorRole = 'primary' | 'accent';

// Background of the shipped dark theme (`.dark --background` in index.css)
const DARK_BACKGROUND_HEX = hslToHex(211, 24, 9);
const DERIVED_PRIMARY_MAX_LIGHTNESS = 85;
const DERIVED_ACCENT_MAX_SATURATION = 30;
const DERIVED_ACCENT_LIGHTNESS = 20;

/**
 * Dark-mode color derived from a light-mode one, used when no dark color is set.
 *
 * - primary (buttons, links, focus ring): same hue, lightened until it reaches
 *   WCAG AA against the dark background (at most 85% lightness).
 * - accent (hover/selected surfaces): same hue as a dark, muted surface.
 */
export function deriveDarkColor(hex: string | null | undefined, role: ThemeColorRole) {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const [h, s, l] = rgbToHsl(rgb);
  if (role === 'accent') {
    return hslToHex(h, Math.min(s, DERIVED_ACCENT_MAX_SATURATION), DERIVED_ACCENT_LIGHTNESS);
  }
  let lightness = l;
  let color = hslToHex(h, s, lightness);
  while (
    lightness < DERIVED_PRIMARY_MAX_LIGHTNESS
    && (contrastRatio(color, DARK_BACKGROUND_HEX) as number) < WCAG_AA_CONTRAST
  ) {
    lightness = Math.min(lightness + 1, DERIVED_PRIMARY_MAX_LIGHTNESS);
    color = hslToHex(h, s, lightness);
  }
  return color;
}

/** Normalize `#rgb`/`#rrggbb` to lowercase `#rrggbb`; null for anything else. */
export function normalizeHexColor(hex?: string | null): string | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  return `#${rgb.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

function themeBlock(selector: string, primary?: string | null, accent?: string | null): string {
  const lines: string[] = [];
  const p = hexToHslTriplet(primary);
  if (p) {
    lines.push(`--primary: ${p};`, `--primary-foreground: ${pickForeground(primary)};`);
    lines.push(`--ring: ${p};`);
  }
  const a = hexToHslTriplet(accent);
  if (a) lines.push(`--accent: ${a};`, `--accent-foreground: ${pickForeground(accent)};`);
  return lines.length ? `${selector} {\n  ${lines.join('\n  ')}\n}` : '';
}

/** Dark-mode colors in effect: the configured ones, else derived from the light ones. */
export function resolveDarkTheme(theme?: BrandingTheme | null) {
  return {
    primary: normalizeHexColor(theme?.primaryDark) || deriveDarkColor(theme?.primary, 'primary'),
    accent: normalizeHexColor(theme?.accentDark) || deriveDarkColor(theme?.accent, 'accent'),
  };
}

/**
 * CSS overriding the theme variables. A dark color that isn't set is derived
 * from the light one (`deriveDarkColor`). Empty string when nothing is configured.
 */
export function buildThemeCss(theme?: BrandingTheme | null): string {
  if (!theme) return '';
  const dark = resolveDarkTheme(theme);
  return [
    themeBlock(':root', theme.primary, theme.accent),
    themeBlock('.dark', dark.primary, dark.accent),
  ].filter(Boolean).join('\n');
}

/**
 * Inject (or remove) the theme overrides. The style goes before the admin's
 * custom CSS so a custom stylesheet can still override the branding colors.
 */
export function applyThemeColors(theme?: BrandingTheme | null): void {
  if (typeof document === 'undefined') return;
  const css = buildThemeCss(theme);
  let el = document.getElementById(THEME_STYLE_ID) as HTMLStyleElement | null;
  if (!css) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement('style');
    el.id = THEME_STYLE_ID;
    const customCss = document.getElementById(CUSTOM_CSS_STYLE_ID);
    document.head.insertBefore(el, customCss);
  }
  el.textContent = css;
}
