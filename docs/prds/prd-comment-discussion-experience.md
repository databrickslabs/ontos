# PRD: Comment Discussion Experience (Threading, Resolve, Rich Text, Attachments)

> **Sibling PRD:** [`prd-comments-audience-and-mentions.md`](./prd-comments-audience-and-mentions.md) (#239) owns *who a comment reaches* — role/owner audience and `@`-mention notifications. This PRD owns *how a comment reads as a conversation* — threading, resolution, formatting, and attachments. The two ship independently; neither blocks the other. Where they touch (reply notifications ride the #239 notification engine; a reply's audience resolves through #239's audience model), the boundary is called out explicitly below.

## Problem Statement

Ontos comments are flat, plain-text annotations. Once a discussion runs longer than one exchange, the surface stops helping:

- **There is no threading.** A reply to a specific point is just another top-level comment in the list, disconnected from what it answers. On an entity with an active discussion, readers cannot tell which comment responds to which, and the unified timeline interleaves unrelated comments and change-log events between a question and its answer.
- **There is no resolution.** A comment that has been addressed looks identical to one that still needs attention. Threads accumulate forever; a reader cannot tell "settled" from "open," and stewards have no way to close out a discussion that reached a conclusion. The only lifecycle states today are `ACTIVE` and `DELETED`.
- **There is no formatting.** Comment bodies are plain text. Authors cannot emphasise a word, paste a bulleted list of findings, quote a prior comment, link out to a runbook, or share a fenced code/SQL snippet — all routine in governance discussions about data quality, contracts, and policy. The application already ships a Markdown renderer used across the product, but comments do not use it.
- **There is no way to attach evidence.** A steward reviewing a data product cannot attach the screenshot of a failing check, the CSV of offending rows, or the PDF of an approval. Discussion of an artefact happens without the artefact, so the artefact ends up in Slack or email and the governance record is incomplete.

Comparable tools (Ataccama ONE's comments feature is the reference point that prompted this PRD) treat asset comments as a real discussion surface: threaded replies, mark-as-closed with reopen, rich-text with links, and file/image attachments. Ontos has genuine advantages those tools lack — per-comment **audience scoping**, **project scoping**, a **unified comments-plus-change-log timeline**, and full **audit logging**. This PRD closes the discussion-experience gap *without* sacrificing those advantages: every new capability is defined so that it respects audience scoping, appears in the unified timeline, and is audit-logged.

## Solution

Turn comments into a threaded, resolvable, formatted, attachment-bearing discussion surface, delivered as four additive capabilities that each degrade gracefully to today's behaviour.

**Threading.** A comment may have a parent. Threading is **single-level**: a top-level comment (`parent_id IS NULL`) can have direct replies; replies cannot themselves be replied to. Storage is a nullable self-referential `parent_id` (UUID) on the existing `comments` table — no separate replies table, no backfill. A thread is a root comment plus its direct replies. Ratings (`comment_type='rating'`) are never parents or children.

- **Audience is resolved at the root.** Replies carry no independent audience tokens; the whole thread's visibility is governed by the root comment's audience (resolved through the sibling PRD's audience model). A reply therefore cannot widen — or narrow — the thread's audience by construction. Editing the root's audience re-scopes the entire thread atomically.
- **In the unified timeline**, the root sits at its own chronological slot and its replies render nested beneath it, contiguous; change-log events are never spliced inside a thread. Discussion readability wins over strict global chronology.
- **Pagination is by thread.** A thread loads as one unit so replies are never orphaned across a page boundary. Replies count toward the entity activity total (the count badge reflects real discussion volume); `visible_count` continues to respect audience at the thread level.

**Resolve / close.** A thread can be marked resolved and later reopened. Resolution is represented by two nullable fields — `resolved_at` and `resolved_by` — kept **orthogonal** to the `ACTIVE`/`DELETED` status (a thread can be resolved and later deleted without enum contortions). Resolution is **thread-level**: it is set on the root only; replies have no independent resolved state. A resolved root renders collapsed with a "Resolved by X" badge, with a filter chip to show/hide resolved threads inline — resolved threads are **not** moved to a separate tab, so the unified timeline stays whole. Resolve and reopen each write a user-action audit entry and emit a system entry into the unified timeline.

**Rich text.** Comment bodies become Markdown. Authors write Markdown in the composer; the timeline renders it through the application's existing `MarkdownViewer` (react-markdown + remark-gfm), extended with `rehype-sanitize` so user-authored bodies cannot inject markup. The stored column is unchanged (raw text that happens to be Markdown), so **existing comments render unchanged with zero migration**. GitHub-flavoured Markdown — emphasis, lists, quotes, fenced code, tables, external links — is in scope. Ataccama-style slash-commands, glossary-term insertion, and internal application-entity links are **out of scope for v1**.

**Attachments.** A comment may carry file attachments (images and common document types). A new multipart upload endpoint writes the blob to a Databricks Volume (reusing the storage model already established for document metadata) and records a row in a new `comment_attachments` table linking the blob to its comment. Uploads are constrained by a content-type/extension allowlist, a per-file size cap, and a per-comment count cap. No antivirus scan in v1 (Ontos has no scanner service today — noted as a v2 follow-up). Soft-deleting a comment keeps its blobs (recoverable); blobs are hard-deleted only when the comment is hard-deleted by an admin or reclaimed by a later orphan sweep.

**Reply notifications.** The *requirement* — "a reply to my comment notifies me" — is owned by this PRD, but the *delivery mechanism* is deferred to the notification engine built in #328 (`prd-comments-audience-and-mentions.md`). Until #328 lands, the reply-notification trigger is a documented no-op; when #328 lands, replies fan out one in-app notification to the parent author (excluding self-replies), reusing that engine rather than duplicating notification plumbing.

**Compatibility.** All four capabilities are additive. A single Alembic migration adds `parent_id`, `resolved_at`, `resolved_by`, and the `comment_attachments` table — all nullable/new, no backfill, existing rows untouched. Rich text and attachments each sit behind an independent feature flag so they can ship dark and roll out gradually; threading and resolve/close ship un-flagged because they degrade to today's behaviour (no replies, no resolved threads = the current experience).

## User Stories

### Threading

1. As a comment author, I want to reply directly to a specific comment, so that my response is visibly attached to what it answers instead of floating as another top-level entry.
2. As a timeline reader, I want a comment's replies to render nested directly beneath it and contiguous, so that I can follow a discussion without hunting through interleaved change-log events.
3. As a comment author, I want replies to inherit the audience of the thread's root comment, so that a private discussion stays private and I never accidentally widen who can see a reply.
4. As an admin editing a root comment's audience, I want the whole thread's visibility to re-scope atomically, so that the discussion has one coherent audience.
5. As a comment author, I want to be unable to reply to a reply (single-level threads), so that discussions stay flat and scannable rather than deeply nested.
6. As a user rating an entity, I want ratings to remain standalone (not repliable, not part of a thread), so that the star-rating flow is unaffected by discussion features.
7. As a timeline reader, I want the entity activity count to include replies, so that the badge reflects the real volume of discussion.
8. As a timeline reader paging through a long history, I want each thread to load as a single unit, so that a root and its replies never get split across a page boundary.

### Delete semantics

9. As a comment author, I want deleting my reply to leave a "[deleted]" placeholder in the thread, so that the reply chain and the audit record stay intact.
10. As a comment author, I want deleting a root comment to soft-delete the whole thread, so that I do not leave orphaned replies pointing at nothing.
11. As an admin, I want hard-delete to remain available on individual comments (and to reclaim their attachment blobs), so that genuinely sensitive content can be purged.

### Resolve / close

12. As a steward, I want to mark a thread as resolved, so that readers can tell a settled discussion from one that still needs attention.
13. As a steward, I want a resolved thread to render collapsed with a "Resolved by X" badge, so that closed discussions do not clutter the active view but remain visible.
14. As a timeline reader, I want a filter chip to show or hide resolved threads inline, so that I can focus on open discussions without losing the resolved ones to a separate tab.
15. As a steward, I want to reopen a resolved thread, so that a discussion that was closed prematurely can continue.
16. As the author of a thread, the entity's owner, or an admin, I want to be the only ones who can resolve or reopen it, so that "this discussion is settled" is a deliberate governance act rather than something any writer can toggle.
17. As an auditor, I want every resolve and reopen recorded in the user-action audit log and shown as a system entry in the unified timeline, so that the lifecycle of a discussion is traceable.

### Rich text

18. As a comment author, I want to write Markdown (emphasis, lists, quotes, fenced code/SQL, tables, external links) and see it rendered in the timeline, so that I can express findings clearly.
19. As a reader of existing comments authored before this feature, I want them to render exactly as before, so that turning on rich text changes nothing retroactively.
20. As a security-conscious admin, I want comment bodies sanitised on render, so that a crafted comment cannot inject markup or script into another user's browser.
21. As an admin, I want rich text behind a feature flag, so that I can enable it when my organisation is ready.

### Attachments

22. As a steward, I want to attach an image (e.g. a screenshot of a failing check) to a comment, so that the evidence lives with the discussion.
23. As a steward, I want to attach a document (PDF, CSV, spreadsheet), so that supporting artefacts are part of the governance record rather than lost in Slack.
24. As a user, I want the upload to reject a file that is too large, too many files on one comment, or a disallowed type, with a clear message, so that I understand the limits.
25. As an admin soft-deleting a comment, I want its attachments preserved (recoverable), so that a mistaken delete does not destroy evidence; and hard-delete to reclaim the blobs.
26. As an admin, I want attachments behind a feature flag, so that I can roll the capability out gradually.

### Notifications (boundary with #239 / #328)

27. As a comment author, I want to be notified when someone replies to my comment — delivered through the same in-app notification engine that #328 builds for mentions — so that I do not have to poll the entity to notice a response.
28. As a comment author, I do not want a notification when I reply to my own comment, so that self-replies are silent.

## Implementation Decisions

### Modules touched

- **Comment DB model + migration** (`db_models/comments.py`, one new Alembic revision): add `parent_id` (nullable `PG_UUID`, self-FK to `comments.id`, indexed), `resolved_at` (nullable timestamptz), `resolved_by` (nullable string). Add a new `comment_attachments` table (see below). All additive; no backfill.
- **Repository** (`repositories/comments_repository.py`): thread-aware listing (group replies under roots, order roots chronologically and replies within a thread chronologically), thread-level pagination, cascade soft-delete of a root's replies, reply-tombstone rendering, resolve/reopen field writes, attachment link CRUD.
- **Manager** (`controller/comments_manager.py`): reply-creation path (validate single-level, reject replying to ratings, ignore any audience tokens supplied on a reply), audience resolution at thread root, resolve/reopen with permission check and audit + timeline emission, attachment orchestration, reply-notification trigger hook (no-op until #328).
- **Routes** (`routes/comments_routes.py`): accept `parent_id` on comment create; add resolve/reopen endpoints; add multipart attachment upload + download/list + delete endpoints. All under the existing `comments` feature permission.
- **Frontend** (`components/comments/comment-sidebar.tsx`, `comment-timeline.tsx`, `lib/`): reply affordance and nested rendering, resolved badge + collapse + filter chip, Markdown composer + render via extended `MarkdownViewer`, attachment upload/preview UI. Shared logic (thread grouping, resolved rendering, Markdown render, attachment chips) extracted to shared hooks/components so the sidebar and embedded variants do not drift.
- **Feature flags**: `comments.rich_text` and `comments.attachments` gate their respective UI and endpoints.

### Threading model

- `parent_id` nullable self-FK on `comments`. `parent_id IS NULL` ⇒ root/top-level. A root plus its direct replies is a thread; the root's `id` is the thread key.
- **Single-level enforced server-side**: creating a comment whose `parent_id` points at a comment that itself has a non-null `parent_id` is rejected. Creating a reply to a `comment_type='rating'` row is rejected.
- **Replies store no audience.** Any `audience` supplied on a reply create/update is ignored (not persisted). Visibility of a reply is computed from its root's audience using the sibling PRD's audience-matching logic. This is a *resolve-at-read* rule: the repository joins each reply to its root and applies the root's audience OR-clauses.
- **Timeline assembly**: roots and change-log events are merged chronologically as today; each root's replies are attached beneath it (contiguous, chronological within the thread); change-log events are never inserted between a root and its replies.
- **Pagination** is by thread: the `limit`/`total_count` semantics count threads (roots) for page boundaries while the activity badge counts roots + replies. A thread is never split across pages.

### Delete semantics

- Deleting a **reply** ⇒ soft-delete (`status='deleted'`), rendered as a "[deleted]" tombstone that preserves position in the reply chain.
- Deleting a **root** ⇒ cascade soft-delete of the root and all its replies in one transaction.
- **Hard delete** (admin, existing `hard_delete` flag) removes the row(s) and, for a root, the whole thread; it also hard-deletes any linked attachment blobs (see lifecycle below).

### Resolve / close model

- Fields `resolved_at` / `resolved_by` on the root only, orthogonal to `status`. `resolved_at IS NOT NULL` ⇒ resolved. Reopen nulls both fields.
- **Thread-level**: resolve/reopen operate on a root `id`; attempting to resolve a reply is rejected.
- **Permission**: resolve/reopen allowed for the thread author **or** an active business owner of the entity **or** an admin. Owner resolution reuses `BusinessOwnersManager.get_owners_for_object` (the same lookup #327 builds). This is stricter than the general `READ_WRITE` comment-write permission.
- **Audit + timeline**: each resolve/reopen writes a user-action audit entry and emits a change-log/system entry so the unified timeline shows "Thread resolved by X" / "Thread reopened by X" at the correct chronological position.

### Rich text model

- Stored body remains the existing plain `comment` text column, now interpreted as Markdown. **No migration** — pre-existing plain-text comments are valid Markdown and render unchanged.
- Render path: reuse `MarkdownViewer` (react-markdown + remark-gfm), add `rehype-sanitize` with a conservative schema (no raw HTML, safe URL protocols only) applied to comment rendering. Sanitisation is mandatory because comment bodies are user-authored and currently unsanitised; this is the one genuine security item in the PRD.
- Composer: a Markdown textarea (not a WYSIWYG editor) with a lightweight preview toggle. Slash-commands, glossary-term insertion, and internal-entity links are explicitly deferred.
- Gated by `comments.rich_text`. With the flag off, the composer is a plain textarea and rendering is plain text (today's behaviour).

### Attachments model

- New table `comment_attachments`: `id` (UUID PK), `comment_id` (FK → `comments.id`, indexed), `filename`, `content_type`, `size_bytes`, `storage_path` (Databricks Volume path), `created_by`, `created_at`. Blobs live under a deterministic Volume path keyed by comment id, reusing the Volume storage model established for `DocumentMetadataDb`.
- New multipart upload endpoint validates against a **content-type/extension allowlist** (images: png/jpg/gif/webp; documents: pdf/csv/txt/xlsx/docx), a **per-file size cap** (default 25 MB), and a **per-comment count cap** (default 10). Rejections return a clear error. Config values are settings-driven so they can be tuned per deployment.
- **No AV scan in v1** (no scanner service exists). Documented as a v2 follow-up.
- **Lifecycle on delete**: soft-delete (reply tombstone or root cascade) keeps blobs and keeps the `comment_attachments` rows (recoverable). Hard-delete (admin) removes rows and blobs. A later orphan-sweep job (out of scope here, noted) can reclaim blobs whose comment is gone.
- Gated by `comments.attachments`. With the flag off, upload endpoints are unavailable and the UI hides the attach affordance.

### Notification boundary

- The reply-notification requirement is captured here but the delivery rides #328's `NotificationsManager`. This PRD adds a single trigger point in the manager's reply-create path: "on reply create, if the parent author ≠ the reply author, enqueue a reply notification." Until #328 ships, the hook is present but does nothing (the notifications manager is not yet wired for comment events). No notification plumbing is built in this PRD.

### Compatibility and migration

- One additive Alembic migration: `parent_id`, `resolved_at`, `resolved_by` columns + `comment_attachments` table + supporting indexes (`ix_comments_parent`, `ix_comment_attachments_comment`). No backfill, no data rewrite.
- Feature flags `comments.rich_text` and `comments.attachments` default off; threading and resolve/close ship un-flagged.
- **Ship order** (each independently shippable): (1) resolve/close, (2) threading, (3) rich text, (4) attachments.

### Entity applicability

- Threading, resolve/close, rich text, and attachments apply to every entity type where comments are already enabled — see [`.cursor/rules/10-entity-panel-matrix.mdc`](../../.cursor/rules/10-entity-panel-matrix.mdc) and `COMMENT_ELIGIBLE_TYPES`. No new entity types are introduced here (ontology concepts/collections are enabled separately by `prd-ontology-lifecycle-management.md`; when they are, they inherit these capabilities for free).

## Testing Decisions

A good test here exercises external behaviour through the manager/route surface and asserts on observable outcomes (returned payloads, DB rows, audit-log entries, timeline entries), never on internals. Notifications are mocked, following the existing comment and notification test patterns.

- **Threading visibility** (manager-level): seed a root with a restrictive audience (team/role/owner/user tokens) and several replies; assert that a reader who matches the root sees the whole thread and a reader who does not sees none of it; assert a reply's supplied audience is ignored; assert replying to a rating and replying to a reply are both rejected. Assertions are on the set of comment IDs returned, not on SQL.
- **Delete semantics** (manager-level): deleting a reply yields a tombstone and preserves siblings; deleting a root cascade-soft-deletes all replies; hard-delete of a root removes the thread and its attachment rows/blobs (blob deletion mocked at the storage boundary).
- **Resolve / reopen** (route + manager): author, entity owner, and admin can resolve; a non-owner writer cannot; resolve then reopen round-trips the fields; each transition writes exactly one audit entry and one timeline system entry. Owner resolution reuses the business-owners lookup (mocked).
- **Timeline assembly** (manager-level): given interleaved roots, replies, and change-log events, assert roots are chronological, replies are contiguous beneath their root, no change-log event lands inside a thread, and thread-level pagination never splits a thread; assert the activity count includes replies while page boundaries count threads.
- **Rich text** (frontend component + one manager render test): a body containing a script/HTML-injection payload renders sanitised (no script, no raw HTML); a pre-existing plain-text comment renders unchanged; GFM constructs (list, code fence, table, link) render.
- **Attachments** (route-level): upload accepts an allowlisted type within caps; rejects an oversized file, an over-count comment, and a disallowed type with clear errors; soft-delete keeps blobs, hard-delete reclaims them (storage boundary mocked); listing/downloading respects the comment's (thread-root) audience.
- **One e2e** (sibling to `src/e2e/tests/test_16_comments.py`): reply to a comment, mark the thread resolved, verify collapse + badge, reopen it.
- **Frontend component tests**: nested-thread render, resolved-collapse toggle + filter chip, Markdown composer preview, attachment chip render. No visual regression.
- **Prior art**: existing comment manager/repository tests, `test_comments_routes.py`, `test_16_comments.py`, and existing notification tests that mock the notifications dependency.

## Out of Scope

- **@-mentions, role audience, and owner audience** — owned by `prd-comments-audience-and-mentions.md` (#239 / #327 / #328). This PRD consumes that audience model for thread-root visibility but does not change it.
- **The notification delivery engine.** Reply notifications ride #328's engine; this PRD only declares the trigger.
- **Multi-level / arbitrary-depth nesting.** Threads are single-level in v1.
- **Reactions / likes / emoji.** No engagement metrics (the reference tool lacks these too; low governance value).
- **Rich-text slash-commands, glossary-term insertion, internal application-entity links.** v1 is GFM only.
- **Antivirus scanning of attachments**, presigned direct-to-Volume upload, and an orphan-blob sweep job. Attachments v1 is a server-mediated multipart upload with allowlist + caps; AV and sweep are v2 follow-ups.
- **WYSIWYG editor.** The composer is a Markdown textarea with preview.
- **Moving resolved threads to a separate tab.** Resolved threads stay inline (collapsed + filter chip) to preserve the unified timeline.
- **Enabling comments on new entity types.** Applicability follows the existing panel matrix.
- **Per-reply audience.** A reply's audience is always its root's.

## Further Notes

- **Why resolve/reopen is a separate field, not a status enum value.** Keeping `resolved_at`/`resolved_by` orthogonal to `ACTIVE`/`DELETED` means a thread can be resolved and later deleted (or hard-deleted) without inventing combined enum states, and the resolution audit trail (`resolved_by`, `resolved_at`) is captured directly rather than inferred from status transitions.
- **Why resolve-at-read for reply audience rather than copy-at-write.** Copying the root's tokens onto each reply would drift the moment the root's audience is edited, requiring a fan-out update across all replies. Resolving from the root at read time makes "edit the root audience ⇒ whole thread re-scopes" free and makes it structurally impossible for a reply to carry a wider audience than its thread.
- **Sanitisation is the one hard security requirement.** Comment bodies are user-authored and currently rendered as plain text; introducing Markdown rendering without sanitisation would open stored-XSS. `rehype-sanitize` with a no-raw-HTML schema is mandatory and must land in the same change as rich-text rendering, behind the same flag. Follows the project rule on error/logging/output security.
- **Attachment safety posture.** Without an AV service, the allowlist + size/count caps + server-mediated upload are the v1 controls. Downloads should be served with `Content-Disposition: attachment` and a non-executable content type where ambiguous, and never rendered inline as HTML. Security review can tighten the allowlist before launch; it is a single config surface.
- **Relationship to `prd-ontology-lifecycle-management.md`.** That PRD enables the comments entity types for ontology concepts/collections and explicitly relies on the comments stack unchanged. The capabilities in this PRD apply automatically to those entity types once both ship; neither PRD blocks the other.
- **Relationship to the unified timeline (a differentiator to protect).** Every capability here was chosen to keep the single interleaved comments-plus-change-log timeline intact: threads render contiguous *within* that timeline rather than in a forum view, resolved threads stay inline rather than moving to a tab, and resolve/reopen emit timeline entries. The comparison tool that prompted this PRD has no equivalent unified view; we do not want to trade it away for parity on the other axes.
- **Performance.** `parent_id` is indexed; thread assembly is one grouping pass over the already-fetched page. The reply→root audience join adds bounded OR-clauses (the same shape the audience model already builds). Attachment metadata is a thin join; blob bytes are streamed from the Volume, never loaded into the comment payload. No new concerns anticipated until a single entity holds tens of thousands of comments.
- **Companion plan.** If an implementation plan is written, it belongs at `docs/plans/comment-discussion-experience.md` (title-based mapping, matching the existing plan/PRD convention). This PRD is the source of truth for *what* and *why*; the plan would own *how*.
