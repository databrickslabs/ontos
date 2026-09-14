# Feature Maturity Policy (GA / Beta / Alpha)

**Date**: 2026-08-31
**Owner**: Frontend + platform
**Source of truth**: `src/frontend/src/config/features.ts` (`FeatureMaturity`)

## What maturity means

Every **top-level, sidebar-visible feature** carries a `maturity` value in
`features.ts`. It gates visibility, not permissions (permissions are a
separate axis — see below).

| Level | Meaning | Default visibility | Bar to qualify |
|---|---|---|---|
| `ga` | Generally available. Stable API + UI, supported, safe for all users. | Always shown | Feature-complete for its scope; has tests (frontend + backend); no known data-loss or auth gaps; docs exist. |
| `beta` | Usable and maintained, but API/UI may still change; rough edges expected. | Shown by default (**Show Beta** on) | Implemented end-to-end and actively maintained; may lack full test coverage or polish. |
| `alpha` | Experimental / not officially supported. May be incomplete or change without notice. | **Hidden by default** (**Show Alpha** off) | Behind the alpha toggle deliberately, regardless of code maturity — signals "not committed to yet". |

Visibility is controlled per-user by two toggles in the user menu
(`feature-visibility-store.ts`): **Show Beta** (default on) and **Show
Alpha** (default off). GA is always visible. The `β` / `α` badges render in
the sidebar (`navigation.tsx`) and on the About cards (`about.tsx`).

## Current classification

| Maturity | Features |
|---|---|
| **GA** | Marketplace, Search, Data Catalog, Assets, Concepts, Contracts, Products, My Products, My Requests |
| **Beta** | Compliance, Master Data Management, Asset Reviews |
| **Alpha** | Security Features, Entitlements, Entitlements Sync, Estate Manager, Catalog Commander |

## Maturity is NOT the permission registry

There are two independent registries — do not conflate them:

- **`src/frontend/src/config/features.ts`** — maturity + sidebar registry.
  ~17 entries. The sidebar and About page are built **entirely** from this
  list, so by construction nothing sidebar-visible is missing a maturity.
- **`src/backend/src/common/features.py`** (`APP_FEATURES`) — the RBAC
  permission registry. ~50 entries. Many entries here are **not** top-level
  features and intentionally have no maturity: Settings sub-pages
  (`settings-*`, `data-domains`, `teams`, `projects`, …), Concepts
  sub-routes (`term-mapping` → `/concepts/mapping`, ontology generator →
  `/concepts/generator`), and `cross_cutting: True` capabilities surfaced
  inline rather than in the sidebar (`schema-importer`, `process-workflows`,
  `access-grants`, `comments`, `ontology`, `entity_relationships`).

**Rule: a route not present in `features.ts` is a sub-route or cross-cutting
capability by design — it is not an "unregistered feature" and should not be
promoted to a top-level maturity-tagged feature just because it has a route.**

Keep the display name for a given feature id aligned between the two
registries (the role editor falls back to the backend name; the sidebar uses
the i18n `features.<id>.name`).

## Outstanding: test debt on newly-promoted GA features

**Data Catalog** and **Assets** were promoted beta→GA on 2026-08-31 as
central, mature, actively-maintained features. Caveat: both still have
**zero frontend tests** and thin backend tests. They carry the GA label
ahead of the GA test bar — track adding coverage as follow-up so the label
and the reality converge. Apply the full test bar before promoting the
remaining beta features (Compliance, MDM, Asset Reviews).

## How to change a feature's maturity

1. Edit the `maturity` field in `features.ts`.
2. Confirm the `β`/`α` badge renders as expected (sidebar + About).
3. If promoting to GA, verify the GA bar (tests, docs, no auth/data gaps).
4. Keep the name/group consistent with `features.py` for the same id.
