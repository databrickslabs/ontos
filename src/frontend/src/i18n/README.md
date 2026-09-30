# Internationalization (i18n) Guide

This application uses **react-i18next** for internationalization support.

## Current Languages

- 🇺🇸 **English (en)** - Default language
- 🇩🇪 **German (de)**

## Directory Structure

```
src/i18n/
├── config.ts              # i18n configuration
├── locales/
│   ├── en/               # English translations
│   │   ├── common.json   # Common UI elements, actions, statuses
│   │   ├── navigation.json
│   │   ├── settings.json
│   │   └── features.json
│   └── de/               # German translations
│       ├── common.json
│       ├── navigation.json
│       ├── settings.json
│       └── features.json
└── README.md
```

## Namespaces

Translations are organized into namespaces for better modularity:

- **common**: Shared UI elements (buttons, actions, statuses, validation messages)
- **navigation**: Navigation menu labels and groups
- **settings**: Settings page content
- **features**: Feature-specific translations (to be expanded)

## Usage in Components

### Basic Usage

```tsx
import { useTranslation } from 'react-i18next';

function MyComponent() {
  const { t } = useTranslation('common');

  return (
    <button>{t('actions.save')}</button>
  );
}
```

### Multiple Namespaces

```tsx
import { useTranslation } from 'react-i18next';

function MyComponent() {
  const { t } = useTranslation(['settings', 'common']);

  return (
    <div>
      <h1>{t('settings:title')}</h1>
      <button>{t('common:actions.cancel')}</button>
    </div>
  );
}
```

### With Interpolation

```tsx
// In translation file:
// "welcome": "Welcome, {{name}}!"

const { t } = useTranslation();
<p>{t('welcome', { name: 'User' })}</p>
```

## Adding New Translations

### 1. Add Translation Keys

Add your translation keys to the appropriate namespace files:

**en/common.json:**
```json
{
  "myFeature": {
    "title": "My Feature",
    "description": "Feature description"
  }
}
```

**de/common.json:**
```json
{
  "myFeature": {
    "title": "Meine Funktion",
    "description": "Funktionsbeschreibung"
  }
}
```

### 2. Use in Components

```tsx
const { t } = useTranslation('common');
<h1>{t('myFeature.title')}</h1>
```

## Adding New Languages

1. Create a new directory in `src/i18n/locales/` (e.g., `fr/` for French)
2. Copy all JSON files from `en/` to the new directory
3. Translate all values (keep keys the same)
4. No manual imports are needed. The i18n config auto-discovers files via `import.meta.glob`.
5. Add the language to the LanguageSelector component:

```tsx
const languages = [
  // ... existing languages
  { code: 'fr', name: 'Français', flag: '🇫🇷' },
];
```

## Language Selector

The language selector is located in the app header (top-right corner) as a globe icon (🌐).

Users can:
- Click the globe icon to see available languages
- Select their preferred language
- The selection is persisted in localStorage
- Language preference persists across browser sessions

## Testing

Playwright tests are available in `src/frontend/tests/i18n.spec.ts`:

```bash
# Run i18n tests
npm run test:e2e -- tests/i18n.spec.ts

# Run in UI mode
npm run test:e2e:ui -- tests/i18n.spec.ts
```

## Tooling & Guardrails (issue #471)

Two scripts under `src/scripts/` (wired as npm scripts) drive and protect the migration:

| Command | What it does |
|---------|--------------|
| `npm run check:i18n` | Validates locale parity: every locale has the same keys per namespace, and every `t('...')` key used in code is defined. Non-zero exit on missing namespaces/keys (CI gate). |
| `npm run audit:i18n` | Heuristic scan for user-facing strings **not yet** wrapped in `t(...)` (JSX text + translatable attributes). The migration worklist. |
| `python3 src/scripts/check_translations.py --scaffold` | Brings every non-`en` locale up to `en`'s key set: creates missing namespace files, seeds missing keys with a `__TODO__ <english>` value (preserving existing translations), and writes a manifest of seeded keys. |

**`__TODO__` convention:** an untranslated value is prefixed with `__TODO__ ` so the gap is visible/greppable rather than silently falling back to English. Translating a key means replacing the value and removing the marker. (Zero `__TODO__` markers remain as of the completed migration.)

**ESLint guardrail:** `i18next/no-literal-string` (`warn`) flags new hardcoded JSX text; test/config/i18n code is excluded. Consider flipping to `error` in `eslint.config.js` once `audit:i18n` is confirmed clean of true positives, to block regressions in CI.

## Migration Status

### ✅ Completed (issue #471)
- Infrastructure (react-i18next, auto-discovery config) + 7 locales (en, de, es, fr, it, ja, nl)
- Language selector in header; persistence across reloads
- Tooling & guardrails above (`check:i18n`, `audit:i18n`, `--scaffold`, ESLint rule)
- **All views, components, dialogs, wizards, panels, navigation, feature configs, toasts, and validation messages migrated to `t(...)`** across every namespace (`check:i18n` passes; `audit:i18n` shows only non-translatable false-positives)
- **Full locale parity** — every namespace has identical keys in all 7 locales
- **Real translations** for de/es/fr/it/ja/nl (0 `__TODO__` markers remaining)
- Playwright coverage across all 7 locales (`tests/i18n-locales.spec.ts`)

## Best Practices

1. **Keep keys organized**: Use nested objects for related translations
2. **Use descriptive keys**: `actions.save` not `btnSave`
3. **Avoid hardcoded strings**: Always use translation keys
4. **Default to 'common' namespace**: For shared UI elements
5. **Create feature namespaces**: For complex features with many strings
6. **Test both languages**: Always verify translations display correctly
7. **Use pluralization**: For count-dependent text (see react-i18next docs)
8. **Context-aware translations**: Use different keys for context-specific meanings

## Resources

- [react-i18next Documentation](https://react.i18next.com/)
- [i18next Documentation](https://www.i18next.com/)
- [Translation Management Tools](https://www.i18next.com/overview/plugins-and-utils#translation-management)

## Future Enhancements

- [ ] Add more languages (French, Spanish, etc.)
- [ ] Implement date/time localization using date-fns locales
- [ ] Number formatting per locale
- [ ] Currency formatting
- [ ] RTL (Right-to-Left) support for Arabic, Hebrew
- [ ] Translation extraction tool for developers
- [ ] Integration with translation management platform (e.g., Lokalise, Crowdin)
