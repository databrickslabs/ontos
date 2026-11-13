# Release notes fragments

Each PR adds one file here instead of editing `src/docs/RELEASE_NOTES.md`, so two PRs
never touch the same path. Fragments are written into `RELEASE_NOTES.md` at release time.

Add `unreleased/<section>/<slug>.md` with exactly one bullet entry:

```markdown
- **workflows**: Pass and Fail steps now end a run. What to check: ...
```

- Sections (folders): `upgrade-notes`, `features`, `bug-fixes`, `documentation`,
  `performance`, `refactoring`, `testing`, `maintenance`, `other`.
- File name: a unique slug such as the branch or feature name (`[a-z0-9][a-z0-9-]*.md`),
  not the PR number.
- Content: one entry starting with `- ` (style `- **area**: text`). Continuation lines are
  fine; no headings, no blank lines and no second top-level bullet.
- A change that needs an upgrade note gets a second fragment in `upgrade-notes`, ending
  with a "What to check:" line.
- PRs with no user-visible change use the `no-release-notes` label.

Check your files: `python3 src/scripts/assemble_release_notes.py --check`.
See the result: `python3 src/scripts/assemble_release_notes.py --preview`.
