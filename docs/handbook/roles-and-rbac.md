# Roles and RBAC

Ontos authorization has two layers that get easily conflated. The **permission
model** says "what is this user allowed to do in this feature?" — it's a
matrix of feature × access level. The **role catalog** says "what bundle of
permissions does this named role carry?" — Admin, Data Steward, Data
Producer, etc. Roles map users (via Databricks groups) to permission rows.

Customers asking about permissions usually want to know one of three things:
"why can't I see X?", "why can someone else edit Y?", or "what does the new
person need to be able to do?". This doc is structured so you can answer all
three.

## The permission model {#permission-model}

A **permission** in Ontos is a `feature_id : access_level` pair. The set of
features (the `APP_FEATURES` map) is the source of truth; each feature
declares which access levels are valid for it.

### Access levels {#access-levels}

`FeatureAccessLevel` defines six levels in ascending order:

| Level | Meaning |
|---|---|
| `None` | No access. Feature is hidden in the UI; API returns 403. |
| `Read-only` | Can view, cannot modify. |
| `Filtered` | Read/Write restricted to a subset (typically by domain). Higher than `Read-only`, lower than `Read/Write`. In the current Ontos version, only the data-products feature implements `Filtered` scoping; other features that list `Filtered` as allowed treat it as `Read/Write` until scoping is wired. |
| `Read/Write` | Can view and modify within the feature. |
| `Full` | All operations within the feature scope, may include feature-level configuration. Used by Catalog Commander and Estate Manager. |
| `Admin` | Everything `Full` does, plus administrative actions (delete glossary, configure feature settings). |

A given feature does not accept every level. Each feature's
`allowed_levels` list constrains what's assignable.

> Practical caveat: an individual API endpoint may apply a stricter gate
> than the feature-level access listed in the matrix below. The matrix
> describes the front-of-feature expectation; production endpoints may
> additionally check sub-permissions. If a user with the documented level
> gets a 403, trust the 403 — the endpoint enforces what it actually
> enforces, even when stricter than this table.

### Representative features and what each level does {#feature-walkthrough}

This is not the full list — `APP_FEATURES` is the source of truth — but
these are the features customers ask about most.

**`data-products`** (sidebar group: Build). `allowed_levels` includes
`None`, `Read-only`, `Filtered`, `Read/Write`, `Admin`.
- `None` — Data Products view is hidden from the sidebar; API returns
  403.
- `Read-only` — Marketplace and detail pages render, but Create / Edit /
  Status-change buttons are absent.
- `Filtered` — Edit rights apply only to products in domains the user
  owns through team membership. The implementation lives in
  DataProductsManager's authorization check.
- `Read/Write` — Standard producer access: create products, edit any
  product in your domain, propose for review, transition status up to
  active (with the appropriate workflow approvals).
- `Admin` — Add the ability to delete products and to publish even
  without going through certification.

**`data-contracts`** (Build). Same access levels as data-products minus
`Filtered`.
- `Read-only` — Can read schemas, quality checks, SLAs.
- `Read/Write` — Can draft and edit contracts, attach to output ports,
  define quality checks.
- `Admin` — Can delete contracts, override certification.

**`semantic-models`** (Build, displayed as "Concept Browser").
- `Read-only` — Browse the concept catalog and glossary terms.
- `Read/Write` — Add concepts to glossary collections, create semantic
  links, upload ontologies, run SPARQL queries.
- `Admin` — Delete glossaries, manage all semantic-model lifecycle.

**`process-workflows`** (Govern). Restricted access levels: `None`,
`Read-only`, `Admin`. Mid-tier `Read/Write` is intentionally absent.
- `Read-only` — View workflow definitions, view executions and
  agreements.
- `Admin` — Author / edit / delete workflow definitions; only Admin
  edits workflow definitions because they have UC-grant-level
  consequences via the `grant_permissions` step.

**`settings`** (Settings layout gate). Read levels gate the visibility
of the Settings sidebar; sub-pages have their own feature IDs (e.g.,
`settings-roles`, `settings-workflows`, `settings-semantic-models`).
- `Read-only` — Can see Settings and read the listed configurations.
- `Read/Write` — Can edit most settings.
- `Admin` — Plus dangerous actions: re-seeding roles, demo-data
  loading, ITSM connector edits.

**`marketplace`** (and the marketplace-style discovery features).
- `Read-only` — Browse published products.
- `Read/Write` — Subscribe / unsubscribe; submit access requests.
- `Admin` — Approve subscriptions, configure marketplace policies.

**`approvals` / `agreements` / `notifications`**.
- `Read-only` — See agreements you signed, notifications addressed to
  you.
- `Read/Write` — Approve agreements assigned to you, mark
  notifications read.
- `Admin` — See all agreements across the workspace, manage
  notification settings centrally.

If you need the full list, read `APP_FEATURES` in `common/features.py`
directly — it carries the canonical names, sidebar groups, and
allowed-levels lists for every feature including the Govern, Deploy,
and Settings groups.

### Why "what level for what feature" actually matters {#why-permissions-matter}

The level matters because the UI and API behave differently per level
in user-visible ways:

| Feature | `Read-only` means… | `Read/Write` means… |
|---|---|---|
| settings-roles | You can see role definitions and the assignment matrix. You can't change them. | You can create new roles, edit access-level grants, reassign user groups. |
| data-products | You see products in the marketplace, drill into details, see lineage. You can't create, edit, or publish. | You can create new products, edit any product (subject to domain scoping if `Filtered`), and move them through lifecycle states. |
| data-contracts | You can read schemas, quality definitions, SLAs. | You can author new contracts, add schemas and quality checks, propose for review. |
| process-workflows | You can read workflow definitions and view past executions. | (Not allowed for this feature — only `None`, `Read-only`, `Admin`.) |
| semantic-models | Browse concepts, glossary, view the graph. | Author concepts, write semantic links, upload ontologies, run SPARQL. |
| approvals | See agreements you signed, notifications addressed to you. | Approve agreements assigned to you. |

A non-obvious pattern: extending a feature to a new persona requires
auditing every endpoint's permission gate, not just the front-of-feature
gate. A wizard that's gated as `settings:READ_ONLY` at the entry point
but `data-contracts:READ_WRITE` inside an inner endpoint will 403 a
consumer-persona user mid-flow — see the
[per-execution authorization](#per-execution-authz) section.

## Built-in roles {#built-in-roles}

Ontos seeds six built-in roles on first start when no roles exist yet.
After seeding they are editable like any other role.

| Role | One-paragraph framing |
|---|---|
| [Admin](#admin) | You own the deployment. Roles, workflows, integrations, demo data, the MCP token store — when something is broken, you're the person Ontos expects to fix it. |
| [Data Governance Officer](#data-governance-officer) | You see the whole catalog. Your job is to make sure products have domains, contracts have quality checks, PII is classified, subscriptions don't outlive their products. You certify and audit; you don't build. |
| [Data Steward](#data-steward) | You curate a slice — usually a domain. You're the gatekeeper at two moments: contract approval and product certification. Outside those gates, you maintain glossary terms and triage reviews. |
| [Data Producer](#data-producer) | You build products and contracts. You spend your time on the detail pages — composing deliverables, drafting schemas, wiring quality checks. Lifecycle promotion is your day job; certification is somebody else's. |
| [Data Consumer](#data-consumer) | You find products and request access. You don't draft anything — you subscribe, sign agreements, provide feedback. |
| [Security Officer](#security-officer) | You configure security features, entitlements, access classifications. You're consulted on contract approvals involving PII or restricted data. You sign off on the security side of certification. |

### Admin {#admin}

Granted `Admin` on every feature by default, including all settings
sub-pages. The Admin role is the canonical carrier of "Ontos admin"
authority: features that require elevated authority (role overrides,
MCP token management, dangerous settings actions) check membership in
*any* role flagged as an admin role rather than treating
`settings:ADMIN` as a proxy. This separation means giving a user write
access to Settings does not implicitly turn on admin-only capabilities
elsewhere.

Group assignment for Admin is seeded from the `APP_ADMIN_DEFAULT_GROUPS`
environment variable (default: `["admins"]`). This is **only consulted
on first-time seeding** — later restarts do not re-merge env-var values
into the existing role. To add admins after first start, edit the
role's `assigned_groups` from Settings → RBAC. This catches new
deployments often enough that it has its own dedicated section in the
Ontos Setup guide.

Other seeded roles (Data Governance Officer, Data Steward, Data
Producer, Data Consumer, Security Officer) also ship with default
group bindings matching the conventional group names — see the role
definitions table below and Settings → RBAC for the live values.

### Data Governance Officer {#data-governance-officer}

Cross-cutting governance authority.

| Feature | Level |
|---|---|
| data-domains | Admin |
| data-products | Admin |
| data-contracts | Admin |
| data-catalog | Admin |
| business-glossary | Admin |
| compliance | Admin |
| estate-manager | Admin |
| master-data | Admin |
| security-features | Admin |
| entitlements | Admin |
| entitlements-sync | Admin |
| data-asset-reviews | Admin |
| catalog-commander | Full |
| process-workflows | Read-only |
| teams | Read-only |
| projects | Read-only |
| comments | Read/Write |

### Data Steward {#data-steward}

Curates domains, contracts, glossary terms; reviews assets.

| Feature | Level |
|---|---|
| data-domains | Read/Write |
| data-products | Read/Write |
| data-contracts | Read/Write |
| data-catalog | Read/Write |
| business-glossary | Read/Write |
| data-asset-reviews | Read/Write |
| compliance | Read-only |
| process-workflows | Read-only |
| catalog-commander | Read-only |
| teams | Read-only |
| projects | Read-only |
| comments | Read/Write |

### Data Producer {#data-producer}

Creates data products and contracts; manages own teams and projects.

| Feature | Level |
|---|---|
| data-products | Read/Write |
| data-contracts | Read/Write |
| teams | Read/Write |
| projects | Read/Write |
| data-domains | Read-only |
| data-catalog | Read-only |
| business-glossary | Read-only |
| catalog-commander | Read-only |
| process-workflows | Read-only |
| comments | Read/Write |

### Data Consumer {#data-consumer}

Read-only access for discovery, subscription, and commenting.

| Feature | Level |
|---|---|
| data-products | Read-only |
| data-contracts | Read-only |
| data-domains | Read-only |
| data-catalog | Read-only |
| business-glossary | Read-only |
| catalog-commander | Read-only |
| process-workflows | Read-only |
| teams | Read-only |
| projects | Read-only |
| comments | Read/Write |

### Security Officer {#security-officer}

Focused on security configuration and entitlements.

| Feature | Level |
|---|---|
| security-features | Admin |
| entitlements | Admin |
| entitlements-sync | Admin |
| compliance | Read/Write |
| process-workflows | Read-only |
| data-asset-reviews | Read-only |
| comments | Read/Write |

Features not listed for a given role default to `None`.

## Identity resolution {#identity-resolution}

When a request arrives, Ontos resolves the caller through three layers
in order:

1. **Identity provider (Entra/Okta, etc.).** Ontos never talks to the
   IdP directly. It only sees what Databricks SCIM exposes.
2. **Databricks workspace/account groups.** Resolved at request time
   via on-behalf-of SCIM lookup. Requires the `iam.current-user:read`
   scope to be declared in the app manifest. Workspace-only groups do
   **not** appear via the OBO `current_user.me()` path; use
   account-level groups for role assignment.
3. **Ontos roles.** A role is a DB row whose `assigned_groups` is a
   list of strings. The matcher is a case-insensitive set intersection
   between the user's resolved groups and each role's
   `assigned_groups`. When multiple roles match, the role with the
   highest summed access-level weight wins.

### Workspace-admin shortcut {#workspace-admin-shortcut}

The `is_user_admin` helper checks membership in
`APP_ADMIN_DEFAULT_GROUPS` (default `["admins"]`). This bypass runs
**independently of the Ontos role system** — a workspace admin is
treated as admin for cascade-bypass checks even if they hold no Ontos
role.

A complementary predicate — the **Ontos-admin** check — resolves
"admin" through the role catalog: a user is an Ontos admin if their
resolved groups intersect the `assigned_groups` of any role flagged
as an admin role. Sensitive endpoints (role overrides, MCP token
management, role-catalog reads) increasingly consult this Ontos-admin
predicate rather than reading `settings:ADMIN` as a proxy. The two
predicates exist side-by-side because the workspace-admin shortcut
is the bootstrap path (it works even before any roles exist), while
the Ontos-admin predicate is the steady-state authority once roles
are configured.

The practical implication for testing: a workspace admin cannot easily
exercise non-admin code paths from their own account; you need a
non-admin token to test denial branches. Equally, an Ontos admin who
is *not* a workspace admin can still be denied by code that hits the
workspace-admin shortcut — audit both paths when verifying a
permission change.

### Email-as-implicit-group fallback {#email-as-group-fallback}

When SCIM returns an empty group list for a user, Ontos falls back to
using the user's own email as a single implicit "group" name. This is
a recovery mechanism for environments where SCIM is broken (local
dev, certain sandbox setups, service principals that cannot read
SCIM). It is **fallback only, never additive**: if the user has any
resolvable real group, the email is not added.

Production deployments should not depend on the email fallback. It
exists for bootstrapping the first admin when SCIM is unavailable.
The Ontos Setup guide documents the DB update to fix this case.

## Filtered (domain-scoped) access {#filtered-access}

The `Filtered` access level signals "read/write, but only to a subset".
In the current Ontos version it is wired only for the **data-products**
feature, where it restricts visibility and edit rights to products in
domains owned by the caller (resolved via team membership and ownership
ties). Other features list `Filtered` as a permitted level only if the
feature explicitly implements the scoping; without an implementation,
the level behaves like `Read/Write` for that feature. This asymmetry is
evolving — more features may grow scoping in future versions.

## Per-execution authorization {#per-execution-authz}

Feature-level checks decide whether a user may enter a feature at all.
Inside a feature, sensitive operations (approving an agreement,
granting permissions, modifying a specific data product) consult
per-entity ownership and per-execution role checks in addition to the
outer feature gate. This is why an Ontos role grant alone may not be
sufficient to approve a specific agreement — the underlying entity's
ownership and the workflow step's configured approver group also gate
the action.

The pattern matters when extending a feature to a new persona: the
outer feature gate gets the persona in the door, but every inner
sensitive operation may have its own check that was originally written
assuming a different persona. Audit the gates end to end before
declaring a permission change done.

## Demo-mode persona override {#persona-override}

For local development and customer demos, Ontos supports a runtime
persona switch:

- Set `TEST_USER_TOKEN` in the backend environment.
- The frontend exposes a persona picker (from
  `data/test_personas.yaml`).
- Each request from the frontend carries `X-Test-Token`,
  `X-Test-User-Email`, and optional `X-Test-User-Groups` headers.
- The backend resolves the identity from these headers instead of OBO
  SCIM for the duration of the request.

The default persona set covers Admin, Data Governance Officer, Data
Steward, Data Producer, Data Consumer, Security Officer, and an
empty-groups "anon" persona for exercising fully-denied paths.

Leave `TEST_USER_TOKEN` unset in production. When it is unset, the
persona headers are ignored and normal OBO resolution applies.

### Role override (impersonation) {#role-override}

Independently from the persona-token mechanism, an admin can apply a
role override for a user via the role-switcher UI. The override is
held in-memory for the backend process lifetime and replaces the
user's group-derived role for permission evaluation. Non-admin
callers may only apply overrides to roles whose `assigned_groups`
they actually belong to; admins may apply any override. Clearing the
override returns the user to group-based resolution.

The role override does not affect the workspace-admin shortcut — a
workspace admin remains a workspace admin even while impersonating a
non-admin role for the rest of Ontos's permission evaluation.

## Cross-references {#cross-references}

- [Permission model](#permission-model) and [Filtered access](#filtered-access)
- [Built-in roles](#built-in-roles) — six seeded roles
- [Demo-mode persona override](#persona-override)
- [Per-execution authorization](#per-execution-authz) for sensitive
  operations
- [Ontos Setup guide](../Ontos%20Setup.md) — first-admin bootstrap if
  SCIM doesn't return the seed group
- [Persona quick reference](personas-quick-reference.md) for the
  questions each persona typically asks

_Last verified against codebase: 2026-05-28_
