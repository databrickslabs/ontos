# PRD: Authority Resolution (Authority Relations, DNA-Coefficient, and the Agentic Decision Gate)

> **Provenance.** This feature implements the **Authority Resolution Framework (ARF)** (Zenodo paper by Parviz N.; a trade-promotion worked example prepared for the CCHBC pilot) as a first-class Ontos feature. ARF's central measurement — the DNA-Coefficient — is explicitly *proposed and not yet validated* in the source paper; this PRD is the basis of a **PoC**, and the PoC is expected to feed corrections back into this document. Treat the DNAco scoring composite (see [Further Notes](#further-notes)) as a design surface pending Parviz's methodology sign-off, not a frozen spec.

## Concept Model

The vocabulary is new to Ontos, so the primitives first:

- **Authority** — the *right to decide*, treated by ARF not as a property stored in one place (an org chart, a RACI matrix, a permission table) but as a **relation that must resolve consistently** across the enterprise's ways of representing itself. Agentic AI does not create the gap between documented and practiced authority; it relocates that gap into an agent's unwatched configuration. The feature makes the gap explicit, measurable, and enforceable.
- **Authority Relation (AR)** — the ARF six-tuple `(Actor, Action, Object, Domain-Context, Justification-Chain, DNA-Coefficient)`. In Ontos an AR is realised as **two entities**:
  - **AR Definition** — the reusable authority *rule*. This is the entity in the list view; it carries the `@id` agents call, its lifecycle status, domain assignments, its stakeholders, its evidence binding, its executable `decisionLogic`, its version family, and its *aggregate* DNA-Coefficient.
  - **AR Decision** — one record per evaluation (an agent call) or per sampled evidence row. It is the ARF JSON-LD `ar-instance` shape, carrying its own `divergenceMagnitude` + `direction` + verdict + timestamp + the AR Definition **version** that decided it. AR Decisions are the sample the Definition's DNAco is rolled up from, and the source of the usage metrics and timeline.
- **Actor** — the role/agent *whose authority is under scrutiny* — the subject of the decision, human or delegated agent. Modelled as an `OrganizationalRole` held by a principal since a date. The Actor is **not** a reviewer.
- **Action** — a governed act from a controlled vocabulary (`approve`, `escalate`, `override`, `delegate`, `veto`).
- **Object** — the entity acted upon, which **must resolve across domains** via `resolvesTo` anchors (a process step, a system permission, a real-world fact). In Ontos the Object binds to existing catalog entities (a Data Product / Data Contract that maps the underlying table the decision changes).
- **Domain-Context** — the bounded scope in which the authority holds (market, currency, threshold). This is where the **evaluable predicate** (e.g., `threshold = 0.10`) lives.
- **Justification-Chain (JC)** — the auditable basis: a **versioned policy document** reference modelled with W3C PROV (`prov:wasDerivedFrom`, `prov:wasGeneratedBy`), stored as triples in the existing RDF store.
- **DNA-Coefficient (DNAco)** — a **calibrated divergence score, `0.0 = best`** (documented authority exactly matches lived practice), higher = worse, carrying a **direction** (`actual-exceeds-documented` / `documented-exceeds-actual`). It measures the gap between the AR *as documented* and how it is *actually exercised*, computed from bound Evidence Sources.
- **Evidence Source** — the data that reveals actual practice. In v1 a single **Unity Catalog Delta table** with a per-AR **column→element mapping**; the comparison of that evidence against the AR is what produces the DNAco.
- **N-functional affirmation** — ARF requires a DNAco to be *affirmed* before it is fit to configure an agent. The paper names three functions (Business / Technical / Governance); Ontos generalises this to **N stakeholders, each with a role**, modelled like a Team. A DNAco is *valid-for-use* only once every defined affirmation is complete.
- **Authority Maturity Level (L0–L5)** — Undocumented → Documented → Object-Resolved → **DNA-Measured (L3)** → **Tri/N-Functionally-Affirmed (L4)** → Agent-Design-Audited (L5). Surfaced as a *derived* attribute, distinct from the operational `Draft/Active/Needs-Review` status. L3 is the realistic PoC target.
- **decisionLogic** — the Ontos-authored, machine-evaluable rule compiled from the AR's fields (allowed principals, context predicate, required affirmations present, status Active) that the MCP runtime evaluates deterministically to return a verdict.

The worked example throughout is **trade-promotion approval**: a Regional Sales Manager approves discounts up to a threshold within a region; a National Account Director approves above it; Category Finance co-signs anything touching a retailer's full-year trade budget; an AI promotion agent recommends and, for some accounts, auto-submits terms.

## Problem Statement

Ontos already governs *declared* authority (RBAC, Data Contract approver roles, the Compliance DSL) and records *observed* practice (audit log, asset reviews), joined by a semantic layer (RDF store, semantic links) and exposed to AI agents through an MCP surface. What it cannot do today:

1. **There is no way to make an authority rule explicit and agent-callable.** "Who may approve this discount, formed how" lives in SOPs, delegation memos, and people's heads. Ontos RBAC (`app_roles`) governs who may use *Ontos*, not the *business* authority to make a domain decision. An AI promotion agent that auto-submits terms has no governed place to ask "am I permitted to make this decision, and is the right principal signing off?" — so the authority check either does not happen or is hard-coded into the agent's own unwatched configuration.
2. **The documented-vs-practiced gap is invisible and unmeasured.** A promotion approved above the submitter's real authority, without a required co-sign, or under a stale role (someone who changed jobs but kept the permission) looks identical to a clean one. Ontos's policy-only checks catch the *traceable, threshold-breaching* cases; they structurally cannot surface the *soft* divergences — the informal-influence and stale-authority patterns that only appear when you compare the rule against a body of real past decisions.
3. **Agentic decisions cannot be gated on soft authority knowledge.** The urgent, differentiated need is a runtime check: before an agent takes a write-capable action, it resolves the action against an explicit, affirmed authority rule and gets a deterministic *approved / denied / no-authority* answer with a machine-readable reason — so it can proceed, escalate, or fail fast.

Trade-promotion spend is one of the largest, least centrally controlled cost lines in FMCG, with thousands of discretionary discount decisions made quarterly under thresholds that are easy to state and easy to drift from — and AI RGM agents are now acting inside that process. It is precisely the environment ARF was built to govern, and the natural PoC.

## Solution

Add an **Authority Resolution** feature (navigation entry next to Entitlements) whose list and detail views behave like Data Contracts / Data Products: browse existing Authority Relations, open one for a detailed view. The feature is delivered as one net-new capability stack layered on Ontos primitives that already exist.

**Author the rule.** A user creates an **AR Definition** with the ARF tuple (Actor role + holder, Action from the controlled vocabulary, Object bound to a Data Product/Contract with cross-domain `resolvesTo` anchors, Domain-Context with its evaluable threshold, Justification-Chain as a versioned policy-document reference). This creates a **Draft** entity. The AR is assigned to one or more Data Domains (reusing the existing multi-domain model), and its stakeholders are named on the AR itself.

**Bind evidence and measure.** The author links **Evidence Sources** to the AR — in v1, a Unity Catalog Delta table plus a column→element mapping that tells Ontos which columns are the documented approver, the actual approver, the action, the object id, the decision value, the threshold reference, the timestamp, and the outcome. A **"Request DNAco computation"** action (mirroring the Data Contract "Request…" affordances) runs the DNA-Coefficient engine over the mapped evidence and produces the aggregate divergence score + direction, persisting per-row AR Decisions as the sample.

**Affirm.** The author routes an **AR review** to the AR's stakeholders — **N approvers, each with a role** (default three: Business / Technical / Governance; customer-tunable), modelled on Teams. The review is triggered as a workflow that routes each stakeholder into a **role-specific review editor** (a business affirmer answers a questionnaire; a technical affirmer sees the raw AR); each affirmation is a distinct check (Business: the documented half is current; Technical: the evidence is complete and unaltered; Governance: the intended use is proportionate). The DNAco becomes *valid-for-use* only when every defined affirmation is complete.

**Activate.** When `DNAco ≤ configured maximum` **and** the AR is fully affirmed, the owner requests a status change to **Active**. Changes to an Active AR trigger a fresh DNAco computation; an optional **schedule** recomputes it via a background job; a Compliance Check can auto-flip an AR to **Needs Review** (disabling it) on drift.

**Resolve decisions.** Once Active, an AR is callable. An agent invokes the **`ResolveAuthority` MCP tool** with an explicit **AR ID** plus the request parameters; Ontos loads the Active AR, evaluates the parameters **deterministically** against its `decisionLogic`, and returns **approved / denied** with machine-readable reasoning — or, if no matching Active AR exists, a distinct **"no authority to answer"** result so the agent can defer rather than assume. The same resolution is available to Ontos-native approval flows through the workflow engine.

**Audit and improve.** The detail view surfaces the current DNAco (as a data-quality-style summary), the derived maturity level, and metric tiles (how often the AR was used, how often it returned approved vs. denied); the list view carries the same as badges. Metadata, Tags, and Comments hang off the AR polymorphically — Comments doubling as the **timeline** that captures every change, affirmation, and DNAco computation result. **Ask Ontos** guides a user toward raising a poor DNAco (which reviews to complete, which evidence to bind).

**Reuse, honestly.** The RDF store, Compliance DSL, audit log, MCP server + tool registry, review-workflow scaffolding, multi-domain model, and the polymorphic Metadata/Tags/Comments stacks are reused unchanged. The net-new work is the AR entities, the DNAco engine, the evidence binding, the N-functional affirmation gate, the `ResolveAuthority` tool, and the front-end feature — plus the honest caveat that the affirmation gate is a real build (asset reviews are single-reviewer today; multi-approver machinery exists only in Data Contracts as first/second approver strings). See [Implementation Decisions](#implementation-decisions).

## User Stories

### Authoring an Authority Relation

1. As a Governance owner, I want to create an Authority Relation with the ARF tuple (Actor, Action, Object, Domain-Context, Justification-Chain), so that a decision's authority is explicit and inspectable rather than tacit.
2. As an AR author, I want to bind the Object to an existing Data Product or Data Contract (with cross-domain `resolvesTo` anchors), so that the entity the decision acts on resolves consistently across the business, process, and machine domains.
3. As an AR author, I want the Domain-Context to carry an evaluable threshold (e.g., 10% in EUR for EMEA-North), so that the rule can be applied deterministically at runtime.
4. As an AR author, I want the Justification-Chain to reference a versioned policy document with its provenance (`prov:wasDerivedFrom`), so that a reviewer or agent can walk backward to *why* the authority is valid.
5. As an AR author, I want to name the AR's stakeholders (principals or groups), each with the role they play, so that the review routes to the right people without depending on an org chart Ontos does not have.
6. As an AR author, I want a new AR to start in **Draft**, so that it cannot be used for decisions before it is measured and affirmed.
7. As a Data Steward, I want to assign the AR to one or more Data Domains with one primary, so that it is discoverable and scoped like every other governed entity.

### Evidence and the DNA-Coefficient

8. As an AR author, I want to link an Evidence Source (a Unity Catalog Delta table) with a column→element mapping, so that the AR can be compared against the actual decisions recorded there.
9. As a Governance owner, I want to request a DNAco computation, so that I get a divergence score (0.0 = documented matches lived practice) and a direction (actual exceeds / is exceeded by documented).
10. As a Governance owner, I want the DNAco to surface the *hidden* divergences a policy-only check misses — an actual approver who is not the documented role-holder, a threshold breached without the required escalation, a missing co-sign — so that soft authority drift becomes visible.
11. As an auditor, I want each computation to persist the per-row AR Decisions it sampled, so that the score can be independently checked and peer-reviewed rather than trusted as an opaque number.
12. As an admin, I want the DNAco scoring configuration to be tunable (and per-Domain), so that different business areas can weight divergence to their own risk posture.
13. As an auditor, I want the direction of divergence displayed alongside the magnitude, so that I know whether real authority sits above or below what is documented.

### Review and affirmation

14. As an AR author, I want to route an AR review to its stakeholders as a workflow, so that affirmation is a structured governance act, not an email thread.
15. As a business stakeholder, I want a questionnaire-style review editor that confirms the documented policy is current (not stale/superseded), so that I affirm the part I am positioned to judge.
16. As a technical stakeholder, I want a review editor showing the raw AR and its evidence binding, so that I can confirm the evidence is complete and unaltered.
17. As a governance stakeholder, I want to confirm the intended *use* of the DNAco is proportionate to the stakes, so that the score does not itself create a new unreviewed concentration of authority.
18. As a Governance owner, I want the DNAco to be treated as valid-for-use only once every defined affirmation is complete, so that an unaffirmed score can never configure an agent.
19. As an admin, I want the number and roles of affirmers to be configurable (one, three, five), so that the gate matches a customer's governance model rather than a fixed trio.

### Lifecycle

20. As an AR owner, I want to promote an AR to **Active** only when `DNAco ≤ maximum` and it is fully affirmed, so that only trustworthy rules can decide.
21. As an AR owner, I want changes to an Active AR to trigger a fresh DNAco computation, so that the score never lags the rule.
22. As an admin, I want to schedule periodic DNAco recomputation via a background job, so that drift is caught without manual re-runs.
23. As a Governance owner, I want an AR to be auto-flipped to **Needs Review** (and disabled) when a Compliance Check detects drift, so that a decayed rule stops making decisions until it is re-affirmed.
24. As an auditor, I want the AR's maturity level (L0–L5) shown as a derived attribute, so that I can see how far it has progressed independently of its operational status.
25. As an auditor, I want each AR to be versioned and each AR Decision to record the version that decided it, so that any past decision is reproducible against the rule as it then stood.

### Agentic runtime (MCP)

26. As an AI promotion agent, I want to call `ResolveAuthority` with an explicit AR ID and my request parameters and get a deterministic approved/denied verdict with a reason, so that I can proceed, escalate, or fail fast before a write-capable action.
27. As an AI agent, I want a distinct "no authority to answer" result when no matching Active AR exists, so that I defer to a human rather than assume permission.
28. As a platform engineer, I want the runtime verdict to be pure deterministic evaluation of request parameters against the AR's `decisionLogic` (not a fresh DNAco computation), so that a live decision is fast and reproducible.
29. As a governance architect, I want the future option to resolve a *chain* of ARs as a boolean expression documented now, so that composite authority checks have a designed path even though v1 evaluates a single AR.

### Discovery, metrics, and assistance

30. As a Data Consumer, I want to browse and filter Authority Relations by domain (primary or additional), so that I can find the rules governing an area.
31. As a Governance owner, I want detail-view tiles showing usage count and approved/denied counts, and list-view badges for DNAco and status, so that I can assess an AR at a glance.
32. As an AR owner, I want a timeline (via Comments) capturing every change, affirmation, and DNAco result, so that the AR's history is one auditable record.
33. As an AR owner, I want to test an AR against sample parameters in the detail view and browse its historical evidence, so that I can validate behaviour before and after activation.
34. As an AR author, I want Ask Ontos to suggest how to raise a poor DNAco (which reviews to complete, which evidence to bind), so that improving a rule is guided rather than guesswork.

## Implementation Decisions

Paths are relative to the backend root (`src/backend/src/…`) and frontend root (`src/frontend/src/…`). The three-layer `db_models` → `repositories` → `controller` (manager) pattern is followed throughout, matching the rest of the codebase.

### Modules touched (net-new unless noted)

- **DB models**: `db_models/authority_relations.py` (the AR Definition), `db_models/authority_decisions.py` (per-evaluation/per-evidence-row records), and DNAco run/result tables modelled on `db_models/compliance.py`'s `ComplianceRunDb`/`ComplianceResultDb`. Reuse `db_models/rdf_triples.py` for AR JSON-LD + PROV justification triples, `db_models/domain_associations.py` for domain assignment, and the polymorphic Metadata/Tags/Comments tables.
- **Repositories**: `repositories/authority_relations_repository.py`, `repositories/authority_decisions_repository.py`, both on `CRUDBase`. Reuse `repositories/rdf_triples_repository.py` and `entity_domain_repo` (`repositories/entity_domain_association_repository.py`).
- **Managers**: `controller/authority_manager.py` — authoring, evidence binding, DNAco orchestration, affirmation-gate state, lifecycle transitions, and the runtime resolution used by both MCP and Ontos-native flows.
- **Workflow**: `workflows/authority_resolution/` for asynchronous DNAco computation, modelled on `workflows/compliance_checks/` (queued → running → succeeded/failed with results). The **scheduled recompute** is a new background job wired into the same pattern.
- **MCP tool**: `tools/authority.py` implementing the `BaseTool`/`ToolContext`/`ToolResult` contract from `tools/base.py`, registered in `tools/registry.py`, exposed via `routes/mcp_routes.py` (JSON-RPC 2.0 + SSE) and scoped through `controller/mcp_tokens_manager.py`, exactly like the ~48 existing tools.
- **Routes**: `routes/authority_routes.py` for CRUD, evidence binding, DNAco request, affirmation routing, lifecycle transitions, test-an-AR, and history — under a new `authority-resolution` feature permission.
- **Migrations**: new Alembic revisions under `alembic/versions/` following the single-head short-revision convention (see `.cursor/rules/11-database-migrations.mdc`).
- **Frontend**: `views/authority-resolution/` (list + detail), reusing the Data Contract/Product view shells, the `<DomainMultiSelector>` component, the metric-tile pattern from `views/home.tsx`, and the Metadata/Tags/Comments panels per the entity-panel matrix.

### AR Definition vs. AR Decision

- `authority_relations` holds the **Definition**: the ARF tuple fields, `status` (`Draft`/`Active`/`Needs-Review`/`Retired`), the evidence binding, the compiled `decisionLogic`, the stakeholder/affirmation set, `version_family_id` (versioned like Data Contracts), the aggregate `dnaCoefficient` (magnitude + direction + `measuredAt`), and the derived `maturityLevel`.
- `authority_decisions` holds one row per runtime evaluation or per sampled evidence row: the JSON-LD `ar-instance` shape, its own `divergenceMagnitude` + `direction`, the verdict, the request parameters, the timestamp, and — critically — the **AR Definition version** that produced it. The Definition's aggregate DNAco is a rollup over these.
- The canonical AR JSON-LD (Actor/Action/Object/Domain-Context/Justification-Chain/DNA-Coefficient with `arf:`/`prov:` predicates) is persisted as triples in `rdf_triples` and served/exported via a JSON-LD adapter; the relational tables carry the operational fields and indexes.

### DNA-Coefficient engine (v1)

- **Polarity is fixed by the ARF paper**: a divergence, `0.0 = exact correspondence`, higher = worse, with a `direction` flag (`actual-exceeds-documented` / `documented-exceeds-actual`). Stored verbatim as `divergenceMagnitude`; the activation gate is a **ceiling** (`magnitude ≤ configured maximum`). The UI presents it as a data-quality-style summary (lower is better, like a defect rate) — no inversion in storage.
- **v1 instrument is decision-log divergence only.** For each evidence row mapped to the AR, flag divergence when the actual approver ≠ the documented role/holder, the Domain-Context threshold was breached without the required escalation, or a required co-sign is absent. `DNAco = fraction of sampled decisions that diverge` (∈ [0,1]); `direction` = the sign of the aggregate authority-level delta.
- **The composite is Ontos-authored net-new IP** (the paper ships no computable formula). Organizational Network Analysis and structured-elicitation instruments are deferred composite terms. The scoring configuration is admin-tunable and keyed by the AR's **primary domain**. This is a named [dependency on Parviz](#further-notes).

### Evidence binding (v1)

- A per-AR binding: `{ source_table_fqn, column_map, row_filter? }`, where `column_map` maps evidence columns to AR decision elements (documented approver, actual approver, action, object id, decision value, threshold reference, timestamp, outcome). Source is a **Unity Catalog Delta table**.
- No Excel/volume/remote-endpoint adapters in v1. Demo/test data is a general-purpose demo-data concern, not part of this feature's engine.

### decisionLogic and the MCP contract

- `decisionLogic` is a structured, machine-evaluable rule compiled from the AR fields at authoring time: allowed principal(s) match, Domain-Context predicate (threshold + currency + market), required affirmations present, `status == Active`. **Soft knowledge is captured during authoring/affirmation and compiled into this rule; runtime is deterministic** — the JSON-LD carries evaluable predicates, not prose.
- `ResolveAuthority(ar_id, request_params)` loads the Active AR by explicit id, evaluates `request_params` against `decisionLogic`, and returns `approved | denied` (+ machine-readable reason) or a distinct `no_authority` sentinel when the AR is absent/inactive. **The runtime does not consult the DNAco** — DNAco gates *activation*, not the per-decision verdict.
- **Selection is by explicit AR ID in v1.** Matching a *chain* of ARs and evaluating it as a boolean expression is documented as a future, not built.

### Affirmation gate

- Stakeholders are defined **on the AR** as **N members, each with a role**, modelled on the Teams member/role structure (`db_models/teams.py`); members may be a principal *or* a group. The default set is the ARF trio (Business/Technical/Governance) but the count/roles are configurable.
- The review is routed via the workflow engine into **role-specific review editors** (reusing and extending the `data_asset_reviews` scaffolding — note this is a genuine build, since asset reviews are single-reviewer today; the multi-approver pattern in Data Contracts covers only first/second approver strings). Affirmations run in parallel (independent checks) unless the author specifies an order.
- The gate is a **validity gate on the DNAco**: an AR cannot reach Active until `DNAco ≤ max` **and** every defined affirmation is complete. This maps ARF's `arf:affirmedBy` onto Ontos approval machinery.

### Domain assignment (reused)

- Multi-domain via `entity_domain_associations` with `entity_type = "authority_relation"`, exactly mirroring Teams/Contracts/Products/Assets: write `domain_ids` + `primary_domain_id`; read `domains: List[AssignedDomain]`; filter via `entity_domain_repo.find_entity_ids_by_domains(...)` (any-of); reuse `<DomainMultiSelector>` in the forms and `DomainExportAdapter` for the JSON-LD/UC export conventions. Exactly one primary; the primary keys the per-domain DNAco scoring config.

### Lifecycle, status, and maturity

- Operational `status`: `Draft → Active → Needs-Review → (Retired)`. `maturityLevel` (L0–L5) is **derived and displayed**, not editable.
- **Auto Needs-Review**: a Compliance Check (scheduled, or on recompute exceeding the max / evidence drift) flips Active → Needs-Review and disables the AR until re-affirmed — reusing `controller/compliance_manager.py` and the compliance DSL as the complemental trigger (AR is a net-new feature *supported by* compliance checks, not a compliance-DSL feature).

### Cross-cutting

- Polymorphic **Metadata, Tags, Comments** attach with `entity_type = "authority_relation"`; **Comments is the timeline**, receiving system entries for every change, affirmation, and DNAco result.
- **Metrics**: usage count and approved/denied counts aggregate `authority_decisions`; rendered as detail-view tiles (per `views/home.tsx`) and list-view badges alongside DNAco and status.
- **Ask Ontos** integration guides DNAco improvement, reusing the existing assistant surface.

## Testing Decisions

Tests exercise external behaviour through the manager/route/tool surface and assert on observable outcomes (returned payloads, DB rows, RDF triples, audit + timeline entries), never on internal SQL.

- **DNAco engine** (manager-level): seed a mapped Delta-table fixture with deliberately planted divergences (actual approver ≠ documented, threshold breach without escalation, missing co-sign) and clean rows; assert the magnitude equals the diverging fraction, the direction is correct, and one AR Decision is persisted per sampled row. Assert per-domain scoring config changes the score deterministically.
- **Affirmation gate** (route + manager): an AR cannot go Active while any affirmation is outstanding or `DNAco > max`; each affirmation writes an audit entry and a timeline entry; the configurable N (one, three, five) is honoured; group-vs-principal routing resolves correctly.
- **MCP `ResolveAuthority`** (tool-level): an Active AR returns `approved`/`denied` deterministically for matching/mismatching request params; an absent or non-Active AR returns the `no_authority` sentinel; the runtime performs no DNAco computation (assert the engine is not invoked); the verdict carries a machine-readable reason.
- **Versioning/reproducibility**: editing an Active AR bumps the version and triggers recompute; an AR Decision records the deciding version; re-evaluating a historical decision against its recorded version reproduces the verdict.
- **Lifecycle**: change → recompute → Needs-Review auto-flip disables the AR from MCP resolution; re-affirmation restores it.
- **Domain association** (per the multi-domain prior art): create with `domain_ids` + `primary_domain_id`, filter any-of, GET returns the full set, deletion-block when the AR holds a domain as primary.
- **Frontend** (component-level): list badges (DNAco/status), detail tiles (usage/approved/denied), the role-specific review editors, and the evidence-binding form. Prior art: existing Data Contract/Product view and `use-domains` tests.
- **One e2e**: author an AR → bind a seeded evidence table → compute DNAco → complete all affirmations → activate → resolve a decision via MCP → verify the timeline captured each step.
- **Deliberately not tested**: the exact DNAco composite math beyond the diverging-fraction contract (it is expected to change under Parviz's review); no SQL/JSON-shape snapshots beyond the contract surface.

## Out of Scope

- **Organizational Network Analysis and automated structured-elicitation instruments** — deferred composite terms of the DNAco; v1 uses decision-log divergence only.
- **Stale-role *validation*** — detecting that a signer's real-world role changed needs org/HR data Ontos does not hold. `arf:actor.heldBy`/`since` are authored metadata for now; live validation is a maturity-path follow-up.
- **Evidence adapters beyond a Delta table** — Excel-in-volumes, arbitrary tables/views, and remote endpoints are later adapters.
- **AR chains as boolean expressions** — v1 resolves a single AR by explicit id; chains are a documented future.
- **Runtime DNAco gating** — DNAco gates activation, not per-decision verdicts.
- **The Real-World domain / operational-state resolution and L5 Agent-Design-Authority auditing** — beyond the L3/L4 PoC target.
- **Demo/synthetic decision data** — handled by the general demo-data mechanism, not this feature.
- **Replacing Ontos RBAC.** AR authority is business authority expressed via principals; `app_roles` continues to govern who may use Ontos itself.

## Further Notes

- **The DNAco composite is our net-new IP and a Parviz dependency.** The paper defines the DNA-Coefficient qualitatively (a "normalized composite of the three instruments," proposed and unvalidated) and ships no formula. The v1 diverging-fraction scoring is a defensible starting point; the PoC is expected to refine it, and this PRD will iterate accordingly. Nothing downstream should hard-code the composite beyond the diverging-fraction contract the tests pin.
- **Polarity reconciliation.** Early planning drafts described DNAco "like data quality" (higher = better); the paper and the canonical JSON-LD are unambiguous that it is a *divergence* (`0.0` best, higher worse) with a direction. We store the divergence and gate on a ceiling; only the UI framing (lower is better) is a presentation choice.
- **The MCP gate is not a security boundary.** ARF assumes a trusted substrate; a poisoned MCP server or a dishonest agent defeats it. `ResolveAuthority` is a governance gate that produces an auditable, affirmed decision — not an enforcement mechanism against a hostile caller. The paper is explicit about this and so are we.
- **Relationship to the Compliance DSL.** AR is a net-new feature *supported by* compliance checks, not built into the DSL. An "AR inference" can be one DSL-triggerable check (e.g., the auto Needs-Review trigger), but the Compliance DSL remains complemental — it is the baseline policy-only layer the DNAco is measured *against*, not the DNAco itself.
- **Relationship to approval workflows.** The affirmation gate reuses and extends the review/approval machinery (`data_asset_reviews`, the process workflow engine; see `docs/prds/prd-approval-workflows-v2.md` and `docs/decisions/approval-workflows-v1-scope.md`). The honest delta: asset reviews are single-reviewer today, so the N-functional, role-specific affirmation is a real build, not a free reuse.
- **PoC framing.** This PRD is the basis of a PoC (the trade-promotion / CCHBC scenario) aimed at Maturity **L3** (one measured DNAco), arguably **L4** if the affirmation gate is honoured on the result. The PoC's purpose is partly to determine what supporting structures Ontos still lacks; expect iterations on this document as it runs.
- **Companion plan.** If an implementation plan is written, it belongs at `docs/plans/authority-resolution.md` (title-based mapping, matching the plan/PRD convention). This PRD is the source of truth for *what* and *why*; the plan owns *how*.
