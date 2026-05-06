# PRD: Marketplace Multi-Entity Support

## Problem Statement

The marketplace currently only surfaces Data Products for discovery and subscription. Users who also manage Data Contracts or curated Assets (Datasets, Dashboards, ML Models) cannot offer those items in the marketplace for consumers to discover, browse, or subscribe to. This limits the marketplace's utility as a central discovery hub — consumers must navigate separate feature views to find contracts or assets, and there is no unified "shop" experience across entity types.

Additionally, the legacy "Datasets" tab in the marketplace fetches from a deprecated endpoint (`/api/datasets/published`) that is disconnected from the ontology-driven Asset model. This creates a confusing split between legacy datasets and the newer asset-backed entities.

## Solution

Extend the marketplace to optionally display Data Contracts and Assets alongside Data Products. An admin-configurable setting controls which entity types appear in the marketplace (default: products only). Each entity type gets its own tab in the marketplace view, with consistent card rendering, domain filtering, search, publication scope controls, and full subscription support.

The legacy Datasets marketplace tab is replaced by the new Assets tab, where Dataset-type assets are one of several publishable asset types.

Key behaviors:

- **Admin setting** (`marketplace_entity_types`): a JSON array stored in `app_settings` controlling which tabs appear. Default `["products"]`. Options: `"products"`, `"contracts"`, `"assets"`.
- **Publication model**: All three entity types use the same `publication_scope` enum (`none`, `domain`, `organization`, `external`). Publication requires `status == 'active'`.
- **Subscription model**: Full subscribe/unsubscribe with notifications for all entity types on the marketplace.
- **Domain filtering**: Works for all entity types (products have `domain`, contracts have `domain_id`, assets have `domain_id`).
- **Asset type curation**: A predefined set of asset types is marketplace-eligible by default (Dataset, Dashboard, ML Model). Admins can toggle which asset types are publishable.

## User Stories

1. As an admin, I want to configure which entity types (Products, Contracts, Assets) appear in the marketplace, so that I can tailor the discovery experience to my organization's needs.
2. As an admin, I want to configure which asset types (Dataset, Dashboard, ML Model, etc.) are eligible for marketplace publication, so that only relevant asset types are surfaced.
3. As a data producer, I want to publish a Data Contract to the marketplace with a specific publication scope (domain, organization, external), so that consumers can discover and subscribe to my contract.
4. As a data producer, I want to unpublish a Data Contract from the marketplace, so that it is no longer discoverable by consumers.
5. As a data producer, I want to publish an Asset (e.g., a Dataset or Dashboard) to the marketplace, so that consumers can discover and subscribe to it.
6. As a data producer, I want to unpublish an Asset from the marketplace.
7. As a data consumer, I want to browse Data Contracts in the marketplace, so that I can find contracts that define data I need.
8. As a data consumer, I want to browse Assets in the marketplace, so that I can discover datasets, dashboards, and models available in my organization.
9. As a data consumer, I want to subscribe to a Data Contract on the marketplace, so that I receive notifications when it changes.
10. As a data consumer, I want to subscribe to an Asset on the marketplace, so that I receive notifications about updates.
11. As a data consumer, I want to filter marketplace items by domain, so that I can narrow results to my area of interest regardless of entity type.
12. As a data consumer, I want to search across all marketplace entity types by name and description, so that I can quickly find what I need.
13. As a data consumer, I want to see consistent card information (name, description, domain, status, rating, owner, certification badge) for every entity type in the marketplace, so that I can compare items easily.
14. As a data consumer, I want to filter marketplace items by publication scope (domain, organization, external), so that I see only items relevant to my visibility level.
15. As a data steward, I want contracts and assets to auto-unpublish when deprecated, so that stale items don't linger in the marketplace.
16. As a data consumer, I want the marketplace to show certification badges on contracts and assets, so that I can gauge trust levels at a glance.
17. As an admin, I want the legacy Datasets tab replaced by the new Assets tab, so that there is a single, consistent path for dataset discovery via the ontology-driven model.
18. As a data producer, I want both the existing approval-based publish flow and the new direct publication-scope flow to coexist for contracts, so that my organization can choose which workflow to use.
19. As a data consumer, I want the home page discovery section to optionally surface contracts and assets (based on admin config), so that the landing page reflects what's available in the marketplace.
20. As an admin, I want the marketplace configuration to persist across app restarts, so that the setting is durable.

## Implementation Decisions

### Admin Configuration

- A single `app_settings` key `marketplace_entity_types` stores a JSON array (e.g., `["products"]`, `["products", "contracts", "assets"]`). Default is `["products"]`.
- A second `app_settings` key `marketplace_asset_types` stores a JSON array of asset type names eligible for publication (e.g., `["Dataset", "Dashboard", "ML Model"]`). This controls which asset types can be published and appear in the marketplace.
- Two new endpoints: `GET /api/settings/marketplace-config` (read, any authenticated user) and `PUT /api/settings/marketplace-config` (write, admin only).
- A new "Marketplace" subsection in Settings > Configuration with checkboxes for entity types and asset type selection.

### Data Contract Publication

- Contracts already have `publication_scope`, `published_at`, `published_by` columns in the DB and `domain_id` for domain filtering. No schema migration needed.
- The ODCS API models (`DataContractRead`, `DataContractSummary`) must be extended to expose `publication_scope`, `published_at`, `published_by` (currently only expose the legacy `published` boolean).
- The `_build_contract_api_model` builder in `DataContractsManager` must map the new columns.
- New routes: `GET /api/data-contracts/published`, `POST /api/data-contracts/{id}/set-publication-scope`, `POST /api/data-contracts/{id}/unpublish` (direct publication, mirroring the product pattern).
- The existing `request-publish` / `handle-publish` approval flow continues to work alongside direct publication. On approval, it sets `publication_scope` to `"organization"`.
- New manager method `get_published_contracts()` filters by `status == 'active'` AND `publication_scope != 'none'`.

### Asset Publication

- New DB migration: add `publication_scope` (String, default `"none"`, indexed), `published_at` (DateTime), `published_by` (String) to the `assets` table.
- Extend `AssetRead` Pydantic model (backend) and `AssetRead` TypeScript interface (frontend) with publication fields.
- New routes: `GET /api/assets/published` (accepts `?asset_types=` query param to filter by type), `POST /api/assets/{id}/set-publication-scope`, `POST /api/assets/{id}/unpublish`.
- Publication gated: only assets whose `asset_type_name` is in the `marketplace_asset_types` config can be published. Endpoint returns 400 if asset type is not eligible.
- Default eligible asset types: `Dataset`, `Dashboard`, `ML Model`.

### Marketplace Frontend

- `MarketplaceAssetType` union becomes `'products' | 'contracts' | 'assets'` (legacy `'datasets'` removed).
- Marketplace view fetches `GET /api/settings/marketplace-config` on mount to determine which tabs to show.
- Each entity type has its own fetch, filter, and render logic. Card rendering is consistent: name, description snippet, domain badge, status badge, certification badge, rating, owner.
- Domain filtering extends to all entity types. Contracts use `domainId`, assets use `domain_id`.
- The dead `scopeFilter` state is wired to actual UI controls (dropdown or pill buttons for scope filtering).
- The legacy datasets fetch (`/api/datasets/published`) and datasets toggle are removed. Asset-type datasets appear under the new Assets tab.

### Publication Prerequisites

- Strict: entity must have `status == 'active'` to be published (consistent across products, contracts, assets).
- Deprecation auto-unpublishes (sets `publication_scope` to `"none"`).

### Subscription Model

- Full subscribe/unsubscribe for contracts and assets, using the existing `entity_subscriptions` polymorphic table with `entity_type` set to `"data_contract"` or `"asset"`.
- Subscription endpoints: `POST /api/data-contracts/{id}/subscribe`, `DELETE /api/data-contracts/{id}/subscribe`, `GET /api/data-contracts/my-subscriptions`. Same pattern for assets.
- The marketplace subscribe flow (approval wizard or fallback dialog) is reused for all entity types.

## Testing Decisions

Good tests verify external behavior (API response shapes, status codes, filter correctness) rather than internal implementation details. Tests should be resilient to refactoring — if the behavior doesn't change, the test shouldn't break.

### Backend tests

- **Published endpoints**: Verify `GET /api/data-contracts/published` and `GET /api/assets/published` return only active + published items. Verify query params (`asset_types`, `scope`, `domain_id`) filter correctly.
- **Publication scope routes**: Verify `set-publication-scope` requires active status, returns 400 for non-active entities. Verify `unpublish` clears scope. Verify ineligible asset types are rejected.
- **Settings routes**: Verify marketplace config CRUD, default values, admin-only write access.
- **Auto-unpublish**: Verify deprecation clears publication scope.
- Prior art: `test_data_product_routes.py::test_get_published_products` for published endpoint patterns.

### Frontend component tests

- **Card renderers**: Verify contract and asset cards render all expected fields (name, domain, status, certification, rating).
- **Tab visibility**: Verify marketplace tabs are conditionally rendered based on config response.
- **Scope filter**: Verify filtering by publication scope works correctly.
- Prior art: existing marketplace view patterns (if any component tests exist) or general Shadcn component test patterns.

## Out of Scope

- **Unified search endpoint**: A single backend endpoint that searches across all entity types is not part of this PRD. Each type has its own published endpoint; search is client-side.
- **Marketplace analytics**: Usage tracking, view counts, popularity metrics are not included.
- **Cross-entity recommendations**: "Users who subscribed to this product also subscribed to..." is not included.
- **Payment or access-gating**: No paywall or formal access request workflow for marketplace items.
- **Asset certification inheritance through marketplace**: Certification propagation is handled by the separate unified-lifecycle-tracking PRD (Phase 7).
- **Contract schema preview in marketplace**: Showing inline schema details on the contract card is deferred.
- **Ontology concept publication**: Publishing ontology concepts to the marketplace is not included.

## Further Notes

- This work builds on the unified lifecycle tracking plan (Phases 4 and 5 specifically). Publication columns for contracts are already in the DB from that work. The asset publication migration is new.
- The existing `request-publish` / `handle-publish` approval workflow for contracts coexists with the new direct publication scope model. Organizations can use either or both — the approval flow just happens to set `publication_scope` on success.
- The `marketplace_asset_types` admin setting provides a guardrail: even if an admin enables "assets" in the marketplace, only the configured asset types can be published. This prevents accidental publication of structural entities like Catalogs or Schemas.
- i18n: New strings needed for marketplace tabs, card labels, settings panel, and scope filter options across all supported locales.
