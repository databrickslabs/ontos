# PRD: Multi-Domain Assignment for Teams, Data Contracts, Data Products, and Assets

## Concept Model

The relevant primitives:

- **Data Domain** — a hierarchical governance grouping (`data_domains` table; self-referential `parent_id`). Domains describe what the data is about (e.g., Sales, Finance, HR, Customer Master) and are used for browsing, discovery, ownership scoping, and tag propagation to Unity Catalog.
- **Domain-aware entities** — Teams, Data Contracts, Data Products, and Assets each carry a single, optional reference to one Data Domain today.
- **Primary domain** — the one domain a downstream system that only accepts a single value (ODCS export, Unity Catalog `data_domain` tag) should treat as authoritative.
- **Additional domains** — further domains the entity also belongs to. These participate fully in browsing, discovery, filtering, and search but are exposed to single-value integrations through extension fields.

These are distinct from the marketplace `publication_scope = "domain"` setting (which controls visibility, not assignment) and from the ODCS/ODPS YAML `domain` string (which is a single name field, exported from the primary).

## Problem Statement

Real assets, products, contracts, and teams routinely span more than one business domain, but Ontos forces every domain-aware entity into exactly one domain. This produces three concrete pains:

1. **Shared entities are misfiled or duplicated.** A `customers` table belongs to both Sales and Marketing; a "Customer 360" data product is consumed by Support, Sales, and Marketing. Today users either pick the "least wrong" domain (silently hiding the entity from the others) or duplicate the entity, which then drifts.
2. **Org structure cannot be modeled honestly.** A platform team that supports Finance and HR has to be filed under one or split into two teams. Cross-domain contracts (e.g., a master data contract used by several domains) cannot represent that fact in metadata.
3. **Discovery silently fails.** Users browsing the Sales domain do not see assets that are filed under Marketing but actually used in Sales workflows. Cross-domain reuse — one of the main reasons to run a data marketplace — becomes invisible.

The single-domain limit is also inconsistent across the four entity types: teams, contracts, and assets store `domain_id` (FK / soft-FK to `data_domains.id`); data products store a free-form `domain` string column that sometimes contains an ID and sometimes a name. Cleaning this up is a prerequisite for any cross-domain feature.

## Solution

Replace each entity's single domain reference with a polymorphic many-to-many relationship that designates exactly one primary domain alongside zero or more additional domains. Internally this is one junction table — `entity_domain_associations` — modeled on `entity_tag_associations`, with a `is_primary` boolean and a uniqueness constraint that enforces at most one primary per (entity_type, entity_id).

Single-value integrations (ODCS/ODPS export, Unity Catalog tag sync) consume the primary as their canonical value and emit additional domains through extension fields — `customProperties` for ODCS, multi-tag for UC. Filtering, search, browsing, and the marketplace are upgraded to "any of" semantics: an entity matches a domain filter when any of its assigned domains match (optionally including descendants, as marketplace already does today). Existing single-domain assignments migrate cleanly: every existing value becomes a primary record in the junction table.

The frontend introduces a single shared `DomainMultiSelector` component (popover + searchable badge list with a primary indicator) that replaces every existing single-domain `<Select>` and the legacy free-text input on the data product form.

## User Stories

### Multi-domain assignment

1. As a Data Steward, I want to assign a Data Product to multiple Data Domains, so that consumers in any of those domains can find it.
2. As a Data Steward, I want to assign a Data Contract to multiple Data Domains, so that contracts shared across business areas (e.g., master data) reflect their true scope.
3. As a Data Producer, I want to assign an Asset to multiple Data Domains, so that a shared table (e.g., `customers`) appears in every domain that uses it.
4. As an Admin, I want to assign a Team to multiple Data Domains, so that platform or cross-functional teams are visible to every domain they support.
5. As a Data Steward, I want to designate exactly one of an entity's domains as primary, so that downstream systems that need a single value have a deterministic answer.
6. As a Data Steward, I want the UI to clearly mark which domain is primary and let me change it without removing/re-adding domains, so that the primary choice is reversible and obvious.
7. As a Data Steward, I want to add or remove an additional domain without affecting the primary, so that I can iterate on domain breadth without re-confirming the canonical owner.
8. As a Data Steward, I want to remove all domains and leave an entity unassigned, so that draft or unclassified entities do not have to fake an affiliation.

### Discovery, search, and filtering

9. As a Data Consumer browsing a Data Domain detail page, I want to see all assets, contracts, products, and teams that include this domain (primary or additional), so that I see the full inventory of what the domain governs.
10. As a Data Consumer in the marketplace, I want to filter by one or more domains and have results show entities matching any of them, so that I can explore the union of multiple domains in one query.
11. As a Data Steward, I want the existing "include child domains" marketplace behavior to keep working with multi-domain entities, so that selecting a parent domain still surfaces entities assigned to its descendants.
12. As a Data Steward, I want list views (Teams, Contracts, Products, Assets) to display every assigned domain as a badge, with the primary visually distinguished, so that I can scan domain affiliation without opening a detail page.
13. As a Data Steward, I want to filter list views by domain and see entities where the domain is primary OR additional, so that the filter behaves like a tag filter.
14. As a Data Consumer searching the catalog, I want full-text and semantic search to match an entity by any of its domain names, so that domain-keyed searches return cross-domain entities.

### Forms and editing

15. As a Data Steward editing a Team, I want to pick multiple domains from a searchable popover and mark one as primary, so that team scope reflects reality.
16. As a Data Producer creating a Data Contract, I want the wizard to let me select multiple domains with one marked primary, so that the contract is correctly classified at creation time.
17. As a Data Producer creating a Data Product, I want a single, consistent domain selector that stores domain IDs (not free-text names), so that domain values are unambiguous and round-trip with import/export.
18. As a Data Producer viewing an Asset detail, I want to edit its domain assignments inline (not just see a read-only ID), so that I can correct or extend asset classification without leaving the page.
19. As a Data Steward, I want bulk imports of Assets to accept a `domain_ids` column (semicolon-separated, with the first treated as primary), so that I can onboard cross-domain inventories at scale.
20. As a Data Steward, I want bulk exports of Assets to emit `domain_ids` (primary first), so that round-tripping the export preserves all assignments.

### ODCS/ODPS exports

21. As a Data Producer exporting a Data Contract to ODCS, I want the standard `domain` field to receive the primary domain name, so that downstream tools that read ODCS see a valid single value.
22. As a Data Producer exporting a Data Contract to ODCS, I want any additional domains to be emitted under `customProperties` (e.g., `additionalDomains: [...]`), so that no information is lost in the export.
23. As a Data Producer exporting a Data Product to ODPS, I want the same primary-plus-additional convention applied to the ODPS export, so that the two formats behave consistently.
24. As a Data Producer importing an ODCS contract that uses the additional-domains custom property, I want those domains to be re-attached on import, so that round-tripping preserves multi-domain assignment.

### Unity Catalog tag sync

25. As a Data Steward, I want the UC tag sync to write the `data_domain` tag value as the primary domain, so that the existing convention is preserved for catalogs and consumers that read a single value.
26. As a Data Steward, I want additional domains to be written as separate UC tags (e.g., `data_domain_additional` per assignment), so that downstream UC tooling can still see the full set without breaking single-value consumers.

### Domain lifecycle

27. As an Admin deleting a Data Domain, I want the system to block the deletion if any entity has it as their primary domain, so that I do not silently leave entities without a canonical owner.
28. As an Admin deleting a Data Domain that is only ever an additional domain, I want the deletion to proceed and the corresponding association rows to be removed, so that domain cleanup does not require manual unassignment of every reference.
29. As an Admin, I want a domain detail page section that lists every entity (across types) assigned to the domain, distinguishing primary from additional, so that I can review impact before deletion.

### Migration and backward compatibility

30. As a System Operator, I want every existing single-domain assignment to be backfilled as a primary association during migration, so that no entity loses its current domain.
31. As a System Operator, I want the migration to resolve the data product `domain` column whether it currently stores a domain ID or a domain name, so that legacy rows are not lost.
32. As an Admin, I want the migration to log any unresolvable domain values (e.g., a stale name with no matching domain) so that I can manually reconcile them after upgrade.

### RBAC and visibility

33. As a User assigned to a team that spans multiple domains, I want my project visibility to consider all domains my teams belong to, so that cross-domain projects do not become invisible after the migration.

## Implementation Decisions

### Data model

- A new polymorphic junction table holds every domain assignment for every entity type, with a boolean primary flag and audit columns. The schema enforces at most one primary per (entity_type, entity_id) and uniqueness on (domain_id, entity_type, entity_id).
- The four scalar columns disappear: `teams.domain_id`, `data_contracts.domain_id`, `assets.domain_id`, `data_products.domain`. They are replaced entirely by the junction table.
- The migration backfills every non-null value as a primary association. For data products, the migration first attempts to interpret the legacy `domain` string as an ID, then falls back to a domain name lookup; unresolved values are logged and dropped.
- `data_domains` keeps its hierarchy. Multi-domain assignment is orthogonal to the parent/child tree — assigning a parent does not implicitly assign children.

### Backend modules

- **EntityDomainAssociationRepository** is the deep module. It provides: `set_domains_for_entity(entity_type, entity_id, domain_ids, primary_domain_id, assigned_by)` with replace-all semantics, idempotent upsert, batch reads (`get_domains_for_entities` for list endpoints to avoid N+1), and inverse lookups (`find_entity_ids_by_domain`, `find_entity_ids_by_domains`). Its interface mirrors `tags_repository.set_tags_for_entity`. It encapsulates the at-most-one-primary invariant and the deletion-blocking check.
- The four entity repositories (teams, contracts, products, assets) lose their domain column references and route domain reads/writes through the junction repository. Existing methods like `get_teams_by_domain`, `get_standalone_teams`, `get_by_domain`, `get_distinct_domains` are rewritten as junction-table queries with "any-of" semantics.
- The four entity managers gain a uniform `domain_ids: list[str]` plus `primary_domain_id: str | None` payload contract; managers validate the primary is in the set, resolve names→IDs where legacy code did so, and call the junction repository.
- A new **DomainExportAdapter** wraps the export-side concerns (ODCS `domain` field + `customProperties.additionalDomains`, ODPS equivalent, UC primary tag + additional tags). Both ODCS and UC code paths consume this adapter rather than reading the junction directly, keeping the export format conventions in one testable place.

### API contract

- Request/response payloads for the four entity types switch from `domain_id` (or `domain`) to `domain_ids: list[str]` and `primary_domain_id: str | null`. The primary is included in `domain_ids`. List endpoints accept `?domain_id=` (single, treated as any-of) and `?domain_ids=` (CSV, any-of) as filters.
- Existing teams routes that scope by domain (`/api/teams/domains/{domain_id}/teams`, `/api/teams/standalone`) keep their paths but adopt any-of semantics. "Standalone" means: zero domain assignments.
- The contract create payload no longer accepts the legacy `domain` (name) field; clients must pass `domain_ids` with resolved IDs.
- Domain delete endpoint surfaces a 409 with a structured body listing the entities for which it is primary, so the UI can offer reassignment guidance.

### Export and integration semantics

- **ODCS export**: standard `domain` string receives the primary domain's name; additional domains are emitted as a list under `customProperties` (key: `additionalDomains`, value: array of domain names). ODCS import recognizes the same custom property and reattaches the additional domains.
- **ODPS export**: same convention. Primary in the ODPS `domain` field; additional domains under `customProperties.additionalDomains`.
- **Unity Catalog tag sync**: primary written as the `data_domain` tag (current convention preserved). Each additional domain written as a separate tag with key `data_domain_additional`. The sync writes the primary tag first, then iterates the additionals.
- **Asset bulk CSV**: column renamed to `domain_ids`, semicolon-separated; the first ID in the list is the primary on import; on export the primary is emitted first, additional IDs follow.
- **Marketplace and term-mapping filters**: existing `RunTargetFilter.domain_ids: list[str]` already supports multi-value on the read side; adapters switch from filtering on the dropped scalar columns to joining through the junction table.

### Frontend modules

- **DomainMultiSelector** (new) is the deep frontend module: searchable popover, badge list with a primary indicator (e.g., a star icon or accent), add/remove and "set as primary" actions, controlled value `{ domain_ids, primary_domain_id }`. Modeled on the existing `TagSelector`. Used by every entity form.
- The data product create dialog and the legacy data product form both use the new selector. The legacy free-text `info.domain` input is removed.
- Asset detail gains a domain editor section using the same component.
- List views render badge groups in their domain columns. The `useDomains` hook gains a `getDomainNames(ids: string[])` helper.
- Marketplace and discovery filters become multi-select and pass `domain_ids` to the backend; the existing "include child domains" toggle behavior is preserved.

### RBAC and visibility

- The `projects_repository.get_projects_by_domain_relationship` join now derives the user's team-domain set from the junction table (union across all the user's teams' domains, primary and additional) and uses `IN` instead of equality. Project visibility expands consistently with multi-domain teams; no project-side schema change is needed for this PRD.

### Domain deletion

- Deletion is blocked when at least one entity has the domain as its primary. The 409 response includes the count and a small sample of affected entities per type so the UI can guide the user.
- When a domain is only ever an additional domain, deletion proceeds and association rows are removed.
- The existing `cascade="all, delete-orphan"` for `data_domains.children` is unchanged.

### Out-of-band cleanups bundled with this PRD

- `src/backend/src/file_models/data_products.py` references `entity.domain_id` against a model whose column is `domain` — broken today; replaced by reading from the junction table.
- Defensive code that matches data products by both ID and name (marketplace views) is removed once products store domain IDs only.

## Testing Decisions

Tests focus on external behavior — domain assignment outcomes, filter results, export shapes — not on implementation details like specific SQL or column names.

### Deep-module unit tests

- **EntityDomainAssociationRepository**: replace-all semantics (adding, removing, reordering domains), at-most-one-primary invariant (rejects two primaries, allows zero only when the set is empty), idempotent upserts, batch reads return correct primary marking, inverse lookups return the right entity IDs for any-of and primary-only queries, deletion-blocking returns the right blocker list. Prior art: `src/backend/src/tests/unit/test_data_domains_repository.py`.
- **DomainExportAdapter**: given a stub primary + additionals, produces the correct ODCS dict (primary in `domain`, additionals under `customProperties.additionalDomains`); UC tag sync emits the primary tag first and then one tag per additional; round-trip from ODCS dict back to (primary, additionals) is lossless. Prior art: `src/backend/src/tests/integration/test_odcs_export_validation.py`.

### Integration tests (per entity)

- For each of teams, contracts, products, assets: create with `domain_ids` + `primary_domain_id`, update to add/remove/swap primary, list with `?domain_ids=A,B` filter and assert any-of, list with `?domain_id=A` and assert any-of, GET detail returns the full set. Prior art: `test_data_contracts_db.py`, `test_teams_routes.py`, `test_data_product_routes.py`.

### Migration tests

- Seed each table with mixed legacy values, including: a contract with `domain_id`, a team with null `domain_id`, an asset with `domain_id`, a product whose `domain` is an ID, a product whose `domain` is a name, and a product whose `domain` is unresolvable. After the upgrade, assert: the right rows exist in `entity_domain_associations`, every backfilled row is `is_primary = true`, and unresolvable values are absent (and were logged).

### Frontend tests

- **DomainMultiSelector** unit tests: rendering with empty / single / multiple domains, add/remove flows, primary indicator, "set as primary" action, search filter, controlled value updates. Prior art: `src/frontend/src/components/ui/tag-selector.test.tsx` (if present) and `src/frontend/src/hooks/use-domains.test.ts`.
- Wizard/dialog updates: existing tests for `data-contract-wizard-dialog.test.tsx` and `data-product-create-dialog.test.tsx` updated to assert the new payload shape (`domain_ids`, `primary_domain_id`).

### What we deliberately do not test

- We do not snapshot SQL strings, column lists, or JSON shapes beyond the contract surface. Tests should keep passing if internal queries are rewritten as long as the API behavior and exports stay correct.

## Out of Scope

- **Per-domain RBAC and permissions.** Feature-level permissions (e.g., `data-domains`, `settings-data-domains`) are unchanged. Future work could add row-level domain-scoped permissions but is not part of this PRD.
- **Hierarchy-aware automatic assignment.** Assigning an entity to a parent domain does not implicitly assign it to descendants. Marketplace's "include child domains" filter remains a discovery-time feature.
- **Multiple primaries** or per-domain ordering beyond `assigned_at`. The model is one primary per entity, period.
- **Soft-deletion of domains** or any kind of "archive" status. Domain deletion is hard delete (blocked when in use as primary).
- **Renaming the entire `domain` concept** (for example to "subject area" or "business glossary domain"). Naming is unchanged.
- **Backfill heuristics for assets without a current `domain_id`** (e.g., infer from contract or product). Backfill is purely the literal column value.

## Further Notes

- The four scalar columns are dropped in the same migration that introduces the junction table. There is no transitional period where both shapes are accepted; clients update with the release.
- The data product `domain` column has long been a soft-typed string with mixed ID/name semantics. This PRD removes the ambiguity at the storage layer and at the API layer at the same time. UI code that previously matched products by both ID and name is simplified.
- The existing process workflow scoping (`scope_config: {type: "domain", ids: [...]}`) and term-mapping `RunTargetFilter.domain_ids` already use list-of-IDs shapes and require no contract changes; only the underlying joins move to the junction table.
- The plan file generated earlier (multi-domain_assignment_2f7410be.plan.md) reflects the prior "fully replace, no primary" decision and needs to be revised to add the `is_primary` column, the export adapter, and the deletion-block behavior described here.
