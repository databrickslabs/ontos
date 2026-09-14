---
sidebar_position: 2
id: teams
title: team
description: Manage teams, team membership, and the domains a team belongs to.
---

# Team

Teams group users and Databricks groups so they can own domains, projects, contracts, and products. A team may be assigned to any number of data domains (one marked primary), or to none at all — a *standalone* team.

**Swagger tag:** `Teams` &nbsp;·&nbsp; **Feature ID:** `teams` &nbsp;·&nbsp; **Route prefix:** `/api/teams`

## Operations

### Teams

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/teams` | Create a team | `Read/Write` |
| `GET` | `/api/teams` | List teams, optionally filtered by domain | `Read-only` |
| `GET` | `/api/teams/summary` | Lightweight team list for pickers | `Read-only` |
| `GET` | `/api/teams/standalone` | List teams with no domain assignment | `Read-only` |
| `GET` | `/api/teams/{team_id}` | Get a team by ID | `Read-only` |
| `PUT` | `/api/teams/{team_id}` | Update a team | `Read/Write` |
| `DELETE` | `/api/teams/{team_id}` | Delete a team | `Admin` |

### Team members

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/teams/{team_id}/members` | Add a member | `Read/Write` |
| `GET` | `/api/teams/{team_id}/members` | List members | `Read-only` |
| `PUT` | `/api/teams/{team_id}/members/{member_id}` | Update a member | `Read/Write` |
| `DELETE` | `/api/teams/{team_id}/members/{member_identifier}` | Remove a member | `Read/Write` |

### Caller-scoped and domain-scoped

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/user/teams` | Teams the current user belongs to | Authenticated |
| `GET` | `/api/domains/{domain_id}/teams` | Teams assigned to a domain | `teams` — `Read-only` |

## Create a team

```http
POST /api/teams
```

**Authorization:** `teams` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Unique team name. Minimum length 1. |
| `title` | `string` | No | Display title. |
| `description` | `string` | No | Free-text description. |
| `domain_ids` | `string[]` | No | All assigned domain IDs, primary included. Defaults to an empty list (standalone team). |
| `primary_domain_id` | `string` | No | Which of `domain_ids` is the primary domain. |
| `tags` | `AssignedTagCreate[]` | No | Rich tags. See [Tags](./tags#assigned-tag-payloads). |
| `metadata` | `object` | No | Arbitrary metadata (links, images, and so on). |

```json
{
  "name": "customer-data-platform",
  "title": "Customer Data Platform",
  "description": "Owns customer master data pipelines and contracts",
  "domain_ids": [
    "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
    "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
  ],
  "primary_domain_id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "metadata": { "wiki": "https://wiki.example.com/cdp" }
}
```

### Response

`201 Created` — a `TeamRead` object.

```json
{
  "id": "3a4b5c6d-7e8f-9012-3456-789abcdef012",
  "name": "customer-data-platform",
  "title": "Customer Data Platform",
  "description": "Owns customer master data pipelines and contracts",
  "domain_ids": ["8f2b1c34-…", "0a1b2c3d-…"],
  "primary_domain_id": "8f2b1c34-…",
  "domains": [
    { "domain_id": "8f2b1c34-…", "domain_name": "customer-360", "is_primary": true,  "assigned_by": "alice@example.com", "assigned_at": "2026-08-05T10:20:00Z" },
    { "domain_id": "0a1b2c3d-…", "domain_name": "marketing",    "is_primary": false, "assigned_by": "alice@example.com", "assigned_at": "2026-08-05T10:20:00Z" }
  ],
  "members": [],
  "tags": [],
  "metadata": { "wiki": "https://wiki.example.com/cdp" },
  "created_at": "2026-08-05T10:20:00Z",
  "updated_at": "2026-08-05T10:20:00Z",
  "created_by": "alice@example.com",
  "updated_by": "alice@example.com"
}
```

### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | A team with that name already exists. |

## List teams

```http
GET /api/teams
```

Lists all teams, optionally narrowed to one or more domains. Domain filtering is *any-of*: a team matches when it is assigned to at least one of the requested domains.

**Authorization:** `teams` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. |
| `domain_id` | `string` | — | Filter by a single domain ID. |
| `domain_ids` | `string` | — | Filter by multiple domain IDs, comma-separated. |

```bash
# Teams in either of two domains
curl -s "$ONTOS_URL/api/teams?domain_ids=8f2b1c34-…,0a1b2c3d-…" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — an array of `TeamRead` objects.

## List teams (summary)

```http
GET /api/teams/summary
```

Returns a lightweight projection intended for dropdowns and pickers — no members or tags are loaded.

**Authorization:** `teams` — `Read-only`

### Query parameters

| Name | Type | Description |
| --- | --- | --- |
| `domain_id` | `string` | Filter by a single domain ID (any-of). |
| `domain_ids` | `string` | Filter by multiple domain IDs, comma-separated (any-of). |

### Response

`200 OK` — an array of `TeamSummary` objects.

```json
[
  {
    "id": "3a4b5c6d-…",
    "name": "customer-data-platform",
    "title": "Customer Data Platform",
    "domain_ids": ["8f2b1c34-…"],
    "primary_domain_id": "8f2b1c34-…",
    "member_count": 7
  }
]
```

## List standalone teams

```http
GET /api/teams/standalone
```

Returns teams that are not assigned to any data domain.

**Authorization:** `teams` — `Read-only`

### Response

`200 OK` — an array of `TeamRead` objects.

## Get a team

```http
GET /api/teams/{team_id}
```

**Authorization:** `teams` — `Read-only`

### Response

`200 OK` — a `TeamRead` object with `domains` and `members` populated.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No team with that ID. |

## Update a team

```http
PUT /api/teams/{team_id}
```

Partial update — omitted fields are left unchanged.

**Authorization:** `teams` — `Read/Write`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | New team name. |
| `title` | `string` | New display title. |
| `description` | `string` | New description. |
| `domain_ids` | `string[]` | **Replace-all** set of assigned domain IDs. Omit to leave the assignments unchanged; send `[]` to make the team standalone. |
| `primary_domain_id` | `string` | New primary domain ID. Must be one of `domain_ids`. |
| `tags` | `AssignedTagCreate[]` | Replaces the current tag set. |
| `metadata` | `object` | New metadata object. |

:::caution
`domain_ids` is replace-all, not additive. Sending a partial list removes the domains you leave out.
:::

### Response

`200 OK` — the updated `TeamRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No team with that ID. |
| `409 Conflict` | The new name collides with an existing team. |

## Delete a team

```http
DELETE /api/teams/{team_id}
```

**Authorization:** `teams` — `Admin`

### Response

`200 OK` — the deleted `TeamRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No team with that ID. |

## Add a team member

```http
POST /api/teams/{team_id}/members
```

Adds a user or a Databricks group to the team.

**Authorization:** `teams` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `member_type` | `"user" \| "group"` | Yes | Whether the member is an individual user or a group. |
| `member_identifier` | `string` | Yes | Email for a user, group name for a group. Minimum length 1. |
| `app_role_override` | `string` | No | Overrides the app role this member would otherwise inherit from their groups. |

```json
{
  "member_type": "user",
  "member_identifier": "bob@example.com",
  "app_role_override": "Data Steward"
}
```

### Response

`201 Created` — a `TeamMemberRead` object.

```json
{
  "id": "9f8e7d6c-…",
  "team_id": "3a4b5c6d-…",
  "member_type": "user",
  "member_identifier": "bob@example.com",
  "member_name": "bob@example.com",
  "app_role_override": "Data Steward",
  "created_at": "2026-08-05T10:31:00Z",
  "updated_at": "2026-08-05T10:31:00Z",
  "added_by": "alice@example.com"
}
```

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No team with that ID. |
| `409 Conflict` | That member is already on the team. |

## List team members

```http
GET /api/teams/{team_id}/members
```

**Authorization:** `teams` — `Read-only`

### Response

`200 OK` — an array of `TeamMemberRead` objects.

## Update a team member

```http
PUT /api/teams/{team_id}/members/{member_id}
```

Only the app role override can be changed. To change the member's type or identifier, remove the member and add them again.

**Authorization:** `teams` — `Read/Write`

### Path parameters

| Name | Type | Description |
| --- | --- | --- |
| `team_id` | `string` | ID of the team. |
| `member_id` | `string` | ID of the membership record (`TeamMemberRead.id`). |

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `app_role_override` | `string` | New app role override. Send `null` to clear it. |

### Response

`200 OK` — the updated `TeamMemberRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | Team or member not found. |

## Remove a team member

```http
DELETE /api/teams/{team_id}/members/{member_identifier}
```

**Authorization:** `teams` — `Read/Write`

### Path parameters

| Name | Type | Description |
| --- | --- | --- |
| `team_id` | `string` | ID of the team. |
| `member_identifier` | `string` | The member's email (users) or group name (groups) — **not** the membership record ID. |

:::note
Removal is keyed on `member_identifier`, while [update](#update-a-team-member) is keyed on the membership record's `member_id`. URL-encode identifiers that contain reserved characters.
:::

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | That member is not on the team. |

## List the current user's teams

```http
GET /api/user/teams
```

Returns every team the authenticated caller is a member of, resolved through both direct user memberships and their Databricks group memberships.

**Authorization:** Authenticated caller — no feature permission required.

### Response

`200 OK` — an array of `TeamRead` objects.

## List teams in a domain

```http
GET /api/domains/{domain_id}/teams
```

Returns all teams assigned to a specific domain. Equivalent to `GET /api/teams?domain_id={domain_id}`.

**Authorization:** `teams` — `Read-only`

### Response

`200 OK` — an array of `TeamRead` objects.

## See also

- [Projects API](./projects) — assigning teams to projects.
- [Data Domains API](./data_domains) — the domains teams are assigned to.
- [Projects and Teams](../../user_guide/basic_elements) — the user-facing guide.
