# PRD: External Marketplace Providers

## Problem Statement

Ontos already lets a workspace publish data products and data contracts internally — the existing Marketplace view lists items whose `publication_scope` makes them visible to all users in this deployment. What it does not do is reach **outside** the workspace.

Today, when a data steward wants to ground their catalog in industry vocabulary, they have to:

- Hunt across the web for the right TTL file (FIBO, Schema.org, GS1, HL7 FHIR, OBO Foundry, ...).
- Save it locally, upload it through `Settings → Semantic Models`, and pray they grabbed the right module.
- Repeat the same dance for every industry, every team, every refresh cycle.
- Maintain a brittle, hand-curated `industry_ontologies.yaml` to remember the URLs we already discovered.

When a steward wants to ground their catalog in **realistic industry data models** (typed tables, foreign-key graphs, metric views, ER diagrams), there is no out-of-the-box source at all. Excellent reference work exists — friends working on the `vibe-business-data-models` project ship 80 production-shaped models across 40 industries (23,918 tables, 924,919 attributes, 10,488 metric views) — but Ontos has no way to surface it. The model.json files sit in a GitHub repo; no Ontos user will ever stumble across them.

Commercial data vendors face the same dead end from the other direction. S&P Global publishes an "ontology read" marketplace at metadata.marketplace.spglobal.com offering their product catalog as semantic metadata, with actual data behind it. There is no mechanism for them to plug Ontos into their catalog so a customer's stewards see S&P products inline when they search Ontos.

Without a marketplace layer that **third parties** can plug into, Ontos is a closed system:

- Customers cannot discover external ontologies and data products from inside Ontos.
- Free providers (Vibe Business) cannot offer their catalog to Ontos users as a built-in default.
- Commercial vendors (S&P, Snowflake Marketplace partners, industry consortia) cannot integrate without bespoke per-vendor code in Ontos itself.
- Workspace admins have no way to curate which external providers their users see, restrict commercial providers to a subset of teams/domains, or audit what came from where.

The promise of an ontology-driven, data-product-first catalog cannot be fulfilled if every customer has to re-discover the same industry models, the same FIBO modules, the same FHIR taxonomies from scratch.

## Solution

Introduce **External Marketplace Providers** — a pluggable, admin-configurable registry of third-party catalogs that expose ontologies, data products, and data contracts as importable, searchable listings inside Ontos. Each provider publishes a **DCAT-AP catalog** as a single Turtle URL (with small Ontos-specific extensions for offering mode, audience hints, and delivery method). Ontos polls those catalogs on a schedule, caches them in the existing RDF triple store, and surfaces the listings inline in unified search plus a dedicated marketplace browse view. A user can import any listing (or a subset of a bundle's children) into their workspace as a **linked copy** — a real Ontos data product / data contract / semantic model with full provenance back to the source listing, including a `sync_state` that flips to "update available" when the upstream version moves. For listings that carry actual data, the existing Access Grant flow is wired through to the provider's contact point so a request for a Delta-Sharing-backed S&P dataset goes through the same audit and approval rails as any internal data product.

The first shipped provider is **Vibe Business**: a small generator script we maintain crawls the `amralieg/vibe-business-data-models` repo, emits a DCAT-AP `catalog.ttl`, and hosts it; Ontos seeds a built-in provider row pointing at that URL on first startup, with a bundled offline snapshot as a fallback when the network is unreachable. Customers who do nothing get Vibe Business for free; customers who add S&P, Snowflake Marketplace, or their internal data exchange add a single Settings row.

Provider configuration lives under `Settings → Marketplace Providers`. Each provider row captures publisher metadata (name, logo, website), offering mode (free / commercial / mixed), the DCAT catalog URL, auth credentials (none / API key / bearer / basic), enable/disable toggle, refresh cadence, and a two-tier visibility model — provider-level audience tokens (Entra group, team, role, data domain) plus rule-based per-listing filters (e.g. "match `dcat:theme=Healthcare` → visible only to data_domain Healthcare"). Disabling a provider hides its listings from search and the marketplace view but does not break previously imported items, because imports are linked copies, not live proxies.

Listings appear as a new search type alongside data products and contracts. The listing detail drawer shows DCAT metadata, license, publisher contact, and the distributions on offer; an Import Wizard renders bundles as an expandable tree (children carry `parent_listing_iri`) and lets the user check which sub-items to materialize and into which project / team. Importers prefer attached ODPS / ODCS distributions when present (`application/vnd.odps+json`, `application/vnd.odcs+json`) and fall back to DCAT-derived stubs otherwise. After import, a new "Marketplace Origin" polymorphic panel attaches to each materialized entity, showing the provider, source IRI, imported version, current upstream version, and re-sync / detach actions.

For data-bearing listings (S&P's case), `delivery_method=delta_sharing` triggers Ontos's existing `ON_REQUEST_ACCESS` workflow trigger to fan out a webhook / email to the provider's `dcat:contactPoint` when the user clicks Request Access on the imported product. The provider grants the Delta Share recipient out-of-band and posts back to a callback endpoint, which materializes a normal Ontos access grant carrying the share name and schema. Admins can manually fulfill a pending request when no webhook is available. Only Delta Sharing is supported in v1 — every other delivery method falls through to a generic "external link" affordance.

## User Stories

### Provider configuration (admin)

1. As an Ontos admin, I want a `Settings → Marketplace Providers` page under the Integrations group, so that I can manage external providers without leaving Settings.
2. As an Ontos admin, I want to see all configured providers in a single list with their enabled state, offering mode, last refresh status, and listing count, so that I can spot misconfigured or stale providers at a glance.
3. As an Ontos admin, I want to add a new provider by entering a name, display name, description, publisher name, publisher website, publisher logo URL, offering mode (free / commercial / mixed), and the DCAT catalog TTL URL, so that I can plug in any DCAT-conformant catalog.
4. As an Ontos admin, I want to choose an auth mode (none / api_key / bearer / basic) and supply the matching credentials, so that I can wire up commercial providers behind API keys.
5. As an Ontos admin, I want provider credentials stored encrypted at rest, so that an attacker with database read access cannot exfiltrate vendor API keys.
6. As an Ontos admin, I want to toggle each provider enabled / disabled, so that I can pause a provider without losing its config or any items already imported from it.
7. As an Ontos admin, I want to set provider-level audience tokens (data domains, Entra groups, teams, roles) using the same grammar I already use for comment audiences, so that I can restrict commercial providers to the teams that have a contract with that vendor.
8. As an Ontos admin, I want to add rule-based per-listing visibility filters (e.g. "any listing whose `dcat:theme` is Healthcare is only visible to data domain Healthcare"), so that I can fine-tune visibility without editing each individual listing.
9. As an Ontos admin, I want a configurable refresh cadence (per provider, default 24 h), so that I can pull more aggressively for fast-moving catalogs and less aggressively for stable ones.
10. As an Ontos admin, I want a "Refresh now" button on each provider row, so that I can force-pull a catalog after a vendor pushes an update.
11. As an Ontos admin, I want the last refresh timestamp, status (success / failed / never), and the last error message visible on the row, so that I can diagnose pull failures.
12. As an Ontos admin without the `settings-marketplace-providers` permission, I do not want to see the Settings entry, so that I am not shown features I cannot use.
13. As an Ontos admin, I want every provider mutation (create / update / delete / enable / disable / refresh) audit-logged, so that I have a forensic trail of marketplace configuration changes.
14. As an Ontos admin, I want the default Vibe Business provider seeded on first startup as `is_builtin=true`, so that brand-new deployments have a working marketplace out of the box.
15. As an Ontos admin, I want the built-in flag to prevent accidental deletion of the default Vibe Business row (with a clearly-labelled "Disable instead" affordance), so that I do not have to re-seed it after a misclick.

### Catalog fetch and cache

16. As an Ontos operator, I want a Databricks workflow to periodically refresh every enabled provider on its configured cadence, so that catalogs stay current without manual intervention.
17. As an Ontos operator, I want each refreshed catalog cached in the existing `rdf_triples` store under a deterministic named graph (`urn:provider:<id>:catalog`), so that SPARQL queries across all catalogs work without a parallel store.
18. As an Ontos operator, I want the cached listings persisted in a flat `marketplace_listings` table (one row per `dcat:Dataset` / `dcat:DataService`), so that search indexing does not have to repeatedly walk the RDF graph.
19. As an Ontos operator, I want a refresh failure (network error, malformed TTL, expired credentials) to leave the previous cache intact and surface a clear error in the provider row, so that a flaky vendor never blanks out my marketplace.
20. As an Ontos operator, I want refresh runs to bulk-replace a provider's listings transactionally per provider, so that a partial refresh never leaves the catalog half-updated.
21. As an Ontos operator, I want refresh fetches to send the provider's auth header (per the configured auth mode), so that authenticated catalogs are pullable.
22. As an Ontos operator, I want a fallback path that loads an offline snapshot of the Vibe Business catalog from a bundled TTL when the hosted URL is unreachable, so that a brand-new deployment without internet still has a working default marketplace.
23. As an Ontos operator, I want bundle child listings linked to their parent via `ontosmkt:parentListing`, so that the import wizard can render the bundle tree without re-parsing the catalog.

### Discovery and browsing

24. As a data steward, I want a "Marketplace" entry in the main navigation, so that I can browse external offerings from one place.
25. As a data steward, I want the Marketplace view to combine **published in your workspace** (current behaviour) and **external providers** in a single browse experience with provider-grouping, so that I do not have to context-switch between internal and external catalogues.
26. As a data steward, I want filter chips on the Marketplace view for provider, listing type (ontology / data product / data contract / bundle), offering mode, and theme, so that I can narrow the catalogue to my current curation task.
27. As a data steward, I want listings of type `marketplace-listing` to appear inline in the global header search and `/search/index`, so that I discover external items in the same flow I use for everything else.
28. As a data steward, I want each marketplace-listing search result tagged with a provider badge and a free / commercial / mixed offering indicator, so that I instantly know what I am looking at.
29. As a data steward, I want clicking a listing to open a detail drawer with the listing's DCAT metadata (title, description, themes, keywords, version, license label and link, publisher contact, distributions on offer), so that I have enough context to decide whether to import.
30. As a data steward browsing a bundle, I want the detail drawer to show an expandable tree of child listings (with their own types and titles), so that I can scan what is inside before importing.
31. As a data steward, I want listings hidden when a provider is disabled or when I am not in the provider's audience, so that I never see items I cannot use.
32. As a data steward, I want listings visibility filters that depend on `dcat:theme` to evaluate against my team memberships and data domains, so that an admin's rule-based filter "Healthcare theme → Healthcare domain" actually works.
33. As a data steward without the `marketplace` permission, I do not want to see the Marketplace entry or marketplace-listing results in search, so that I am not shown a feature I cannot use.

### Importing a listing

34. As a data steward, I want an "Import" button in the listing detail drawer, so that I can pull a listing into my workspace from where I am reading it.
35. As a data steward, I want the Import Wizard to render the listing — or for a bundle, the listing and its children — as a checkbox tree, so that I can select exactly which sub-items to materialize.
36. As a data steward, I want the ontology child of a bundle to be checked by default and the data product / data contract children unchecked, so that the lightest-weight default is one click.
37. As a data steward, I want to choose the target project (and / or team) for the imported entities in the wizard, so that imported products land in the right organizational context.
38. As a data steward, I want the wizard to warn me when a child item already exists in my workspace (by external_listing_iri), so that I do not silently create a duplicate.
39. As a data steward, I want the importer to prefer attached ODPS / ODCS JSON distributions when the listing provides them and fall back to DCAT-derived stub fields when it does not, so that I get the highest fidelity available without manual editing.
40. As a data steward, I want imported entities to carry `external_provider_id`, `external_listing_iri`, `external_version`, `imported_at`, `imported_by`, and `sync_state`, so that I can answer "where did this come from?" forever.
41. As a data steward, I want every import recorded in a `marketplace_import_records` row, so that there is a single page to query historical provenance.
42. As a data steward, I want an ontology import to land in the existing semantic models store and immediately become available in the concept picker, so that I can start linking concepts to entities right away.
43. As a data steward, I want a data product / data contract import to land in the existing data-products / data-contracts tables (respecting my chosen target project), so that the imported items behave identically to natively-authored ones.
44. As a data steward, I want audience hints published by the provider on a listing (`ontosmkt:audience` tokens) to carry through to the imported entity, so that the provider's intended scoping is preserved.
45. As a data steward, I want a clear progress indicator during multi-child imports and a final summary (N entities imported, list of links), so that I know whether the operation succeeded.
46. As a data steward, I want imports to be permission-checked against the **target entity type**, so that I cannot use the marketplace import to bypass per-project data-product write permissions.

### Provenance and sync state

47. As a data steward, I want a "Marketplace Origin" panel on every detail page for an imported entity, showing provider name + logo, source listing IRI (link out to provider), imported version, current upstream version, and `sync_state`, so that I always know whether the entity is in sync with the upstream.
48. As a data steward, I want the background refresh job to compute a fresh upstream version for every imported entity and flip its `sync_state` to `update_available` when the version moves, so that I get notified about new vendor releases without manual checking.
49. As a data steward, I want a "Re-sync" button in the Marketplace Origin panel that fetches the latest version and overwrites the local entity (with confirmation dialog), so that I can adopt upstream updates in one click.
50. As a data steward, I want a "Detach from upstream" button that clears the provenance fields and sets `sync_state=drifted_locally`, so that I can take ownership of an entity that I have customised beyond what re-sync should overwrite.
51. As a data steward who has manually edited an imported entity, I want `sync_state` to transition to `drifted_locally` automatically (or at least on next refresh check) so that "Re-sync" surfaces a destructive-change warning before overwriting my edits.
52. As a data steward, I want the Marketplace Origin panel to be polymorphic so that the same panel implementation works for data products, data contracts, and semantic models, so that the UX is consistent.

### Request Access for data-bearing listings (Delta Sharing v1)

53. As a data consumer, I want imported data products that carry a Delta Sharing delivery method to expose a "Request Access" button that opens the existing access-grant request dialog, so that the access flow is identical to any internal data product.
54. As a data consumer, I want my access request to be persisted as a pending `access_grant_request` row in Ontos, so that the request is auditable and visible in my pending-requests view.
55. As a data consumer, I want submission of the access request to fire the existing `ON_REQUEST_ACCESS` workflow trigger with the provider id and source listing IRI in `entity_data`, so that any configured approval / notification workflow runs unchanged.
56. As a data consumer, I want the workflow to send a webhook (or email fallback) to the provider's `dcat:contactPoint`, including my email, the requested duration, the reason, and a callback URL, so that the provider knows who is asking and how to respond.
57. As a provider, I want a documented callback endpoint (`/api/marketplace/access-callback`) that I can POST to with the recipient name, share name, and schema name (plus optional expiry), so that I can hand a Delta Share grant back to Ontos without phone calls.
58. As a provider's callback, I want my POST authenticated against a per-provider shared secret, so that random callers cannot fabricate grants.
59. As Ontos, I want the callback to persist a normal `access_grant` row with the Delta Sharing payload, mark the original request as approved, and notify the requester, so that the rest of the access-grant UX works unchanged.
60. As an Ontos admin handling a provider that has no webhook capability, I want an "Admin fulfill" action on the pending request where I can paste the recipient / share / schema by hand, so that I am not blocked on the provider supporting callbacks.
61. As a data consumer, I want the approved grant to show me the Delta Sharing recipient name, share name, and schema name in a copy-able form, so that I can wire up my consumer side immediately.
62. As an Ontos operator, I do not want any delivery method other than Delta Sharing to be auto-fulfilled in v1; instead, I want the listing to expose a generic "External link" button pointing at the provider's `ontosmkt:requestAccessURL`, so that v1 scope is contained but non-Delta-Sharing flows still work degraded.

### Default Vibe Business provider

63. As a fresh-install Ontos user, I want Vibe Business to appear pre-configured under Marketplace Providers as `enabled=true` with a non-empty catalog, so that I see real listings on first login without any setup.
64. As an Ontos admin, I want the Vibe Business catalog.ttl to be hosted at a stable URL that we (the Ontos team) maintain, so that we control the schema and update cadence.
65. As an Ontos admin, I want a small generator tool (separate repo) that crawls the `amralieg/vibe-business-data-models` GitHub repo and emits a DCAT-AP catalog.ttl, so that updates to that source repo propagate to the hosted catalog through a deterministic build.
66. As an Ontos admin, I want a bundled offline catalog.ttl snapshot to load when the hosted URL is unreachable on first startup, so that air-gapped or initial-bootstrap deployments still get the default marketplace.
67. As a data steward exploring Vibe Business, I want each industry (Retail, Healthcare, ...) exposed as one Bundle listing whose children are the ontology, the data contracts, the data products, and the metric views, so that I can pick exactly what I want without importing everything.
68. As a data steward, I want imported Vibe Business items to be visibly attributed to Vibe Business in the Marketplace Origin panel, so that downstream consumers know the lineage of these models.

### Permissions

69. As an Ontos admin, I want a `settings-marketplace-providers` feature permission that gates the entire Settings page (CRUD on providers), so that only authorised admins manage external providers.
70. As an Ontos admin, I want a `marketplace-listings` (or extended `marketplace`) feature permission that gates listing browse and import for end users, so that I can roll out the marketplace to a subset of teams during pilot.
71. As an Ontos admin, I want the import action to also require the user's existing permissions on the **target entity type** (e.g. `data-products` write on the chosen project), so that the marketplace cannot be used as a privilege-escalation back door.
72. As an Ontos admin, I want the callback endpoint authenticated only by the per-provider shared secret (not requiring user session), so that a server-to-server webhook works without UI-level auth.

### Operations and observability

73. As an Ontos operator, I want every catalog refresh (per provider) to log start, end, listing count delta, and failure reason if any, so that I can monitor catalog freshness with our existing log pipeline.
74. As an Ontos operator, I want the refresh job to emit metrics suitable for our existing dashboard pattern (count per status, average duration per provider), so that I can SLO catalog freshness.
75. As an Ontos operator, I want a provider in repeated failed state for more than N consecutive refreshes to surface a warning banner in `Settings → Marketplace Providers`, so that operators notice silent breakages.

### Edge cases

76. As an Ontos admin, I want deleting a provider to leave previously imported entities intact (since they are linked copies, not proxies), but to clear their `external_provider_id` (or mark provider as deleted) so that "update available" checks no longer fire, so that nothing breaks but provenance is degraded gracefully.
77. As an Ontos operator, I want catalog parsing tolerant of unknown DCAT properties (forward-compat) and intolerant of structural violations (missing required `dcat:Catalog`, malformed TTL), so that conformant catalogs always load and broken ones fail loudly.
78. As an Ontos operator, I want a hard cap on number of listings per provider (configurable, default 50,000), so that a misbehaving provider cannot exhaust the listings table.
79. As an Ontos operator, I want a hard cap on TTL fetch size (configurable, default 100 MB), so that a misbehaving provider cannot OOM the refresh worker.
80. As a data steward importing a listing whose ontology IRI collides with an already-imported ontology IRI from a different provider, I want the second import blocked with a clear conflict message, so that I am never silently shadowing one provider's terms with another's.

## Implementation Decisions

### Architecture

- **Wire protocol with providers**: DCAT-AP / DCAT-3 Turtle catalog at a single root URL per provider. A small Ontos-specific extension vocabulary (namespace `https://ontos.dev/ns/marketplace#`, prefix `ontosmkt:`) adds:
  - `ontosmkt:listingType` ∈ `{Ontology, DataProduct, DataContract, Bundle}`
  - `ontosmkt:offeringMode` ∈ `{free, commercial, mixed}`
  - `ontosmkt:audience` (string token grammar reusing the comments-audience grammar)
  - `ontosmkt:requestAccessURL`
  - `ontosmkt:deliveryMethod` ∈ `{delta_sharing}` (v1; future: `s3_volume_share`, `uc_table_share`, `rest_endpoint`, `external_link`)
  - `ontosmkt:parentListing` (links bundle child to parent)
- ODPS / ODCS payloads ride as `dcat:Distribution` with media types `application/vnd.odps+json` and `application/vnd.odcs+json` (or `+yaml`).
- The Ontos extension TTL is bundled and loaded into the graph on startup like the other shipped taxonomies.

### Data model

Three new tables:

- **`marketplace_providers`** — registry of external providers. Columns include: id, name (unique), display_name, description, publisher metadata (name, url, logo url), offering_mode enum, catalog_url, auth_mode enum, auth_config JSON (encrypted), enabled, audience_tokens JSON, listing_audience_rules JSON, refresh_interval_seconds, last_refreshed_at, last_refresh_status, last_refresh_error, is_builtin, webhook_secret, plus standard audit columns.
- **`marketplace_listings`** — cache of per-listing metadata, rebuilt per provider per refresh. Columns include: id, provider_id (FK), listing_iri, title, description, listing_type, parent_listing_iri, themes JSON, keywords JSON, offering_mode, license_url, license_label, contact_point JSON, audience_tokens JSON, distributions JSON, delivery_methods JSON, request_access_url, raw_metadata JSON, version, indexed_at. UNIQUE on (provider_id, listing_iri).
- **`marketplace_import_records`** — provenance log. Columns include: id, provider_id, listing_iri, listing_version, imported_entity_type enum (semantic_model | data_product | data_contract), imported_entity_id, sync_state enum (up_to_date | update_available | drifted_locally), imported_at, imported_by.

Additive columns on existing entity tables (`data_products`, `data_contracts`, `semantic_models`):
- `external_provider_id` (nullable FK), `external_listing_iri`, `external_version`, `sync_state`.

Catalog RDF caching reuses `rdf_triples` with a deterministic `context_name` per provider: `urn:provider:<id>:catalog`. SPARQL across all caches is therefore free.

### Modules

Deep modules with simple, testable interfaces:

- **`MarketplaceManager`** — singleton on `app.state`. Public surface: `refresh_provider(id)`, `refresh_all_due()`, `list_providers()`, `list_listings(filters)`, `get_listing(iri)`, `import_listing(iri, child_selection, target_project)`, `register_webhook_callback(provider_id, payload)`. Implements `SearchableAsset.get_search_index_items()` for the unified search registry. Encapsulates audience-evaluation against the user's principal context.
- **`DcatCatalogParser`** — stateless. Public surface: `parse(ttl_text, base_iri) -> ParsedCatalog`. Converts a TTL blob into a `ParsedCatalog` data class containing `provider_metadata`, `listings: list[ParsedListing]`, `extension_warnings`. Pure function over the rdflib graph; easy to unit-test against fixture TTL files.
- **`Importers`** — one per `listing_type` (`ontology_importer`, `data_product_importer`, `data_contract_importer`). Each accepts a `ParsedListing` + `ImportContext` (provider, target project, target team, importer email) and returns the new entity ID plus an import record. Importers prefer attached ODPS / ODCS distributions and fall back to DCAT-derived stub fields. Each importer is independently testable with a fixture listing and a fake repository.
- **`AudienceEvaluator`** — stateless. Public surface: `evaluate(audience_tokens, principal_context) -> bool`. Reuses the same grammar as comments and is exercised by tests against a matrix of token / principal combinations.
- **`MarketplaceWebhookDispatcher`** — handles the outbound side of the Access Request flow. Public surface: `dispatch_access_request(provider, request, callback_url)`. Listens to the `ON_REQUEST_ACCESS` workflow trigger filtered to `entity_type=data_product` with provenance to an external provider.
- **`MarketplaceCallbackHandler`** — handles the inbound POST from a provider. Public surface: `handle(provider_id, signed_payload) -> AccessGrant`. Authenticates the per-provider shared secret, materialises the access grant, notifies the requester.

These modules are intentionally extracted so they can be unit-tested without spinning up the FastAPI app or the Postgres harness.

### Permissions

- `settings-marketplace-providers` (admin) — Settings group: Integrations.
- `marketplace-listings` (consumer browse + import) — possibly fold under existing `marketplace` permission to avoid permission sprawl.
- Per-import permission check against the target entity type (e.g. `data-products` write on the target project).
- Webhook callback endpoint authenticated by a per-provider shared secret (not user session).

### Visibility evaluation

Two-tier:

- **Provider-level**: `audience_tokens` JSON on `marketplace_providers`. Evaluated once per request against the caller's principal context. If the provider is invisible, none of its listings are returned regardless of other filters.
- **Listing-level**: `listing_audience_rules` JSON on `marketplace_providers` is a list of rules `{match: {dcat_theme|listing_type|keyword|...: value}, audience: [tokens]}`. Each cached listing is tested against each rule; the most restrictive matching audience applies. Per-listing direct audience hints from the provider (`ontosmkt:audience`) are merged in. If no rule matches and the provider has no audience filter, the listing is visible to everyone with the `marketplace` permission.

### API contracts

`/api/marketplace/providers` — CRUD + `POST /{id}/refresh`.
`/api/marketplace/listings` — `GET` (paginated, filterable by provider, type, theme, offering mode, free-text), `GET /{iri:path}`.
`/api/marketplace/listings/{iri:path}/import` — `POST` with body declaring `child_selection: [listing_iri]`, `target_project_id`, `target_team_id`.
`/api/marketplace/imports` — `GET` provenance.
`/api/marketplace/access-callback` — `POST` from provider with HMAC-signed payload.

Listings appear in `/api/search` as type `marketplace-listing` via the SearchableAsset implementation.

### Background refresh

- Reuse the existing `workflow_installations` + `SettingsManager` job pattern. Register a `marketplace_catalog_refresh` job at startup; it iterates enabled providers, picks those whose `last_refreshed_at + refresh_interval_seconds < now()`, and calls `MarketplaceManager.refresh_provider(id)`.
- Refresh failures persist `last_refresh_status='failed'` and `last_refresh_error=<message>` without clearing the cache.

### Polymorphic panel matrix

Add a new "Marketplace Origin" panel to the polymorphic entity panel matrix. Supported entity types: data product, data contract, semantic model. Hidden when the entity has no `external_provider_id`.

### Provider seeding

- A small companion generator tool (separate small repo under our ownership) crawls the `amralieg/vibe-business-data-models` repo and emits a DCAT-AP `catalog.ttl`.
- The generated catalog is hosted at a stable URL we own.
- Ontos startup tasks idempotently insert a `marketplace_providers` row with `is_builtin=true`, `name="vibe-business"`, pointing at that URL.
- A bundled offline snapshot of the catalog.ttl is shipped inside the backend resources and used as a fallback on first startup when the URL is unreachable.

### Phasing

The feature is delivered as six vertical slices, each independently shippable:

- **P1 – Providers Registry.** Tables, models, repository, manager skeleton, Settings UI CRUD, audience tokens, auth_config. No DCAT fetch yet.
- **P2 – Catalog Fetch + Cache.** `DcatCatalogParser`, refresh workflow + manual refresh, RDF + listing-table cache, last-refresh status surfaced.
- **P3 – Search + Browse.** SearchableAsset integration, marketplace-view extension, listing detail drawer.
- **P4 – Import Wizard.** Tree selector, ontology / data product / data contract importers, provenance columns, Marketplace Origin panel, re-sync / detach.
- **P5 – Access Flow.** `MarketplaceWebhookDispatcher`, `MarketplaceCallbackHandler`, admin manual-fulfill dialog; Delta-Sharing-only.
- **P6 – Vibe Business Default.** Generator script, hosted catalog, seed in startup tasks, offline TTL fallback.

## Testing Decisions

A test is good when it asserts the **external behaviour** of a module — what callers observe — and is silent about internal organisation, caching strategy, query shape, or which library is used to parse a Turtle file. Tests that fail when an internal helper is renamed but no observable behaviour changes are anti-tests.

### Unit-tested modules (in priority order)

- **`DcatCatalogParser`** — fixture-driven. Input: a directory of canonical TTL fixtures covering free / commercial / bundle / missing-extension / malformed catalogs. Output: a `ParsedCatalog` dataclass. Tests assert: required fields present, optional fields default sensibly, bundle children correctly nested via `ontosmkt:parentListing`, attached ODPS / ODCS distributions detected, audience hints extracted, malformed inputs raise the documented error class. Prior art: the existing OWL parser tests around `clean_truncated_turtle()`.
- **`Importers`** (one test class per importer). Inputs: a `ParsedListing` fixture + an `ImportContext`. Assertions: the right entity type is created in the (fake) repository, provenance fields are populated, audience hints carry through, ODPS / ODCS preferred when present and DCAT fallback used when not. Prior art: existing importer tests for ODCS upload in data contracts.
- **`AudienceEvaluator`** — pure function table tests. Input: token-list + principal context fixture. Assertions: matches Entra group, team, role, domain tokens correctly; empty audience means visible; logical OR semantics across tokens. Prior art: existing comment-audience tests.
- **`MarketplaceManager.refresh_provider`** — using a fake DCAT fetcher and a fake repository. Assertions: successful refresh replaces the listings transactionally; failures persist the error without clearing the cache; the listings table delta is correct (insert / update / delete); RDF cache context is updated.
- **`MarketplaceCallbackHandler`** — using a fake repository and signing helper. Assertions: a valid signed payload materialises an access grant and marks the request approved; an invalid signature is rejected; an unknown listing IRI is rejected; an idempotent retry is a no-op.

### Integration-tested flows

- **Provider CRUD + audit log.** Settings UI CRUD operations write audit log rows; permission gating returns 403 for unauthorised callers.
- **Catalog refresh end-to-end against a local HTTP fixture server.** Wire-level test that a real refresh job hits a fixture HTTP server serving a TTL file, populates `marketplace_listings`, and surfaces in `/api/marketplace/listings`.
- **Search index sees marketplace listings.** Add a listing, refresh, hit `/api/search?search_term=...`, assert a `marketplace-listing` result is returned with the correct provider badge data.
- **Import wizard happy path.** POST `/api/marketplace/listings/{iri}/import` with a bundle selection; assert the target entities exist with correct provenance; assert the Marketplace Origin panel data is returned by the entity detail endpoint.
- **Access flow happy path.** POST a request, assert workflow trigger fired, simulate a callback POST, assert grant materialised.

### Out of testing scope

- We do not test that rdflib parses Turtle correctly — that is the library's job.
- We do not test cross-provider conflict resolution beyond the documented IRI collision rule.
- We do not load-test the refresh workflow under thousands of providers; capacity is bounded by the per-provider limits.

## Out of Scope

- A bi-directional **Ontos Access API** spec for providers to implement (poll-based access negotiation). v1 uses webhook + email + manual fulfillment only. The spec is a v2 follow-up.
- Delivery methods other than Delta Sharing in v1. S3 volume share, UC table share, REST endpoints, email-delivered files all fall through to a generic external-link affordance.
- `oauth_client_credentials` auth mode. Token-refresh worker adds operational surface; deferred to v2.
- Provider rating / reputation / verified badge.
- Cross-provider dependency resolution (listing X depends on ontology Y from another provider).
- Paid-subscription / billing integration with commercial providers.
- A per-individual-listing audience editor UI. v1 supports admin-defined rule-based per-listing visibility only; provider-published `ontosmkt:audience` hints are honoured.
- A workspace-internal marketplace publication flow targeting Ontos itself (we already have `publication_scope`). External providers do not push **into** Ontos.

## Further Notes

- Adopting DCAT-AP is a strategic bet: it aligns Ontos with the EU Data Spaces / Gaia-X direction and avoids us re-inventing a marketplace JSON schema. It also makes Ontos a natural sink for any DCAT-AP catalog that already exists (national open-data portals, sector consortia).
- The Vibe Business generator tool is intentionally a separate, small repo. We do not want Ontos itself to ship a GitHub crawler; we want it to ship a DCAT consumer. The architecture stays clean.
- The Marketplace Origin panel is a precedent worth re-using: any future "this entity was imported / generated from elsewhere" feature (e.g. the LLM Ontology Generator's outputs) can reuse the same provenance shape.
- The `ON_REQUEST_ACCESS` workflow trigger reuse means commercial providers can plug into any approval workflow a customer has already configured (CAB review, Slack approval, ticket creation, etc.) without further provider-side work.
- We expect early-stage commercial providers (Vibe Business in alpha; small data-product startups) to be the dominant ecosystem before large vendors like S&P. The protocol must be cheap to author manually, which is why DCAT-AP TTL was chosen over a heavy JSON spec.
