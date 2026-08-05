---
sidebar_position: 3
id: projects
title: project
description: Manage projects, their assigned teams, and the caller's project context and access requests.
---

# Project

Projects scope work across teams. A project is owned by one team, may have additional teams assigned to it, and acts as a visibility boundary for data contracts and data products. Users see a project when they belong to one of its assigned teams.

**Swagger tag:** `Projects` &nbsp;·&nbsp; **Feature ID:** `projects` &nbsp;·&nbsp; **Route prefix:** `/api/projects`

## Operations

### Projects

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/projects` | Create a project | `Read/Write` |
| `GET` | `/api/projects` | List projects visible to the caller | `Read-only` |
| `GET` | `/api/projects/summary` | Lightweight project list for pickers | `Read-only` |
| `GET` | `/api/projects/{project_id}` | Get a project by ID | `Read-only` |
| `PUT` | `/api/projects/{project_id}` | Update a project | `Read/Write` |
| `DELETE` | `/api/projects/{project_id}` | Delete a project | `Admin` |

### Project teams

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/projects/{project_id}/teams` | Assign a team to a project | `Read/Write` |
| `GET` | `/api/projects/{project_id}/teams` | List teams assigned to a project | `Read-only` |
| `DELETE` | `/api/projects/{project_id}/teams/{team_id}` | Remove a team from a project | `Read/Write` |

### Caller-scoped

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/user/projects` | Projects the caller can access | Authenticated |
| `POST` | `/api/user/current-project` | Set the caller's active project | Authenticated |
| `POST` | `/api/user/request-project-access` | Request access to a project | Authenticated |

## Create a project

```http
POST /api/projects
```

**Authorization:** `projects` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Unique project name. Minimum length 1. |
| `title` | `string` | No | Display title. |
| `description` | `string` | No | Free-text description. |
| `owner_team_id` | `string` | No | UUID of the team that manages this project. |
| `project_type` | `string` | No | `PERSONAL` or `TEAM`. |
| `team_ids` | `string[]` | No | Teams to assign to the project at creation time. |
| `tags` | `AssignedTagCreate[]` | No | Rich tags. See [Tags](./tags#assigned-tag-payloads). |
| `metadata` | `object` | No | Arbitrary metadata (links, images, and so on). |

```json
{
  "name": "customer-360-migration",
  "title": "Customer 360 Migration",
  "description": "Migrate customer master data onto the new contract model",
  "owner_team_id": "3a4b5c6d-7e8f-9012-3456-789abcdef012",
  "project_type": "TEAM",
  "team_ids": [
    "3a4b5c6d-7e8f-9012-3456-789abcdef012",
    "5d6e7f80-9012-3456-789a-bcdef0123456"
  ]
}
```

### Response

`201 Created` — a `ProjectRead` object.

```json
{
  "id": "7c8d9e0f-1234-5678-9abc-def012345678",
  "name": "customer-360-migration",
  "title": "Customer 360 Migration",
  "description": "Migrate customer master data onto the new contract model",
  "owner_team_id": "3a4b5c6d-…",
  "owner_team_name": "customer-data-platform",
  "project_type": "TEAM",
  "teams": [
    { "id": "3a4b5c6d-…", "name": "customer-data-platform", "title": "Customer Data Platform", "team_count": 0, "member_count": 7 }
  ],
  "tags": [],
  "metadata": null,
  "created_at": "2026-08-05T11:02:00Z",
  "updated_at": "2026-08-05T11:02:00Z",
  "created_by": "alice@example.com",
  "updated_by": "alice@example.com"
}
```

### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | A project with that name already exists. |

## List projects

```http
GET /api/projects
```

Lists projects visible to the caller based on their team and domain relationships. Administrators see all projects.

**Authorization:** `projects` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. |

### Response

`200 OK` — an array of `ProjectRead` objects.

## List projects (summary)

```http
GET /api/projects/summary
```

Returns a lightweight projection intended for dropdowns and pickers.

**Authorization:** `projects` — `Read-only`

### Response

`200 OK` — an array of `ProjectSummary` objects.

```json
[
  {
    "id": "7c8d9e0f-…",
    "name": "customer-360-migration",
    "title": "Customer 360 Migration",
    "team_count": 2
  }
]
```

## Get a project

```http
GET /api/projects/{project_id}
```

**Authorization:** `projects` — `Read-only`

### Response

`200 OK` — a `ProjectRead` object with `teams` populated.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No project with that ID. |

## Update a project

```http
PUT /api/projects/{project_id}
```

Partial update — omitted fields are left unchanged.

**Authorization:** `projects` — `Read/Write`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | New project name. |
| `title` | `string` | New display title. |
| `description` | `string` | New description. |
| `owner_team_id` | `string` | New owning team UUID. |
| `project_type` | `string` | `PERSONAL` or `TEAM`. |
| `tags` | `AssignedTagCreate[]` | Replaces the current tag set. |
| `metadata` | `object` | New metadata object. |

:::note
Team assignments are not changed through this operation. Use [`POST /api/projects/{project_id}/teams`](#assign-a-team-to-a-project) and [`DELETE /api/projects/{project_id}/teams/{team_id}`](#remove-a-team-from-a-project).
:::

### Response

`200 OK` — the updated `ProjectRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No project with that ID. |
| `409 Conflict` | The new name collides with an existing project. |

## Delete a project

```http
DELETE /api/projects/{project_id}
```

**Authorization:** `projects` — `Admin`

### Response

`200 OK` — the deleted `ProjectRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No project with that ID. |

## Assign a team to a project

```http
POST /api/projects/{project_id}/teams
```

**Authorization:** `projects` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team_id` | `string` | Yes | ID of the team to assign. |

```json
{ "team_id": "5d6e7f80-9012-3456-789a-bcdef0123456" }
```

### Response

`201 Created`

```json
{ "message": "Team assigned to project successfully" }
```

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | Project or team not found. |
| `409 Conflict` | That team is already assigned to the project. |

## List teams assigned to a project

```http
GET /api/projects/{project_id}/teams
```

**Authorization:** `projects` — `Read-only`

### Response

`200 OK` — an array of team objects.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No project with that ID. |

## Remove a team from a project

```http
DELETE /api/projects/{project_id}/teams/{team_id}
```

**Authorization:** `projects` — `Read/Write`

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | That team is not assigned to the project. |

## List the caller's projects

```http
GET /api/user/projects
```

Returns every project the authenticated caller can access, together with the caller's currently selected project.

**Authorization:** Authenticated caller — no feature permission required.

### Response

`200 OK` — a `UserProjectAccess` object.

| Field | Type | Description |
| --- | --- | --- |
| `projects` | `ProjectSummary[]` | Projects the caller has access to. |
| `current_project_id` | `string \| null` | The caller's currently selected project. |

```json
{
  "projects": [
    { "id": "7c8d9e0f-…", "name": "customer-360-migration", "title": "Customer 360 Migration", "team_count": 2 }
  ],
  "current_project_id": "7c8d9e0f-…"
}
```

## Set the caller's current project

```http
POST /api/user/current-project
```

Sets the active project context for the caller's session. Access is verified first: non-administrators must belong to a team assigned to the project.

**Authorization:** Authenticated caller — no feature permission required.

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `project_id` | `string \| null` | Project to activate. Send `null` to clear the project context. |

```json
{ "project_id": "7c8d9e0f-1234-5678-9abc-def012345678" }
```

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `403 Forbidden` | The caller does not have access to that project. |

## Request access to a project

```http
POST /api/user/request-project-access
```

Sends a notification to the members of the project's teams asking them to grant the caller access.

**Authorization:** Authenticated caller — no feature permission required.

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `project_id` | `string` | Yes | Project to request access to. |
| `message` | `string` | No | Explanation of why access is needed. |

```json
{
  "project_id": "7c8d9e0f-1234-5678-9abc-def012345678",
  "message": "Need read access to review the migration contracts."
}
```

### Response

`201 Created` — a `ProjectAccessRequestResponse` object.

```json
{
  "message": "Access request sent to 3 project members",
  "project_name": "customer-360-migration"
}
```

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No project with that ID. |
| `409 Conflict` | An equivalent access request already exists. |

## See also

- [Teams API](./teams) — the teams you assign to projects.
- [Data Contracts API](./data_contracts#list-data-contracts) — filter contracts with `project_id`.
- [Data Products API](./data_products#list-data-products) — filter products with `project_id`.
- [Projects and Teams](../../user_guide/projects_teams) — the user-facing guide.
