# Delivery and Propagation

Two unrelated things in Ontos share the word *delivery*. Customers conflate
them constantly, and so do engineers writing tools that touch them. Sort the
two out first; the rest of this doc is about the second one.

## Two "delivery" concepts {#two-deliveries}

| Term | What it governs | Where it shows up |
|---|---|---|
| **Delivery Method** | How a product's **data** flows to consumers — the channel customers connect to. | On a Deliverable (output port). Configured from Settings → Delivery Methods. |
| **Delivery Mode** | How a governance **change** propagates out of Ontos into the underlying system (Unity Catalog, Git, a human's queue). | On the Delivery Service. Configured from Settings → Delivery. |

The values are also disjoint, so there is no overlap by mistake:

- Delivery Method values are `Table Access`, `Serving Endpoint`, `File
  Export`, `Streaming` — the `DeliveryMethodCategory` enum (`access`,
  `endpoint`, `export`, `streaming`).
- Delivery Mode values are `Direct`, `Indirect`, `Manual` — the
  `DeliveryMode` enum.

When in doubt: *Method* answers "how does the consumer get bytes?" — *Mode*
answers "how does Ontos's decision become real in the platform?".

The rest of this document is about Delivery Mode and the Delivery Service.
For Delivery Method, see
[Data Product Delivery Methods](data-product-lifecycle.md#delivery-methods).

## Why the Delivery Service exists {#why-delivery-service}

Ontos is a system of record for a lot of *decisions*: who can access what,
which tags belong on which column, which roles carry which permissions,
which versions of which products are active. Those decisions only have value
when they land in the systems that actually enforce them — Unity Catalog,
external IT change-management, the customer's own GitOps pipeline.

The **Delivery Service** is the layer that turns Ontos's decisions into
side-effects in those systems. It owns three orthogonal concerns:

- **Where to land the change** — Direct (apply via SDK), Indirect (persist
  as YAML in Git), Manual (notify a human).
- **What kind of change** — grant, revoke, tag assignment, entity
  create/update/delete, role change.
- **Whether several modes run in parallel** — the configuration is a set,
  not an exclusive choice. A site can run Direct + Indirect simultaneously
  so that every direct UC change also produces a Git-trackable YAML
  artifact.

Customers ask about this layer using a few characteristic phrases — "we want
to maintain everything in Ontos and load it back to our workspace", "we
need indirect delivery via a volume so our deployment pipeline can pick it
up", "can Ontos write tags back to UC for us?". Those are all questions
about Delivery Mode.

## The three modes {#the-three-modes}

Modes are not mutually exclusive. Every configured mode runs for every
deliverable change, and the results are aggregated. If Direct succeeds but
Indirect fails, the aggregate is `any_success=True, all_success=False`, and
both outcomes are surfaced.

### Direct mode {#direct-mode}

**What it does.** Applies the change immediately, in-process, by calling
the underlying system's API. For grants and revokes, that means the
service principal's workspace client issuing a UC `GRANT` / `REVOKE`. The
result is visible in the underlying system within seconds.

**When to use it.** When Ontos has the authority to write directly (the
service principal holds the necessary privileges) and the customer wants
governance decisions to take effect without a human in the loop.

**What the user sees.** Status flips on the entity (e.g., subscription
becomes Active) and the new state is observable in the target system on
the next read.

**Dry-run support.** `DELIVERY_DIRECT_DRY_RUN=true` lets the mode log what
it *would* do without actually issuing the SDK call. Used when validating
a configuration before turning live changes on.

**Current coverage in the shipping version.** Direct mode wires
`GRANT` and `REVOKE` end-to-end via `GrantManager`. Other change types
(tag assignments, entity create/update) currently no-op in Direct mode
with a `Change type not applicable for direct mode` marker and are
expected to land via Indirect or Manual — or, for the concept-to-UC-tag
path, via the `uc_tag_sync` workflow described below.

### Indirect mode {#indirect-mode}

**What it does.** Serializes the change to a YAML file in the configured
Git repository (or volume — the `GitService` abstraction covers both).
A separate process — the customer's CI/CD pipeline, a workspace job, a
manual deploy — picks the YAML up and applies it.

**When to use it.** When the customer has an existing change-management
discipline they don't want Ontos to bypass, when the workspace's SP
doesn't have direct write authority, or when an auditable trail of every
governance change in source control is mandatory. Customers who say
*"maintain everything in Ontos and load it back to the workspace via our
pipeline"* are asking for Indirect.

**What the user sees.** The change is recorded in Ontos immediately
(databases get updated, the UI reflects the new state). The Git commit
shows up in the configured repo / volume location. The downstream UC
reality lags until the customer's pipeline runs.

**File layout.** Each entity type has a registered `FileModel` that
controls subdirectory, filename, and YAML schema. The wrapper
(`wrap_as_resource`) gives every record a consistent envelope so the
target loader can identify what kind of resource it is.

**Current coverage.** Indirect mode covers data contracts, data products,
data domains, roles, and tags — anything that has a `FileModel` in the
registry. Change types that don't have a file model fall back to a
generic timestamped YAML in `changes/` capturing the raw payload.

### Manual mode {#manual-mode}

**What it does.** Creates a notification (and/or logs an entry) asking a
named human or group to perform the change in another system. Used when
there is no programmatic surface to drive the change automatically.

**When to use it.** When the customer's enforcement system doesn't expose
an API — a legacy data catalog, an offline approval queue, or a downstream
system requiring human inspection. Also useful as a *belt-and-suspenders*
mode alongside Direct, when an admin wants visibility into every change
even if Ontos applies it automatically.

**What the user sees.** A notification in the bell menu pointing to the
required action. The notification carries the title (e.g., *Grant Access:
DataProduct*) and a body describing principal, privileges, and target.

**Current coverage.** The notification title/body templates exist for the
common change types. The DB-session-bound notification creation has a
TODO marker in the current implementation; admins should expect the entry
to appear in app logs and treat the in-UI notification surface as
evolving.

## Change types {#change-types}

Everything that goes through Delivery is one of these `DeliveryChangeType`
values, grouped by what they govern:

| Group | Change types |
|---|---|
| **Access** | `GRANT`, `REVOKE` |
| **Tags** | `TAG_ASSIGN`, `TAG_REMOVE`, `TAG_CREATE`, `TAG_UPDATE`, `TAG_DELETE` |
| **Data entities** | `CONTRACT_CREATE` / `CONTRACT_UPDATE` / `CONTRACT_DELETE`, `PRODUCT_CREATE` / `PRODUCT_UPDATE` / `PRODUCT_DELETE`, `DOMAIN_CREATE` / `DOMAIN_UPDATE` / `DOMAIN_DELETE` |
| **Roles** | `ROLE_CREATE`, `ROLE_UPDATE`, `ROLE_DELETE` |

Each change type is meaningful in each mode independently — `GRANT` in
Direct issues a UC GRANT; `GRANT` in Indirect writes a grant manifest to
Git; `GRANT` in Manual creates a notification reading "grant SELECT to
group-x on catalog.schema.table".

Not every mode handles every change type yet. Direct currently
implements `GRANT`/`REVOKE` only; the other change types serialize via
Indirect or notify via Manual. Tag-assignment delivery to UC is described
in the next section because it travels via a different path today.

## How concept → UC tag actually flows {#concept-to-uc-tag}

This is the question customers ask most often, and it deserves an honest
answer because there are two paths and only one of them is fully wired.

**The intended path (evolving).** A Steward writes a Semantic Link from
a column to a concept. The Delivery Service receives a `TAG_ASSIGN`
change and propagates it via the active modes — Direct (UC tags API),
Indirect (YAML manifest in Git), or Manual (notification). In the
shipping version, this path is partially wired: the change type exists,
the notification templates exist, but `TAG_ASSIGN` does not yet have a
fully-wired Direct handler that calls UC's tag API. Treat this as an
evolving area.

**The path that ships today.** A Databricks job — the `uc_tag_sync`
workflow — reads `entity_semantic_links` joined with contracts,
products, domains, and assets, computes the desired UC tag set per
table, and issues `ALTER TABLE … SET TAGS (...)` statements via Spark
SQL. The job is installable from Settings → Background Jobs, runs on a
schedule (or on demand), and is the production path for concept-to-UC
sync on customer deployments today. It is independent of the Delivery
Service modes.

In conversation: yes, semantic links *do* reach UC tags. The mechanism is
a job (not the Delivery Service direct mode). The Delivery Service path
for tag assignment is being filled in; the workflow path is what's
running in customer demos right now.

## How agreements use Delivery {#agreement-integration}

Approval workflows produce signed Agreements. The post-approval side
effect — actually granting UC access to the consumer — lives in the
`grant_permissions` step of the workflow definition, **not** in the
Delivery Service path described above.

`grant_permissions` runs directly inside the workflow executor: it reads
the workflow execution context, uses the service principal's workspace
client, and issues UC `GRANT`s. The two paths converge conceptually
(both are about delivering a grant change to UC) but are wired
independently. The agreement workflow is the producer; the
`grant_permissions` step is the in-line deliverer. The Delivery Service
GRANT path is the alternative route for grants raised outside an
approval workflow.

See [grant_permissions step](agreement-workflow.md#grant-permissions-step)
for the requirements (notably: the SP needs explicit `MANAGE` on each
securable, not `ALL_PRIVILEGES`).

## What each persona sees {#per-persona}

- **Admin** — Configures which modes are active (Settings → Delivery),
  the dry-run flag, the Git repo connection, and the notification
  targets for Manual mode. Audits the Delivery Service logs when a
  customer pipeline gets out of sync.
- **Data Steward / Data Producer** — Sees the result of propagation
  rather than the propagation itself. When they make a change in
  Ontos, the UI reflects it immediately; the underlying-system
  reality follows the mode.
- **Data Consumer** — Doesn't see Delivery directly. Sees the end
  effect: their subscription becomes active, their UC `SELECT`
  succeeds.

## Cross-references {#cross-references}

- [Delivery Method on a Deliverable](data-product-lifecycle.md#delivery-methods) — the *other* delivery concept
- [grant_permissions workflow step](agreement-workflow.md#grant-permissions-step) — agreement-driven UC grants
- [Semantic Link](ontology-and-knowledge-graph.md#three-tier-linking) — the source row a concept-to-UC-tag flow reads
- [Round-trip asymmetry](ontology-and-knowledge-graph.md#round-trip-asymmetry) — current state of concept → UC tag wiring

## Common questions {#common-questions}

**"We want to maintain everything in Ontos and load it back to the
workspace via our own deployment pipeline. Can Ontos do that?"**

Yes. Turn on Indirect mode, point it at your Git repo (or a configured
volume), and Ontos serializes every governance change as YAML there.
Your pipeline reads those YAML files and applies them on its own
schedule. Direct mode can stay off if you want Ontos to be advisory
only, or on (alongside Indirect) if you want the same change to be
applied immediately *and* recorded in Git for audit.

**"Do these modes conflict? If I enable Direct and Indirect, does the
change happen twice?"**

The change happens once per mode but they are not duplicates of each
other — Direct calls UC, Indirect writes YAML. Together they give you
"applied" plus "auditable". Conflict only arises if your downstream
pipeline (consuming the Indirect YAML) and Direct mode both try to
write the same UC tag — and even then, idempotency on UC's side makes
the second write a no-op. The aggregated `DeliveryResults` object
captures success per mode independently.

**"Tags reading from UC is not there — when will the round-trip be
complete?"**

The forward path from a Semantic Link to a UC tag does ship today via
the `uc_tag_sync` workflow (see [concept → UC tag](#concept-to-uc-tag)).
The Delivery Service Direct mode for `TAG_ASSIGN` is partial in the
current version. The reverse path — pulling existing UC tags into Ontos
as concept assignments — is not yet shipping. Plan demos around the
forward direction with the workflow; flag the reverse direction as
evolving.

**"Our SP doesn't have MANAGE on the catalog — what happens to Direct
mode grants?"**

Direct mode raises an error from the underlying UC API. The
`DeliveryResults` records the failure on the Direct entry; if Indirect
is also enabled, the same change is still serialized to YAML there and
the customer's pipeline can apply it under a more-privileged identity.
This is one of the common reasons to enable Direct + Indirect together.

**"Can I turn Direct off and run only Indirect?"**

Yes. The active set is a settings toggle. With Direct off, Ontos becomes
a pure system-of-record — it persists what *should* be true, and a
downstream pipeline is responsible for making it true. A common pattern
in regulated environments.

**"Where do role changes go?"**

Through the Delivery Service. `ROLE_CREATE` / `ROLE_UPDATE` /
`ROLE_DELETE` are valid change types; Direct mode currently no-ops them
(role state lives in the Ontos DB, not in UC), Indirect serializes them
to Git, Manual notifies. Most customers run roles via Indirect so the
role definitions are auditable in source control alongside their other
governance manifests.

**"What's the difference between Delivery Method = Table Access and
Delivery Mode = Direct?"**

They answer different questions about different layers. *Table Access*
is the channel a consumer uses to read a product's data — they query UC
through whatever client. *Direct* is whether Ontos itself wrote the
grant that made that query possible synchronously via UC's API. A
deliverable can be Table Access (channel) while its access grant is
applied Indirect (mode) — those are independent choices.

_Last verified against codebase: 2026-05-28_
