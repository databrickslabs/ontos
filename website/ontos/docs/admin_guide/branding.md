---
sidebar_position: 7
---
# Branding

Admins can adapt the look of the app to their organization in **Settings > UI Customization**
(or with environment variables). Everything is optional: with nothing set, the app looks as it does
by default.

| Setting (Settings form) | Environment variable | Notes |
| ----------------------- | -------------------- | ----- |
| Display name | `UI_APP_DISPLAY_NAME` | Up to 64 characters |
| Short name | `UI_APP_SHORT_NAME` | Up to 16 characters |
| Tagline | `UI_APP_TAGLINE` | Up to 80 characters; shown next to the name in the sidebar and under the welcome title on the home page |
| Logo | `UI_CUSTOM_LOGO_URL` | See *Image values* |
| Dark mode logo | `UI_CUSTOM_LOGO_DARK_URL` | Used in dark mode; the logo is used when empty |
| Favicon | `UI_FAVICON_URL` | See *Image values* |
| Primary / accent color, light mode | `UI_THEME_PRIMARY`, `UI_THEME_ACCENT` | `#rgb` or `#rrggbb` |
| Primary / accent color, dark mode | `UI_THEME_PRIMARY_DARK`, `UI_THEME_ACCENT_DARK` | When empty, derived from the light color |
| Show "Powered by Ontos" | `UI_SHOW_POWERED_BY` | `true` by default; the sidebar footer only appears while a custom name or logo is set |

A value saved in Settings overrides the environment variable. Saving an empty value clears it.

## Image values

A logo or favicon is either an `http(s)` URL or a root-relative path to a file served by the app
itself, for example `/branding/acme/logo.svg`. Other schemes (`javascript:`, `data:`, `file:`),
`//host/...` URLs, spaces, backslashes and `..` segments are refused. The app does not ship the
files for a root-relative path: whoever builds or deploys it places them in the frontend `public`
folder.

A logo of any shape keeps its aspect ratio, also in the collapsed sidebar.

## Theme colors

Colors must be `#rgb` or `#rrggbb`; they are stored as lowercase `#rrggbb`. An invalid value in an
environment variable is ignored, so a typo gives the default theme instead of an error.

The color becomes the app's primary or accent color (buttons, focus rings, highlights). The text
color on top of it is picked automatically, and the form shows its contrast ratio (WCAG AA needs
4.5:1 for normal text). Pick colors that reach AA: a mid-tone color can be hard to read whichever
text color is used. For example, `#2563eb` with white text reaches AA.

When no dark mode color is set, the primary color keeps its hue and is lightened until it reaches
4.5:1 on the dark background, and the accent becomes a dark, muted surface of the same hue.
