# Plan: Domains ↔ UC governed tags, bidirectional (nebw #3)

> Branch: `nebw-domain-uc-sync` (off `nebw-bugfixes`). Targets `development`.
> Part of the [nebw customer batch](./nebw-customer-batch.md).

## The hard constraint (verified Aug 2026)

Databricks Discover **Domains/Subdomains are layered on governed tags**, but:
- There is **no native "this governed tag IS a domain" boolean**.
- There is **no public API to create/publish a Discover Domain card** (UI only, needs `MANAGE DISCOVERY`).
- What is programmatic: create the governed tag (`CREATE GOVERNED TAG` via SQL Statement Execution / tag-policy APIs) and assign it (`SET TAG` / Entity Tag Assignments API). Subdomains use the `{parentTag}/{subdomain}` key convention.
- SDK surface: `ws.tag_policies` (governed-tag policies), `ws.entity_tag_assignments`. **Not** `ws.governed_tags.*`.

So "denote a domain natively" realistically means: **create a governed tag per domain and assign it, following the Discover key convention**; the final Discover Domain card stays a documented manual step.

## Current state

- `uc_tag_sync` job (cluster-side, reads Lakebase, writes via Spark SQL `ALTER … SET TAGS`) already tags datasets/tables with `ontos_data_domain_name = {DOMAIN.NAME}` as a **plain** tag. `data_domain` is a configured `entity_type`.
- Domains/subdomains are `DataDomain` rows (self-FK `parent_id`).

## Status (updated 2026-08-19)

- ✅ Shared pure helpers `src/common/governed_tags.py` (key/value convention, parse, import ordering) + tests.
- ✅ Outbound: `uc_tag_sync` emits the domain as the `databricks_domain` governed tag (`{domain}` / `{parent}/{subdomain}`) when `use_governed_domain_tag` is set (replaces the plain tag). Domain read SQL now joins the parent; yaml default enables the flag. Tested via a stubbed-import test.
- ✅ Inbound: `DomainUcSyncManager` — compute proposals (auto-inserts missing parents, dedups, marks exists/create), `create_import_review` (review-gated, skips when nothing new), `apply_import` (parents before subdomains, idempotent). Fixed a latent UUID-stringify bug in `create_domain_internal`.
- ✅ Routes: `POST /data-domains/import-from-uc/{preview,review,apply}`.
- ⬜ **Follow-up:** a UC reader that discovers domain governed-tag values (information_schema / entity tag assignments) to feed the import endpoints (they currently accept `tag_values` in the body). The Discover Domain *card* remains a manual UI step (no API).

## Scope for this PR (outbound first, then inbound)

1. **Outbound — domains as governed tags.** Extend `uc_tag_sync` so domain tagging uses a **governed tag** whose key follows the Discover convention (`{domain}` for top-level, `{parent}/{subdomain}` for subdomains) instead of / in addition to the current `ontos_data_domain_name` plain tag. Ensure the governed tag key exists (tag-policy create-if-missing, idempotent) before assignment. Config flag to opt in so existing plain-tag behavior is preserved.

2. **Inbound — import domains from UC.** An app-side importer that reads governed tags present in UC (via information_schema tag views / entity tag assignments) and, through the **Asset Review** flow from #2, proposes creating/updating `DataDomain` rows (including subdomain hierarchy from the `{parent}/{subdomain}` key convention). Reuses the custom-UUID create path from #1 so imported domains can keep a stable id.

## Decisions (confirmed)

- **Outbound: replace** the plain `ontos_data_domain_name` tag with the governed-tag domain convention (`{domain}` / `{parent}/{subdomain}`). Cleaner end state; existing tag-key consumers must migrate.
- **Inbound: via Asset Review.** Proposed domain create/updates go through the Asset Review flow (from #2) for human approval before writing — consistent with contract-drift adoption.
- **Subdomain import auto-creates missing parents**: a `{parent}/{subdomain}` tag whose parent domain doesn't exist locally creates the parent `DataDomain` first, then the subdomain under it.

## Testing

- Unit: governed-tag key derivation (top-level + `{parent}/{subdomain}`), idempotent ensure-key, reconcile add/remove.
- Unit: inbound parse of UC governed tags → DataDomain create/update payloads (hierarchy from key convention).
