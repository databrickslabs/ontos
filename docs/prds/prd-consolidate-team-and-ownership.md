# PRD: Consolidate Team and Ownership Model

## Concept Model

Four governance primitives are involved in this consolidation. Disambiguating them is a prerequisite for the UI cleanup:

- **Principals** — users or groups, backed by manual entries or the Directory feature. The atomic identity unit referenced by all other constructs.
- **Projects** — group work into distinct units; define visibility/accessibility of entities by principals. Optional — entities without a project default to visible to all principals.
- **Teams** — a set of principals with optional role overrides (e.g., a Data Engineer working as a Data Steward for objects assigned to that team). Teams are optional — entities without a team can only be modified by the owner and admins directly. Teams can also be populated from the original ODCS/ODPS record during import.
- **Owners** — a polymorphic list of principals with a business role assigned to an entity. Owners can be assigned manually by the owner/admin, copied (even partially) from the Team to the entity, or imported from the original ODCS/ODPS owners/team information.

These are distinct from the ODCS/ODPS "team" section in a contract/product YAML, which is an imported metadata array of contacts — not the Ontos Team governance entity.

## Problem Statement

Data Products and Data Contracts currently surface "who is responsible" through three independent, uncoordinated mechanisms:

1. **Contacts** (sidebar card) — filters the ODCS/ODPS `team.members` for owner-type roles and displays them as quick-reference contacts.
2. **ODCS/ODPS Team** section (main content) — the imported `team.members` array, editable, with roles like "owner", "data steward", "contributor".
3. **Ownership Panel** (main content) — reads from the polymorphic `business_owners` table, supports role assignment, lifecycle tracking (assigned_at, removed_at, history), and works across all entity types.

Additionally, the metadata grid labels the assigned **Ontos Team** as "Owner:" — which conflicts with the Ownership Panel that tracks actual business owners. The tooltip says "Team ID: ..." and the link navigates to `/teams/:id`, yet the label says "Owner", creating confusion.

These surfaces are fully decoupled: you can have Alice in the ODCS/ODPS Team section but Carol/Frank/Eva as Business Owners, while the "Owner:" label in the header points to a completely different Ontos Team entity. Users must mentally reconcile three separate concepts.

When exporting to ODCS/ODPS YAML, only the imported Team section is written — any ownership changes made via the Ownership Panel are lost.

## Solution

Make **Business Owners** (the `business_owners` table) the single authoritative source for "who is responsible for this entity." The ODCS/ODPS Team data is preserved as read-only import provenance. A unified "People & Ownership" card replaces the separate Team and Ownership Panel sections. On YAML export, active Business Owners are merged into the Team section for standards compliance.

The sidebar Contacts card switches to pulling from Business Owners instead of Team members, ensuring consistency between the quick-reference and the detailed view.

## User Stories

### Label and layout clarity

1. As a Data Steward, I want the metadata grid to label the assigned Ontos Team as "Team" (not "Owner"), so that I do not confuse the team assignment with individual business owners.
2. As a Data Steward, I want to see the Project and Team assignments together in the metadata grid, so that I understand the governance context (who manages it + what scope it belongs to) at a glance.

### Ownership consolidation

3. As a Data Producer, I want a single, unambiguous list of who owns and manages my Data Product, so that I do not need to reconcile two separate panels (ODCS/ODPS Team vs Owners).
4. As a Data Consumer, I want the sidebar Contacts to always reflect the current authoritative owners, so that I know who to reach out to without checking multiple sections.
5. As a Data Steward, I want to assign owners with lifecycle tracking (assigned date, removal date, removal reason, history), so that I have a full audit trail of ownership changes over time.
6. As a Data Steward, I want to see who was imported from an ODCS/ODPS YAML Team section, so that I retain provenance of the original contract/product metadata.
7. As a Data Steward, I want a one-click "Import as Owners" action that converts imported ODCS/ODPS Team members into Business Owner records, so that I do not have to re-enter the same people manually.
8. As a Data Steward, I want to copy selected Ontos Team members to the Owners panel, so that I can bootstrap ownership from the assigned team without re-entering each person.
9. As a Data Producer, I want the YAML export to include my current Business Owners merged into the Team section, so that downstream consumers of the YAML see up-to-date ownership without manual synchronization.
10. As a Data Producer, I want ODCS/ODPS Team members from the original YAML who are NOT current Business Owners to still appear in the exported Team section, so that contributor-level team members are not lost.
11. As a Data Steward importing an existing ODCS contract YAML, I want the Team section to be stored verbatim as read-only provenance, so that round-trip fidelity is preserved.
12. As a Data Producer, I want to see the imported ODCS/ODPS Team data collapsed by default with a member count, so that it does not clutter the interface when I primarily work with the Owners section.
13. As an Admin, I want ownership roles (Data Owner, Technical Owner, Business Sponsor, etc.) to be consistent across Data Products, Data Contracts, and all other entity types, so that reporting on ownership is uniform.
14. As a Data Consumer viewing the sidebar, I want to see owner-role contacts (Data Owner, Technical Owner, Business Sponsor) pulled from Business Owners, so that I always see the authoritative responsible parties.
15. As a Data Consumer, I want a fallback to ODCS/ODPS Team members if no Business Owners exist yet (e.g., freshly imported contract), so that Contacts is never empty when people are known.
16. As a Data Steward, I want the "Import as Owners" flow to suggest role mappings (e.g., ODCS role "owner" maps to Business Role "Data Owner"), so that I can review and confirm before committing.
17. As a Data Producer, I want to still be able to view and expand the original imported ODCS/ODPS Team data, so that I can reference who was originally specified in the external YAML.
18. As an Admin, I want the ODCS/ODPS Team section to become read-only after consolidation, so that there is no ambiguity about which list to edit.

## Implementation Decisions

### Label cleanup

**Rename "Owner:" to "Team:" in the metadata grid:**
- The metadata grid currently displays `owner_team_name` under the label "Owner:" — this is misleading because it refers to the Ontos Team entity, not a business owner person.
- Change the label to "Team:" on both Data Contract and Data Product detail pages.
- Both already navigate to `/teams/:id` and show tooltip "Team ID: ..." — only the label text needs updating.

**Group Project and Team together in the metadata grid:**
- Currently Project and Team (labeled "Owner:") are separated by other fields (Domain, Tenant, etc.).
- Move them adjacent to each other so the governance context (Team + Project) is visible as a pair.
- Suggested order in the metadata grid row: Domain, Team, Project (or Team and Project on the same line).

### Source of truth

- `business_owners` table (polymorphic, with `object_type` + `object_id`) is the single authoritative source for ownership across all entity types.
- The ODCS/ODPS Team (`data_contract_team` table / `product.team.members` JSON) is preserved as-is but becomes read-only in the UI. It serves as import provenance.
- The Ontos Team entity (`teams` table, referenced via `owner_team_id`) remains the governance team assignment — it controls access/permissions and provides a pool of principals that can be copied to the Owners panel.

### Unified "People & Ownership" card

- Replaces the separate ODCS/ODPS Team section and OwnershipPanel with a single card.
- Top section: "Owners" — the current OwnershipPanel functionality (assign, remove, history toggle). Owners can be assigned manually, copied from the Ontos Team, or imported from the ODCS/ODPS data.
- Bottom section: "Imported Contacts (from ODCS/ODPS)" — read-only, collapsed by default showing member count. Expandable to see all original ODCS/ODPS Team members with their roles. This preserves provenance of imported YAML data.
- "Import as Owners" button in the Imported Contacts section: creates Business Owner records from ODCS/ODPS Team members with a role-mapping confirmation dialog.
- "Copy from Team" action in the Owners section: allows copying selected members from the assigned Ontos Team into the Owners panel with role selection.

### Sidebar Contacts changes

- Pulls from `business_owners` (active records with owner-type role IDs) instead of `team.members`.
- Fallback chain: (1) active Business Owners, (2) ODCS/ODPS `team.members` filtered by owner-type roles, (3) Ontos Team name as last resort. This ensures Contacts is never empty when people are known, regardless of migration status.

### YAML export merge strategy

- Start with original `team.members` as base.
- For each active Business Owner: check if a matching Team member exists (by email/username). If yes, update the role. If no, add as new Team member.
- Team members not present in Business Owners are preserved (they may be contributors).
- Mapping from BusinessRole name to ODCS/ODPS role string is maintained in a configuration map.

### Import behavior

- On YAML import, ODCS/ODPS Team data is stored verbatim (no change from today).
- No automatic creation of Business Owner records. The user is shown the Imported Contacts section with an "Import as Owners" button.
- The role-mapping dialog shows a table: ODCS/ODPS member username/name, their role, suggested Business Role, with ability to override or skip individual members.
- Separately, when an Ontos Team is assigned to the entity, the user can "Copy from Team" to create Owner records from Team members — this is a distinct action from importing ODCS/ODPS contacts.

### ODCS/ODPS Team editability

- The ODCS/ODPS Team section (now labeled "Imported Contacts") becomes read-only in the UI after this change.
- The "Add Member" and edit/delete buttons are removed from this section.
- All people-management goes through the Owners section (Assign Owner / Remove Owner / Copy from Team).
- The underlying `data_contract_team` / `product.team` data is still writable via API for programmatic use (e.g., YAML import), but the UI does not expose editing.

### Terminology disambiguation

To avoid confusion between the Ontos Team entity and the ODCS/ODPS team metadata:
- The metadata grid field is labeled **"Team:"** (links to the Ontos Team entity page)
- The collapsed provenance section is labeled **"Imported Contacts (from ODCS/ODPS)"** (not "Team")
- The "Import from Team" button (which copies Ontos Team members into ODCS/ODPS data) is renamed or removed — its functionality is superseded by "Copy from Team" which creates Owners directly
- API and code comments distinguish: `owner_team_id` (Ontos Team FK), `data_contract_team` (ODCS imported contacts), `business_owners` (authoritative owners)

### Scope

- Applies to Data Products and Data Contracts initially (the two entity types that have both Team and Owners today).
- Other entity types (glossaries, datasets, etc.) already only have OwnershipPanel — no change needed for them.

### Backend endpoints

- New endpoint: `POST /api/business-owners/import-from-team` — accepts `object_type`, `object_id`, and a list of `{username, suggested_role_id}` mappings. Creates Business Owner records in bulk. Works for both ODCS/ODPS team imports and Ontos Team member copies.
- Existing YAML export endpoints gain merge logic: when serializing Team for YAML output, merge active Business Owners into the team array.

## Testing Decisions

### What makes a good test

Tests verify externally observable behavior through public interfaces. They should not test wiring between components but rather the end-to-end effect of a user action (e.g., "after importing team as owners, the GET owners endpoint returns the imported members with correct roles").

### Modules to test

- **Import-from-team endpoint**: POST with valid/invalid mappings, duplicate detection, role resolution.
- **YAML export merge logic**: various scenarios (no owners, owners matching team, owners not in team, team members not in owners).
- **Sidebar contacts API behavior**: returns Business Owners when they exist, falls back to Team members when they don't.
- **OwnershipPanel component**: renders owners section, renders collapsed imported team, expand/collapse behavior, import dialog interaction.

### Prior art

- `test_business_owners_routes.py` — existing Business Owners endpoint tests.
- `test_data_contracts_routes.py` — contract CRUD and team member tests.
- Ownership panel component tests (if they exist).

## Out of Scope

- **Deleting the ODCS/ODPS Team data model or tables.** The `data_contract_team` table and `product.team` JSON field remain for backward compatibility and YAML round-trip fidelity.
- **Changing the Ontos Team or Project entities.** Teams and Projects are unaffected structurally — only the UI label ("Owner:" → "Team:") and layout (grouping with Project) change.
- **Automatic bidirectional sync.** Changes to Owners do NOT auto-update the stored ODCS/ODPS Team data (only export merges them). Changes to ODCS/ODPS Team (via API/import) do NOT auto-create Owners.
- **Migration of existing data.** Existing ODCS/ODPS Team members are not automatically converted to Business Owners. Users migrate on their own schedule via the "Import as Owners" button.
- **Owner-type role taxonomy changes.** The existing Business Roles (Data Owner, Technical Owner, Business Sponsor) are used as-is. Adding new roles is a separate concern.
- **Other entity types beyond Data Products and Data Contracts.** Glossaries, datasets, etc., already only use OwnershipPanel.
- **Removing the `owner_team_id` / `owner_team_name` field.** This stays as the Team assignment (now labeled "Team:" instead of "Owner:").

## Further Notes

### Relationship to existing features

- **OwnershipPanel** (`src/frontend/src/components/common/ownership-panel.tsx`): Extended with an optional "Imported Contacts" sub-section and "Copy from Team" action rather than replaced.
- **Business Owners API** (`/api/business-owners/`): Gains a new bulk-import endpoint.
- **Data Contract YAML export** (`data_contracts_manager.py`): Export logic enhanced with merge step.
- **Data Product YAML export** (if applicable): Same merge logic.
- **Ontos Teams** (`/api/teams`): Unchanged structurally. The only change is the UI label from "Owner:" to "Team:" in the metadata grid.
- **Projects** (`/api/projects`): Unchanged structurally. Only the layout position in the metadata grid changes (moved adjacent to Team).

### Migration path

- The UI change is non-breaking: existing ODCS/ODPS Team data remains visible (just read-only and collapsed under "Imported Contacts").
- Users see a clear prompt to "Import as Owners" when viewing entities with imported contacts but no Business Owners.
- No forced migration — entities can remain in the "imported contacts only" state indefinitely, with Contacts falling back to ODCS/ODPS team members.
- The "Owner:" → "Team:" label rename is purely cosmetic and requires no data migration.

### Resolved decisions

- **No banner/toast for "Import as Owners"** — the action remains manual via the collapsible section. Users discover it organically.
- **No bulk migration tool** — migration happens per-entity at the user's pace.
- **Yes — sidebar fallback indicator** — when the Contacts card shows imported ODPS/ODCS team members (tier 2) or team-name-only (tier 3), a subtle muted description appears below the title (e.g., "From imported data" / "Team assignment only") so users know these are provisional, not confirmed business owners.
- **Remove old "Import from Team" button** — the button that copied Ontos Team members into the ODCS/ODPS team array is removed since that section is now read-only. The "Copy from Team" action in the Owners panel (which creates Business Owner records) remains as the correct flow for assigning team principals as owners.
