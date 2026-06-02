# Data Quality

Data quality in Ontos is split into **two parallel systems** that interact at
specific seams. Customers consistently get confused here — they assume the
quality checks on the contract are also the execution results, and they ask
where DQX-style profiling output lives. The short version: the contract
holds *definitions*; the per-entity quality table holds *measurements*; the
DQX workflow is the most-integrated execution path; everything else lands
via the `external` source.

## The two systems at a glance {#two-systems}

| System | What it stores | Where it lives | Lifecycle |
|---|---|---|---|
| Contract quality checks | Check **definitions** — the rule, dimension, severity, threshold | `DataQualityCheckDb`, attached to `SchemaObjectDb` (table-level) or `SchemaPropertyDb` (column-level) inside the contract | Steward authors, contract approval gates the definition |
| Per-entity quality items | Check **measurements** — score, pass/fail, when, by which engine | `QualityItemDb` rows scoped to an entity (`data_product`, `data_contract`, `asset`, `data_domain`) | Written by profiling jobs, dbt runs, DQX runs, custom pipelines |

A contract that has 12 checks defined and zero measurements is normal —
the contract is the design intent, the measurements are what actually
happened last Tuesday at 03:00.

## ODCS check definitions on the contract {#contract-check-definitions}

A `DataQualityCheckDb` row carries:

- **Level** — `object` (whole table) or `property` (one column). Property
  checks set `property_id`; object checks leave it null.
- **Dimension** — one of the ODCS-native dimensions: `accuracy`,
  `completeness`, `conformity`, `consistency`, `coverage`, `timeliness`,
  `uniqueness`.
- **Business impact** — `operational` or `regulatory`. Drives how a
  violation propagates: operational fires consumer alerts; regulatory
  additionally flags compliance.
- **Severity** — `info`, `warning`, or `error`. Surfaces in UI badges and
  in subscriber notifications.
- **Type** — `library` (a named reusable rule), `text` (free description
  the steward fills in), `sql` (a `query` field with a SQL predicate), or
  `custom` (with an `engine` and `implementation` field for plugging in
  external tooling).
- **A family of declarative comparator fields** — `must_be`,
  `must_not_be`, `must_be_gt`, `must_be_lt`, `must_be_between_min`,
  `must_be_between_max`, etc. These are how the steward expresses "this
  metric must be greater than 0.99" without writing SQL.

Definitions ride along with the contract through its lifecycle. They are
not executed by the contract itself. Something else has to actually
measure the column and report back — see the next section.

## Per-entity measurements and rollup {#measurements-and-rollup}

A `QualityItemDb` row is generic: scoped by `entity_type` (one of
`data_product`, `data_contract`, `asset`, `data_domain`) and `entity_id`.
Each row records one measurement at one moment by one source.

The row carries:

- `score_percent` (0–100)
- `checks_passed`, `checks_total`
- `measured_at` (timestamp)
- `dimension` — same enum as the contract-check dimension
- `source` — one of `manual`, `dbt`, `dqx`, `great_expectations`, `soda`,
  `external`. (See [external sources](#external-sources) below.)

`QualityManager.aggregate_for_product` is the rollup that the Data Product
detail page reads. The logic is:

1. Find the contracts bound to the product (via output ports → contract
   ID).
2. Pull all `QualityItemDb` rows for those contract IDs.
3. Keep the **latest** measurement per `(entity_type, entity_id,
   dimension)` tuple. Stale measurements drop out — only the freshest
   reading per dimension survives.
4. Average per-dimension and per-source.
5. Return a `QualitySummary` with `overall_score_percent`,
   `by_dimension`, and `by_source`.

Crucially, a data product does **not** own quality directly. The product's
Quality panel is a view over the contracts it binds. If you want quality
to show up on a product, attach a contract to one of its output ports and
let measurements flow into that contract.

## DQX integration — concrete end-to-end flow {#dqx-flow}

DQX is the most-tightly-wired integration. It is a complete loop, not a
one-shot.

**Step 1 — Steward kicks off profiling.** From the contract detail page,
the steward triggers a "Profile dataset" action. The action launches the
`dqx_profile_datasets` workflow.

**Step 2 — Workflow profiles a sample.** For each schema in the contract,
the workflow:

- Uses `databricks.labs.dqx.profiler.profiler.DQProfiler` to profile a
  sample (10% sample, capped at 5000 rows).
- Hands the profile to `DQGenerator` and calls
  `generator.generate_dq_rules(profiles, level="error")` to propose rules.

**Step 3 — Workflow writes suggested rules.** Each generated rule becomes
a row in the `suggested_quality_checks` table with `status = 'pending'`.
This is *not* a real check yet — it's a draft the steward can accept,
reject, or modify.

**Step 4 — Steward reviews and accepts.** From the contract's Schema tab,
the steward sees the pending suggestions inline with the actual columns.
Accept → the suggested row is promoted into a real `DataQualityCheckDb`
attached to the relevant `SchemaObjectDb` or `SchemaPropertyDb`. Reject →
the suggestion is dismissed. Edit → modify thresholds and accept.

**Step 5 — Periodic re-measurement.** Later runs of profiling (or any
quality engine configured for the contract) re-measure the columns and
write `QualityItemDb` rows with `source = 'dqx'` (or the appropriate
engine).

**Step 6 — Rollup feeds the product Quality panel.**
`QualityManager.aggregate_for_product` averages the latest measurements
per dimension. The data product's detail page Quality panel renders
`QualitySummary`.

**Step 7 — Subscribers get compliance alerts.** A subscription to a data
product implicitly subscribes the consumer to compliance alerts for the
bound contracts. When a measurement's severity is `error` and the check
fails, subscribers are notified via the configured notification channels.

Profiling-run state is tracked in `data_profiling_runs`. Each run has a
`status` (`running` / `completed` / `failed`) and a `summary_stats` blob.
A failed run surfaces `status = 'failed'` plus an `error_message` — the
intent is that the steward should see profiling-job failures inside Ontos
without needing to drill into the Databricks Workflows UI.

## DQX → ODCS dimension mapping {#dqx-odcs-mapping}

DQX has its own rule names. When suggestions are written, those names map
to ODCS dimensions:

| DQX rule name pattern | ODCS dimension |
|---|---|
| `is_not_null` | `completeness` |
| `is_in`, `min_max`, `pattern` | `conformity` |
| `is_unique` | `uniqueness` |
| anything else | `accuracy` (fallback) |

This means a profiling run will populate several dimensions at once for a
typical column. The fallback to `accuracy` is intentional — it ensures
every DQX rule lands somewhere on the ODCS scale even if there's no
obvious mapping.

## Where quality surfaces in the UI {#where-it-surfaces}

- **Data Product detail page → Quality panel.** Reads the rolled-up
  `QualitySummary` for the contracts bound to the product. Shows
  per-dimension scores and per-source breakdown. This is the "is my
  product healthy?" view.
- **Data Contract detail page → Schema tab.** Shows per-check
  *definitions* attached to each schema object / property, plus
  *suggested* checks pending review from the most recent profiling run.
  This is the "what does the contract require?" view.
- **Subscription compliance alerts.** A consumer who subscribes to a data
  product receives notifications when the bound contract's quality checks
  fail at `error` severity. The channels are configured per notification
  type.

## External quality sources {#external-sources}

Customers running their own DQ pipelines outside Ontos can still get their
results to show up. The `source` enum supports:

- `manual` — entered by hand (steward filling in a one-time number).
- `dbt` — dbt test results. The enum exists; the dedicated import workflow
  is not yet shipping in the current Ontos version (the schema reserves
  the path but no first-class importer is wired).
- `dqx` — the integrated path described above.
- `great_expectations` — Great Expectations runs. Same status as dbt.
- `soda` — Soda runs. Same status.
- `external` — a deliberate catch-all. Custom DQ pipelines can write
  `QualityItemDb` rows via the manager with `source='external'`. The
  rollup treats them like any other source.

If you have an organization-standard DQ tool that isn't on this list, the
recipe is: write your results to `QualityItemDb` via the manager with
`source='external'`, populate the dimension and score, and the rollup
will pick them up. This is the same path the integrated engines use; the
only difference is which workflow writes the rows.

## Common questions {#common-questions}

**"How do DQX checks made outside Ontos surface inside Ontos?"**

Two paths. (1) If your external DQX pipeline writes back to the
`QualityItemDb` table via the manager with `source='dqx'`, they show up in
the product's Quality panel automatically. (2) If your pipeline writes to
its own custom delta tables, those results are invisible to Ontos until
something translates them into `QualityItemDb` rows. There is no current
shipping job that reads from arbitrary external DQX delta tables.

**"If I accept 14 suggested rules from a profiling run, do they go back
into the contract YAML?"**

Yes — at least within Ontos. Accepting a suggestion promotes it from
`suggested_quality_checks` to a real `DataQualityCheckDb` row attached to
the contract's schema object or property. The contract's ODCS export
includes those checks. If you maintain a YAML copy of the contract in
your workspace (indirect-delivery via volume), the next contract version
generated by Ontos will reflect the new checks. The seam between Ontos's
DB-of-record and an externally-edited YAML is a place where teams need to
pick one as authoritative — see
[data-contract-lifecycle.md](data-contract-lifecycle.md#editor-of-record).

**"Does Ontos own DQ execution or just observe results?"**

For DQX it owns execution (the workflow runs from the contract page and
writes back). For everything else, Ontos prefers to *observe* — it
expects the engine of record (your dbt project, your Great Expectations
suite, your Soda checks) to write its results to `QualityItemDb` and lets
the rollup do its work. Customers who want Ontos to be the orchestrator
of all DQ runs are at a sharp end of the spec — the current Ontos version
is biased toward observation.

**"Where do I see a failed profiling job?"**

Inside Ontos. The `data_profiling_runs` row has a `status` field and an
`error_message`. The contract page surfaces the latest run status. The
single-pane-of-glass goal is intentional — customers shouldn't need to
chase the Databricks Workflows UI to find out why a profiling job
failed.

**"Can I import dbt test results?"**

The `source='dbt'` enum exists, so the schema is ready. But the
dedicated import workflow is not currently shipping. The pragmatic path
today is to use the `external` source and write your dbt test outcomes
through the manager. Treat this as an evolving area — first-class dbt
integration is the kind of thing that becomes a discrete shipped feature
later.

## Cross-references {#cross-references}

- [Quality check definitions on contracts](data-contract-lifecycle.md#quality-checks)
- [Subscription compliance alerts](data-product-lifecycle.md#publication-subscription)
- [QualityItem](entities-glossary.md#quality-item) and
  [Quality Check](entities-glossary.md#quality-check) in the glossary
- [Bottom-up flow Step 4](end-to-end-flows.md#flow-a-bottom-up) for where
  DQ fits in the day-to-day contract-authoring journey

_Last verified against codebase: 2026-05-28_
