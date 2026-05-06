# PRD: UI branding and display customization

## Problem Statement

Deployers of the application need to **re-skin** the product so it feels like their own organization’s tool, not a vendor-branded shell. Today, key identity signals are effectively fixed: the **product name** is embedded throughout translated copy and some views, while **logo** customization exists only as an image URL and **custom CSS** as an advanced escape hatch. The **browser tab title** and **favicon** remain static from the shipped frontend assets. Administrators can change some appearance settings, but they cannot complete a simple, guided “white label lite” flow (name + iconography + tab chrome) without hunting strings or relying solely on CSS.

From an operator’s perspective, the gap is **discoverability and completeness**: branding is split between runtime settings, static build artifacts, and dozens of locale strings, so changes are fragile and incomplete across languages and surfaces.

## Solution

Introduce **first-class branding fields** stored with existing UI customization settings: a **global display name**, an optional **short name** for compact UI, and a **favicon URL**, alongside the existing custom logo URL, about content, i18n toggle, and custom CSS. These values are exposed on the **same unauthenticated bootstrap endpoint** the SPA already uses so every session applies branding early.

Copy that currently hardcodes the vendor product name in translations is refactored to use **i18n interpolation** (a single `appName` variable resolved from settings with a safe default when unset). After load and after save, the client **updates document title** and **injects or replaces the favicon** in the document head, mirroring how custom CSS is already injected.

Administrators configure everything from the **UI Customization** settings page with validation, previews, and clear guidance that some artifacts (e.g. install-time PWA manifest name) may remain static until a future enhancement.

## User Stories

1. As an **Administrator**, I want to set a **global application display name**, so that the product is identified consistently with my organization’s name across the UI.
2. As an **Administrator**, I want to set an **optional short name**, so that compact areas (tabs, side labels) can show an abbreviation without redesigning layouts.
3. As an **Administrator**, I want to set a **favicon URL** with the same safety expectations as the logo URL, so that browser tabs and bookmarks reflect our brand.
4. As an **Administrator**, I want to **preview** logo and favicon before saving, so that I can catch broken or blocked URLs early.
5. As an **Administrator**, I want **display name and favicon** to persist in the same place as other UI customization options, so that I do not hunt multiple configuration surfaces.
6. As an **Administrator**, I want **validation** on URLs and reasonable limits on name length, so that I cannot accidentally break the layout or inject unsafe content through the name field.
7. As an **Administrator**, I want saving branding to **refresh runtime appearance** without redeploying the app bundle, so that changes take effect for new loads and for my current session after save.
8. As an **end user**, I want the **welcome and navigation copy** in my selected language to use the **configured display name** instead of a hardcoded vendor name, so that the experience feels coherent in every supported locale.
9. As an **end user**, I want the **browser tab title** to reflect the configured name, so that I can find the correct tab among many.
10. As an **end user**, I want the **favicon** in the tab to match the organization, so that visual scanning matches my expectation of internal tools.
11. As a **reader-only user**, I want branding applied **without needing settings API write access**, so that I still see the tenant’s identity (bootstrap remains public read).
12. As a **security reviewer**, I want display names treated as **plain text** and URLs restricted to safe schemes, so that branding cannot be used as an XSS vector.
13. As an **operator**, I want fresh installs to start with the **shipped default product name** when no branding is configured, so that the app is immediately usable without setting environment variables (env-level defaults are explicitly out of scope for v1).
14. As an **Administrator**, I want clearing the display name to fall back to a **documented default product name**, so that empty configuration does not produce blank titles or broken grammar.
15. As an **Administrator**, I want the **About** experience to remain markdown-driven, so that legal or extended positioning text stays separate from the short display name.
16. As an **Administrator**, I want **custom CSS** to remain supported as the advanced theming path, so that power users can still tune shadcn or layout tokens without waiting for preset pickers.
17. As a **translator or localization owner**, I want product-name phrases in JSON to use **interpolation placeholders** instead of literal vendor strings, so that one branding setting updates all locales consistently.
18. As a **developer**, I want a **single module** responsible for applying branding side effects (CSS injection already exists; extend with favicon and title), so that behavior stays consistent and testable.
19. As a **QA engineer**, I want automated checks that the **public branding JSON** includes the new fields when set, so that regressions in the bootstrap contract are caught early.
20. As an **Administrator**, I want **inline help text** explaining which surfaces update immediately vs which remain build-time static (e.g. PWA manifest), so that I set correct expectations for my organization.
21. As an **end user** using **screen readers**, I want landmark and page titles to remain meaningful when the display name changes, so that accessibility is not degraded by customization.
22. As an **Administrator**, I want invalid favicon or logo URLs to show **actionable error messages**, so that I can fix CDN permissions or HTTPS issues quickly.
23. As a **multi-tab user**, I want branding updates after an admin save to apply when the store **refetches**, so that long-lived sessions can pick up changes without a full redeploy.
24. As an **Administrator**, I want branding changes to flow through the **same settings update path** as other UI customization keys, so that any existing logging, change tracking, or governance hooks on settings updates apply automatically (no new audit subsystem in v1).
25. As an **integrator**, I want the **admin settings update API** to accept the new keys alongside existing UI keys in one payload, so that automation scripts can configure branding idempotently.
26. As an **end user**, I want **search / assistant / catalog** surfaces that today say “Ask &lt;vendor&gt;” to use the **configured name**, so that the copilot metaphor matches our internal assistant branding.
27. As an **Administrator**, I want the **short name** to be optional with sensible UI when omitted, so that I am not forced to invent an acronym.
28. As a **mobile browser user**, I want the favicon change to apply where the browser reads `link rel="icon"`, so that home-screen shortcuts look correct when the browser uses that metadata.
29. As a **Databricks App operator**, I want branding to work in **embedded** contexts where the app runs inside another shell, so that tab title and favicon still help disambiguation (within browser constraints).
30. As a **future maintainer**, I want the **default product name constant** defined in one conceptual place on the client, so that fallback copy does not drift across modules.

## Implementation Decisions

- **Single global display name** (not per-locale DB fields): all supported languages use the same configured name via i18n interpolation in strings that previously hardcoded the vendor name.
- **Optional short name**: persisted for compact copy; UI may use it selectively where grammar allows (e.g. “Ask {{shortName}}” with fallback to display name if short name empty).
- **v1 scope is branding-only**: no curated color preset pickers; advanced appearance remains **custom CSS** as today.
- **Persistence model**: new keys stored in the same **app settings** key-value store pattern as existing UI customization keys, loaded into the shared **application settings** object on startup and updated on admin save (same mutation path as logo and CSS).
- **Public read contract**: extend the existing **unauthenticated** UI customization bootstrap endpoint so the SPA can fetch names, favicon, logo, CSS, and i18n flag before interactive auth flows complete.
- **Admin write contract**: extend the existing **authenticated** settings update endpoint to accept the new snake_case fields alongside current UI fields.
- **Runtime application**: after successful fetch (and after save-triggered refresh), the client updates **document title**, **favicon link element(s)** in the document head, and continues to inject **custom CSS** via the existing mechanism.
- **Interpolation strategy**: locale files use placeholders (e.g. `Welcome to {{appName}}`); React call sites pass the effective display name from client state with a **fixed default** when the setting is null or empty.
- **Validation**: display name — plain text, max length, strip control characters; URLs — same **http/https** rules as the existing logo URL validation pattern.
- **Deep module**: encapsulate “**apply branding side effects**” (CSS already partially there; add favicon + title) behind a small, stable interface invoked from the central client store after hydration so views do not duplicate DOM manipulation.
- **Backward compatibility**: missing DB keys behave as today (default name, no custom favicon); no breaking change to existing API consumers beyond **additive** JSON fields.
- **Static build limitations** documented for v1: **PWA manifest display name** and some static HTML meta remain unchanged unless a future phase adds a server-generated manifest or build-time templating.

## Testing Decisions

- **Good tests** assert **observable behavior and contracts**: HTTP response shapes for public bootstrap and admin update paths, and that optional fields round-trip when set and clear when nulled.
- **Modules to test**: primarily the **settings HTTP layer** (existing integration/e2e style tests that already assert UI customization payloads); optionally pure **URL validation / string sanitization** helpers if extracted for unit testing.
- **Prior art**: existing tests that call **GET** public UI customization and **GET/PUT** full settings; extend expectations **additively** for new keys without coupling to DOM implementation details of favicon injection.
- **Non-goals for automated tests in v1**: pixel-diff branding, full cross-browser PWA manifest behavior, or every interpolated string in every locale (spot-check English + one non-English locale in manual QA if needed).

## Acceptance Criteria

A v1 implementation is complete when **all** of the following are true:

1. **Settings model**: `app_display_name`, `app_short_name`, and `favicon_url` exist as optional string fields on the application settings, persisted via the same `app_settings` key-value pattern as the existing UI customization keys, and survive process restart.
2. **Public bootstrap contract**: `GET /api/settings/ui-customization` returns the three new fields (snake_case) alongside existing UI customization fields, without authentication, and returns `null` (or an absent value, consistent with current style) when unset.
3. **Admin write contract**: `PUT /api/settings` accepts the three new snake_case fields in the same payload as existing UI keys, persists them, and a subsequent `GET` reflects the new values; clearing a field (empty string or null per existing convention) reverts to the default behavior described in story 14.
4. **Validation**: display name is plain text with a documented max length and stripped control characters; `favicon_url` is validated with the same scheme rules as the existing custom logo URL; invalid input returns an actionable error from the settings update endpoint and is surfaced inline in the settings form.
5. **Runtime application**: on initial SPA load and after a successful save, the client (a) sets `document.title` to the effective display name, (b) injects or replaces the favicon `<link rel="icon">` in `<head>` when `favicon_url` is set and removes the override when cleared, and (c) continues to inject custom CSS via the existing mechanism.
6. **i18n interpolation**: locale files no longer hardcode the vendor product name in the strings touched by this work; affected strings use an `appName` (and where applicable `shortName`) interpolation variable resolved from client state with a fixed default constant; English plus at least one additional shipped locale are spot-checked.
7. **Default fallback**: when `app_display_name` is unset, the UI, document title, and i18n interpolations render the documented default product name; no string shows an empty placeholder or a literal `{{appName}}`.
8. **Settings UI**: the UI Customization settings view exposes inputs for display name, short name, and favicon URL with previews for logo and favicon, inline help that names the surfaces which update immediately vs remain build-time static (PWA manifest, static `index.html` `<title>`), and respects existing permission gates for settings writes.
9. **Backward compatibility**: existing API consumers see only **additive** JSON fields; deployments with no new keys configured behave exactly as before this change.
10. **Tests**: integration / e2e tests for the public bootstrap and settings update endpoints are extended to assert the three new fields round-trip, including the `null`/cleared case; no test asserts low-level DOM details of favicon injection.

## Out of Scope

- **Per-locale marketing names** stored separately in the database.
- **Admin UI color pickers** or preset themes that write design tokens (beyond custom CSS textarea).
- **Server-generated `manifest.json`** or dynamic Open Graph tags for social sharing.
- **Logo or favicon file upload** to Unity Catalog volumes or app storage (URLs only in v1).
- **Renaming backend infrastructure identifiers** (e.g. Databricks app technical name) or Unity Catalog comments that reference an internal product name.
- **Email / notification templates** branding unless already covered by a separate notifications PRD.

## Further Notes

- Problem framing and scope choices (**single global name**, **branding-only v1**) were aligned in a prior design conversation; this PRD captures them for delivery and review.
- **Suggested issue labels** (mapped to existing repo labels): `enhancement`, `feature`, `feat/settings`, `python`, `javascript`.
