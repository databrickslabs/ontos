# PRD: Comment audience (roles & owner) and @-mention notifications

## Problem Statement

Comment authors cannot reliably reach the right readers. The audience picker on a comment lists role choices that do not behave like roles do everywhere else in the product, and there is no way to address the owners of the entity being discussed. As a result, authors target a "role" but the intended people never see the comment, and conversations meant for owners get sent into the void or broadcast too widely.

There is also no first-class way to call out an individual in the body of a comment. Authors paste names or emails into prose and hope the right person notices. They want the same `@` convention they use in other collaboration tools, with a notification on the receiving end.

## Solution

Bring comment audience in line with the rest of the product:

- The role list comes from the same source the workflow designer uses (canonical app roles with stable identifiers).
- A new `Owner` audience option resolves at read time to the entity's currently assigned business owner(s).
- The server decides "is this reader in the audience?" using the same role logic that drives feature permissions, not a narrower team-override signal.
- Audience tokens already in the database keep working unchanged.

Add `@`-mentions to comment bodies:

- Typing `@` opens an inline picker scoped to plausible candidates (members of teams on the current project), with a free-form email fallback when the right person is not in the list.
- Saving a comment fans out one in-app notification per distinct mentioned user (excluding the author).
- Mentions never bypass entity access. Notifications carry minimal context and a deep link; whether the recipient can open the entity is governed by the existing access rules.

## User Stories

1. As a comment author, I see the same role list in the comment audience picker that I see in the workflow designer (with the same labels and "no groups" hint), so the two surfaces stay consistent.
2. As a comment author, I can pick one or more roles for the audience, and only people whose effective app role matches receive the comment in their timeline.
3. As an admin renaming a role in settings, comments previously targeted at that role still reach the right people because the audience stores a stable role identifier.
4. As a Data Producer whose groups map to a producer role, comments addressed to that role appear in my timeline regardless of any team-level role override I happen to carry.
5. As an admin testing the app via the existing role override, role-based audience visibility follows the override, mirroring how feature permissions already behave.
6. As a user with no matching role, role-scoped comments stay out of my timeline.
7. As a comment author, I can pick `Owner` as an audience, and the entity's current owners receive the comment without me having to look up their emails.
8. As an entity owner, comments addressed to `Owner` appear in my timeline when I open the entity; when I am no longer owner, future owner-scoped comments stop reaching me.
9. As a non-owner, owner-only comments are hidden from me unless an existing rule (such as admin) already lets me see all comments on the entity.
10. As a comment author on an entity with no assigned owner, picking `Owner` is allowed but the UI tells me the comment will reach no one specifically and that owners assigned later will see it.
11. As a comment author, I can combine teams, roles, and `Owner` in one audience to address, for example, "this squad and the Data Steward role and the entity owners."
12. As a project member, leaving the audience empty keeps today's behaviour: anyone with access to the entity in the current project context can see the comment.
13. As a comment author, when I edit a comment my previously chosen teams, roles, owner flag, and mentions are preselected so I can adjust without rebuilding the audience.
14. As a timeline reader, audience chips show human-readable labels (role name, team name, `Owner`) regardless of which token shape the comment was stored in.
15. As a comment author writing the body, typing `@` opens a picker filtered by the people on my current project's teams; selecting one inserts a recognisable mention into the text.
16. As a comment author, when the person I want to tag is not in the picker, I can type their full email address after `@` and it is treated as a mention.
17. As a comment author, mentioning the same person twice in one comment yields exactly one notification for that person.
18. As a comment author, mentioning myself does not generate a notification for me.
19. As a mentioned user, I receive an in-app notification titled in a way that tells me I was mentioned, names the entity, and links me to it.
20. As a mentioned user who does not have access to the entity, the notification still arrives but contains no excerpt of the comment body, only the entity reference and the fact that I was mentioned; the link returns the standard access-denied page if I follow it.
21. As an editor of a comment, only newly added mentions trigger notifications on save; people who were already mentioned in the previous version are not re-notified.
22. As a timeline reader, mentioned identities in the rendered comment body are visually distinct from surrounding text so I can scan long threads.
23. As a keyboard user, I can open the `@` picker, navigate, and confirm a selection without using the mouse.
24. As a support engineer, when notification creation fails for a mention, the failure is logged with enough context to diagnose without writing the comment body or recipient identifiers in clear text into long-lived logs.

## Implementation Decisions

### Modules touched

- **Comment list/timeline read path** (route, manager, repository): change the inputs the manager passes for visibility evaluation; extend the OR-clauses the repository builds for audience matching.
- **Comment composer and timeline UI** (sidebar variant and embedded variant): switch the role source, add the owner option, render new badges, hydrate edit form. The two existing variants share enough logic that the audience option loading and badge rendering are extracted to a small shared hook/component to prevent drift.
- **Notification fan-out on comment write** (comment route or manager, depending on where transactional commit lives today): parse mentions, deduplicate, exclude author, call the existing notifications manager once per recipient.
- **Optional mention-candidates endpoint**: only added if the project teams payload the UI already loads does not expose member emails; otherwise the UI builds the candidate list client-side.

### Audience model

- Audience remains a list of opaque string tokens stored against the comment. New token literals: `role_id:<uuid>` and `owner`. Existing literals (`team:<id>`, `role:<name>`, plain group names, `user:<email>`) keep working as a read-side fallback. New writes prefer `role_id:` over `role:`.
- "User matches a role audience" is decided server-side by the union of: roles whose assigned groups intersect the user's groups (case-insensitive, the same calculation the permissions stack already uses), plus the user's currently applied role override if any. Team-level role overrides may contribute additional matches but never replace the group-derived set.
- "User matches `owner`" is decided by looking up active business owners for the comment's `entity_type`/`entity_id` and checking the reader's email against that list. Owner lookup happens once per list call and is reused across rows.

### @-mention model

- The wire format inside the comment body is the literal email surrounded by an `@` prefix and word boundaries (e.g. `@jane.doe@company.com`). The server uses a single regex to extract candidates and validates each against an email shape. No structured marker is stored; this keeps the field plain text and avoids a migration.
- Notification payload contains: title ("You were mentioned"), entity type and entity name (where derivable cheaply), a deep link if the product already has a stable URL pattern for that entity type, and—only if the recipient passes the same access check the comment list endpoint uses—a short excerpt. Otherwise no excerpt.
- On update, the manager diffs the mention set against the previous version and notifies only added recipients. Removed mentions do not produce a notification.

### Compatibility and migration

- No schema migration. All new behaviour is additive on top of the existing audience JSON column and notifications table.
- A one-time backfill rewriting `role:<name>` into `role_id:<uuid>` is explicitly out of scope; the read path handles both indefinitely.

## Testing Decisions

- **Audience resolution** is covered by manager-level tests that set up: users with defined group→role mappings, an active business-owner assignment, and stored comments with various audience token shapes (legacy `role:`, new `role_id:`, `team:`, `owner`, `user:`, plain group, mixed). Assertions are on the set of comment IDs returned, not on SQL.
- **Mention fan-out** is covered by route or manager tests that post a comment containing zero, one, several, and duplicate mentions, with the notifications manager replaced by a spy/fake. Assertions are on the count and recipient set of notifications created. Update tests assert the diff behaviour.
- **Backwards compatibility** is asserted by seeding pre-existing comments with legacy tokens and confirming the same readers see them after the change.
- Frontend changes are covered by component tests around the composer's audience hydration on edit and the `@` picker's keyboard navigation. Visual regression is not in scope.
- Prior art: existing comment manager/repository tests and existing notification tests already mock the notifications dependency; new tests follow that pattern.

## Out of Scope

- Workspace-wide user directory search (SCIM-style lookup across the whole workspace).
- Email, Slack, Teams, or webhook delivery of mention notifications. In-app only.
- Rich-text comments, threading/replies, reactions, or real-time presence.
- Backfill rewriting legacy audience tokens to the new identifier format.
- Changing which users may author, edit, or moderate comments.
- Mentioning roles, teams, or groups via `@` (audience picker covers that).
- Localisation of new strings beyond following whatever pattern the comment composer already uses today.

## Further Notes

- The product decision on mentions to users without entity access is to **notify with minimal payload, no body excerpt, link still rendered**. This keeps the social signal working without leaking content. Security review can flip this to "suppress" before launch if needed; the manager exposes the check as a single function so the policy is one line of code.
- The `Owner` audience does not currently include role-typed business owners as a separate concept; it resolves to the email list of all active assignments for the entity. If a future audience needs "owners of role X," that is an additive token (`owner_role:<role_id>`) and not part of this PRD.
- Performance: the additional owner lookup is one query per timeline call (cached for the request), and audience matching adds OR-clauses bounded by the number of roles the user holds. No new indexes are anticipated; revisit if a single entity ever holds tens of thousands of comments.
