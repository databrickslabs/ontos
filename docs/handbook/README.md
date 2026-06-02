# Ontos Handbook (LLM Grounding Corpus)

These documents are **internal grounding material for the Ask Ontos copilot**,
not user-facing product documentation. They define the canonical vocabulary,
role model, lifecycle states, ontology stack, data-quality model, and
end-to-end flows of Ontos so that a retrieval tool (`search_ontos_handbook`,
grep-style match) can return citable text fragments to the LLM at answer
time.

Naming note: this corpus used to be called "concepts", but "Concept" is
already an Ontos ontology entity (an RDFS class / SKOS concept in the
knowledge graph). To avoid overloading the noun in code, API surface,
and docs, the LLM-grounding markdown corpus is "handbook".

## How to read this corpus {#how-to-read}

If you are new to Ontos, start with
[end-to-end-flows.md](end-to-end-flows.md) — it walks the bottom-up and
top-down flows that the rest of the corpus elaborates. Then read the
[entities-glossary.md](entities-glossary.md) as a one-paragraph map of
every first-class thing. Then read whichever lifecycle / domain doc your
task touches. Citation discipline is required (see below) — if the
copilot can't anchor a claim to an anchor in this corpus, it should
refuse to answer rather than hallucinate.

## Scope {#scope}

In scope:

- Conceptual definitions of every first-class entity (data product,
  contract, domain, agreement, workflow execution, concept, semantic
  link, quality check, etc.)
- Role catalog, permission model, identity resolution, demo-mode override
- Status state machines for data products, contracts, agreements, and
  workflow executions
- Ontology + knowledge graph + glossary distinctions
- Data quality model — definitions, measurements, rollups, DQX
  integration
- End-to-end flows — bottom-up (UC → curated catalog) and top-down
  (ontology → physical assets)
- Customer-voice "common questions" sections, role-targeted persona
  framings

Out of scope:

- API reference (use the FastAPI `/docs` endpoint)
- File / line implementation citations (these live in
  `docs/architecture/` if needed)
- Tutorials, marketing material, customer playbooks

## Citation discipline {#citation-discipline}

When the copilot answers a conceptual question, it attaches a citation of
the form `[ref: <file>.md#<anchor>]` to the relevant claim. In v1 these
citations are **internal-only** — they are stripped from the
user-facing response. They exist so reviewers can audit grounding
quality and so the citation contract is ready when we expose them in
v2.

Authoring rules for citation-ready sections:

1. Every concept worth citing has an explicit HTML anchor:
   `## Thing {#thing}`.
2. Anchor names are kebab-case derived from the section heading.
3. Cross-references between docs use relative anchored links:
   `[Output Port](data-contract-lifecycle.md#output-port)`.
4. Each file ends with a verification footer
   (`_Last verified against codebase: YYYY-MM-DD_`).

## Adding a new concept doc {#adding-a-doc}

1. Pick a single subject (a role, a lifecycle, an entity family, a
   cross-cutting concern). Keep each file under ~3.5 pages.
2. Add anchors for every concept the LLM might be asked about — not
   every paragraph, but every nameable thing. Aim for 10–20 anchors per
   file.
3. Ground claims in source (managers, db models, enums). Mark anything
   in flux as "in the current Ontos version" or "evolving".
4. Include a Common Questions section if the doc covers something
   customers ask about repeatedly.
5. Update the file list below.
6. Re-verify and bump the verification footer.

## Current corpus {#current-corpus}

| File | Subject |
|---|---|
| [roles-and-rbac.md](roles-and-rbac.md) | Permission model (feature × access level), built-in roles, identity resolution, demo-mode override, per-execution authz, Ontos-admin vs workspace-admin |
| [data-product-lifecycle.md](data-product-lifecycle.md) | ODPS data product states, deliverables, consumables, delivery methods, consumer principals, version family, common questions |
| [data-contract-lifecycle.md](data-contract-lifecycle.md) | ODCS v3.1.0 contract states, schema, quality definitions, editor-of-record framing, contracts-first vs products-first, version family, common questions |
| [agreement-workflow.md](agreement-workflow.md) | Approval workflow runtime, agreement vs execution vs wizard session, approval gates, grant_permissions, webhook extras, common questions |
| [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md) | Ontology, knowledge graph, semantic links, glossary, three-tier linking, runtime graph, SPARQL, round-trip current state, common questions |
| [asset-model.md](asset-model.md) | One-pager: unified Asset entity, ontology-driven AssetType, AssetTypeCategory, entity relationships, asset reviews |
| [delivery-and-propagation.md](delivery-and-propagation.md) | Delivery Method vs Delivery Mode, Direct/Indirect/Manual modes, change-type taxonomy, concept→UC tag flow, integration with grant_permissions, common questions |
| [mcp-and-ask-ontos.md](mcp-and-ask-ontos.md) | In-product Ask Ontos copilot (grounding, permissions, refusals) vs the external MCP server (tokens, scopes, JSON-RPC), common questions |
| [data-quality.md](data-quality.md) | ODCS quality definitions, per-entity quality items, DQX end-to-end flow, source enums, surfacing, common questions |
| [end-to-end-flows.md](end-to-end-flows.md) | Bottom-up flow (UC → product → contract → concept), top-down flow (ontology → assets → tags), where they meet, common questions |
| [entities-glossary.md](entities-glossary.md) | One-paragraph definitions of every first-class entity |
| [installation-and-troubleshooting.md](installation-and-troubleshooting.md) | Distribution channels (Marketplace vs Git), first-install prerequisites, update workflow, alembic discipline, common UI errors users hit (request-role prompt, 403s, scope-missing, grant_permissions, sync layout), common questions |
| [personas-quick-reference.md](personas-quick-reference.md) | Plain-language persona framings, pages they touch, what they ask Ask Ontos |

_Last verified against codebase: 2026-05-29_
