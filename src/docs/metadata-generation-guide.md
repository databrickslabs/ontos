# Metadata Generation

Metadata Generation drafts descriptions for Unity Catalog tables, views and columns with an LLM, puts them up for review in Ontos, and writes the approved ones back to Unity Catalog. It runs [dbxmetagen](https://github.com/databricks-industry-solutions/dbxmetagen) as an Ontos background job.

Open it from **Build → Metadata Generation**.

## Before you start

An administrator has to:

1. Enable the **Metadata Generation** background job under **Settings → Jobs**. An installed job keeps its definition: after an Ontos upgrade, turn it off and on again there to deploy the new one.
2. Grant the app's service principal access in Unity Catalog. It reads the objects you describe and writes the descriptions back. See [UC grants for the app service principal](https://github.com/databrickslabs/ontos/blob/main/docs/decisions/uc-grants-for-app-sp.md#metadata-generation) for the full list. In short:
   - `SELECT` on what you describe.
   - `MODIFY` on tables, and ownership of views, whose descriptions should be applied.
   - `CAN QUERY` on the serving endpoints.
3. Load the default workflows (**Settings → Workflows → Load Defaults**). This provides the `metadata-generation-review` workflow.

## Generation Runs

A **Generation Run** describes one selection of catalogs, schemas, tables or views. A catalog or schema includes all of its tables.

1. Click **New run** and pick the objects.
2. Choose the options:
   - **Description style**: concise, standard or detailed.
   - **Serving endpoint**: the app's default endpoint or one an administrator allowed.
   - **Regenerate existing descriptions**: by default, only objects without a description get suggestions.
   - **Include sample data**: only offered when an administrator allows it. See below.
   - **Submit for review when done**: opens a review as soon as the run finishes, optionally with a reviewer you pick.
3. Start the run. Its page shows the progress. When it finishes, the suggestions are listed per table, with the current and proposed text side by side.

Two runs can't describe the same objects at the same time. Each user can have a limited number of active runs, and each run a limited number of tables (500 by default).

## What is sent to the LLM

| Sent | When |
|---|---|
| Table, view and column names, data types, existing comments | always |
| Column statistics: null and distinct counts, value lengths; tags and constraints | unless an administrator turns off **Send column statistics** |
| Sample rows, and column min/max values | only for a run with **Include sample data**, which an administrator must allow first |

The LLM is called through the selected Databricks Model Serving endpoint, as the app's service principal.

## Reviewing suggestions

Click **Submit N for review** on the run page. Ontos opens a Data Asset Review with one item per suggestion; each item is named by its table or column. If you don't pick a reviewer, it goes to a Data Steward. You can't review your own run.

In the review, the reviewer sees the current and proposed text. For each suggestion they can:

- **Approve**, optionally with an edited text.
- **Reject** it.
- Mark it **Needs clarification**. It returns to the run and can be submitted again.

When the reviewer approves the review as a whole, the `metadata-generation-review` workflow writes the approved descriptions to Unity Catalog and notifies the requester. A closed review takes no more decisions. Suggestions nobody decided go back to the run.

## Applying descriptions

Approved descriptions are applied by the workflow. **Apply N approved** on the run page retries or catches up, for example after a failed write.

Each suggestion ends in one of these states:

- **Applied**: written to Unity Catalog and to the matching Ontos Asset. The change log keeps the text before and after, the approver and the person who applied it.
- **Conflict**: the description in Unity Catalog changed after the run, so it's left alone. Regenerate it, or an administrator can **Force-apply** it.
- **Not applicable**: the object is gone, or the app's service principal may not change its description. Ontos checks this when it loads a run's results, so these never reach a reviewer.

## Settings (administrators)

**Settings** on the Metadata Generation page:

- **Tables per run**, **Active runs per user**.
- **Send column statistics**.
- **Allow sample data**, and **Sample rows per table**.
- **Additional serving endpoints**: one per line. The app's default endpoint is always allowed.

## Usage tracking

dbxmetagen is developed by Databricks. Its notice states: "By using this repository and the notebooks within, you consent to Databricks collection and use of usage and tracking information in accordance with our privacy policy at https://www.databricks.com/legal/privacypolicy." Generation Runs run dbxmetagen in your workspace, so this applies to using Metadata Generation.
