# Ontos

Ontos is a data governance and catalog application for managing data products, data contracts, assets, and their business semantics on top of Unity Catalog and other data platforms.

## Language

### Estates

**Estate**:
A single Ontos setup together with all the data workloads it governs. Several Estates, separated by cloud, region, or account boundaries, are connected through the Estate Manager to share Data Products, glossaries, and other entities.
_Avoid_: Instance, landscape, tenant

### Estate Import

**Estate Import**:
Bulk adoption of every workload accessible to an Estate (catalogs, schemas, tables, and their business metadata across one or more platforms) into Ontos-managed entities, gated by human review; the usual way to set up an Estate.
_Avoid_: Bulk import, mass import, onboarding

**Import Run**:
One persistent, resumable instance of an Estate Import, spanning one or more Sources and progressing through Phases over any number of sessions.
_Avoid_: Job, import job, session

**Source**:
One origin of metadata that an Import Run reads from, either a Connector Source or an Exchange Source.
_Avoid_: Connection, origin

**Connector Source**:
A Source that Ontos pulls from through a system connector with a root selection (e.g. a Unity Catalog metastore with selected catalogs, or a BigQuery project).
_Avoid_: Live source, direct source

**Exchange Source**:
A Source where an external script, job, or tool pushes metadata into known, versioned exchange objects (Delta tables or Lakebase tables) that Ontos reads, used when Ontos has no connector or no network path to the system.
_Avoid_: Push source, indirect source, drop zone

**Ontos Exchange**:
The versioned specification of exchange objects through which external systems push metadata to Ontos, made of independently versioned Exchange Modules.
_Avoid_: Exchange schema, interchange format

**Exchange Module**:
One independently versioned part of the Ontos Exchange covering one kind of metadata (core, catalog, lineage, workloads, usage, validation, migration); a provider implements only the modules it has.
_Avoid_: Exchange table set, extension

**Exchange Location**:
The registered place (a UC schema of Delta tables, or a Lakebase schema) where a provider's exchange objects live.
_Avoid_: Exchange schema, drop zone

**Phase**:
One unit of work within an Import Run that produces one kind of Ontos entity (Reference Data, Assets, Ontology, Contracts, Products, Semantic Links), each moving through Suggest, Review, and Apply.
_Avoid_: Stage, step, round

**Suggestion**:
A proposed Ontos entity (or change to one) held in staging until a reviewer accepts, edits, or rejects it, and only then applied.
_Avoid_: Candidate, proposal, draft

**Scope Rule**:
A declarative include/exclude criterion (name pattern, tag or property predicate, object type, staleness) that decides whether a source object becomes a Suggestion or is staged as excluded.
_Avoid_: Filter, knob

**Scope Profile**:
A named, reusable set of Scope Rules.
_Avoid_: Filter preset, template

**Mapping Rule**:
A rule that derives an entity attribute (typically its Domain, Team, or owning Product) from a metadata key on the source object or from a Descriptor Source.
_Avoid_: Tag mapping, resolver

**Product Grouping**:
The decision of which source objects form one Data Product (and its output-port Contract) within an Import Run, made once and shared by the Contracts and Products Phases.
_Avoid_: Bundling, clustering

**Provenance Record**:
The link from an Ontos entity to the Import Run and source object key that created or last updated it.
_Avoid_: Lineage, origin tag

**Run Summary**:
The small, permanently retained record of an Import Run (who, when, Sources, counts per Phase and status) that survives after its staged Suggestions are pruned.
_Avoid_: Run log, history entry

**Descriptor Source**:
Customer-supplied business metadata that augments Suggestions, either a per-schema descriptor file or a central mapping table keyed by object name.
_Avoid_: Manifest, sidecar file

### Data Product Migration

**Migration Program**:
A long-running, planned effort to move a set of Data Products from legacy platforms onto Databricks, organized into Waves and tracked through Assessment, Planning, Tracking, and Cutover.
_Avoid_: Migration project, migration run

**Migration Candidate**:
A Data Product considered for migration within a Migration Program, together with the Workloads and Assets it depends on.
_Avoid_: Migration item, migration unit

**Workload**:
A piece of processing logic (ETL mapping, stored procedure, scheduled script, pipeline, report query) that reads and writes datasets and must be converted or replaced when its Data Product migrates.
_Avoid_: Job, code, artifact

**Assessment**:
The evaluation of a Migration Candidate's suitability and effort for Databricks, combining external analysis results with what Ontos knows about lineage, usage, consumers, contracts, and cost.
_Avoid_: Analysis, profiling, scoring

**Disposition**:
The decided treatment of a Migration Candidate: Rehost, Refactor, Re-architect, Retire, or Retain.
_Avoid_: Strategy, recommendation, treatment

**Wave**:
An ordered group of Migration Candidates that are migrated and cut over together, typically because they share Workloads or depend on each other.
_Avoid_: Batch, sprint, phase

**Cutover**:
The switch of a migrated Data Product from its legacy Assets to their Databricks counterparts, after which the legacy Assets are deprecated and the old-to-new link is kept.
_Avoid_: Go-live, switchover
