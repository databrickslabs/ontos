# End-to-End Flows

Ontos supports two narratives that customers walk in with. Most platforms
force one or the other. Ontos plumbs both, and the join point is the
semantic link table.

- **Flow A — Bottom-up.** Start from Unity Catalog. Find a table that's
  already producing value. Wrap it in a data product. Attach a contract.
  Pin meaning to it. Publish.
- **Flow B — Top-down.** Start from a model of the business in your head.
  Author an ontology that captures it. Map the concepts to real data
  assets. Layer a glossary on top.

This doc walks each flow step by step, calls out who does what at each
step, and points at the questions Ask Ontos can answer along the way.
Both flows produce semantic links — that's the join.

## Two flows, one bridge {#two-flows-one-bridge}

The shared mechanism is a row in `entity_semantic_links`. A bottom-up
team adds those rows after they have data and need to express what it
means. A top-down team adds those rows after they have concepts and need
to ground them in real data. Same rows, opposite arrows.

```
                  Bottom-up                       Top-down
                       │                              │
                       ▼                              ▼
              UC table / view              Ontology / TTL upload
                       │                              │
                       ▼                              ▼
               Data Product                Knowledge graph context
                       │                              │
                       ▼                              ▼
       Contract bound to Output Port         Glossary collection
                       │                              │
                       └────────┬─────────────────────┘
                                ▼
                       entity_semantic_links
                       (the bridge — same table,
                        two directions of travel)
```

## Flow A — Bottom-up: UC → curated catalog {#flow-a-bottom-up}

The canonical phrasing customers use: *"bring asset from UC to Ontos,
asset to product, product to contract, assign concepts"*. Eight steps.

### Step 0 — Set up domain, team, project {#step-a-0}

**Who:** Admin or Data Governance Officer.

**What:** Create a Data Domain (the business area — Sales, Supply Chain,
etc.), a Team (the durable group of users who own the work), and
optionally a Project (a bounded initiative under the team).

**Why first:** Everything downstream — products, contracts, glossary
collections — scopes to a domain. Some access scoping (`Filtered` level)
keys off domain ownership too. Don't skip this even for small demos.

**Ask Ontos at this stage:** "What domains exist?" "Show me teams in
domain X."

### Step 1 — Bring an asset from UC into Ontos {#step-a-1}

**Who:** Data Producer or Data Engineer.

**What:** Identify the UC table, view, or model that already exists and
produces value. Register it as an Asset in Ontos (Asset Explorer →
Create Asset with the appropriate type — PhysicalTable, PhysicalView,
Dataset). The asset carries a pointer back to the UC fully-qualified
name and inherits typing from the ontology-driven asset type system.

**Why this step exists:** Ontos doesn't own the UC table. It owns a
governance record *about* the UC table. That record can carry custom
properties, tags, semantic links, costs, ratings — context the platform
itself doesn't provide.

**Ask Ontos at this stage:** "Which UC table does this asset point at?"
"What's the meaning of this column?"

### Step 2 — Create the Data Product {#step-a-2}

**Who:** Data Producer / Data Product Owner.

**What:** Create a Data Product, give it a name, assign it to the domain
and owner team. Add **Deliverables** (output ports): each Deliverable
gets a name, a Delivery Method (Table Access / Serving Endpoint / File
Export / Streaming), and one or more linked UC assets. Add
**Consumables** (input ports): declared upstream dependencies, each
required to reference a contract version (per ODPS).

**The vocabulary:** in conversation you'll hear *Deliverable* and
*Consumable*; in the persisted ODPS model these are *output_port* and
*input_port*. They're the same thing — the customer-facing names are the
primary ones.

**Ask Ontos at this stage:** "What does this delivery method mean?"
"What status do I move the product to next?"

### Step 3 — Attach a Data Contract per Deliverable {#step-a-3}

**Who:** Data Producer (drafting) and Data Steward (reviewing).

**What:** Decide between **Products-First** (the product exists,
contracts come later per Deliverable) and **Contracts-First** (the
contract is drafted before assets are linked; the product is built to
satisfy the contract). Both supported, neither preferred — it's a
workflow choice driven by team culture, not a value judgment by the
platform.

A contract is attached to a Deliverable by setting the Deliverable's
`contract_id`. That field may be NULL during early lifecycle stages —
deliberate, not an oversight. Input ports' contract references, by
contrast, are required.

**Ask Ontos at this stage:** "Which output ports of my product still
have NULL contracts?" "Show me contracts in this domain in
under_review."

### Step 4 — Enrich the product {#step-a-4}

**Who:** Data Producer + Data Steward.

**What:** Add tags, business owners, custom properties, costs. Define
quality check definitions on the contract — pick dimensions, set
thresholds, choose business impact. Optionally kick off a DQX profiling
run to get *suggested* checks (see [data-quality.md](data-quality.md#dqx-flow)).
Document the product (purpose, usage, limitations, getting-started).

**Why this matters:** This step is where the product becomes
*discoverable*. A product with no description, no quality, no owner is
indistinguishable from any other UC table. Enrichment is what justifies
the wrapper.

**Ask Ontos at this stage:** "What quality dimensions am I covering on
this contract — am I missing accuracy on PII fields?" "Which products in
my domain don't have a documented owner?"

### Step 5 — Assign semantic terms / concepts {#step-a-5}

**Who:** Data Steward, Data Engineer, or Business Analyst.

**What:** Pin meaning. Open the Semantic Links panel on the product,
contract, or column. Search the glossary or the broader ontology. Pick
the concept that fits. The link is written to `entity_semantic_links`.
The three tiers — product, schema, property — are deliberate; pin at the
lowest level you can defend.

**Why this matters:** This is where the data becomes addressable by
business meaning. Ask Ontos can now answer "products related to customer
churn" by walking the graph; the marketplace search ranks
semantically-linked products higher; agents grounded via MCP can find
the right table by concept, not by name.

**Ask Ontos at this stage:** "Which products in my domain don't have a
glossary term?" "What concept is this column linked to, and why?"

### Step 6 — Steward review + certify + publish {#step-a-6}

**Who:** Data Steward (certifies) + Data Product Owner (publishes).

**What:** The producer submits the product for certification. The
Steward reviews against the contract, the quality, the semantic links,
the documentation. If approved, the product moves through `approved` to
`active` status when the owner publishes it. Publication scope
(`domain` / `organization` / `external`) controls who sees it in the
marketplace.

Approval workflows (see
[agreement-workflow.md](agreement-workflow.md#approval-roles)) may gate
this step — the certification action can trigger an approval workflow
that captures sign-off from named business owners.

**Ask Ontos at this stage:** "What changed in v2 compared to v1?" "Who
needs to approve this status change?"

### Step 7 — Consumer discovers + subscribes {#step-a-7}

**Who:** Data Consumer.

**What:** The consumer browses the marketplace or asks Ask Ontos a
natural-language question. They drill into a product, review the
contract, request access via the subscribe wizard. The subscribe wizard
is itself an approval workflow — it captures use case, on-behalf-of
principal (if subscribing for a team or service principal), and routes
to the Data Product Owner for approval. On approval, a
`grant_permissions` step issues real UC grants to the consumer
principals.

**Ask Ontos at this stage:** "Where can I find a product about customer
churn?" "Who owns the daily-orders product?" "How do I request access?"

## Flow B — Top-down: ontology → physical assets → UC tags {#flow-b-top-down}

The mirror narrative. Five steps. The last one — propagating concept
assignments back to UC governance tags — ships today through a workflow
path, with a parallel Delivery Service path being filled in.

### Step 1 — Author the ontology externally {#step-b-1}

**Who:** Knowledge Engineer / Data Architect.

**What:** Open Protégé, TopBraid, or a text editor. Author an ontology
in OWL / Turtle / RDF/XML / N-Triples. Declare classes, data properties,
object properties, optional SHACL shapes for constraints. The
deliverable is a `.ttl` / `.owl` / `.rdf` / `.nt` file.

Customers at this skill level talk about RDF, OWL, SHACL the way an
analytics engineer talks about Delta tables. They expect Ontos to handle
those formats natively — and Ontos does, via rdflib.

**Alternative — LLM-assisted inference.** For teams without an ontology
yet, `OntologyGeneratorManager` (UI: `/concepts/generator`) points at UC
metadata and proposes concepts. Treat the output as a starting point
requiring human curation, not a finished ontology.

**Ask Ontos at this stage:** Less useful here — the knowledge engineer
is writing TTL outside Ontos. Once it's uploaded, Ask Ontos becomes
useful for exploration.

### Step 2 — Upload + enable + visualize {#step-b-2}

**Who:** Knowledge Engineer or Admin.

**What:** Settings → Semantic Models → Upload. Pick the file. Enable it.
Refresh the runtime conjunctive graph
(`POST /api/semantic-models/refresh-graph`). Open the Knowledge Graph
view (`/concepts/home` → Graph tab) and explore. The graph is rendered
with Cytoscape; nodes are concepts, edges are object properties.

**Why visualize:** Customers want to *see* the graph. The visual is what
makes ontology investment legible to non-technical stakeholders.
Identify gaps — clusters with sparse relationships, concepts that don't
connect to anything, missing domains.

**Ask Ontos at this stage:** "What concepts does our ontology cover for
the Sales domain?" "Which concepts have no data mapping yet?"

### Step 3 — Map ontology concepts down to UC assets {#step-b-3}

**Who:** Data Steward / Data Engineer.

**What:** Navigate to a concept. Open the Linked Entities panel.
Search for products, contracts, schemas, columns that fit this concept.
Create semantic links. Repeat per concept.

This is the same `entity_semantic_links` table the bottom-up flow
writes. The difference is direction of approach: top-down starts from
the concept and finds the data; bottom-up starts from the data and
finds the concept.

Three tiers apply — link at product, contract-schema, or column level.
For ontology grounding, column-level is the gold standard; product-level
is the fallback.

**Ask Ontos at this stage:** "Show me all products that satisfy concept
X." "What concept does this column embody?"

### Step 4 — Layer a Business Glossary on top {#step-b-4}

**Who:** Data Steward / Business Analyst / Domain Expert.

**What:** Create a glossary collection. Add concepts to it (these become
the displayable "terms"). Lifecycle each concept through draft →
published → certified. Decide the scope (domain-specific glossary vs
org-wide glossary).

The relationship to Step 1: the concept IRIs the knowledge engineer
authored can be added to a glossary collection so the steward and
business users have a curated, browse-able view of the parts that matter
to them. The full ontology stays as the long tail; the glossary is the
short list.

**Ask Ontos at this stage:** "What's the canonical definition of ARR in
our org?" "Show me certified terms in the Finance glossary."

### Step 5 — Push concept tags back to UC {#step-b-5}

**Who:** Data Steward / Admin, with the UC tag-sync job installed.

**What this does:** Translate concept-to-column semantic links into
Unity Catalog governance tags on the corresponding tables and columns,
so UC search, lineage, and access policies can leverage the concept.
This closes the round-trip from ontology → physical asset → UC.

**How it ships today.** The `uc_tag_sync` workflow reads
`entity_semantic_links` joined with the contract, product, domain, and
asset metadata, computes the desired UC tag set per table, and issues
`ALTER TABLE … SET TAGS (...)` via Spark SQL. The job is installable
from Settings → Background Jobs and runs on schedule or on demand. It
is the production path for concept-to-UC sync on customer deployments
today. Tags propagate at table and schema granularity in the current
implementation; column-level tag propagation is evolving.

**The parallel path via Delivery Service.** Separately,
[Delivery Service](delivery-and-propagation.md#concept-to-uc-tag)
defines `TAG_ASSIGN` as a first-class change type, with Direct /
Indirect / Manual modes. The Direct mode handler for tag changes
against UC is partially wired in the current version — the change
type, notification templates, and Indirect (Git) path exist; the
Direct mode call to UC's tag API is being filled in. Customers running
Indirect mode already see concept-driven tag manifests serialized to
Git as a by-product of every link write.

**What's not yet shipping in either path:** the reverse direction —
reading existing UC tags and reflecting them back into Ontos as concept
assignments. The customer voice tracking this work captures it as
"Tags reading from UC is not there." Forward propagation works; the
backward pull is the part still evolving.

**Ask Ontos at this stage:** "Has the latest concept-to-column link on
the X product been synced to UC yet?" "When was the uc_tag_sync job
last run?" "Show me UC tables tagged with concept Y."

## Where the flows meet {#where-they-meet}

Step 5 of Flow A and Step 3 of Flow B are the same action: writing a
row to `entity_semantic_links`. A team running both flows simultaneously
(common in mid-size enterprises with both a "let's catalog what we
have" effort and a "let's model what we want" effort) will see the same
table grow from both ends.

The implication: it does not matter which flow you start with. What
matters is that linking happens at the lowest tier the team can
defend, that the same concept IRI is reused across links instead of
being re-created with subtly different IRIs, and that the glossary is
curated as a published subset of the broader ontology rather than as a
separate parallel artifact.

## Common questions {#common-questions}

**"We have UC already populated and no ontology. Where do we start?"**

Flow A, Steps 0–4. Get a Domain, a Team, one product wrapping one
high-value UC table, a contract with a few quality checks, and one
semantic link to one concept (you can use the bundled ontology or add a
single concept to a glossary collection). Don't start by trying to
model the whole organization.

**"We have an ontology authored in Protégé and no UC adoption yet. Can
we still use Ontos?"**

Yes. Upload the ontology (Step B-1, B-2). Use the LLM-assisted
generator to *propose* asset structures from any UC presence you do
have, even partial. Use the marketplace as the place producers see
their concept coverage relative to what data exists. The bottom-up flow
will catch up as UC adoption grows.

**"Do I have to pick one flow?"**

No. The two flows are deliberately designed to share the same table.
Mid-size organizations almost always run both. The risk to manage is
glossary drift — two teams creating subtly different concepts for the
same thing. Address this by making the glossary curation a steward
responsibility, not a free-for-all.

**"What's the difference between an output port and a Deliverable?"**

Same thing. *Output port* is the persisted ODPS-spec label; *Deliverable*
is the customer-facing name. Same for *input port* and *Consumable*.
Use the customer-facing names in conversation; the ODPS names show up
in exports and in the persisted model.

**"My consumers are subscribing but not getting access — what's
missing?"**

Three usual suspects. (1) The subscribe wizard's approval workflow has
not been approved (it sits in `paused` waiting for the Data Product
Owner to respond). (2) The `grant_permissions` step ran but the app's
service principal does not hold `MANAGE` on the target UC securable
(`ALL_PRIVILEGES` is not sufficient). (3) The `consumer_principals`
list on the product points at a workspace-only group; UC accepts only
account-level groups.

**"Can the consumer see the contract they're signing?"**

Yes. The subscribe wizard shows the contract details (schema, quality,
SLAs, support channels) before the signer commits. The resulting
agreement record snapshots the contract version at sign-time, so later
contract edits don't retroactively change what the consumer agreed to.

**"Tags reading from UC is not there. How do concepts in Ontos make it
back to UC governance tags?"**

Today via the `uc_tag_sync` workflow — a job that reads
`entity_semantic_links` plus the contract/product/domain/asset
metadata and writes UC tags through Spark SQL `ALTER TABLE … SET TAGS`.
The Delivery Service is the parallel emerging path: it defines
`TAG_ASSIGN` as a first-class change type with Direct/Indirect/Manual
modes; the Direct UC handler is being filled in, the Indirect (Git
manifest) path already records every tag assignment. Plan demos around
the forward direction; the reverse direction (UC tags → Ontos concept
assignments) is the part still evolving. See
[Delivery and Propagation](delivery-and-propagation.md#concept-to-uc-tag).

## Cross-references {#cross-references}

- [Data Product](data-product-lifecycle.md#what-is-a-data-product) and
  [Deliverable](data-product-lifecycle.md#output-port)
- [Data Contract](data-contract-lifecycle.md#what-is-a-contract) and
  [Editor of record](data-contract-lifecycle.md#editor-of-record)
- [Ontology and the Knowledge Graph](ontology-and-knowledge-graph.md)
- [Delivery and Propagation](delivery-and-propagation.md) — how
  governance changes (grants, tags, entity writes) reach UC and other
  external systems
- [Data Quality DQX flow](data-quality.md#dqx-flow)
- [Approval Gate](agreement-workflow.md#approval-gates) and the
  [grant_permissions step](agreement-workflow.md#grant-permissions-step)

_Last verified against codebase: 2026-05-28_
