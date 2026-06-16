# Personas Quick Reference

This file orients the copilot to "what does this persona typically need from
Ask Ontos?" Each persona maps to one of the seeded roles described in
[roles-and-rbac.md](roles-and-rbac.md#built-in-roles) — except the
Knowledge Engineer, which is a persona without a seeded role (no permission
matrix; described here for completeness).

The framings below are in the persona's own voice. The questions are
representative, not exhaustive — they shape ranking and disambiguation, not
gating.

## Admin {#admin}

**What you do.** You own the deployment. Roles, workflows, integrations,
demo data, the MCP token store — when something is broken, you're the
person Ontos expects to fix it. You almost never edit individual
products or contracts; you edit the rules that govern them.

**Where you spend time.** Settings → RBAC, Settings → Workflows,
Settings → Semantic Models, Settings → MCP, Settings → Connectors,
Settings → Demo Data, the workspace logs page when something is
broken.

**Typical questions for Ask Ontos:**

- "Why is user X not seeing feature Y?" — debug a permission gap.
- "Which roles have access to data-contracts at Read/Write?"
- "What workflow steps does the publish flow run in this deployment?"
- "Show me the failed workflow executions in the last 7 days."
- "What does `APP_ADMIN_DEFAULT_GROUPS` do, and is it consulted on
  every start?"

Admins want grounded references to settings, role assignments,
workflow definitions, and the underlying permission matrix.

## Data Governance Officer {#data-governance-officer}

**What you do.** You see the whole catalog. Your job is to make sure
products have domains, contracts have quality checks, PII fields are
classified, subscriptions don't outlive the products they depend on.
You don't build; you certify and audit.

**Where you spend time.** The Data Products list filtered by status,
the Compliance dashboard, Estate Manager, Master Data Management, the
Asset Reviews queue, the Glossary across all collections.

**Typical questions for Ask Ontos:**

- "Which data products are missing a domain assignment?"
- "Which contracts have no quality checks for the `accuracy`
  dimension?"
- "Are all PII-flagged Deliverables in approved-or-active status?"
- "Which subscriptions are still active on deprecated products?"
- "What's the certification coverage for products in the Finance
  domain?"

A DGO answer often spans multiple entity types and benefits from
links into the compliance and entitlements features.

## Data Steward {#data-steward}

**What you do.** You curate a slice — usually a domain. You're the
gatekeeper at two moments: when a contract is proposed for approval,
and when a product is submitted for certification. Outside of those
gates, you're maintaining glossary terms and triaging asset reviews.

**Where you spend time.** The contract approval queue, the product
certification queue, the Glossary editor for your domain, the Asset
Reviews assigned to you, the Schema tab on contracts (where DQX
suggestions land), Semantic Links panels on products and contracts.

**Typical questions for Ask Ontos:**

- "Which contracts in my domain are stuck in `under_review`?"
- "What asset reviews are assigned to me right now?"
- "Who's the business owner of the customer-360 product?"
- "What glossary terms are linked to this contract?"
- "What changed in the latest version of this product compared to
  the previous?"
- "I accepted 14 DQX suggestions yesterday — did they make it into
  the contract definitions?"

A Steward wants action-oriented answers: what needs my attention,
who should I escalate to, what's the current state.

## Data Producer {#data-producer}

**What you do.** You build products and contracts. You spend your
time on the detail pages — composing Deliverables, drafting schemas,
wiring quality checks, picking delivery methods. Promotion through
lifecycle states (draft → proposed → approved → active) is your day
job; certification is somebody else's.

**Where you spend time.** Data Products list filtered by your team,
the product detail page (Deliverables, Consumables, semantic links,
quality), the contract detail page (Schema tab, quality, SLAs),
sometimes the Asset Explorer for UC ingestion.

**Typical questions for Ask Ontos:**

- "How do I move my product from `draft` to `proposed`?"
- "What does `auto_approve` on a Deliverable do?"
- "Why is my Deliverable's contract showing as NULL — is that
  allowed?" (Yes — see
  [Deliverable](data-product-lifecycle.md#output-port).)
- "What quality dimensions does ODCS support?"
- "What does the publish workflow do — does it grant permissions
  automatically?" (No — publishing controls visibility; access
  comes through the subscribe workflow.)
- "What's the difference between a Deliverable and an output port?"
  (Same thing — see
  [Deliverable](data-product-lifecycle.md#output-port).)

Producers benefit from concrete answers about lifecycle transitions,
ODPS / ODCS field semantics, and what a workflow will do when
triggered.

## Data Consumer {#data-consumer}

**What you do.** You find products in the marketplace and request
access. You don't draft anything — you subscribe, sign agreements,
provide feedback. Notifications tell you when a product you
subscribe to changes or breaks.

**Where you spend time.** The Marketplace, the home page Discovery
section, individual product detail pages, your "My Subscriptions"
view, the Notification center.

**Typical questions for Ask Ontos:**

- "Where can I find a product about customer churn?"
- "Who owns the daily-orders product?"
- "How do I request access to this Deliverable?"
- "What does subscribing to a product do for me?" (Notifications on
  deprecation, new versions, compliance violations.)
- "Why don't I see this product in the marketplace?" (Likely
  `publication_scope` is `none` or below the consumer's visibility.)

Consumers want short, action-oriented answers and direct links to
the request-access wizard.

## Security Officer {#security-officer}

**What you do.** You configure security features, entitlement sync,
and access classifications. You're consulted on contract approvals
when PII or restricted data is involved. You don't certify products;
you sign off on the security side of the certification.

**Where you spend time.** Settings → Security Features, Settings →
Entitlements, Settings → Entitlements Sync, the Compliance dashboard,
sometimes contract approval queues for sensitive data.

**Typical questions for Ask Ontos:**

- "Which entitlement personas have admin on `security-features`?"
- "What sync jobs are configured for entitlements, and when did they
  last run?"
- "Which contracts mark fields with `RESTRICTED` classification?"
- "What does the on_first_access disclaimer workflow look like?"

Security Officer questions often cross into Admin territory; answers
should respect the persona's `Admin`-level access to
security-features, entitlements, and entitlements-sync, with
`Read-only` on data-asset-reviews.

## Knowledge Engineer / Data Architect {#knowledge-engineer}

**What you do.** You author the ontology in OWL/TTL/SHACL externally
and load it into Ontos. You decide what the canonical concepts are,
how they relate, and where SHACL constraints live. Ontos uses your
ontology to drive asset types, drive concept search, ground Ask
Ontos, and feed agents via MCP.

**Where you spend time.** Outside Ontos in Protégé or TopBraid
authoring TTL. Inside Ontos: Settings → Semantic Models (upload),
the Concept Browser, the Knowledge Graph view, the SPARQL search
tab, the Ontology Generator when starting from UC metadata.

**Not a seeded role.** The Knowledge Engineer doesn't have a built-in
Ontos role. Most knowledge engineers map to Data Producer or Data
Steward depending on whether they also work on data products.
Permissions to author semantic models come from the
`semantic-models` feature's `Read/Write` or `Admin` level.

**Typical questions for Ask Ontos:**

- "What concepts does our ontology cover for the Sales domain?"
- "Which concepts have no data mapping yet?" (Gap analysis.)
- "What's the difference between an ontology and a knowledge graph
  in Ontos?"
- "Can I use SHACL shapes for validation?"
- "How do I bring my Protégé file into Ontos?"
- "What does it mean for the ontology to be prescriptive?"

Knowledge Engineers expect technical, RDF-aware answers — saying
"concept" when you mean concept, "term" when you mean term,
distinguishing the source artifact from the runtime graph.

## The empty-groups persona ("anon") {#anon}

Used in testing to exercise fully-denied paths. A request from a
user with zero groups should resolve to no Ontos role and hit `None`
on every feature. The copilot should answer such users only on
**public** concept questions (e.g., "what is a data contract?") and
refuse to surface specific entity data.

## Cross-references {#cross-references}

- [Roles and RBAC](roles-and-rbac.md) — the seeded permission
  matrices behind these personas
- [Demo-mode persona override](roles-and-rbac.md#persona-override) —
  how to switch personas at runtime for testing or demos
- [End-to-end flows](end-to-end-flows.md) — who does what at each
  step in the canonical bottom-up and top-down journeys

_Last verified against codebase: 2026-05-28_
