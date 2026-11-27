# PRD: erwin Data Model Import

> Import **erwin Data Modeler** models (logical and physical) into Ontos. The logical layer becomes **ontology concepts**. The physical layer becomes **draft ODCS contracts** that are bound to existing Unity Catalog assets. Sources: XML file upload (v1), JSON file upload, and a live **erwin Mart** connection. Branch: `erwin-import`. Issue: #1718.

## Problem Statement

Many enterprises keep their system of record for data structure in erwin: subject areas, entities, attributes, keys, relationships, definitions, domains and user-defined properties (UDPs). They have maintained it for years, often for warehouses that are now moving to Databricks. Ontos can't read any of it. Today:

- Stewards retype entity and attribute definitions into Ontos concepts and contract properties by hand, or don't bother. The business meaning that lives in the erwin model never reaches the catalog.
- Primary keys, alternate keys, foreign keys, nullability and data types are already modeled in erwin. Contract authors re-derive them from UC (which has no reliable FK metadata) or leave them out.
- There's no way to compare what was modeled with what was deployed in UC. Drift between the erwin physical model and the real tables goes unnoticed.
- Migration programs (Oracle/Teradata/SQL Server → Databricks) carry an erwin model of the legacy estate. That model would be the best seed for the target-state contracts, but there is no path for it into Ontos.
- erwin Mart holds the governed, versioned copy of each model. Ontos has no connector for it, so any import is a one-off snapshot that goes stale.

## Solution

An **erwin model import** that parses the model into a format-neutral intermediate representation (IR) and maps it onto existing Ontos primitives through one **staged, reviewable import run**:

1. A steward uploads an erwin model file (XML Standard export; JSON in a later slice) or picks a model and version from a registered **erwin Mart** connection.
2. Ontos parses the file into the IR and shows a **preview**: subject areas, entities and tables, how many concepts and contracts would be created or updated, physical tables matched to UC assets (and those that aren't), and warnings.
3. The steward chooses the scope (subject areas), the target **semantic model** for the logical layer, how contracts are grouped (default one per subject area), and the **catalog/schema mapping** used to resolve physical names to UC.
4. On confirm, Ontos creates or updates:
   - **Concepts** (logical layer): entities become classes, attributes become datatype properties, relationships become object properties, and subtype relationships become `rdfs:subClassOf`, all in Draft.
   - **ODCS contracts** (physical layer), all in Draft:
     - tables become schema objects and columns become properties;
     - PK, AK, FK and nullability map to ODCS `primaryKey`, `unique`, `relationships` and `required`;
     - definitions become descriptions.
   - **Semantic links** from every schema object and property to its logical concept, so model lineage shows Concept → Contract → UC asset without any extra work.
   - A **drift report** comparing each contract to the UC table it resolves to.
5. **Re-import** of a newer model version is idempotent. It matches on erwin object IDs, shows a diff, mints new versions of contracts and concepts that are beyond Draft, and flags removed objects instead of deleting them.

## Ontos Primitives & End-to-End Flow

No parallel model store. erwin content lands on what already exists.

| Step | Ontos primitive | Change needed |
|---|---|---|
| Upload / pick model | New **Model Import** dialog (Contracts → Import → *From erwin model*; also from Semantic Models) | New route + dialog; upload size cap above the default 5 MiB |
| Register Mart | **Settings → Connections** (`ConnectorRegistry`, `connections_manager`) | New `erwin_mart` connector + form section (slice 6) |
| Parse | New `erwin/` package: format parsers → IR | New |
| Stage + preview + confirm | Token-bound review, modeled on `semantic_models_manager.preview_upload` / `confirm_upload` / `gate_or_apply_upload` | New `model_import_runs` table (reuse `schema_import_runs` shape and async thread pattern) |
| Logical → concepts | Knowledge collections / semantic models (`/knowledge/collections/{iri}/import`, `conflict_mode`, `_mint_new_concept_version`) | Generate Turtle from IR, feed the existing import path |
| Physical → contracts | `data_contracts_manager` create path, `SchemaObjectDb`, `SchemaPropertyDb`, `SchemaObjectRelationshipDb`, `SchemaPropertyRelationshipDb` (ODCS v3.1 FKs incl. composite) | IR → ODCS dict; reuse the create/version path, not raw inserts |
| Link layers | `SemanticLinksManager` (`data_contract_schema`, `data_contract_property` → concept IRI) | None |
| Contract ↔ UC | `SchemaObjectDb.physical_name` = UC FQN → `model_lineage` derives `implementedBy` | Catalog/schema mapping in the run; drift check |
| UDPs → governance | Tags (`TagsManager.set_tags_for_entity`), `classification`, `critical_data_element` | Configurable UDP mapping per run (saved as a profile) |
| Audit | Run record + entity change log | None structurally |

**Flow**

1. *Contracts → Import → From erwin model:* upload `customer_dw.xml`, or choose Mart → catalog → model → version.
2. *Preview:* "Logical: 142 entities, 1,380 attributes, 96 relationships → 142 classes, 1,380 properties (create). Physical: 138 tables in 7 subject areas → 7 contracts (create). UC match: 121/138 tables resolved; 17 unresolved (listed). 4 warnings."
3. *Options:* target semantic model, subject areas, contract grouping, catalog mapping (`DW` owner → `prod_catalog.dw`), UDP mapping profile.
4. *Confirm:* the run executes async with progress notifications. The result page lists the created and updated entities, with deep links and the drift report.
5. *Later:* re-import of v43 of the same model shows a diff against the previous run ("3 tables added, 11 columns changed, 1 entity removed → flagged"). On confirm, new Draft versions are minted for anything already Approved or Certified.

## User Stories

### Import
1. As a data modeler, I want to upload an erwin XML export, so that my model reaches Ontos without retyping.
2. As a steward, I want a preview that counts what will be created or updated and lists unresolved tables and warnings before anything is written, so that a bad file never pollutes the catalog.
3. As a steward, I want to import only selected subject areas, so that a 2,000-entity enterprise model can be adopted one domain at a time.
4. As a steward, I want to choose how physical tables are grouped into contracts (per subject area, per schema/owner, per table, or per model), so that contract granularity matches how the domain team owns its data.
5. As a steward, I want a catalog/schema mapping (erwin owner or schema → UC `catalog.schema`), so that physical names resolve to the real UC tables.
6. As a steward, I want to map UDPs to Ontos tags, classification or the critical-data-element flag, and save that mapping as a reusable profile, so that governance attributes kept in erwin carry over consistently.

### Logical layer
7. As a business steward, I want entities, attributes and their definitions imported as Draft concepts in a semantic model I choose, so that I can review, approve and publish them through the normal concept lifecycle.
8. As a business steward, I want relationships imported as object properties with their verb phrases and cardinality, and subtype hierarchies imported as subclasses, so that the conceptual structure is preserved and not just a flat word list.
9. As a steward, I want erwin domains imported as reusable datatype definitions (with their base type and valid values), so that "Currency Amount" means the same thing everywhere.

### Physical layer
10. As a contract author, I want tables and columns imported as Draft ODCS contracts with physical types, nullability, primary keys (with position), alternate keys and foreign keys (composite too), so that I start from the modeled truth.
11. As a contract author, I want each contract property linked to the logical attribute it implements, so that the business meaning shows up in the contract and model lineage reads Concept → Contract → UC column.
12. As a data owner, I want a drift report for each contract that lists columns missing in UC, columns in UC but not in the model, type mismatches and nullability mismatches, so that I can see where deployment diverged from design.
13. As a migration lead, I want to import a legacy-platform physical model (Oracle, Teradata, SQL Server, Db2) and have types translated to Databricks types through their logical types, so that the model seeds target-state contracts for the Databricks build.

### Lifecycle and sync
14. As a steward, I want re-imports matched on erwin object IDs, so that renames update the existing concept or contract rather than creating duplicates.
15. As a steward, I want a re-import diff, and I want Approved or Certified contracts and concepts to get a new Draft version instead of being edited in place, so that governance state is never bypassed.
16. As a steward, I want objects that disappeared from the model flagged as "removed in source" rather than deleted, so that I decide whether to deprecate.
17. As an admin, I want to register an erwin Mart connection with credentials held in a Databricks secret scope, so that stewards can import governed model versions without handling files.
18. As an admin, I want a scheduled check for new Mart model versions that opens a pending import run for review, so that Ontos follows the model without applying changes silently.
19. As an auditor, I want every import run recorded with its source (file hash or Mart model and version), its options, counts, warnings and created entities, so that I can trace any concept or contract back to the model version it came from.

## Implementation Decisions

### Scope (v1)
- **erwin Data Modeler r9.x – 15.x**, model types **Logical**, **Physical** and **Logical/Physical**.
  - A Logical-only model produces concepts only.
  - A Physical-only model produces contracts only, with no semantic links (unless the steward links the contracts to an existing semantic model by name match. That's an option, off by default).
- **Input formats:**
  - **XML Standard** (*File → Save As → XML*): the primary format. Its schema is documented (`EMX.xsd`, `EMXProps.xsd`, `UDP.xsd` ship in the erwin `Doc` folder), and it covers every object type.
  - **XML Repository Format:** also accepted. It carries extra derived properties, which are ignored.
  - **XML Standard with Min Info:** accepted, with a warning that defaulted properties (e.g. `Null_Option`) are absent and get erwin defaults applied.
  - **JSON** (DM 14+ *Save As JSON*): **slice 5**, gated on real sample files. The format is not publicly documented.
  - **Native `.erwin`:** rejected with guidance to export as XML. It's a proprietary binary, and the only reader is the Windows COM API (SCAPI).
- **Row data and live DB connections:** never read. erwin's own reverse-engineering is not replicated; UC is the physical truth on the Ontos side.
- **Target ODCS version:** **v3.1.0**, the highest bundled schema. Under ODCS 3.2 (branch `odcs-3_2_0-support`) the same mapping holds; nothing here depends on 3.2.

### Architecture: parsers → IR → mappers
A deep module with a narrow interface: `erwin.parse(source) -> ErwinModel`, then independent mappers.

- **`erwin/ir.py`** holds Pydantic models with no dependency on Ontos or the input format. They capture the elements needed for mapping:
  - `ErwinModel`: id, name, type, target DBMS and version, model version (Mart), plus collections of the objects below.
  - `SubjectArea`, `Entity` (logical name, physical name, owner/schema, definition, note, `is_view`, view SQL), `Attribute` (logical and physical names, logical data type, physical data type, null option, default, domain ref, definition, `parent_attribute_id` for FK migration).
  - `KeyGroup` (PK / AK / IE, members with order) and `Relationship` (parent, child, type: identifying / non-identifying / subtype, verb phrases, cardinality, FK column pairs).
  - `Domain`, `SubtypeGroup` (complete/exclusive), and `UdpDefinition` + `UdpValue`.
  - Every object keeps its erwin **object ID** (`{GUID}+…`), used as the stable key.
- **`erwin/parsers/xml.py`:**
  - Uses `lxml` `iterparse` with a hardened parser: `resolve_entities=False`, `no_network=True`, `huge_tree=False`, and DTDs forbidden (defusedxml semantics).
  - Matches on element **local names**, so the `EMX:` prefix and default namespaces both work.
  - Builds an `id → object` index first, then resolves `*_Ref` references (relationship parent/child, subject-area `Referenced_Entities`, key-group members, domain refs, FK parent attributes).
  - Unknown elements are ignored, with a count reported in the warnings. Dangling refs are warnings, not failures.
- **`erwin/parsers/json.py`** (slice 5) and **`erwin/parsers/mart.py`** (slice 6) produce the same IR.
- **Mappers:**
  - `erwin/map_concepts.py`: IR → Turtle in the target semantic model namespace.
  - `erwin/map_contracts.py`: IR → list of ODCS dicts.
  - `erwin/map_links.py`: IR → semantic-link specs.
  - `erwin/match_uc.py`: IR + catalog mapping → resolved UC asset IDs + drift.
  - All are pure functions over IR plus a read-only Ontos lookup, which makes them unit-testable without a DB.
- **The `erwin/` IR is not persisted as its own model store.** A run stores the uploaded source in the UC upload volume (`uploads/model-import/{run_id}/`) plus its SHA-256, so it can be re-run and audited.

### Logical → ontology mapping
| erwin | Ontos (RDF in the target semantic model) |
|---|---|
| Model | `owl:Ontology` header (or an existing semantic model chosen by the steward); `ontos:sourceSystem "erwin"`, model name and version |
| Subject area | `skos:Collection` with `skos:member` the entity classes; also offered as an Ontos **domain** hint in the preview (not auto-created) |
| Entity | `owl:Class` (concept type `class`), `rdfs:label` = logical name, `skos:definition` = definition, `skos:note` = note, `skos:altLabel` = physical name |
| Attribute | `owl:DatatypeProperty`, `rdfs:domain` = entity class, `rdfs:range` = XSD type from the logical type (or the domain), `skos:definition` |
| Relationship (identifying / non-identifying) | `owl:ObjectProperty` named from the parent-to-child verb phrase (fallback `<parent>_has_<child>`), domain/range = the classes, `owl:inverseOf` from the child-to-parent phrase; cardinality as `ontos:cardinality` annotations (OWL restrictions deferred) |
| Subtype relationship | `rdfs:subClassOf`; complete/exclusive recorded as annotations |
| Domain | `rdfs:Datatype` with `owl:onDatatype` + `owl:withRestrictions` (length, valid values → `owl:oneOf` when listed) |
| UDP | Per mapping profile: an annotation property (`erwin:udp/<name>`) or an Ontos tag on the linked contract objects |
| Object ID | `ontos:sourceId "erwin:<model-id>/<object-id>"` on every resource; this is the re-import match key |

- IRIs are minted as `<semantic-model-base>/<slug(logical name)>`, with collisions suffixed. They're **stable across re-imports** because the match goes through `ontos:sourceId` and never the IRI, so renames keep the IRI.
- Applied through the existing knowledge import path:
  - first import: plain add with Draft status;
  - re-import: diff preview + `conflict_mode=update`, versioning via `_mint_new_concept_version` for concepts beyond Draft.
- Don't use the legacy asset types `ontos:LogicalEntity` / `ontos:LogicalAttribute`. Lineage hides them as superseded, and concepts + ODCS schema are the live logical layer.

### Physical → ODCS mapping
| erwin | ODCS v3.1 |
|---|---|
| Table / view | `schema[]` object. Fields: `name` = physical name, `physicalName` = resolved UC FQN, `businessName` = entity logical name, `description` = definition, `physicalType` = `table` / `view` |
| View SQL | `customProperties.erwin.viewSql` (not parsed) |
| Column | `properties[]`: `name`, `physicalType` (as modeled), `logicalType` (mapped), `businessName` = attribute logical name, `description`, `required` = `Null_Option == NOT NULL` |
| PK key group | `primaryKey: true` + `primaryKeyPosition` from member order |
| AK key group | Single column: `unique: true`. Multi-column: `quality[]` rule `type: custom`, `unique` over the column set (recorded, not executed) |
| Inversion entry (IE) | Ignored (index); counted in the preview |
| FK (from relationship) | `schema[].relationships[]` `type: foreignKey`, `from`/`to` as arrays for composite keys → `SchemaObjectRelationshipDb` |
| Default value / check constraint | `customProperties.erwin.default` / `.check` (not executed) |
| Domain valid values | `logicalTypeOptions.enum` when ≤ 200 values |
| UDPs | Per profile: tags, `classification`, `criticalDataElement`, or `customProperties.erwin.udp.<name>` (default) |
| Object IDs | `customProperties.erwin.id` on schema objects and properties; contract-level `erwin.modelId`, `erwin.modelVersion`, `erwin.runId` |

- **Type mapping:**
  - The **target DBMS** decides how `physicalType` is read. Databricks / Spark SQL targets (erwin 15 supports Databricks and Unity Catalog) pass through. Other targets keep the modeled physical type in `physicalType` and add `customProperties.erwin.sourcePhysicalType`.
  - `logicalType` is derived through a per-DBMS table: Oracle, SQL Server, Teradata, Db2, PostgreSQL, MySQL, Snowflake, Databricks.
  - **Migration mode** (option): replace `physicalType` with the mapped Databricks type. Examples: `NUMBER(p,s)` → `DECIMAL(p,s)`, `VARCHAR2(n)` → `STRING`, `DATE` (Oracle) → `TIMESTAMP` with a warning.
- **Contract grouping:**
  - Default: **one contract per subject area**. Tables outside any subject area go into `<model> – Unassigned`.
  - Alternatives: per owner/schema, per table, single contract.
  - A table that appears in several subject areas goes to the first one, ordered by the steward in the preview, and the preview shows a warning.
- **Ownership:** contract owner = importing user unless overridden. erwin `Author` / UDP owner fields can map to owners via the profile.
- **Domain:** optional target data domain per subject area, chosen in the preview. Not auto-created.

### Layer linking
- Every schema object gets a semantic link to its entity class, and every property to its attribute property (`SemanticLinksManager`, entity types `data_contract_schema` / `data_contract_property`).
- `model_lineage` then derives the business → logical → physical lanes with no change. `implementedBy` comes from `physical_name` matching an asset `location`.

### UC resolution & drift
- The catalog mapping table maps erwin `owner` or `schema` (or the model's default) to UC `catalog.schema`. Names are compared case-insensitively. Overrides can be entered per table.
- Resolution goes against the **existing Ontos UC assets** only. Missing tables are listed as *unresolved*, and the steward can (a) fix the mapping, (b) leave `physicalName` unset, or (c) run a UC schema import first through the Schema Importer (link provided). The erwin import **never creates UC assets**.
- **Drift report:**
  - Computed per resolved table: missing columns, extra columns, type mismatch (normalized through the logical type), nullability mismatch, PK mismatch (only if UC declares constraints).
  - Stored on the run and shown on the result page. A drift summary note is added to the contract's metadata panel, refreshed on re-import.
  - Re-computing drift without a re-import is a later enhancement.

### Staging, review and re-import
- New `model_import_runs` table. Fields: `id`, `source_kind` (`file_xml` | `file_json` | `mart`), `source_ref` (file hash + volume path, or Mart catalog/model/version), `options_json`, `preview_json`, `result_json`, `status` (`parsed` → `previewed` → `confirmed` → `running` → `completed` | `failed` | `cancelled` | `expired`), `created_by`, and timestamps.
- **Flow:**
  - `POST /api/model-import/runs` (upload or Mart ref) parses and returns a preview + `confirm_token`.
  - `PATCH …/runs/{id}` changes the options and re-previews.
  - `POST …/runs/{id}/confirm` with the token executes async, reusing the `schema_import_runs_manager` thread/cancel/progress pattern.
  - The token is bound to `(run_id, preview hash)`, so a changed option invalidates it. Unconfirmed runs expire after 7 days.
- **Re-import:**
  - Previous imports from the same erwin model (`erwin.modelId`) are found automatically.
  - The diff is computed per object ID: added / changed (with a field list) / removed / unchanged.
  - Draft entities are updated in place. Proposed, Approved or Certified contracts and concepts get a **new Draft version** through the existing versioning paths.
  - Removed objects get a `removed_in_source` flag + notification to the owner. They're never deleted.
- **Atomicity:** the contracts and concepts of one run are committed per contract. The run result lists partial failures, the same way `BatchImportResult` reports per-entity outcomes. The concept import is one transaction per semantic model.

### Security & limits
- Upload cap: dedicated `MODEL_IMPORT_MAX_BYTES` (default **100 MiB**, configurable). Large enterprise models exceed the 5 MiB `read_uploads_capped` default. The upload is streamed to the volume, never read fully into memory, and parsed with `iterparse`.
- Hardened XML parsing (see above). Entity expansion, external DTDs and network fetches are disabled, and a test proves a billion-laughs and an XXE payload are rejected.
- Model text such as definitions and notes is treated as untrusted. It's escaped on render, and markdown is sanitized the same way as rich texts.
- Mart credentials live in a Databricks secret scope (BigQuery/Tableau pattern) and are never stored in `connections.config` or returned by the API.

### erwin Mart (slice 6)
- **Connector:** new `connectors/erwin_mart.py` (`AssetConnector`, read-only capabilities). Config: `server_url`, `auth_mode` (`basic` | `bearer`), `username`, `secret_scope` / `secret_key`, and an optional CA bundle.
- **Browse:** catalogs → libraries → models → versions, through the Mart Reporting REST API (`/MartServer/api/report/generateReport/{reportName}`, XML).
- **Content (speculative, spike first):**
  - Mart's documented REST surface is report-oriented. There's **no documented endpoint that exports a model version as erwin XML**. The spike evaluates, in order:
    - (a) custom Mart reports that return entity, attribute, key, relationship, domain and UDP rows for a model version, fed to `parsers/mart.py`;
    - (b) the installation's Swagger for undocumented model-export routes;
    - (c) a read-only DB connection to the Mart repository database. Vendor-unsupported schema, so last resort.
  - If (a) proves lossy (e.g. no FK column pairs), Mart ships for **browse + version tracking only**, and content comes from the drop zone below.
- **Drop zone** (works with or without Mart): an admin configures a UC Volume path. The customer's erwin automation (erwin DM API/scheduler, or a modeler's manual export) writes `*.xml` there. A scheduled Ontos job (`uc_bulk_import` job pattern) picks up new files by hash and opens a `previewed` run assigned to the model's previous importer for review. **Nothing is applied without confirm.**

### UI
- **Model Import dialog** (`src/frontend/src/components/model-import/`):
  - Step 1 source (upload / Mart / drop-zone run).
  - Step 2 preview with tabs: Summary, Logical, Physical, UC resolution, Warnings; and Diff on re-import.
  - Step 3 options: semantic model, subject areas, grouping, catalog mapping, UDP profile, migration mode.
  - Step 4 confirm and progress.
- Entry points: Data Contracts list → *Import* menu → *From erwin model*; Semantic Models → *Import* → *From erwin model*; **Settings → Model Imports** for the run history.
- The contract and concept detail views show a small **"Source: erwin · <model> v<version>"** provenance badge, read from `customProperties` / `ontos:sourceId`, that links to the run.
- i18n for every string (use the `__TODO__` marker convention for non-English locales).

### Permissions
- Start, preview and confirm need **Read/Write on `data-contracts`** (when contracts are produced) **and on `semantic-models`** (when concepts are produced). The preview tells the user which permission is missing.
- Mart connections: the existing connections permission.
- Run history: visible to the run creator and admins.

## Testing Decisions
- **Fixtures:**
  - Hand-crafted XML Standard, Repository and Min Info exports covering every mapped element: composite PK/FK, identifying and non-identifying relationships, a subtype group, domains with valid values, UDPs, multi-subject-area tables, views, and an Oracle target.
  - Plus at least one real export per major erwin version (r9.8, 2021 R1, 14, 15). Stored under `src/backend/src/tests/data/erwin/`. Anonymized, no customer names.
- **Parser tests** check IR output exactly, via snapshot tests of the serialized IR. Separate tests cover hostile XML (XXE, billion laughs, oversized input, dangling refs).
- **Mapper tests** are pure: IR → Turtle (parsed back with rdflib and asserted), and IR → ODCS (validated against the bundled ODCS v3.1.0 JSON schema).
- **Manager-level integration tests** use the `db_session` fixture:
  - first import, re-import with renames/adds/removes, and versioning of a Certified contract;
  - drift against seeded UC assets.
  - HTTP route tests are kept thin, because of the local audit-service gap in worktrees.
- **Playwright:** upload → preview → confirm → contract detail shows FKs, the semantic links and the provenance badge; model lineage shows Concept → Contract → Table.

## Out of Scope
- Writing back to erwin, or exporting Ontos contracts and concepts as erwin XML. This is a plausible v2 for round-tripping, and object IDs are preserved to make it possible.
- Pushing modeled descriptions, comments or PK/FK constraints into UC (`COMMENT ON`, `ALTER TABLE … ADD CONSTRAINT`). That would be a separate "apply to UC" action with its own review.
- Executing modeled check constraints or multi-column AK rules as data-quality checks. They're recorded only. Hand-off to the DQX work happens later.
- Native `.erwin` binary, erwin naming-standards files (`.nsm`), and erwin Data Intelligence (DI) Suite glossary/metadata APIs.
- Generic DDL import. A cheaper alternative for non-erwin tools, worth its own PRD.
- Auto-creating Ontos domains, teams or UC assets.

## Open Questions
1. **JSON format:** need 2–3 real DM 14/15 JSON exports to confirm it's lossless compared with XML. If it is, it may be the easier format to parse.
2. **Mart content access:** the spike result decides between full Mart import, browse + version tracking + drop zone, or drop zone only.
3. **Default contract grouping:** per subject area is the default here. Validate with 2–3 modeling teams; some may treat subject areas as diagram views only.
4. **Relationship naming:** erwin verb phrases are often empty or generic ("has"). Should Ontos fall back to `<parent>_<child>` or require the steward to name them in the preview?
5. **Logical-only attributes** (no physical column) and **physical-only columns** (no logical attribute): import both and skip the semantic link, or flag them?
6. Should subject areas map to **Ontos domains** automatically when the names match exactly?

## Slices
1. (#1719) **Parser + IR**: `erwin/` package, hardened XML parser, IR, fixtures, parser tests. No API or UI.
2. (#1720) **Staged run + logical import**: `model_import_runs`, upload route with its own cap, preview/confirm/token, IR → Turtle → knowledge import, Model Import dialog (logical tabs), run history.
3. (#1721) **Physical import**: IR → ODCS (types, keys, FKs, UDP profile, grouping, migration mode), semantic links, UC resolution + drift report, physical/UC tabs, provenance badge.
4. (#1722) **Re-import & lifecycle**: object-ID matching, diff tab, versioning of non-Draft entities, `removed_in_source`, notifications.
5. (#1723) **JSON parser**: gated on sample files; IR parity tests against XML exports of the same model.
6. (#1724) **erwin Mart + drop zone**: spike → connector (browse + version tracking, and content if the spike succeeds), scheduled drop-zone job, pending-review runs.
7. (#1725) **Docs**: user guide (export from erwin, run an import, mapping reference), admin guide (Mart, drop zone, limits), and the `10-entity-panel-matrix.mdc` update for the provenance badge.

## References
- erwin DM 15.0 — Setting up Unity Catalogs in Databricks: https://bookshelf.quest.com/bookshelf/public_html/15.0/Content/User%20Guides/erwin%20Help/Setting%20up%20Unity%20Catalogs%20in%20Databricks.html
- erwin DM — Save a model in XML format (Standard / Min Info / Repository): https://bookshelf.quest.com/bookshelf/9.8.00/Bookshelf_Files/HTML/erwin%20Help/Save_a_Model_in_XML_Format_XML_Export.html
- erwin DM 14.0 — Save a model as JSON: https://bookshelf.quest.com/bookshelf/public_html/14.0/Content/User%20Guides/erwin%20Help/Save%20a%20Model%20as%20JSON.html
- erwin API Reference (EMX.xsd / EMXProps.xsd / UDP.xsd): https://support-public.cfm.quest.com/61771_API_Reference.pdf
- erwin Metamodel Overview: https://bookshelf.erwin.com/bookshelf/9.8.00/Bookshelf_Files/PDF/erwin%20Metamodel%20Overview.pdf
- erwin Mart 15.0 — Generating REST reports: https://bookshelf.quest.com/bookshelf/public_html/15.0/Content/User%20Guides/Creating%20Custom%20Mart%20Reports/Generating_REST_Reports.html
- Quest KB 4369817 — Ways to extract data from erwin Mart: https://support.quest.com/erwin-data-modeler/kb/4369817
- Bundled ODCS schema: `src/backend/src/schemas/odcs-json-schema-v3.1.0.json`
