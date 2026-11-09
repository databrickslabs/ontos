# Connecting Ontos MCP to Genie One

This guide sets up a **single-credential** connection so **Genie One** (and other
Databricks agents) can call the Ontos MCP tools. It uses the Databricks Python SDK
from a notebook to create everything, then covers the Genie One UI steps.

For the conceptual split between the in-product Ask Ontos copilot and the MCP server
(tokens, scopes, JSON-RPC), see [mcp-and-ask-ontos.md](mcp-and-ask-ontos.md). This page is
the practical setup companion for the Genie connection specifically.

## How the auth works (why this is single-credential)

The Ontos MCP endpoint (`/api/mcp`) sits behind two layers:

1. **Databricks App proxy** — any principal with `CAN_USE` on the app passes (Databricks OAuth).
2. **Ontos MCP layer** — normally requires an `X-API-Key` (an Ontos-issued MCP token).

Ontos supports **keyless MCP**: when no `X-API-Key` is sent, the request is authenticated
from the app-proxy identity that Databricks forwards, and mapped to a single **keyless
default** MCP token. That default token's **scopes** apply to every keyless call.

A Unity Catalog HTTP connection can carry only one credential (OAuth M2M). Keyless is what
makes that one credential sufficient — no second token to inject.

> ⚠️ **Keyless calls run as the default token's identity and scopes, not the end user's.**
> Some tools (e.g. `global_search`) bypass per-user filtering. **Scope the keyless default
> token read-only** unless you intend write access for everyone using Genie.

## Prerequisites

- **Ontos** deployed as a Databricks App, with the **keyless MCP** code live, and an
  **active, non-expired keyless-default MCP token** configured in Ontos
  (Settings → MCP Tokens → star/set a token as keyless default; scope it read-only).
- Workspace preview **"Third Party Connectors for Agents"** enabled (workspace admin).
- Workspace is in a region that **supports Model Serving**.
- You can run a notebook as a **workspace admin** (needed to create the SP secret and grant
  app permissions), and you have `CREATE CONNECTION` on the metastore.

---

## Part 1 — Set up the SP and connection from a notebook (Databricks SDK)

Run these cells in a Databricks notebook in the **same workspace** as the Ontos app.
In a notebook `WorkspaceClient()` authenticates automatically as the notebook user.

### Cell 1 — install / import

```python
%pip install --upgrade databricks-sdk
dbutils.library.restartPython()
```

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()  # auto-auth as the notebook user

# ---- configure these ----
APP_NAME         = "ontos-dev"          # the Ontos Databricks App name
SP_DISPLAY_NAME  = "ontos-mcp-genie"    # dedicated SP for the connection
CONNECTION_NAME  = "ontos_mcp"          # UC connection name (no spaces)
SECRET_LIFETIME  = "63072000s"          # ~730 days, in seconds + "s"
```

### Cell 2 — resolve app URL + token endpoint

```python
app = w.apps.get(name=APP_NAME)
app_url = app.url.rstrip("/")                       # https://<app>-<id>.<region>.databricksapps.com
host = w.config.host.rstrip("/")                    # https://<workspace-host>
token_endpoint = f"{host}/oidc/v1/token"
print("app_url        :", app_url)
print("token_endpoint :", token_endpoint)
```

### Cell 3 — create the dedicated service principal

```python
sp = w.service_principals.create(display_name=SP_DISPLAY_NAME, active=True)
sp_numeric_id = sp.id             # e.g. "212719236027824" (used to mint the secret)
client_id     = sp.application_id # UUID -> this is the connection's client_id
print("sp_numeric_id :", sp_numeric_id)
print("client_id     :", client_id)
```

### Cell 4 — mint an OAuth secret for the SP

Uses the workspace SP-secrets proxy endpoint (despite `accounts` in the path, it is called
against the workspace host).

```python
secret_resp = w.api_client.do(
    "POST",
    f"/api/2.0/accounts/servicePrincipals/{sp_numeric_id}/credentials/secrets",
    body={"lifetime": SECRET_LIFETIME},
)
client_secret = secret_resp["secret"]  # shown once — stored into the connection below
print("secret_id :", secret_resp["id"])
print("expires   :", secret_resp["expire_time"])
```

### Cell 5 — grant the SP `CAN_USE` on the app

Additive — does not touch existing app permissions.

```python
w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/apps/{APP_NAME}",
    body={"access_control_list": [
        {"service_principal_name": client_id, "permission_level": "CAN_USE"},
    ]},
)
print("granted CAN_USE to", client_id)
```

### Cell 6 — create the Unity Catalog HTTP (MCP) connection

```python
conn = w.api_client.do(
    "POST",
    "/api/2.1/unity-catalog/connections",
    body={
        "name": CONNECTION_NAME,
        "connection_type": "HTTP",
        "comment": "Ontos MCP server (/api/mcp, keyless) for Genie One",
        "read_only": True,
        "options": {
            "host": app_url,                 # full https URL
            "port": "443",
            "base_path": "/api/mcp",         # NOT /mcp (that returns the SPA)
            "client_id": client_id,
            "client_secret": client_secret,
            "oauth_scope": "all-apis",
            "token_endpoint": token_endpoint,
            "is_mcp_connection": "true",
        },
    },
)
print("created connection:", conn.get("full_name", conn["name"]))
```

### Cell 7 (optional) — verify keyless MCP works before wiring Genie

```python
import requests

tok = requests.post(
    token_endpoint, auth=(client_id, client_secret),
    data={"grant_type": "client_credentials", "scope": "all-apis"},
).json()["access_token"]

r = requests.post(
    f"{app_url}/api/mcp",
    headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
)
print("HTTP", r.status_code)
# tools arrive as SSE 'data:' lines; a 200 with a jsonrpc result listing tools = success
print(r.text[:400])
```

A `200` whose body contains a `tools` array confirms the full chain (proxy OAuth →
keyless MCP) works with the single credential. If you get `-32001 Invalid or missing API
key`, no active **keyless-default** token is configured in Ontos — set one first.

> 🔐 **Secret hygiene:** the `client_secret` is stored (encrypted) in the UC connection and
> is also printed in the notebook. Clear the cell outputs, or store the secret in a
> Databricks **secret scope** instead of printing it.

### High-level SDK alternatives

`w.api_client.do(...)` is used above so the calls are version-independent. Newer SDKs also
expose typed methods you can use instead: `w.connections.create(...)`,
`w.apps.update_permissions(...)`, and `w.service_principal_secrets_proxy.create(...)`.
The REST paths above are the source of truth if a typed method differs by version.

---

## Part 2 — Add the connection in Genie One (UI)

1. Open **Genie One** — the workspace's Genie home page (the "How can I help you?" screen
   with the lamp icon). This is **not** a classic Genie Space / Genie Agent.
2. In the prompt bar, click the **+** button (next to **Search** / **Ask**).
3. Choose **Connectors** → **Browse connectors** at the bottom.
   - The inline shortcut list only shows built-in first-party connectors (Google Drive,
     Slack, etc.). Custom UC/MCP connections appear under **Browse connectors**.
4. Find your connection (**`ontos_mcp`**) and add it.
5. Ask a question that exercises a tool, e.g.:
   - *"Search Ontos for customer data products"*
   - *"What does the Ontos handbook say about delivery modes?"*
   - *"List the data domains in Ontos"*

   Genie discovers the MCP tools and calls them through the connection.

### If the connection doesn't appear or errors

- **Not listed under Browse connectors** → the "Third Party Connectors for Agents" preview
  isn't enabled, or the workspace region doesn't support Model Serving.
- **Tool calls fail with an auth error** → confirm an active **keyless-default** MCP token
  exists in Ontos, and that the SP has `CAN_USE` on the app (Cell 5).
- **404 / HTML responses** → `base_path` must be `/api/mcp`, not `/mcp`.

---

## What got created (for cleanup)

- Service principal `ontos-mcp-genie` (+ one OAuth secret).
- App permission: `CAN_USE` for that SP on the Ontos app.
- Unity Catalog connection `ontos_mcp` (metastore-level).

To remove: delete the connection (`w.connections.delete(CONNECTION_NAME)`), revoke the app
permission, and delete the service principal.

## Cross-references {#cross-references}

- [mcp-and-ask-ontos.md](mcp-and-ask-ontos.md) — Ask Ontos vs the MCP server, tokens, scopes, JSON-RPC surface
- [roles-and-rbac.md](roles-and-rbac.md#permission-model) — how MCP token scopes relate to Ontos permissions

_Last verified against codebase: 2026-09-19_
