# Installation, Updates, Maintenance, and Common UI Errors

This doc covers how Ontos gets into a workspace, how it gets updated, the
day-2 maintenance footwork it expects, and the UI errors users surface
most often. Step-by-step setup screenshots live in `docs/Ontos Setup.md`;
this file is the conceptual layer around it — what the choices mean,
where they trade off, and what breaks when something is misconfigured.

## Distribution channels {#distribution-channels}

Ontos ships through two channels. They install the same application,
but they expect different operator skills and different update
discipline.

### Databricks Marketplace {#marketplace-channel}

The default path. From the workspace's Marketplace UI, an admin searches
for "Ontos", clicks Install, and the workspace's Apps service handles
the rest — container build, OAuth scope acceptance, Lakebase wiring,
and first deploy. Each Marketplace listing version is a semver release
of the OSS repo packaged for distribution. Receiving an update means
re-installing or upgrading through the Marketplace UI; the running
deployment is replaced by the new version.

Trade-off: governed and versioned. The workspace stays on a known
release; the in-product scope set is fixed in the listing's manifest
and can't be edited from the workspace side. If a customer needs a
different scope set or a pre-release fix, the Marketplace channel is
the wrong choice — go to the Git path.

### GitHub repository {#git-channel}

`databrickslabs/ontos` is the canonical OSS repo. Advanced users clone
or fork it, then deploy via `databricks bundle deploy` /
`databricks sync` plus `databricks apps deploy`. This is the path for
running a feature branch, hot-patching an unmerged PR, or customizing
the app beyond what the Marketplace listing exposes.

Trade-off: current-tip but unstable. The repo's `main` may carry
in-progress work; pinning to a tag is the operator's responsibility.
Scope changes can be applied directly to the deployed `manifest.yaml`,
but each scope edit forces affected users to re-accept (see
[OAuth scope changes](#oauth-scope-changes)).

### When to choose which {#channel-choice}

For most customer deployments: Marketplace. It gives a clean semver
upgrade story and removes scope-cookie maintenance from the operator's
plate. For partners, OEMs, or any deployment that needs to fork — Git.
For temporary hot-patches against an unmerged upstream PR, Git is the
only option; see [Customer fork hygiene](#customer-fork-hygiene).

## First-time installation {#first-install}

`docs/Ontos Setup.md` walks the step-by-step. What matters
conceptually:

### Prerequisites {#install-prerequisites}

- A **Lakebase Postgres** instance the deployment can claim. The
  database (`app_ontos` by default) must be created with a permissive
  initial grant (`GRANT ALL ON DATABASE app_ontos TO PUBLIC`) because
  the app's service principal does not yet exist at create time. The
  SP gets created when the app is first deployed and takes ownership
  of the schema thereafter.
- A **Unity Catalog Volume** for artifacts (images attached to
  entities, the Git-sync repo used by Indirect delivery mode). The SP
  gets `READ_WRITE` on the volume after first deploy.
- **On-behalf-of (OBO) authentication enabled** on the workspace's
  Apps service. OBO is in Public Preview at time of writing; the
  toggle lives in workspace Previews. Without OBO, the app falls back
  to SP-only auth and most lifecycle actions fail because they need
  the calling user's permissions to grant securely.
- Optionally, a **Marketplace listing** in the workspace's regional
  Marketplace feed.

### First-admin bootstrap {#first-admin-bootstrap}

The very first user reaching a freshly seeded Ontos database hits a
chicken-and-egg problem: no role is yet bound to their groups. Two
mechanisms cover this:

- **`APP_ADMIN_DEFAULT_GROUPS` env var** — read once on first start
  by the role-seeding code in `SettingsManager`. The named groups are
  written into the Admin role's `assigned_groups` list. This is a
  **first-start-only** seeding: subsequent app restarts do not
  re-merge changes to the env var. Post-deploy admin changes go
  through Settings → RBAC or direct SQL.
- **Email-as-implicit-group fallback** — when SCIM returns an empty
  group list for a user (typical on FEVM workspaces, or when the SP
  lacks `iam.current-user:read`), the user's email is injected as a
  synthetic group name so a direct `Admin.assigned_groups = ["alice@..."]`
  entry can still match. The fallback is non-additive — it only
  fires when SCIM returned zero groups, never alongside real groups.
  Use it as a recovery escape hatch, not as a primary admin path.

See [Roles and RBAC](roles-and-rbac.md#permission-model) for the full
permission model.

### Demo presets {#demo-presets}

Ontos ships with five self-contained demo packs — `retail` (default),
`hls`, `fsi`, `mfg`, `auto`. Each is delivered as a standalone SQL
file under `src/backend/src/data/demo_data_{preset}.sql` and uses a
per-preset UUID prefix segment (`0000`, `0001`, `0002`, …). Loading is
through `POST /api/settings/demo-data/load?preset=<name>`. Cleanup is
through `DELETE /api/settings/demo-data` and removes records across
all loaded packs by demo UUID prefix. There is no implicit base
overlay: each preset stands alone.

## Updating to a new version {#updates}

### Marketplace upgrade {#marketplace-update}

Re-install or upgrade the listing through the workspace UI. Databricks
handles the swap; the running deployment is replaced by the new
version. Persistent state (Lakebase tables, Volume artifacts,
configured roles) survives because it's external to the app
container.

### Git deploy update {#git-update}

The expected sequence:

1. `git pull` (or rebase) on the deployed branch.
2. `databricks sync` the contents of `src/` to the workspace deploy
   path. **Sync from `src/`, not from the repo root** — the app's
   `app.yaml` lives at `src/app.yaml` and must end up at the
   workspace path's root. See
   [workspace sync direction](#workspace-sync-direction).
3. If the update touches the handbook corpus
   (`docs/handbook/*.md`), upload that tree separately via
   `databricks workspace import-dir docs/handbook/ <ws_path>/docs/handbook/`.
   `docs/` lives outside `src/` so the regular sync skips it.
4. `databricks apps deploy <app_name>` to roll the new deployment.

### Migration discipline {#migration-discipline}

Alembic migrations are **append-only**. Once a revision ID has been
applied to any database, treat its body as frozen — add a new
migration on top rather than editing in place. Editing an already-
applied revision means alembic skips re-running it (because the
version table already records that ID), so the new code never
actually executes against the existing database.

Revision IDs themselves have a hard ceiling: Postgres
`alembic_version.version_num` is `VARCHAR(32)`. A revision string
longer than 32 characters causes the version-table UPDATE to fail
with `StringDataRightTruncation`, which rolls back the whole
migration and stops the app from starting. Verify length before
upload.

Single-head invariant: the migration history must have exactly one
head. CI enforces this via `scripts/check-alembic-heads.py`. If two
PRs land sibling revisions, the merging PR must include an explicit
`alembic merge`.

### Restart vs database state {#restart-vs-db-state}

App restarts pick up code changes immediately. Database state
**persists across deploys, branch switches, and git reverts**. This
catches operators off-guard: rolling back a code commit does not
roll back the database row it touched. Use the dedicated reset
endpoint (`DELETE demo-data`) or direct SQL for state changes that
need to mirror a code revert.

### Customer fork hygiene {#customer-fork-hygiene}

When a deployment runs hot-patches against unmerged upstream PRs, it
is functionally a fork. Track the delta explicitly (which PRs are
applied on top of what upstream commit), and reconcile once each
upstream PR merges. The risk to manage: an upstream reviewer asks
for changes during review, and the merged version diverges from what
the deployment already runs. Re-deploys after each upstream PR merge
keep the deployment converging on stock OSS.

## Maintenance {#maintenance}

### Database migrations {#db-migrations-at-startup}

`alembic upgrade head` runs at startup, before the FastAPI app
finishes initializing. A migration failure stops the app — health
endpoints return 200 (process is up) but `/api/health` JSON reports
`db_ok: false`. The Apps UI may show "running" while the app is
effectively broken; verify via the health JSON, not the badge.

### Role re-seeding {#role-reseeding}

`APP_ADMIN_DEFAULT_GROUPS` seeds only on the first start that
encounters an empty role table. Later restarts do not re-merge. To
add admins post-deploy: edit `Admin.assigned_groups` in Settings →
RBAC, or update the row directly in Postgres. Don't expect env-var
edits to propagate to a running database.

### Workspace sync direction {#workspace-sync-direction}

The sync source directory matters. `app.yaml` lives at `src/app.yaml`
in the repo, but the Apps service expects to find it at the
workspace deploy path's root. Sync from `src/`, not from the repo
root.

A common failure: an operator runs `databricks sync` from the repo
root, so `app.yaml` lands at `<deploy_path>/src/app.yaml` instead of
`<deploy_path>/app.yaml`. Apps can't find the manifest, falls back
to defaults, and the deploy reports "App process did not start
within 10 minutes." This is a sync-layout error, not a code error,
and it is the dominant cause of that timeout message.

`databricks sync` also adds without removing. Re-syncing from the
correct directory does not delete the wrong-layout files left from
a prior bad sync — both sets coexist in the workspace until the
operator deletes the stale paths explicitly. Verify the workspace
layout before deploying.

### OAuth scope changes {#oauth-scope-changes}

When the deployment's required OAuth scopes change — for example,
adding `unity-catalog` to the manifest — already-authorized users
do **not** automatically pick up the new scope set. The first-visit
scope-acceptance is stored in the user's browser cookie for the
app's URL and re-used until the cookie is cleared. The visible
symptom is an error like
`"Provided OAuth token does not have required scopes: unity-catalog"`
even though the manifest lists the scope correctly.

The fix is per-user: clear the cookie for the app's URL and reload
the page. The user is re-prompted to accept the current scope set,
the new cookie carries the updated scopes, and the error goes away.
There is no admin-side override that can force a re-prompt on every
user — communicate the cookie-clear step when shipping a scope
change.

### Customer fork delta {#customer-fork-delta}

For deployments carrying unmerged upstream patches, maintain a
delta document listing each applied PR and its upstream status.
Rebase once any PR merges into upstream. Don't accumulate divergent
patches without a reconciliation plan; the longer the delta lives,
the more expensive each reconciliation deploy becomes.

## Common UI errors {#common-ui-errors}

What follows is the recurring set of user-visible errors with their
root causes. Each entry covers symptom, cause, and fix.

### Identity and access errors {#identity-errors}

#### "Request role" prompt on every page load {#request-role-prompt}

The user lands on Ontos and is asked to pick a role on every visit,
because the role-resolution step found no matching `assigned_groups`
intersection.

Two common causes:

- The app SP can't read the user's groups via SCIM (often because
  `iam.current-user:read` is missing from the manifest scope set, or
  the workspace returns empty group lists). Fix: verify the SCIM
  scope; if the workspace doesn't support SCIM group reads for SPs,
  fall back to email-as-implicit-group by adding the user's email
  directly to `Admin.assigned_groups` and confirming the SCIM call
  returns empty (the fallback only fires when SCIM returns zero
  groups).
- The `APP_ADMIN_DEFAULT_GROUPS` env var wasn't set on first start,
  so the Admin role was seeded with an empty group list. Fix: edit
  Settings → RBAC manually, or rewrite `Admin.assigned_groups` via
  SQL.

#### 403 on data products or contracts the user should be able to see {#unexpected-403}

The user has the documented feature-level access but a specific
endpoint returns 403. Endpoints can apply stricter sub-gates than
the feature-level access in the matrix; the matrix describes the
front-of-feature expectation, not every endpoint's authorization.
Trust the 403 — read the endpoint's actual `PermissionChecker`
dependency. If the gate is wrong for the user persona, the gate
needs to be lowered; the fix is a code change, not a permission
change on the user's side. See
[Roles and RBAC — permission model](roles-and-rbac.md#permission-model).

#### "Unity Catalog scope missing" {#uc-scope-missing}

The browser's cached scope-accept cookie predates a recent scope
change. The new scope is in the manifest, but the user's session
token doesn't carry it. Fix: clear the cookie for the app's URL,
reload, and re-accept the prompt. See
[OAuth scope changes](#oauth-scope-changes).

### Workflow and approval errors {#workflow-errors}

#### "Cannot approve agreement" for a non-Admin reviewer {#cannot-approve}

A Business Owner or other non-Admin reviewer can't approve an
agreement they're listed on. Two causes recur:

- **Approver-role filter mismatch.** The agreement's approval
  workflow definition filters approvers by role, and the user's
  current Ontos role doesn't match. Fix: check the workflow's
  approver-role spec and the user's role assignment.
- **Outer permission gate.** The approval-handling endpoint may
  require a feature access level the reviewer doesn't have at the
  configured level (historically `notifications:READ_WRITE` or
  `data-contracts:READ_WRITE`). Fix: align the user's role with the
  endpoint's gate, or relax the gate in the deployment's role
  config.

#### "grant_permissions step failed" {#grant-permissions-failed}

The `grant_permissions` step in an agreement workflow tries to grant
UC permissions and the platform rejects the call with
`"User does not have MANAGE"`. The app SP needs **explicit MANAGE**
on each UC securable it grants on. `ALL_PRIVILEGES` is **not**
sufficient on AWS Unity Catalog — MANAGE must be granted separately.
Fix: `GRANT MANAGE ON CATALOG <name> TO <sp_application_id>` for
each catalog the workflow touches. Document this in the deployment
runbook; it bites every customer that uses `grant_permissions` in
production. See
[Agreement workflow — grant_permissions step](agreement-workflow.md#grant-permissions-step).

### Database and data errors {#database-errors}

#### "Alembic version too long" or startup hang {#alembic-version-too-long}

The app fails to start, logs show `StringDataRightTruncation` on
`alembic_version`. A new migration's revision ID exceeded
`VARCHAR(32)`. Fix: rename the revision in the migration file to a
short identifier (≤32 chars), redeploy. If the database has already
recorded the old long ID, update `alembic_version.version_num`
manually via SQL to the new value before deploying.

#### Lakebase autoscale not picking up {#lakebase-autoscale-stuck}

The app reports it can't connect to Lakebase, but the Lakebase
instance shows healthy. The autoscale signal sometimes sticks after
a long idle. Fix: pause and resume the Lakebase instance from the
UI. The app retries on next request.

#### Stale data in product detail page after a code revert {#stale-data-after-revert}

The operator reverted a code commit but the bug behavior persists.
Database state is independent of git state — reverting code does
not roll back rows. Fix: either re-apply a corrective migration, or
update the relevant rows manually via SQL. See
[restart vs database state](#restart-vs-db-state).

### Deploy and app process errors {#deploy-errors}

#### "App process did not start within 10 minutes" {#process-did-not-start}

The most common cause is a workspace sync layout bug: `app.yaml`
landed at the wrong path because the sync was run from the repo
root instead of `src/`. Fix: verify `databricks workspace list`
shows `app.yaml` at the deploy path's root; if it sits one level
deeper, re-sync from `src/`. Also check for missing required env
vars in `app.yaml` — a missing env binding can stall the container
the same way.

#### Ask Ontos returns "I don't have authoritative information" for everything conceptual {#corpus-not-found}

The `docs/handbook/` tree wasn't packaged into the deployment. The
`search_ontos_handbook` tool can't find the corpus on disk, so
every conceptual query returns the refusal default. Fix: upload
`docs/handbook/` to the deployment path
(`databricks workspace import-dir docs/handbook/ <ws_path>/docs/handbook/`),
or set `ONTOS_HANDBOOK_DIR` to point at an alternate corpus
location on the container. Restart the app to pick up the new
files.

## Where to get help {#getting-help}

- **Bugs and feature requests:** open issues at the
  `databrickslabs/ontos` GitHub repository.
- **Contributing:** see `CONTRIBUTING.md` in the repo for the PR
  workflow, testing expectations, and code-style conventions.
- **Customer support:** Marketplace deployments are supported
  through the workspace's Ontos administrator; Git-channel
  deployments take support questions directly to GitHub.

## Cross-references {#cross-references}

- [Roles and RBAC — first-admin bootstrap and permission model](roles-and-rbac.md#permission-model)
- [Agreement workflow — grant_permissions step](agreement-workflow.md#grant-permissions-step)
- [Delivery and propagation — Indirect mode requires the Volume-backed Git repo](delivery-and-propagation.md#indirect-mode)
- [MCP and Ask Ontos — what the copilot grounds against, and how the corpus is consumed](mcp-and-ask-ontos.md#grounding-sources)

## Common questions {#common-questions}

**"What's the difference between installing Ontos from Marketplace and from the GitHub repo?"**

Marketplace gives a packaged, versioned, governed install — the
workspace receives a known release, scope acceptance happens once
per user, and upgrades happen through the Marketplace UI.
GitHub-repo install gives current-tip code with the ability to
customize the manifest, fork the code, or run an unmerged feature
branch. Marketplace is the default for production deployments;
Git is the right choice for partner forks, hot-patches, or
deployments that need a custom scope set. See
[Distribution channels](#distribution-channels).

**"How do I update Ontos to a new version?"**

If the deployment came from Marketplace, re-install or upgrade
through the workspace's Marketplace UI; the running deployment is
replaced and Lakebase state survives. If the deployment came from
Git, `git pull` the deployed branch, `databricks sync` `src/` to
the workspace, run `databricks apps deploy`, and (if the handbook
corpus changed) upload `docs/handbook/` separately. See
[Updating to a new version](#updates).

**"The app says my Unity Catalog token is missing a scope, but the manifest looks correct. What's wrong?"**

The user's scope-accept cookie predates the manifest update.
Clear the cookie for the app's URL, reload, and re-accept the
prompt. Communicate this step to all affected users when shipping
a scope change. See [OAuth scope changes](#oauth-scope-changes).

**"The app process didn't start within 10 minutes. Is my code broken?"**

Usually not. The dominant cause of that error is a workspace sync
layout bug — `app.yaml` is at the wrong path because the sync was
run from the repo root instead of `src/`. Verify the workspace
layout with `databricks workspace list` and re-sync from `src/` if
`app.yaml` is one level too deep. See
[workspace sync direction](#workspace-sync-direction).

**"How do I add a new admin after the app is already deployed?"**

Don't rely on editing `APP_ADMIN_DEFAULT_GROUPS` — that env var is
read only on the first start that encounters an empty role table.
Edit `Admin.assigned_groups` through Settings → RBAC, or update
the row directly in Postgres. See
[Role re-seeding](#role-reseeding).

**"I reverted a buggy commit and redeployed, but the bug is still there. Why?"**

Database state persists across deploys and git reverts. The code
revert removed the buggy code path; it did not undo the database
rows that path wrote. Apply a corrective migration or update the
rows manually. See
[restart vs database state](#restart-vs-db-state).

**"Why is my `grant_permissions` step failing with 'User does not have MANAGE'?"**

The app's service principal needs explicit `MANAGE` on each UC
securable the workflow grants on. `ALL_PRIVILEGES` is not
sufficient — MANAGE must be granted separately. Add a UC
pre-flight to the deployment runbook:
`GRANT MANAGE ON CATALOG <name> TO <sp_application_id>` for every
catalog the workflow touches. See
[grant_permissions step failed](#grant-permissions-failed).

_Last verified against codebase: 2026-05-29_
