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
// Foregrounds used by the shipped theme (index.css)
const LIGHT_FOREGROUND = '0 0% 98%';
const DARK_FOREGROUND = '0 0% 9%';

function parseHex(hex?: string | null): [number, number, number] | null {
  if (typeof hex !== 'string' || !HEX_COLOR_RE.test(hex.trim())) return null;
  let h = hex.trim().slice(1);
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** `#2563eb` -> `"4 74% 56%"` (the `H S% L%` form the theme variables use). */
export function hexToHslTriplet(hex?: string | null): string | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
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
    h = Math.round(h * 60);
    if (h < 0) h += 360;
  }
  return `${h} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

/**
 * Pick a readable foreground for a background color: the light one when it
 * reaches WCAG AA (4.5:1) against the color, otherwise the higher-contrast one.
 */
export function pickForeground(hex?: string | null): string | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const vsLight = (0.96 + 0.05) / (lum + 0.05);
  const vsDark = (lum + 0.05) / (0.0085 + 0.05);
  return vsLight >= 4.5 || vsLight >= vsDark ? LIGHT_FOREGROUND : DARK_FOREGROUND;
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

/**
 * CSS overriding the theme variables. Dark mode falls back to the light value
 * when no dark-specific color is set. Empty string when nothing is configured.
 */
export function buildThemeCss(theme?: BrandingTheme | null): string {
  if (!theme) return '';
  return [
    themeBlock(':root', theme.primary, theme.accent),
    themeBlock('.dark', theme.primaryDark || theme.primary, theme.accentDark || theme.accent),
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
