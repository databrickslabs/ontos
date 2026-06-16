# Ask Ontos and the MCP Server

Ontos exposes its tool catalog through two surfaces — the **in-product
copilot** and an **MCP server endpoint**. They share the same underlying
tools but are accessed by different clients with different rules. Most
customer questions conflate the two; this doc separates them.

## Ask Ontos — the in-product copilot {#what-is-ask-ontos}

Ask Ontos is the chat panel you can open from any page. It's a slim LLM
client that lets a logged-in user ask natural-language questions, run
small admin actions where they're allowed, and search the catalog without
having to navigate to the right page first.

It is meant to feel like talking to a co-worker who knows the platform
well — the user can ask "show me products in my domain that have no
contract yet" or "what does the `arr_usd` column on the daily-revenue
contract mean?" and get a grounded answer.

### What grounds it {#grounding-sources}

Two complementary sources keep Ask Ontos honest:

- **This handbook corpus.** Conceptual questions (lifecycle states,
  permissions, what a Deliverable is) ground against the docs in
  `docs/handbook/` — the same files this one belongs to. The retrieval
  layer finds anchor-tagged sections and gives the model citable
  fragments. If a question can't be grounded, the assistant should
  decline rather than guess.
- **The tool registry.** Live data (counts, names, IDs, statuses) comes
  from calling tools — same tools the MCP server exposes. The
  assistant doesn't compose database numbers from the prompt; it asks
  the tool and reports back.

The discipline matters: a copilot that hallucinates lifecycle states or
permission rules erodes trust faster than one that says "I'm not sure".

### Tools it has access to {#tool-categories}

The full registry is the source of truth (over forty tools at last
count); a high-level grouping helps:

- **Search & discovery** — full-text search across products, contracts,
  glossary, reviews; semantic-link lookup; concept browsing.
- **Data product CRUD** — read product details, list deliverables, walk
  consumer principals.
- **Data contract CRUD** — fetch schemas, quality definitions, version
  history.
- **Semantic models** — list concepts, query SPARQL, neighbours, add /
  remove semantic links.
- **Tagging** — list tags, list assignments, assign/remove (subject to
  permission).
- **Analytics queries** — basic counts and lifecycle breakdowns for
  dashboard surfaces.
- **Workflows** — list workflow definitions, look up executions and
  agreements.

If you need the exact list, the registry's `to_mcp_format()` returns the
canonical schema for every tool, and the in-product Settings panel
lists tools the assistant can use.

### Permissions and impersonation {#permissions}

Ask Ontos runs **as the calling user**, on-behalf-of. It has exactly the
authority the logged-in caller already has — no more. A Data Consumer
asking it to publish a data product will get the same `403` they'd get
if they hit the publish endpoint directly.

This is the right default: the assistant is a productivity layer, not a
permission-escalation path. If a user can't do an action manually, the
assistant declines and explains why. See
[Roles and RBAC](roles-and-rbac.md#permission-model).

### Personalization {#personalization}

In the current Ontos version, the assistant adapts to two pieces of
caller context: the user's role (so an admin sees admin-specific
suggestions where a consumer sees marketplace-discovery suggestions),
and the page the user is on (so an answer on a contract detail page is
scoped to that contract). Deeper personalization — mode-aware starter
prompts, page-specific tool selection — is evolving.

### What it deliberately won't do {#wont-do}

- Run write queries against UC data tables. Read-only by default.
- Delete data products, contracts, or other governed entities through
  the chat surface, even when the caller has Admin. Destructive
  operations require the explicit UI confirmation flow.
- Operate outside Ontos — no Slack messaging, no email composition, no
  Git pushes initiated by the assistant. Those live in other layers.
- Bypass the citation discipline. If a conceptual claim can't be
  anchored against the corpus or a tool result, the assistant should
  decline.

Hallucination risk is real and persistent on this kind of surface. The
mitigation is grounding plus a refusal default — when a query can't be
satisfied with confidence, the right behavior is "I don't know" rather
than a fabricated answer.

## MCP Server — Ontos as a tool catalog for external agents {#mcp-server}

Separately from the in-product copilot, Ontos exposes a **Model Context
Protocol** (MCP) server at `/api/mcp`. This is a JSON-RPC 2.0 endpoint
that external clients — Claude Code, Cursor, custom agent frameworks —
can connect to. The server publishes the same tool catalog Ask Ontos
uses, but with a different authentication scheme and a different
permission model.

### Why two surfaces {#two-surfaces}

The in-product copilot is convenient for an authenticated user who's
already in Ontos. The MCP server is for cases where an agent running
*outside* Ontos needs to read or act on Ontos's data — a Claude Code
session helping a data engineer write a transformation, a custom agent
generating documentation, a Cursor IDE pulling product metadata into
the editor.

Same tool registry, different transport, different authentication:

| | Ask Ontos (in-product) | MCP Server (`/api/mcp`) |
|---|---|---|
| **Caller** | A logged-in Ontos user | An external agent / IDE |
| **Auth** | Browser session + OBO | MCP token (DB-stored, scope-tagged) |
| **Acts as** | The logged-in user (OBO) | The token's bound principal |
| **Permissions** | Inherits the caller's Ontos role | Constrained by the token's scopes |
| **Transport** | App UI calls backend | JSON-RPC 2.0 over HTTP (with SSE option) |

### Tokens and scopes {#mcp-tokens}

External clients authenticate with a token — created from Settings → MCP
Tokens, shown once on creation, then hashed in the DB. Each token
carries a list of scopes (`data-products:read`, `sparql:query`, etc.)
that further restrict what tools it can call. A token with no scope for
a tool can't invoke it even if the bound user has the Ontos permission.

Admins manage the token store. The MCP feature is gated separately from
ordinary settings access — a user with `settings:READ_WRITE` does not
implicitly get MCP token management.

### What MCP exposes {#mcp-exposes}

The same tool catalog as Ask Ontos, surfaced through the MCP protocol's
`tools/list` and `tools/call` methods. Each tool's input schema is the
canonical JSON-schema definition from `tool.to_mcp_format()`. The MCP
endpoint also implements the protocol's `initialize`, `ping`, and
notification semantics; SSE transport is available for streaming agent
sessions.

### What MCP isn't {#mcp-isnt}

The Ontos MCP server is a *server* (it exposes Ontos's tools so
external agents can call them). It is **not** a *client* of other MCP
servers. Ontos does not currently consume third-party MCP catalogs at
runtime to ground its own answers; for that, the in-product copilot
relies on its concept corpus and tool registry as described above.

## Cross-references {#cross-references}

- [Roles and RBAC — permission model](roles-and-rbac.md#permission-model)
- [Semantic Link — what the assistant reads when answering a "what does this column mean?" question](ontology-and-knowledge-graph.md#three-tier-linking)
- [Personas — what each role typically asks](personas-quick-reference.md)

## Common questions {#common-questions}

**"Can Ask Ontos delete a data product or revoke someone's access?"**

Destructive actions are gated. The assistant won't run a delete or a
revoke from the chat surface even when the caller has Admin permission
— those actions require the explicit confirmation flow in the UI. Read
operations, lifecycle promotions with the caller's normal permissions,
and small CRUD operations are in scope.

**"Why did it refuse to answer a question I think it should know?"**

Two common reasons: (1) the conceptual claim couldn't be anchored
against the corpus, and the assistant is configured to decline rather
than guess; (2) the caller doesn't have the permission to read the
underlying data — the assistant won't surface a number the caller
couldn't see directly. Both are intentional. If a refusal feels wrong,
check the user's role and the corpus coverage for the topic.

**"Is Ask Ontos calling my own LLM provider or a Databricks-hosted
model?"**

Either, depending on configuration. The model and endpoint live in
Settings → LLM and can point at a Databricks Foundation Model serving
endpoint, an external provider, or a custom deployment. The
configuration is Admin-controlled; the assistant doesn't expose the
endpoint to end users.

**"Can my Claude Code session in the IDE use Ontos's tools?"**

Yes — that's what the MCP server is for. Create an MCP token in
Settings → MCP Tokens with the scopes your session needs, register the
Ontos MCP endpoint in your client's config, and your IDE agent will see
the same tools Ask Ontos uses.

**"If I create an MCP token, does that token bypass Ontos permissions?"**

No. The token is bound to a principal, and the principal's Ontos
permissions still apply. The token's scopes are an *additional* restrict
— they narrow what the token can do, never widen it.

_Last verified against codebase: 2026-05-28_
