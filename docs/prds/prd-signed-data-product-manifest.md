# PRD: Signed Data Product Manifest

## Problem Statement

Ontos governs Data Products end to end — ODPS products, ODCS contracts, semantic links, owners, quality, certification and publication — but it cannot **prove** any of it to someone who does not trust the Ontos database.

Concretely:

- **A published product is mutable.** Nothing prevents a description, a contract property, or an output port from changing after `publish_product`. Consumers who subscribed to "version 1.2.0" have no way to tell whether what they see today is what was approved and published.
- **Exports are not verifiable.** `GET /api/data-products/{id}/odps/export` and `GET /api/data-contracts/{id}/odcs/export` return YAML that is not canonical (list order follows the database, keys are not sorted) and carries no integrity information. Two exports of the same product can differ byte-for-byte, and a tampered export is indistinguishable from a genuine one.
- **The link to physical data is implicit.** An output port references `catalog.schema.table`, but nothing records *which* table (Unity Catalog `table_id`), *which* snapshot (Delta version), or *which* schema was in place when the product was approved. A table can be dropped and recreated under the same name, or rewritten, with no trace in the product.
- **Audit and change logs are internal.** `audit_logs` and `entity_change_log` record that Ontos saw a change, but they live in the app database and cannot be handed to an auditor, a partner organization, or another Ontos instance as independent evidence.
- **Upcoming work needs a trust anchor.** Estate Manager federation (#143) imports remote entities, Marketplace publication (#165, #168) exposes products to external consumers, and the post-v1 RFC (#574) proposes a portable semantic package. All three need a way to say "this is exactly the product version that was approved", and none of them defines one.

The gap is not storage or transport — Unity Catalog, Delta and Delta Sharing already cover those — but a **portable, verifiable statement of what a product version is**.

## Solution

Introduce a **Signed Data Product Manifest**: a canonical, content-addressed, signed snapshot of a Data Product version, produced by Ontos and verifiable without Ontos.

- Each manifest contains the product **definition** (identity, ODPS, ODCS of every linked contract, semantic links, owners, tags) and the product **evidence** (Unity Catalog asset digests and a quality snapshot).
- Content is serialized with a strict subset of **RFC 8785 (JCS)** and hashed with **multihash sha2-256**, so identical content always yields the identical `content_hash`, independent of database order.
- Each manifest is appended to a **hash chain per version family** (`version_family_id`), referencing the previous manifest, and **signed with Ed25519** through a pluggable key provider (local key for development, Databricks Secrets for deployments). Private keys never live in the database or Git.
- Lifecycle facts that do not change content — published, unpublished, certified, decertified — are recorded as small signed **attestations** that reference a manifest hash, instead of creating new manifests.
- A standalone **offline verifier** (stdlib + `cryptography`) validates signature, hashes and chain from the exported artifacts alone. The Ontos verify endpoint additionally re-reads live state and reports *content modified since seal* and *data changed since seal*.

The feature is **opt-in and alpha**: disabled by default (`MANIFEST_SIGNING_ENABLED=false`) and surfaced in the UI only behind **Show Alpha Features**, following `docs/decisions/feature-maturity-policy.md`.

The manifest is deliberately transport-neutral. It is the envelope that Estate Manager imports (#143), Marketplace listings (#165) and the portability package (#574) can reference by `manifest_hash`; it does not replace any of them.

## User Stories

### Producer / steward stories

1. As a Data Product owner, I want publishing a product to seal its current definition automatically, so that "what we published" is fixed evidence rather than a mutable record.
2. As a Data Steward, I want to seal a product version manually (and to backfill products that were published before this feature existed), so that existing products can enter the chain.
3. As a Data Steward, I want certification and decertification to be recorded as signed attestations referencing the sealed manifest, so that a certificate points to the exact content it certified.
4. As a Data Product owner, I want re-publishing unchanged content to reuse the existing manifest, so that the chain only grows when content actually changes.

### Consumer / auditor stories

5. As a Data Consumer, I want to download a product's manifest and the publisher's public keys, so that I can verify the product independently of the Ontos UI.
6. As an Auditor, I want an offline verifier that checks signature, content hash, manifest hash and chain links, so that I can validate evidence handed to me without access to the Ontos database.
7. As a Data Consumer, I want Ontos to tell me whether a product's definition was modified after it was sealed, so that I notice silent edits to a published version.
8. As a Data Consumer, I want Ontos to tell me whether the underlying Delta tables changed (new commit, schema change, table recreated) since the product was sealed, so that I can decide whether my consumption is still valid.
9. As a Data Consumer, I want the manifest to pin each table to its Unity Catalog `table_id` and Delta version, so that I can reproduce the sealed snapshot with time travel while retention allows.

### Platform / security stories

10. As a Security Officer, I want signing keys to come from Databricks Secrets and only public keys to be stored by the app, so that a database leak cannot be used to forge manifests.
11. As a Security Officer, I want key rotation not to invalidate previously sealed manifests, so that historical evidence stays verifiable.
12. As an Ontos operator, I want sealing failures never to block publication or certification, so that enabling the alpha feature cannot break existing workflows.

## Implementation Decisions

Detailed rules (canonicalization, hash encoding, signing input, chain constraints, key identifiers) are specified in the companion ADR `docs/decisions/manifest-canonicalization-hashing-signing.md`. This section records the product-level decisions.

### What is sealed

- **Definition** (drives "content modified"): product identity (`id`, `version_family_id`, `version`, `parent_product_id`, `name`, domains), the ODPS export, the ODCS export of each contract linked from an output port, semantic links, owners (team members and business owners), and tags.
- **Evidence** (drives "data changed"): one digest per output port and the latest quality score per dimension.
- **Excluded from content**: lifecycle and presentation state — `status` (product, ports, datasets, contracts), `publication_scope`, `published_*`, `certification_*`, `maturity_*`, `created_at`/`updated_at`, draft ownership and `change_summary`. These change without changing *what the product is*; they are captured as attestations or remain in the existing audit trail.

### Asset digests (Unity Catalog)

- For output ports that reference a Unity Catalog table or view, sealing calls `WorkspaceClient.tables.get` with the app service principal and records `table_id`, `table_type`, `delta.lastUpdateVersion`, `delta.lastCommitTimestamp`, a digest of the physical schema (column name, type, nullability in position order) and, for views, a digest of `view_definition`.
- No SQL warehouse is used and no table data is read.
- The physical schema digest serves **integrity** ("has the table changed since the seal?"). It is not a contract-vs-catalog comparison: when contract drift detection is available (`ContractDriftManager.analyze_contract_drift`, proposed in #736), the seal records its result per linked contract (severity and suggested version bump) as evidence instead of implementing a second drift algorithm. Without it, the field is recorded as `not_evaluated`.
- Ports that are not Unity Catalog assets (Kafka topics, object storage paths, APIs) are recorded by reference with `verifiable: false`. Permission or lookup failures are recorded as `unavailable` with a reason (see `docs/decisions/uc-grants-for-app-sp.md`).
- Hashing actual table content is out of scope for this PRD.

### When manifests and attestations are produced

Sealing and attesting are wired into every code path that changes publication or certification state of a Data Product today:

| Path | Effect |
|---|---|
| `DataProductsManager.publish_product` | seal + `published` attestation |
| `POST /data-products/{id}/set-publication-scope` | seal + `published` (or `unpublished` when scope is `none`) |
| `POST /data-products/{id}/handle-publish` (approved) | seal + `published` |
| `POST /data-products/{id}/unpublish` | `unpublished` attestation |
| `POST /data-products/{id}/certify` | seal + `certified` |
| `POST /data-products/{id}/handle-certify` (approved) | seal + `certified` |
| `POST /data-products/{id}/decertify` | `decertified` attestation |
| Workflow step `_handle_publication` / `_handle_unpublish` | same as the matching route |
| Workflow step `_handle_certification` | `certified` / `decertified` |

With #991, `set-publication-scope` and `handle-publish` both call `DataProductsManager.set_publication_scope` (which also runs the output-port contract checks of `publish_product`), so the publication paths reduce to four sites: `publish_product`, `set_publication_scope`, the `/unpublish` route and the workflow `entity_action` step. Approved publication requests (Publication Request Review) publish through that workflow step.

A single helper is called from each site after its final commit — and therefore after any publish gate on the same path: the output-port contract checks, the `before_status_change` gates that `publish_product` runs through `transition_status` (which block since #985), and the Compliance Templates completeness gate proposed in #731. A blocked publication is never sealed. Hooks are **fail-open**: an error is logged and audited (`MANIFEST_SEAL_FAILED`) but never fails the user action. The manual seal endpoint is **fail-closed** and returns the error.

### Storage

- Three append-only tables: `data_product_manifests`, `data_product_manifest_attestations` and `manifest_signing_keys` (public keys only).
- The repository exposes insert and read operations only. Unique constraints on `manifest_hash`, `(version_family_id, sequence)` and `(version_family_id, previous_manifest_hash)` prevent duplicates and chain forks.
- Manifests do not hold a foreign key to the product, so evidence survives product deletion.

### API surface (alpha)

| Method | Path | Permission |
|---|---|---|
| `POST` | `/api/data-products/{id}/manifests` | `data-products` Read/Write |
| `GET` | `/api/data-products/{id}/manifests` | `data-products` Read-only |
| `GET` | `/api/manifests/keys` | `data-products` Read-only |
| `GET` | `/api/manifests/{manifest_hash}` | `data-products` Read-only |
| `GET` | `/api/manifests/{manifest_hash}/attestations` | `data-products` Read-only |
| `GET` | `/api/manifests/{manifest_hash}/verify?live=true` | `data-products` Read-only |
| `POST` | `/api/manifests/backfill` | `settings` Admin |

No new feature id is introduced; permissions reuse `data-products`, so default roles need no changes.

### Configuration

`MANIFEST_SIGNING_ENABLED` (default `false`), `MANIFEST_KEY_PROVIDER` (`local` | `databricks_secrets`), `MANIFEST_LOCAL_KEY_PATH`, `MANIFEST_SECRET_SCOPE`, `MANIFEST_SECRET_KEY`.

### Modules

1. **Canonicalization and hashing** — JCS subset, multihash encode/decode, section digests.
2. **Signing** — `KeyProvider` interface, local and Databricks Secrets providers, sign/verify with domain-separated inputs.
3. **Offline verifier** — `src/scripts/verify_manifest.py`, no Ontos imports.
4. **Manifest builder** — normalizes ODPS/ODCS exports and assembles definition + evidence.
5. **Asset digester** — Unity Catalog lookups for output ports.
6. **Manifests manager and repository** — seal, attest, verify, dedupe, chain management.
7. **Lifecycle hooks** — the single helper called from the paths above.
8. **Routes** — the endpoints above.
9. **UI** — alpha panel and badge on Data Product details, seal and verify actions, backfill for admins.
10. **Alembic migration** — the three tables.

## Testing Decisions

### Backend Tests (pytest)

| Module | Test Type | What to Test |
|---|---|---|
| Canonicalization | Unit | RFC 8785 key ordering and string escaping vectors; floats stringified; NaN/Infinity rejected; datetimes normalized to UTC `Z`; multihash round-trip for sha2-256 and sha3-256; unknown codes rejected |
| Signing | Unit | Sign/verify round-trip; tampered hash fails; manifest signatures do not verify as attestations (domain separation); stable `key_id`; Databricks secret decoding (mocked) |
| Offline verifier | Integration (subprocess) | Same golden vectors as the backend; exit codes for valid, tampered and malformed inputs |
| Manifest builder | Unit | Same content in different database order gives the same `content_hash`; status and publication changes do not change it; description changes change the definition digest |
| Manifests manager | Integration (SQLite) | Dedupe; chain sequence and previous hash per version family; concurrent fork rejected; key rotation keeps old manifests verifiable |
| Asset digester | Unit (mocked `tables.get`) | Delta properties captured; view definitions hashed; non-UC ports unverifiable; permission errors recorded as `unavailable`; physical schema digest changes when a column changes; contract drift recorded from the drift manager when present, `not_evaluated` otherwise |
| Verify | Integration | Detects tampered stored envelopes, broken chains, content modified after seal, data changed after seal |
| Lifecycle hooks | Integration | Every path in the table above seals or attests; sealing failures do not fail the user action; flag off is a no-op; existing workflow triggers still fire |
| Routes | Integration (`TestClient`) | Permission checks; 409 when disabled; backfill is admin-only and idempotent |
| Alembic migration | Integration | `alembic upgrade head` succeeds and `scripts/check-alembic-heads.py` reports a single head |

Prior art: `test_version_family.py`, `test_data_product_routes.py`, `test_workflow_triggers_publish.py`.

### Frontend Tests (Vitest + React Testing Library)

| Module | Test Type | What to Test |
|---|---|---|
| Manifest panel | Component | Renders latest manifest, chain and attestations; hides "Seal version" for read-only users; verify result shows content/data drift; empty state for unsealed products |
| Seal badge | Component | Renders sealed / modified / unsealed states |

Prior art: `entity-tags-panel.test.tsx`, `certification-badge` usage.

## Out of Scope

- **Data content hashing.** Hashing table rows (logical or physical) requires a canonical value encoding, a scan of the data and `SELECT` privileges; it is a candidate follow-up, not part of this PRD.
- **Contract-only manifests.** Contracts are sealed as part of the product that links them. Independent contract manifests can follow the same design later.
- **Transport and packaging.** Shipping manifests via Delta Sharing, Git or a portability bundle belongs to #143, #165 and #574; this PRD only defines the artifact they can carry.
- **Governance Event Stream.** Attestations are recorded directly by the lifecycle hooks. When #421 lands, the hooks can become event subscribers without changing the attestation format.
- **Decentralized identifiers.** Publisher identity is a key id plus the app instance; DID methods (`did:key`, `did:odf`) are a possible later mapping.
- **Fail-closed publication.** Blocking publication when sealing fails is not offered in this PRD; a `MANIFEST_SEAL_REQUIRED` setting is listed as an open question.
- **Database-level immutability.** Append-only behavior relies on the repository surface and unique constraints, not on Postgres triggers, to stay portable.

## Further Notes

### Implementation phases

1. **Crypto core and offline verifier** — canonicalization, multihash, Ed25519 signing, key providers, verifier script. No database or routes.
2. **Storage and manual seal** — tables, migration, builder, manifests manager, read and key endpoints.
3. **Asset digests and verify** — Unity Catalog digests, verify endpoint with live drift.
4. **Lifecycle hooks** — sealing and attestations on every publication and certification path.
5. **UI (alpha) and backfill** — Data Product details panel, seal badge, seal/verify actions, admin backfill.

### Open questions

- **Fail-closed option.** Should a deployment be able to require a successful seal before publication completes (`MANIFEST_SEAL_REQUIRED`)?
- **Media type.** Which media type should portability bundles use for the envelope (e.g. `application/vnd.ontos.manifest.v1+json`)?
- **Latency.** Sealing performs one Unity Catalog lookup per output port inside the request. Should large products seal asynchronously through a job?
- **Retention.** Delta time travel retention limits how long a sealed snapshot stays reproducible. Should the panel warn when a sealed version is past the table's retention window?
- **ODF mapping.** Open Data Fabric uses SHA3-256 multihashes and `did:odf` identifiers; the verifier already accepts sha3-256. A future adapter could project manifests into ODF metadata.

### Relationship to existing PRDs and issues

- **#574 (post-v1 RFC, portability lane)** — the manifest is the integrity envelope a canonical semantic package can reference by `manifest_hash`.
- **#143 / #153 (Estate Manager)** — imports can verify manifests and expose a `verification_status` for remote entities.
- **#165 / #168 (Marketplace provider)** — a listing can reference the `manifest_hash` of the exact version that was approved for publication.
- **#421 (Governance Event Stream)** — attestations are designed so that event subscribers can produce them once the stream exists.
- **#442 (Unified version family)** — `version_family_id` is the anchor of the manifest chain.
- **#736 (contract drift detection)** — the manifest reuses the drift result as evidence rather than computing its own contract-vs-catalog diff.
- **#731 (Compliance Templates)** — its publish completeness gate runs before sealing on the same paths; filled template values could be added to the sealed definition in a later version.
- **Lifecycle tag automation and deprecation PRD** — adds `deprecated` / `retired` attestation types.

### Approval before publication

The demo data ships four "pre-publish" approval gates (BCBS 239 Pre-Publish Attestation, IRB Approval Gate, HIPAA PHI Pre-Publish Check, OTA / Connected Services Release Gate) on a `before_publish` trigger that doesn't exist, so they load as `manual` and never run. A real gate needs to remember that a version was approved: re-running an approval workflow on every publish attempt pauses again. A sealed manifest gives that approval a fixed target: an approval can be recorded against a `manifest_hash`, and publication can check that the content about to be published still has that hash. The gate itself (trigger, workflow semantics) is tracked separately; this PRD only keeps the manifest usable for it.
