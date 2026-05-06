# PRD: Configurable Data Product Maturity Levels

## Problem Statement

Data governance teams need a way to measure and communicate how "mature" a Data Product or Data Contract is -- not just whether it's active or certified, but how complete its metadata, documentation, lineage, quality monitoring, and governance practices are. Today, a hardcoded "Production Readiness" panel on the Data Product detail page checks six fixed criteria (ODPS metadata, output contracts, logical attribute mappings, business terms, upstream systems, delivery channels), but this is insufficient:

1. The checks are hardcoded in Python -- admins cannot add, remove, or reorder them.
2. It only applies to Data Products (not Data Contracts).
3. There are no levels -- just a binary "ready / not ready / partial" outcome.
4. There is no history -- the check is computed fresh on every page load with no trending.
5. It does not account for key governance signals like certification, tagging, naming conventions, or active quality monitoring.

Organizations typically define a multi-level maturity model (e.g., five levels: Accessible, Described, Defined, Monitored, Trusted), where each level requires specific governance criteria to be met. The current system cannot express this.

## Solution

Introduce **Maturity** as a configurable, fourth orthogonal lifecycle dimension alongside Status, Certification, and Publication. Admins define an ordered set of maturity levels per entity type (Data Products and Data Contracts independently). Each level is gated by one or more compliance policies (using the existing compliance DSL). An entity's maturity level is the highest level whose required gates all pass, evaluated cumulatively (level N requires all levels 1..N-1 to also pass).

Maturity is evaluated automatically on entity changes, periodically via a Databricks background job, and manually on demand. Every evaluation persists a timestamped snapshot, enabling maturity progression tracking over time. Level changes fire a process workflow trigger (`ON_MATURITY_CHANGE`), allowing admins to wire up notifications, approvals, or any other workflow steps.

The existing Production Readiness panel is replaced by a richer Maturity Panel that shows per-level gate results, the current maturity badge, and a historical progression indicator.

## User Stories

1. As a **Data Governance lead**, I want to define a multi-level maturity model for Data Products (e.g., Accessible, Described, Defined, Monitored, Trusted), so that product owners have a clear ladder of governance completeness to climb.
2. As a **Data Governance lead**, I want to define a separate maturity model for Data Contracts, so that contract-specific criteria (schema completeness, SLA definitions, quality rules) are evaluated independently from product criteria.
3. As an **Admin**, I want to create, edit, reorder, and delete maturity levels in the Settings UI, so that our maturity model can evolve as our governance practices mature.
4. As an **Admin**, I want to assign one or more compliance policies as gates for each maturity level, so that level promotion is based on objective, auditable criteria.
5. As an **Admin**, I want to mark individual gates as "required" or "advisory", so that advisory gates produce warnings but do not block level achievement.
6. As an **Admin**, I want to reuse existing compliance policies as maturity gates, so that I do not have to duplicate rule definitions.
7. As a **Data Product owner**, I want to see my product's current maturity level on the detail page, so that I know where it stands in the governance ladder.
8. As a **Data Product owner**, I want to see which gates passed and which failed at each maturity level, so that I know exactly what to fix to reach the next level.
9. As a **Data Product owner**, I want to click "Re-evaluate" to get a fresh maturity assessment, so that I can check progress after making changes.
10. As a **Data Contract owner**, I want to see my contract's maturity level and gate results on the contract detail page, so that I have the same visibility as product owners.
11. As a **Data Consumer**, I want to see a maturity badge on Data Products in the marketplace, so that I can gauge governance quality before subscribing.
12. As a **Data Consumer**, I want to filter marketplace products by minimum maturity level, so that I can find only well-governed data products.
13. As a **Data Governance lead**, I want maturity to be re-evaluated automatically when an entity is saved or its status changes, so that the maturity level stays current without manual intervention.
14. As a **Data Governance lead**, I want a periodic background job to re-evaluate maturity for all products and contracts, so that maturity stays accurate even when upstream conditions change (e.g., a quality monitor is disabled).
15. As a **Data Governance lead**, I want maturity level changes to fire a process workflow trigger, so that I can configure notifications, Slack messages, or approval workflows when maturity regresses or advances.
16. As a **Data Governance lead**, I want to see maturity progression over time (historical snapshots), so that I can report on governance improvements across the organization.
17. As an **Admin**, I want deletion of a maturity level to be blocked when entities have snapshots referencing it, so that historical data is not orphaned.
18. As a **Data Product owner**, I want the maturity evaluation to consider my certification level (e.g., "certified at Silver or above"), so that certification is a signal the maturity model can build on.
19. As a **Data Product owner**, I want the maturity evaluation to consider relationship counts (business terms linked, upstream systems defined, delivery channels), so that the model can check governance completeness beyond just column-level metadata.
20. As a **Data Governance lead**, I want the system to ship with a default 5-level maturity model and pre-built compliance policies for each gate, so that teams have a working starting point out of the box.
21. As a **Data Governance lead**, I want maturity level changes to be recorded in the entity change log, so that there is an audit trail.
22. As an **Admin**, I want to sort the marketplace by maturity level, so that the most trusted products appear first.

## Implementation Decisions

### Data model

- **Three new tables**: `maturity_levels` (admin-configurable ordered levels with `entity_type` scope), `maturity_gates` (join table linking levels to compliance policies with `required` flag and display order), `maturity_snapshots` (timestamped evaluation results with full gate-result JSON).
- **Entity table additions**: `maturity_level_order` (Integer, nullable, cached) and `maturity_evaluated_at` (DateTime, nullable) columns on `data_products` and `data_contracts`.
- Maturity levels are scoped per entity type. Admins configure separate level sets for Data Products vs. Data Contracts (or shared, if they create identical levels for both).
- Maturity levels follow the same admin CRUD pattern as `certification_levels` (ordered list, reorder endpoint, delete-guard when in use).

### Evaluation engine

- Maturity evaluation is **cumulative**: levels are processed in `level_order` sequence; evaluation stops at the first level where any required gate fails. The achieved level is the highest level where all required gates passed.
- Gates reference existing `compliance_policies` rows. The compliance DSL rule on each policy is evaluated via `evaluate_rule_on_object()` against an **enriched entity dictionary**.
- The enriched entity dict includes computed fields beyond the raw entity columns: `contract_count`, `output_port_count`, `business_term_count`, `dataset_count`, `upstream_system_count`, `delivery_channel_count`, `logical_attribute_mapping_count`, `certification_level`, `certification_level_name`, `has_quality_checks`, `tag_count`, etc. This keeps the DSL simple -- rules just check `obj.certification_level >= 2` or `obj.business_term_count > 0`.
- An entity dict builder module constructs this enriched dict by querying entity relationships, tags, quality items, and certification data. This module is the main new abstraction and should be tested in isolation.

### Evaluation triggers

- **On entity change**: after a Data Product or Data Contract is saved or its status changes, the maturity evaluator runs automatically. This piggybacks on the existing save/status-change code paths in `DataProductsManager` and `DataContractsManager`.
- **Scheduled**: a new Databricks Workflow job (`maturity_evaluation`) re-evaluates all products and contracts periodically. Follows the same pattern as `compliance_checks.yaml`.
- **Manual**: a "Re-evaluate" button on the detail page calls `POST /api/data-products/{id}/maturity/evaluate`.

### Process workflow integration

- A new `TriggerType.ON_MATURITY_CHANGE` is added to the trigger registry. It fires after evaluation when the achieved maturity level differs from the previously cached level. The trigger event includes `from_level` and `to_level` metadata.
- Admins can wire this trigger to notification, webhook, or approval workflow steps just like any other trigger.

### Change log integration

- Maturity level changes are logged to `entity_change_log` with action type `MATURITY_CHANGED`, recording old and new level.

### Seed data

- The system ships with a default 5-level maturity model: Accessible (1), Described (2), Defined (3), Monitored (4), Trusted (5).
- Pre-built compliance policies are created for each gate, with DSL rules covering the criteria from the reference model (owner known, description present, business terms linked, quality monitoring active, lineage documented, certification level, data contract complete, etc.).
- The six existing hardcoded readiness checks are migrated to compliance policies and wired as gates on the appropriate levels.

### API routes

- Admin CRUD: `GET/POST /api/maturity-levels`, `PUT/DELETE /api/maturity-levels/{id}`, `PUT /api/maturity-levels/reorder`, `POST /api/maturity-levels/{id}/gates`, `DELETE /api/maturity-levels/{id}/gates/{gate_id}`
- Evaluation: `GET /api/data-products/{id}/maturity` (returns current assessment), `POST /api/data-products/{id}/maturity/evaluate` (force re-evaluate), `GET /api/data-products/{id}/maturity/history` (snapshots list). Same pattern for `/api/data-contracts/`.
- Marketplace: existing published endpoint gains `?min_maturity=` query param.

### Frontend components

- `MaturityPanel` -- replaces `ReadinessChecklist` on product and contract detail pages. Shows current level badge, per-level expandable sections with gate results (pass/warn/fail rows), re-evaluate button, and a sparkline/mini-chart of maturity over time from snapshots.
- `MaturityBadge` -- compact inline badge for list tables and marketplace cards (level name + color dot).
- `MaturityLevelsSettings` -- Settings page section for admins to manage levels and assign gate policies. Follows the `CertificationLevelsSettings` pattern with drag-to-reorder and a compliance policy picker for gates.

### Relationship to existing Production Readiness

- The `/api/data-products/{id}/readiness` endpoint and `ReadinessChecklist` component are deprecated and eventually removed once the maturity system is live.
- The six readiness checks become compliance policies, and their results are subsumed by the maturity gate evaluation.

## Testing Decisions

Good tests for this feature exercise external behavior through the public API or component interface, not internal implementation details. Tests should verify that given a specific entity state and maturity configuration, the correct maturity level is computed and persisted.

### Modules to test

1. **Maturity evaluation engine** (`maturity_evaluator.py`): Unit tests covering cumulative level logic, required vs. advisory gates, empty configurations, edge cases (no levels defined, no gates on a level, all gates fail, all gates pass). Test via a function that accepts a level config and entity dict, returns the achieved level and gate results.

2. **Entity dict enrichment** (`entity_dict_builder.py`): Unit tests verifying that given a product/contract with specific relationships, tags, certification, etc., the enriched dict contains the expected computed fields. Mock the database layer.

3. **API routes** (`maturity_routes.py`): Integration tests for CRUD operations (create/update/delete levels and gates, reorder, delete guards), evaluation endpoint (returns correct level), and history endpoint (returns snapshots). Follow the existing pattern in `test_compliance_routes.py`.

### Prior art

- `src/backend/src/tests/integration/test_compliance_routes.py` -- route-level integration tests
- `src/backend/src/tests/unit/test_compliance_manager.py` -- manager-level unit tests
- `src/backend/tests/test_compliance_dsl.py` -- DSL evaluation tests

## Out of Scope

- Maturity for Datasets and Assets (can be added later by extending `entity_type` scope).
- Custom DSL extensions for relationship-aware operators (the enriched entity dict approach avoids this).
- Maturity-based access control (e.g., "only level 4+ products can be published"). This could be a future workflow gate.
- Aggregated domain-level maturity scores (e.g., "Domain X has average maturity 3.2"). Useful but deferred.
- UI for creating compliance policies inline from the maturity settings page (admins must create policies separately in the Compliance section first, then link them as gates).

## Further Notes

- The 5-level model in the seed data is inspired by common data governance maturity frameworks (DCAM, EDM Council) and the specific reference model provided (Accessible -> Described -> Defined -> Monitored -> Trusted).
- The enriched entity dict approach was chosen over DSL extensions because it keeps the compliance DSL stable and simple, while the builder module can be extended with new computed fields as needed.
- Maturity snapshots enable future analytics: maturity distribution dashboards, progression rates, regression alerts. These are deferred but the data model supports them.
- The `entity_type` scoping on `maturity_levels` means admins could later extend this to Datasets or Assets without schema changes.
