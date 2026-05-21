# PRD: Governance Event Stream

## Problem Statement

Ontos today has four separate primitives that each capture a slice of "something governance-relevant happened" and a handful of side-effecting calls that fire after a state change. None of them are coordinated, all of them are invoked directly from controller code, and there is no way for an external system to react to a governance change at all.

Concretely:

- **`audit_manager.log_action(...)`** is called from individual controllers whenever a developer remembered to add it. The action string and details payload are invented per call site, so the audit trail is uneven and easy to forget.
- **`change_log_manager.log_change(...)`** records polymorphic per-entity create/update/delete/status rows. It is also called directly from controllers and overlaps semantically with the audit log: the same edit produces both rows, with different shapes, in two different tables.
- **`certification_propagator`** runs synchronously inside the certify request to BFS-walk `entity_relationships` and update `inherited_certification_level`. The certify endpoint blocks on it; failures cascade to the user-facing call.
- **`search_manager`** reindexing happens via direct calls from mutation paths. New manager? New reindex hook to remember.
- **`notifications_manager`** is invoked ad-hoc per producer to fan out user notifications. Each new producer wires its own templated calls.
- **`entity_subscriptions_manager`** lets a user subscribe to a Data Product, but the subscription is only honored where the producer explicitly remembered to send a notification. Most lifecycle changes never reach subscribers.
- **The `connectors/kafka.py` stub is empty.** There is no path for a downstream catalog, IAM platform, ITSM tool, or compliance platform to react to a governance change in Ontos. Integrations would have to poll the REST API.

The result is tight coupling, brittle integrations, and a governance trail that is structurally unable to satisfy "what happened, when, by whom, and what reacted to it" for any non-trivial change. As Ontos grows toward a Data Mesh control plane, this becomes a hard ceiling: ownership, policy, lifecycle, discoverability, and compliance are distributed concerns by design and need a shared coordination spine.

## Solution

Introduce a single **governance event stream** as the canonical mechanism by which every governance-meaningful state change is announced inside Ontos and (in later phases) to external systems. Producers emit small, factual, versioned, CloudEvents-shaped events; subscribers react independently; a transactional outbox guarantees that events match committed DB state.

The four existing primitives are not replaced — they are re-expressed as **subscribers** to the new bus. `audit_manager` writes its file + DB log from event handlers. `change_log_manager` writes the polymorphic per-entity log from event handlers. `notifications_manager` becomes the templated user-notification subscriber, keyed off event type. `search_manager` reindex becomes a subscriber. The certification propagator becomes an async subscriber instead of a blocking sync call inside the certify request. `entity_subscriptions_manager` becomes a fan-out subscriber, so user subscriptions finally honor every governance event automatically.

The PRD ships in three phases, modelled on PRD #86 (Unified Lifecycle) and PRD #242 (Approval Workflows v2):

- **Phase 1 — Internal control plane.** In-process subscribers, transactional outbox, the six built-in subscribers above, ~9 producer managers, ~15 fine-grained event types plus a generic `EntityFieldChanged` for routine edits.
- **Phase 2 — External webhook subscriptions.** Admin UI to register webhook endpoints with event-type filters, domain scoping, HMAC signing, retry policy, and a dead-letter queue. Same outbox, new sink. Approval Workflows v2 webhook step migrated to subscribe instead of fire-and-forget.
- **Phase 3 — Streaming sink.** A broker-backed sink (Kafka, NATS, or Databricks Delta-table-as-stream / Lakeflow Pipeline) for true mesh interop with downstream catalogs, IAM, and compliance platforms. Broker choice deferred to its own PRD.

The event taxonomy follows the three-layer model called out in the design brief: **Governance** events at the top (domains, owners, policies, certification, publication, subscriptions, access), **Metadata** events underneath (schemas, tags, glossary terms, semantic links), and **Operational** events below (provisioning finished, validation failed, sync completed). Phase 1 focuses on the Governance layer; Metadata and Operational layers grow in later phases.

## User Stories

### Producer / developer stories

1. As an Ontos backend developer, I want to emit a single `event_bus.emit(...)` call from a manager method, so that I do not have to remember to call `audit_manager`, `change_log_manager`, `notifications_manager`, and `search_manager` individually after every state change.
2. As an Ontos backend developer, I want the emit call to participate in the same SQLAlchemy transaction as the entity write, so that a committed entity change always produces an event and a rolled-back entity change never does.
3. As an Ontos backend developer, I want to declare a subscriber by decorating a function with `@event_subscriber("DataProductCertified")`, so that registering a new reaction to an event does not require touching the producer.
4. As an Ontos backend developer, I want to look up the schema for an event type at runtime via an event registry, so that I can validate payloads in tests and document the contract for external consumers.
5. As an Ontos backend developer, I want to add a new event type by registering it once and then emitting it, so that the catalog stays self-describing without a separate schema repo.

### Audit / governance stories

6. As a Compliance Officer, I want every governance-meaningful change in Ontos (ownership, certification, publication, policy attachment, access grant, subscription, lifecycle transition) to produce a structured event with actor, timestamp, before/after state, and a correlation ID, so that I can reconstruct what happened and who did it for any entity at any point in time.
7. As a Compliance Officer, I want the audit log to be populated automatically from the event stream, so that no future feature can ship a state change without leaving an audit trail.
8. As a Compliance Officer, I want events to carry the `domain` and `tenant` of the affected entity, so that I can scope audit reports to a single business unit without reverse-resolving every entity.
9. As an Auditor, I want a correlation ID on every event that originates from the same user action, so that I can follow one click in the UI through every system that reacted to it.
10. As a Compliance Officer, I want events to be retained for a configurable window (default 30 days for the outbox, indefinite for the audit log projection), so that retention policies can be tuned without code changes.

### Internal-consumer stories (Phase 1)

11. As a Data Steward, I want certification changes to propagate to downstream contracts, datasets, and tables asynchronously, so that the certify request returns immediately and propagation failures do not surface as user-facing errors.
12. As a Data Consumer who has subscribed to a Data Product, I want to receive a notification when its certification level changes, when it is deprecated, when its published scope changes, when a new contract version is published, or when a compliance violation is detected on it, so that I learn about anything that affects my consumption without polling.
13. As an end user searching the catalog, I want search results to reflect lifecycle and certification changes within seconds of the change being saved, so that I never see a stale "draft" badge on a product that was just certified.
14. As a Data Steward, I want the system to keep `inherited_certification_level` consistent across the entity graph automatically after I certify or decertify a parent, so that I do not have to manually re-trigger propagation.
15. As an end user, I want notifications for events on my subscribed entities to come from one place with consistent templates, so that the inbox is coherent rather than a patchwork of per-feature one-offs.

### Admin / operator stories

16. As an Admin, I want a Settings panel that lists every registered event type with its schema, owning manager, and recent emission count, so that I can see what the system actually emits without reading code.
17. As an Admin, I want to see the last N emitted events with their type, subject, actor, and dispatch status, so that I can debug "did my change actually fire an event?" without SSHing into a worker.
18. As an Admin, I want failed event dispatches to be visible (with the failing subscriber, error, and attempt count), so that a stuck integration is observable rather than silent.
19. As an Admin, I want to manually replay a single event or a range of events from the outbox, so that I can recover after a subscriber bug without manufacturing fake state changes.
20. As an Admin, I want event delivery to keep working when Ontos runs with multiple uvicorn worker replicas, so that scaling out the App does not introduce duplicate or missed handler invocations.

### External-integration stories (Phase 2)

21. As an Integration Admin, I want to register a webhook endpoint that receives a subset of event types (filtered by event type, domain, and tenant), so that an external catalog only sees the events it cares about.
22. As an Integration Admin, I want each outgoing webhook delivery to be HMAC-signed with a per-subscription secret, so that the receiving system can verify authenticity.
23. As an Integration Admin, I want failed webhook deliveries to retry with exponential backoff up to a configurable budget and then move to a dead-letter queue I can inspect and replay, so that a transient outage on the receiver side does not silently drop events.
24. As an Integration Admin, I want each webhook delivery to use the standard CloudEvents 1.0 binary or structured HTTP encoding, so that off-the-shelf CloudEvents SDKs in any language can consume Ontos events without a custom client.
25. As a workflow designer using Approval Workflows v2, I want the existing per-step webhook to be replaceable by a webhook subscription on `AgreementSigned`, so that long-term I have one mechanism instead of two.

### External-integration stories (Phase 3)

26. As a Platform Engineer, I want Ontos governance events to be available on a streaming broker (Kafka topic, Delta table, or equivalent), so that downstream Lakeflow pipelines, Spark jobs, and external mesh services can consume them with at-least-once delivery without polling Ontos.
27. As a Platform Engineer, I want each event on the streaming sink to preserve the same CloudEvents envelope used internally and via webhooks, so that consumers do not have to special-case the source.

### Anti-pattern stories (negative requirements)

28. As an Ontos backend developer, I do not want every UI click to produce an event, so that the stream stays meaningful and downstream subscribers are not flooded.
29. As an Ontos backend developer, I do not want vague `DomainUpdated` or `ProductUpdated` events to be emitted, so that consumers can react precisely to ownership, certification, publication, or policy changes individually.
30. As an Ontos backend developer, I do want a single `EntityFieldChanged` event to exist for routine non-governance edits (description, tag, name) carrying a diff, so that coverage is complete without requiring a fine-grained event for every nullable column.

## Implementation Decisions

### Layering relative to existing primitives

- The new event bus is **layered over** `audit_manager`, `change_log_manager`, `notifications_manager`, `search_manager`, and `certification_propagator`. None of these tables or managers are deleted.
- All five become **built-in subscribers** to the bus. Producers stop calling them directly.
- The migration from direct calls to event-driven invocation is incremental: each producer manager is refactored in its own commit, and in that commit the previous direct calls are removed in the same diff to avoid dual-write windows.
- `entity_subscriptions_manager` is added as a sixth built-in subscriber, providing automatic user-level fan-out for events on any subscribed entity.

### Envelope

- CloudEvents 1.0 with the JSON content mode.
- Standard fields: `id`, `source`, `specversion`, `type`, `time`, `subject`, `datacontenttype`, `data`.
- Governance extension attributes: `actor` (username or service principal), `actoremail`, `tenant`, `domain`, `correlationid`. Extensions follow the CloudEvents extension naming rules (lower-case alphanumeric).
- The `data` payload is event-type-specific and validated against a registered Pydantic model.
- Events that represent a state change carry `before` and `after` blocks inside `data`, scoped to the fields that changed; full snapshots are not included.
- Lineage events (Phase 2+) wrap an OpenLineage payload inside `data` while still using the CloudEvents envelope.

### Event taxonomy and granularity

- **Hybrid grain.** Fine-grained for governance-meaningful state changes; coarse `EntityFieldChanged` (with diff) for routine field edits.
- Phase 1 fine-grained event types (initial set, owned by the manager indicated):
  - `data_domains_manager`: `DomainCreated`, `DomainArchived`
  - `business_owners_manager`: `OwnerAssigned`, `OwnerRemoved`, `StewardChanged`
  - `data_products_manager`: `DataProductRegistered`, `DataProductCertified`, `DataProductDecertified`, `DataProductPublished`, `DataProductUnpublished`, `DataProductDeprecated`
  - `data_contracts_manager`: `DataContractVersionPublished`, `DataContractCertified`
  - `entity_subscriptions_manager`: `SubscriptionCreated`, `SubscriptionCancelled`
  - `access_grants_manager`: `AccessRequestSubmitted`, `AccessGranted`, `AccessRevoked`
  - `approvals_manager`: `AgreementSigned` (emitted on workflow completion; subsumes the workflow webhook step long-term)
  - `compliance_manager`: `ComplianceViolationDetected`, `ComplianceViolationResolved`
  - Cross-cutting: `PolicyAttached`, `PolicyDetached`
- Generic event for routine edits: `EntityFieldChanged` with `data` containing `entity_type`, `entity_id`, and a `diff` map of `{field: {before, after}}`.
- Vague names like `DomainUpdated` or `ProductUpdated` are explicitly forbidden; producers emit either a fine-grained governance event or `EntityFieldChanged`.

### Producer scope (Phase 1)

- Mesh-core managers only: `data_domains_manager`, `data_products_manager`, `data_contracts_manager`, `entity_subscriptions_manager`, `access_grants_manager`, `business_owners_manager`, `approvals_manager`, `certification_propagator`, `compliance_manager`.
- Operational/utility managers (CatalogCommander, MDM, SemanticModels, SchemaImport, etc.) are out of Phase 1 scope. They can be added in Phase 1.5 as needs arise.

### Subscriber scope (Phase 1)

Six built-in subscribers ship in Phase 1:

1. **Audit subscriber** — writes the existing `audit_log` table + file log from every event.
2. **Change log subscriber** — writes the polymorphic `entity_change_log` table from every event whose `subject` resolves to an entity.
3. **Search index subscriber** — calls into `search_manager` to (re)index the affected entity for create/update/delete-shaped events.
4. **Certification propagator subscriber** — listens for `DataProductCertified` / `DataProductDecertified` and re-runs the BFS propagation asynchronously. Replaces the in-line sync call in the certify endpoint.
5. **Notification subscriber** — looks up a templated `NotificationTemplate` by event type and dispatches via `notifications_manager` using the existing in-app/email/webhook channels and role/recipient rules.
6. **Entity-subscriptions fan-out subscriber** — for every event whose `subject` matches an entity any user is subscribed to, generates a user-targeted notification (delegated to subscriber #5 by emitting a derived notification event, or handled inline — to be decided in implementation).

### Outbox + delivery model

- New table `outbox_events` with columns: `id` (UUID), `event_type`, `subject`, `source`, `time`, `actor`, `tenant`, `domain`, `correlation_id`, `payload` (JSONB), `dedupe_key` (nullable, used for idempotency), `attempts`, `status` (`pending`/`dispatched`/`failed`), `locked_until`, `locked_by`, `last_error`, `created_at`, `dispatched_at`.
- Indexes on `(status, locked_until)`, `(event_type)`, `(subject)`, `(correlation_id)`, `(dedupe_key)`.
- Producers write the outbox row in the same SQLAlchemy session as the entity mutation, so DB commit is atomic across both.
- A relay loop runs as a FastAPI lifespan task in **every** uvicorn worker. Each loop iteration:
  - Selects up to N pending rows with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT N`, sets `locked_until = now() + lease_seconds`, `locked_by = worker_id`.
  - Invokes every registered subscriber for each event's type.
  - Marks the row `dispatched` on full success, increments `attempts` and records `last_error` on partial/total failure with exponential backoff up to a per-event budget.
- This design works on Lakebase / Postgres without any new infrastructure, gives at-least-once delivery, and dedupes via `dedupe_key` when subscribers are non-idempotent.
- Outbox rows are kept for a configurable retention window (default 30 days after dispatch) and reaped by a background task. Audit log + change log retain on their own existing schedules.

### Subscriber registration

- A `@event_subscriber(event_type)` decorator collects handler functions at startup, mirroring the existing `@searchable_asset` pattern in the search registry.
- A handler signature receives the deserialized envelope (Pydantic model) and a fresh DB session.
- Handlers are invoked sequentially per event by default (so the audit row is written before the notification is sent). A future enhancement may allow parallel handlers per event when ordering is not required.

### Schema evolution

- Each event type carries an integer `schema_version` inside `data`.
- Additive changes (new optional fields) do not bump the version.
- Removing or renaming a field requires a new version (e.g. `DataProductCertifiedV2`); the old version stays registered until all known subscribers have migrated.

### Phase 2 — external webhook subscriptions (sketch)

- New tables: `webhook_subscriptions` (id, name, url, secret, event_type_filter, domain_filter, tenant_filter, active, created_at, created_by) and `webhook_deliveries` (id, subscription_id, event_id, attempt, status, http_status, response_body, error, scheduled_at, completed_at).
- Same outbox drives delivery; the webhook delivery worker is registered as a meta-subscriber that fans matching events out to every active subscription.
- HMAC-SHA256 signature in `X-Ontos-Signature` header using the per-subscription secret. Standard CloudEvents headers (`Ce-Id`, `Ce-Source`, `Ce-Type`, `Ce-Time`, `Ce-Subject`, `Ce-Specversion`, plus `Ce-` extensions for actor/domain/tenant/correlation) on every request (binary content mode); structured content mode supported via `Content-Type: application/cloudevents+json`.
- Retry budget: 6 attempts with exponential backoff, then dead-letter. Admin UI surfaces deliveries and offers a Replay action.
- Approval Workflows v2 webhook step (#242) is migrated to subscribe to `AgreementSigned` instead of firing inline. The legacy step is preserved for one release for backward compatibility, then deprecated.

### Phase 3 — streaming sink (sketch)

- A streaming sink is added as another meta-subscriber on the outbox. Choice of sink (Kafka topic, Delta table append + change feed consumed via Lakeflow Pipeline, NATS) is deferred to its own PRD.
- Sink preserves the CloudEvents envelope. Delta-table-as-stream is the most likely default given the platform: it costs no new infra, integrates with existing Unity Catalog governance, and gives Spark/Lakeflow consumers an immediate way to subscribe.

### Modules

The Phase 1 module breakdown — designed for deep modules with simple, testable interfaces:

1. **Event Envelope** — Pydantic models for the CloudEvents 1.0 envelope, governance extensions, and per-event-type `data` payloads. Pure data, no I/O.
2. **Event Registry** — registry of event types: name, owning manager, payload Pydantic model, current schema version. Discoverable at runtime, used by the Admin UI and by tests.
3. **Event Bus** — single-method `emit(db, event_type, subject, payload, *, before=None, after=None, correlation_id=None)` interface. Validates payload against the registry, builds the envelope, writes the outbox row using the supplied session. Pure side-effect-on-session module; no networking.
4. **Outbox Repository** — CRUD on `outbox_events` plus the `claim_batch_for_dispatch()` method that issues the `FOR UPDATE SKIP LOCKED` query.
5. **Outbox Relay** — FastAPI lifespan-managed background task that loops over `claim_batch_for_dispatch()`, invokes the dispatcher, and updates row state. Owns the retry policy.
6. **Subscriber Registry + Decorator** — collects `@event_subscriber` handlers at import time. Provides `dispatch(event)` which invokes every registered handler for the event's type sequentially.
7. **Built-in Subscribers** — six handler modules (audit, change log, search index, cert propagator, notification, entity-subscriptions fan-out). Each is a thin adapter over the existing manager.
8. **Producer Refactors** — manager-by-manager replacement of direct calls to audit/change_log/search/cert/notifications with `event_bus.emit(...)`. Each producer refactor is its own commit/sub-issue.
9. **Admin Settings Panel** — frontend view listing event types from the registry, recent emissions from the outbox, dispatch status, and a manual replay action.
10. **Alembic Migration** — adds the `outbox_events` table, indexes, and any reaper bookkeeping table.

Each of modules 1–6 is deliberately deep and shallow-interfaced: they encapsulate the entire event mechanism behind small, stable APIs (`emit`, `claim_batch`, `dispatch`, `@event_subscriber`) that the rest of the codebase consumes without seeing internals.

## Testing Decisions

### Testing Philosophy

Tests verify **external behavior through public interfaces**, not implementation details. A good test:

- Calls a manager method that emits an event and asserts the resulting outbox row, audit log entry, change log entry, and notification — i.e. the observable side effects of the system, not the wiring between bus and subscribers.
- Uses real Postgres (Lakebase test schema or local Postgres via the existing `conftest.py` patterns) for any test that exercises the outbox, since the `FOR UPDATE SKIP LOCKED` semantics are not faithfully reproducible with SQLite.
- Mocks only at the outermost integration boundary (e.g. an external HTTP server for Phase 2 webhook tests, simulated via `respx`).
- Uses fixtures for setup/teardown of the outbox and subscriber registry.

### Backend Tests (pytest)

| Module | Test Type | What to Test |
|---|---|---|
| Event Envelope | Unit | CloudEvents 1.0 field validation, governance extension attribute serialization round-trip, per-event-type payload validation, `before`/`after` shape constraints |
| Event Registry | Unit | Registration of new event types, lookup by name, schema-version retrieval, rejection of duplicate registrations |
| Event Bus | Integration (real Postgres) | `emit()` writes the correct outbox row in the supplied transaction; rollback of the transaction also rolls back the outbox row; payload validation rejects malformed input; correlation_id propagates correctly |
| Outbox Repository | Integration (real Postgres) | `claim_batch_for_dispatch()` skips locked rows under concurrent claimers, releases leases on timeout, idempotent on `dedupe_key` |
| Outbox Relay | Integration (real Postgres + fake clock) | Successful dispatch marks rows dispatched; subscriber error increments attempts and records last_error; exhausted retries mark rows failed; concurrent workers do not double-dispatch |
| Subscriber Registry | Unit | Decorator registers handler under the right event type; dispatch invokes all registered handlers sequentially; missing-handler-for-type is logged but not fatal |
| Audit subscriber | Integration | Emitting any event of any type produces an `audit_log` row with the right actor/feature/action |
| Change-log subscriber | Integration | Events whose subject resolves to an entity produce an `entity_change_log` row of the correct shape |
| Search index subscriber | Integration | Lifecycle / certification / publication events trigger reindex of the affected entity |
| Cert propagator subscriber | Integration | `DataProductCertified` triggers async BFS propagation of `inherited_certification_level` end-to-end |
| Notification subscriber | Integration | Templated notifications dispatch through the existing `notifications_manager` with correct recipient / role rules |
| Entity-subscriptions fan-out | Integration | A user subscribed to a Data Product receives a notification for every event whose subject is that product |
| Producer refactors | Integration | For each refactored manager (×9), the externally observable side effects after a state change (audit row, change log row, search reindex, notification, propagation) match the pre-refactor behavior — i.e. behavior-preserving refactor |
| Alembic Migration | Integration | `alembic upgrade head` and `alembic downgrade -1` succeed; outbox table and indexes exist; downgrade leaves no orphaned objects |

Prior art:

- `test_data_products_manager.py` — manager unit tests with mocked DB session.
- `test_data_product_routes.py` — integration tests via FastAPI `TestClient`.
- `test_workflow_notification_channels.py` — integration test of in-app/email/webhook channel dispatch (closest existing analogue for delivery-level testing).

### Frontend Tests (Vitest + React Testing Library)

| Module | Test Type | What to Test |
|---|---|---|
| Event Registry view (Settings) | Component | Renders the list of event types with owning manager, schema version, recent count |
| Recent Emissions table | Component | Renders rows from the outbox API, status badge per row, replay action calls the right endpoint |
| Replay confirmation dialog | Component | Confirms before replay, surfaces success/error toast |

Prior art: `permissions-store.test.ts` (store/hook tests), `data-product-form-dialog.test.tsx` (component rendering tests).

## Out of Scope

- **Event sourcing.** Current-state tables remain the source of truth. Events are a side-effect log + integration channel, not the canonical state.
- **Replacement of the `audit_log` or `entity_change_log` tables.** Both stay; they become projections written by built-in subscribers.
- **Ontology Concept events.** RDF-backed concepts have a different storage model and are not in mesh-core scope. Adding them later requires a small extension to the subject-resolution logic, not a redesign.
- **Operational / metadata layer events** (provisioning finished, validation failed, schema drift detected, lineage changed). These belong in Phase 1.5 / Phase 2 and would land in operational managers (jobs, quality, lineage) rather than mesh-core managers.
- **Phase 3 broker selection.** The decision among Kafka, NATS, Delta-table-as-stream, and Lakeflow Pipeline is deferred to its own PRD because it has heavy operational and licensing implications.
- **External-consumer SDKs.** We rely on standard CloudEvents tooling (any HTTP client) for Phase 2; no Ontos-branded client SDK ships.
- **Per-event RBAC at the bus level.** Event emission is an internal mechanism; access control is at the subscription endpoint (Phase 2 admin UI) and at the entity level (existing). Sensitive payload fields are filtered by the producer, not by the bus.
- **Cross-instance federation of events** (Estate Manager #14). Once Estate Manager lands, events likely need a `workspace`/`account` axis on the envelope; that extension is documented as an Open Question rather than designed here.
- **Replacement of the workflow `webhook` step in v2 (#242)** in Phase 1. The migration to "subscribe to `AgreementSigned`" lands in Phase 2.

## Further Notes

### Implementation phases

- **Phase 1a — Foundations.** Envelope, registry, bus, outbox repository, outbox relay, subscriber decorator, Alembic migration, single throwaway test producer to prove the loop end-to-end.
- **Phase 1b — Built-in subscribers.** Audit, change log, search index, cert propagator, notification, entity-subscriptions fan-out (six sub-issues, one per subscriber).
- **Phase 1c — Producer refactors.** One sub-issue per mesh-core manager (×9), each removing direct calls to audit/change_log/search/cert/notifications in the same diff that adds the `event_bus.emit(...)` call.
- **Phase 1d — Admin Settings panel.** Read-only event-type registry view + recent emissions table + manual replay.
- **Phase 2** — Webhook subscriptions and admin UI; Approval Workflows v2 webhook-step migration.
- **Phase 3** — Streaming sink (own PRD).

### Anti-patterns (from the design brief)

- Per-click eventing is forbidden. Events represent meaningful state changes in the mesh operating model.
- Vague `*Updated` events are forbidden. Producers emit a specific governance event or `EntityFieldChanged` with a diff.
- Direct calls to `audit_manager`, `change_log_manager`, `notifications_manager`, `search_manager`, or the certification propagator from a refactored producer are forbidden — the lint should grow to enforce this once Phase 1c is complete.

### Open questions

- **Phase 3 broker choice.** Kafka vs NATS vs Delta-table-as-stream vs Lakeflow Pipeline. Defer to a Phase 3 PRD.
- **Estate Manager interaction.** Once #14 (Estate Manager) lands, the envelope likely needs `workspace_id` / `account_id` as additional governance extensions.
- **Ontology concept events.** Whether to extend coverage to `concepts_manager` (RBAC-backed RDF entities) and how to express the subject for an RDF resource in a CloudEvents `subject` field.
- **Sensitive-payload filtering.** Whether to enforce a producer-side `PII` annotation on event-type fields and have the bus refuse to emit events whose `before`/`after` carry unannotated sensitive values.
- **Fan-out subscriber design.** Whether `entity_subscriptions_fanout_subscriber` should derive secondary `UserNotificationRequested` events (cleaner separation, double the rows in outbox) or call `notifications_manager` directly inside the handler (simpler, but couples two subscribers).

### Backward compatibility

- The migration from direct manager calls to event-driven invocation is performed manager-by-manager in Phase 1c. Each commit is behavior-preserving — the externally observable side effects (audit row, change log row, notification, search reindex, propagation) match the pre-refactor behavior.
- Existing `audit_log` and `entity_change_log` rows are not migrated or rewritten.
- The Approval Workflows v2 webhook step continues to work unchanged in Phase 1; migration to subscriptions happens in Phase 2 with a one-release deprecation window.

### Relationship to existing PRDs

- **PRD #86 (Unified Lifecycle Tracking)** — defines the lifecycle / certification / publication dimensions whose state changes are the highest-value Phase 1 events. This PRD assumes #86 has shipped.
- **PRD #242 (Approval Workflows v2)** — `AgreementSigned` is one of the Phase 1 event types. The v2 webhook step migrates to a webhook subscription in Phase 2.
- **EPIC #14 (Estate Manager)** — informs the future tenant/workspace extension on the envelope.
- **EPIC #254 (Indirect Delivery Mode)** — orthogonal; file-backed governance mutations also flow through the same producers and therefore emit the same events.
