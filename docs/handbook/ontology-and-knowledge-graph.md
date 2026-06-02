# Ontology and the Knowledge Graph

Most platforms that try to do "business glossary" land on a flat list of terms.
Ontos treats meaning as a graph. The pieces are an **ontology** (the source
artifact your knowledge engineer authors), a **knowledge graph** (the runtime
graph Ontos keeps in memory and in the DB), **semantic links** (the pins from
real Ontos objects to graph nodes), and a **business glossary** (a view onto
published concepts that non-technical users actually browse). They are all the
same plumbing under different labels.

Customers asking these questions tend to be highly skilled — they say "RDF",
"OWL", "SHACL" the way a database engineer says "primary key". This document
is written for that audience first, then translated for everyone else.

## Four words that get confused {#four-words}

- **Ontology** — the source artifact. A `.ttl` / `.owl` / `.rdf` / `.nt` file
  authored externally (Protégé, TopBraid, any text editor). Declares classes,
  data properties, object properties, and constraints (SHACL shapes). It is a
  file you can put in version control.
- **Knowledge graph** — the runtime structure. An rdflib `ConjunctiveGraph`
  rebuilt from the union of enabled ontologies, stored as triples in the
  `rdf_triples` table, in memory at request time. You query it with SPARQL.
- **Semantic link** — a pin. One row in `entity_semantic_links` that says
  "this Ontos object (a data product, contract, schema, column, …) means this
  concept (this IRI)". It is the load-bearing bridge from RDF-land to data
  product-land.
- **Business glossary term** — a published concept presented for browsing.
  There is **no separate glossary terms table**. A "term" is the UX surface
  of a concept that lives in a `urn:glossary:` collection. If you delete the
  glossary collection, the underlying concept survives; if you delete the
  concept, the term is gone.

These four words sit on a "semantic maturity ladder" — Controlled
Vocabulary (a flat business glossary) → Taxonomy (a hierarchy) → Ontology
(taxonomy + typed relationships) → Knowledge Graph (ontology + instances).
Each layer adds expressivity on top of the previous one. Ontos is built
for the full ladder but lets customers enter at whichever level their team
is ready for.

Anti-pattern phrasing: "let me add a term and link it to a column". What you
are actually doing is **adding a concept** to a glossary collection and then
**writing a semantic link** from the column to that concept. The distinction
matters because the same concept can be linked from many places, and a
concept can exist without ever being published as a glossary term.

## The "ontology is prescriptive" principle {#prescriptive-principle}

Before the redesign, the ontology was decorative — Ontos loaded the TTL but
nothing in the application changed when you edited it. That is no longer
true. The current Ontos version makes the ontology **the source of truth for
the asset type system**:

- `ontos-ontology.ttl` is parsed at startup.
- For every class annotated with `ontos:modelTier "asset"`, an `AssetTypeDb`
  row is created or updated. That row carries the UI icon, the category, the
  persona visibility, the required-fields/optional-fields JSON schema, the
  allowed incoming/outgoing relationships.
- The frontend's Asset Explorer reads asset types from the API, not from a
  hardcoded list. Adding a new entity type to your knowledge model is an
  ontology edit, not a code change.
- The ODCS ontology (`odcs-ontology.ttl`) and the Databricks platform
  ontology (`databricks_ontology.ttl`) ship alongside and provide reusable
  vocabulary for contract schemas and physical assets.

If you change the ontology and re-sync, downstream things shift: the form
that renders when you create an asset changes, the relationship types
offered in the relationship panel change, the asset sidebar changes. That
gives the knowledge engineer a real lever over the platform.

## Bundled taxonomies {#bundled-taxonomies}

Three ontologies ship out of the box under
`src/backend/src/data/taxonomies/`:

- **ontos-ontology.ttl** — the application's own vocabulary: `DataDomain`,
  `DataProduct`, `Team`, `Project`, `Asset` subclasses (Dataset,
  PhysicalTable, PhysicalView, PhysicalColumn, Policy, BusinessTerm,
  Dashboard, APIEndpoint, Notebook, MLModel, Stream, System), and the
  relationship properties (`hasDataset`, `governedBy`, `hasTable`,
  `hasColumn`, `attachedPolicy`, etc.). UI annotations
  (`ontos:uiIcon`, `ontos:uiCategory`, `ontos:modelTier`,
  `ontos:uiPersonaVisibility`) live here too.
- **odcs-ontology.ttl** — the Open Data Contract Standard vocabulary
  (`DataContract`, `SchemaObject`, `SchemaProperty`, `Server`,
  `QualityRule`, etc.). Bridges contract semantics with the asset model.
- **databricks_ontology.ttl** — physical-platform vocabulary:
  `Catalog`, `Schema`, `Table`, `View`, `Column`. Useful as anchor concepts
  when you semantic-link Ontos entities to UC objects.

These are synced into the DB at startup via `SemanticModelsManager`. You can
disable any of them from Settings → Semantic Models; they will keep their
DB rows but stop contributing triples to the runtime graph.

## Authoring and uploading an ontology {#authoring}

The recommended path for a serious knowledge engineering effort:

1. Author the ontology externally in OWL / Turtle / RDF/XML / N-Triples.
   Protégé, TopBraid Composer, or just a text editor will do. Include SHACL
   shapes for constraints if you need them.
2. Open Settings → Semantic Models.
3. Upload the file. Ontos accepts `.ttl`, `.owl`, `.rdf`, `.nt`. The format
   is auto-detected by rdflib.
4. Ontos parses, validates the triple count is non-zero, and persists the
   model to `semantic_models`. Triples are stored under a URN context
   (e.g., `urn:semantic-model:my-org-customer-ontology`).
5. Enable the model so its triples join the runtime conjunctive graph.
6. Trigger a graph rebuild (Settings → Semantic Models → Refresh, or
   `POST /api/semantic-models/refresh-graph`).
7. The model is now queryable via SPARQL, visible in the graph view, and
   available to Ask Ontos and MCP agents.

## LLM-assisted inference (a starting point, not an ontology) {#inference}

`OntologyGeneratorManager` is the LLM-assisted alternative for teams that
don't have an ontology yet. It points at UC metadata (table names, column
names, column comments, tags, descriptions) and proposes concepts,
properties, and relationships. Available at `/concepts/generator` and from
inside the contract detail page via the infer-from-catalog dialog.

Generation runs in the background; the UI shows progress, and the
caller can navigate away and return without losing the run. Recent runs
are persisted so they survive a server restart, and admins can see
runs across users. Cancel mid-flight, delete completed runs, save any
completed run into a collection.

Set expectations explicitly with the customer: this is **a starting point
that requires human curation, not a finished ontology**. Quality depends on
the richness of the source metadata. The output is OWL/Turtle the user
reviews, edits, and accepts before it is persisted as a semantic model.

## The runtime knowledge graph {#runtime-graph}

`SemanticModelsManager` owns the runtime graph:

- Conjunctive graph: a union of all enabled models, each loaded under its
  own URN context (one per model). Contexts make it possible to enable /
  disable individual models without rebuilding from scratch.
- Caches concepts, taxonomies, and stats with a five-minute TTL. Refresh
  is explicit: changing a semantic model's enable bit invalidates the cache.
- Handles OWL `equivalentClass` parent/child extraction, blank-node
  skolemization (so you can address blank nodes by stable URNs after
  loading), and RDF list walking.
- Exposes the graph to the rest of the app via `/api/semantic-models/*` —
  including `/query` (SPARQL), `/neighbors` (one-hop traversal),
  `/statistics` (counts), and `/refresh-graph` (force rebuild).

## Semantic links — the three-tier story {#three-tier-linking}

This is what makes Ontos different from a flat glossary tool. A semantic
link is a row in `entity_semantic_links` that pins one Ontos entity to one
concept IRI, with an optional human-readable label and optional context
notes.

`SemanticLinksManager` writes rows. The supported `entity_type` values are:

- `data_domain`
- `data_product`
- `data_contract`
- `data_contract_schema` — a schema object inside a contract
- `dataset`
- `asset`
- `uc_catalog`, `uc_schema`, `uc_table`, `uc_column` — Unity Catalog
  objects identified by their three- or four-part name

The "three tiers" in everyday conversation are:

- **Product / Contract level** — "this data product is about Customer
  Order". Used for marketplace discovery and high-level grounding of
  agents.
- **Schema level** — "this schema object in the contract is the
  Customer entity". Used for cross-contract joins and concept-level
  lineage.
- **Property / Column level** — "this `arr_usd` column is Annual
  Recurring Revenue". Used for column-level definitions in Ask Ontos
  and for data-driven concept exploration.

Same table, same manager, three narratives. Discovery, governance, and
agent grounding all benefit from linking at the lowest tier you can
reasonably justify.

## Business glossary as a published-ontology view {#glossary-as-view}

When a steward "creates a glossary":

1. Ontos creates a knowledge collection with `collection_type=glossary`.
   Under the hood this lives in the `urn:glossary:` context inside the
   conjunctive graph.
2. The steward adds concepts to the collection. These are real RDF
   triples — they get an IRI, a label, optional synonyms, optional
   broader/narrower relations.
3. To bind a glossary term to a real asset, the steward (or an automated
   workflow) writes a semantic link from the asset to the concept IRI.
4. Publication is a lifecycle action on the concept (publish / certify /
   deprecate). It controls UX visibility, not the underlying graph
   storage.

This means the same concept can be (a) part of an enterprise ontology
loaded by upload, (b) presented as a glossary term in a domain-scoped
collection, and (c) linked to dozens of contracts and columns — all
through the same triple plumbing.

## SPARQL and graph navigation {#sparql-and-navigation}

- `POST /api/semantic-models/query` runs SPARQL against the conjunctive
  graph. `SPARQLQueryValidator` does basic input validation. On Unix, a
  SIGALRM-based timeout cap protects against runaway queries.
- `GET /api/semantic-models/neighbors` returns one-hop neighbours of a
  given IRI — used by the Knowledge Graph view to expand a node on click.
- `GET /api/semantic-models/statistics` returns counts (concepts,
  relationships, by-type breakdowns) — used by the graph stats tab.
- `POST /api/semantic-models/refresh-graph` rebuilds the conjunctive
  graph from currently-enabled models. Cheap on small ontologies, can be
  slow on large industry packs.

For non-SPARQL users, the same data is reachable through
`/api/semantic-models/concepts` (paged concept list with filters) and
`/api/semantic-models/hierarchy` (subclass tree).

## Industry packs {#industry-packs}

`IndustryOntologyManager` ships pre-built ontologies that you can load as
starting points: FIBO (financial industry), GS1 (supply chain), schema.org
(generic web concepts), and simple OWL packs for common patterns. These
are not opinionated about your specific data — they give the customer a
populated graph to react to rather than a blank canvas.

## Round-trip asymmetry — be honest about it {#round-trip-asymmetry}

The top-down flow (ontology → physical assets → UC tags) ships in the
forward direction; the reverse direction is still evolving. Here's the
honest current state.

**What ships today.** Ontos can:

- Author and store the ontology.
- Pin concepts to UC objects via semantic links — the read-time
  representation works at product, contract, schema, and column levels.
- Surface those links in marketplace, Ask Ontos, and MCP agents.
- **Propagate concept assignments to UC governance tags via the
  `uc_tag_sync` workflow.** The job reads `entity_semantic_links`
  joined with contract/product/domain/asset metadata and issues UC
  `ALTER TABLE … SET TAGS (...)` statements through Spark SQL. Runs
  on schedule or on demand. Installed from Settings → Background Jobs.
  This is the production path on customer deployments.
- Serialize the same tag changes through the
  [Delivery Service](delivery-and-propagation.md#concept-to-uc-tag) in
  Indirect mode, so a Git manifest captures every concept-driven tag
  assignment for auditable downstream replay.

**What's still evolving.**

- The Delivery Service **Direct** mode for `TAG_ASSIGN` against UC's
  tag API is partial — the change type, notification templates, and
  Indirect path exist; the Direct call to UC's tag API is being filled
  in. Today's production path is the workflow described above.
- **Reading existing UC tags back into Ontos as concept assignments**
  (the reverse direction) is not shipping. The customer voice tracking
  this work captures it as "Tags reading from UC is not there." Plan
  demos around the forward path and flag the reverse pull as evolving.

## Common questions {#common-questions}

**"What's the best practice to start setting up a knowledge-graph-based
business glossary for our team?"**

Start small and bottom-up. Pick one domain (say, Customer). Pick five
concepts everyone agrees about. Author them either as a TTL upload or by
adding concepts to a glossary collection. Link them to two or three real
data products you already have. Show the team how the same concept now
surfaces in marketplace search, in Ask Ontos, and in the column-level
glossary panel. Expand from there. Trying to model the whole organization
before linking anything to real data is the usual failure mode.

**"What is the difference between an ontology and a knowledge graph in
Ontos?"**

The ontology is the file you upload (or the bundled TTL). The knowledge
graph is the runtime structure built by union'ing all the enabled
ontologies and adding the per-instance triples you generate over time
(glossary collections, instance-level links). One ontology, one graph,
many semantic links sitting on top.

**"My team uses Protégé and SHACL — does Ontos handle that?"**

Yes. Ontos uses rdflib to parse uploaded files, so anything rdflib reads
(TTL, OWL, RDF/XML, N-Triples) lands cleanly. SHACL shapes are stored as
triples like everything else. Ontos does not currently run SHACL
validation against your instance data at write time — treat SHACL as
authoritative documentation of constraints rather than as an enforcement
hook in the current version.

**"Can I have multiple ontologies enabled at the same time?"**

Yes. Each enabled model contributes its triples to the conjunctive graph
under its own URN context. Ontos handles `owl:imports` lightly — you may
need to upload imported ontologies separately. Watch for concept-IRI
collisions: if two ontologies declare the same IRI, the graph treats them
as the same concept. That's usually what you want.

## Further reading {#further-reading}

- [Semantic Link](#semantic-link) and [Concept](#three-tier-linking) in
  this file
- [Three-tier linking on contracts](data-contract-lifecycle.md#schema-objects)
- [Bottom-up vs top-down flows](end-to-end-flows.md)
- [Knowledge Engineer persona](personas-quick-reference.md#knowledge-engineer)

_Last verified against codebase: 2026-05-28_
