"""Metadata Generation workflow.

Runs dbxmetagen (comment mode, apply_ddl=false) over the selected Unity Catalog
objects and writes normalized results to the Delta table
``<output_catalog>.<output_schema>.metagen_results`` keyed by the Ontos run id.
The Ontos app ingests that table when the job finishes; this job never talks to
the Ontos database (see docs/decisions/metadata-generation-execution.md).
"""

import argparse
import sys
import traceback
import uuid
from typing import Dict, List, Optional, Tuple

from pyspark.sql import SparkSession
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

RESULTS_TABLE = "metagen_results"
DBXMETAGEN_LOG_TABLE = "metadata_generation_log"
SKIP_SCHEMAS = {"information_schema"}

RESULTS_SCHEMA = StructType([
    StructField("ontos_run_id", StringType(), False),
    StructField("object_type", StringType(), False),  # table | view | column
    StructField("table_fqn", StringType(), False),
    StructField("column_name", StringType(), True),
    StructField("base_text", StringType(), True),
    StructField("proposed_text", StringType(), False),
    StructField("model", StringType(), True),
    StructField("generated_at", TimestampType(), True),
])


def parse_bool(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes")


def quote_fqn(fqn: str) -> str:
    return ".".join(f"`{part.replace('`', '``')}`" for part in fqn.split("."))


def expand_selection(spark: SparkSession, names: List[str]) -> List[str]:
    """Expand ``cat``, ``cat.sch`` and ``cat.sch.tbl`` entries into table FQNs."""
    tables: List[str] = []
    for name in names:
        parts = name.split(".")
        if len(parts) == 3:
            tables.append(name)
        elif len(parts) == 2:
            tables.extend(_tables_in_schema(spark, parts[0], parts[1]))
        elif len(parts) == 1:
            for row in spark.sql(f"SHOW SCHEMAS IN {quote_fqn(parts[0])}").collect():
                schema = row[0]
                if schema.lower() in SKIP_SCHEMAS:
                    continue
                tables.extend(_tables_in_schema(spark, parts[0], schema))
        else:
            print(f"Skipping unrecognized selection entry: {name}")
    # De-duplicate while keeping order
    seen = set()
    unique = []
    for t in tables:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique


def _tables_in_schema(spark: SparkSession, catalog: str, schema: str) -> List[str]:
    rows = spark.sql(f"SHOW TABLES IN {quote_fqn(catalog + '.' + schema)}").collect()
    # SHOW TABLES returns (database, tableName, isTemporary)
    return [f"{catalog}.{schema}.{row['tableName']}" for row in rows if not row["isTemporary"]]


def describe_table(spark: SparkSession, fqn: str) -> Tuple[str, Optional[str], Dict[str, Optional[str]]]:
    """Return (object_type, table_comment, {column: comment}) for a table or view."""
    rows = spark.sql(f"DESCRIBE TABLE EXTENDED {quote_fqn(fqn)}").collect()
    columns: Dict[str, Optional[str]] = {}
    table_comment: Optional[str] = None
    object_type = "table"
    in_columns = True
    for row in rows:
        col_name = (row["col_name"] or "").strip()
        if in_columns:
            if not col_name or col_name.startswith("#"):
                in_columns = False
                continue
            columns[col_name] = row["comment"] or None
            continue
        if col_name == "Comment":
            table_comment = row["data_type"] or None
        elif col_name == "Type" and (row["data_type"] or "").upper() == "VIEW":
            object_type = "view"
    return object_type, table_comment, columns


def is_fully_described(table_comment: Optional[str], columns: Dict[str, Optional[str]]) -> bool:
    return bool(table_comment) and all(bool(c) for c in columns.values())


def read_generated(
    spark: SparkSession, log_table: str, started_us: int, wanted: Dict[str, str]
) -> Dict[Tuple[str, Optional[str]], Tuple[str, Optional[str], object]]:
    """Read this run's comment rows from dbxmetagen's log.

    dbxmetagen's log has no run id, so rows are matched by table and by having
    been written after this job started (compared as epoch microseconds, so
    the session time zone doesn't matter). Latest row per (table, column) wins.
    ``wanted`` maps lowercased FQN -> FQN as selected.
    """
    df = spark.sql(
        f"""
        SELECT `table`, catalog, `schema`, table_name, ddl_type, column_name,
               column_content, model, _created_at
        FROM {quote_fqn(log_table)}
        WHERE metadata_type = 'comment' AND unix_micros(_created_at) >= {int(started_us)}
        ORDER BY _created_at
        """
    )
    results: Dict[Tuple[str, Optional[str]], Tuple[str, Optional[str], object]] = {}
    for row in df.collect():
        raw_table = row["table"] or ""
        if raw_table.count(".") == 2:
            fqn_lower = raw_table.lower()
        else:
            fqn_lower = f"{row['catalog']}.{row['schema']}.{row['table_name']}".lower()
        fqn = wanted.get(fqn_lower)
        text = (row["column_content"] or "").strip()
        if not fqn or not text:
            continue
        column = None if row["ddl_type"] == "table" else (row["column_name"] or None)
        results[(fqn, column)] = (text, row["model"], row["_created_at"])
    return results


def main():
    print("=" * 80)
    print("Metadata Generation workflow started")
    print("=" * 80)

    parser = argparse.ArgumentParser(description="Generate UC descriptions with dbxmetagen")
    parser.add_argument("--ontos_run_id", type=str, required=True)
    parser.add_argument("--table_names", type=str, required=True)  # comma-separated cat[.sch[.tbl]]
    parser.add_argument("--output_catalog", type=str, required=True)
    parser.add_argument("--output_schema", type=str, required=True)
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--comment_style", type=str, default="standard")
    parser.add_argument("--allow_data", type=str, default="false")
    parser.add_argument("--sample_size", type=str, default="0")
    parser.add_argument("--add_metadata", type=str, default="true")
    parser.add_argument("--max_tables", type=str, default="500")
    parser.add_argument("--regenerate_existing", type=str, default="false")
    args, _ = parser.parse_known_args()

    run_id = str(uuid.UUID(args.ontos_run_id))  # also guards the DELETE below
    allow_data = parse_bool(args.allow_data)
    add_metadata = parse_bool(args.add_metadata)
    max_tables = int(args.max_tables)
    regenerate_existing = parse_bool(args.regenerate_existing)
    selection = [n.strip() for n in args.table_names.split(",") if n.strip()]
    output_prefix = f"{args.output_catalog}.{args.output_schema}"

    print("\nJob Parameters:")
    print(f"  Ontos run ID: {run_id}")
    print(f"  Selection: {selection}")
    print(f"  Output schema: {output_prefix}")
    print(f"  Model: {args.model}, style: {args.comment_style}")
    print(f"  Allow data: {allow_data}, column metadata: {add_metadata}, regenerate existing: {regenerate_existing}")

    spark = SparkSession.builder.getOrCreate()

    try:
        tables = expand_selection(spark, selection)
        print(f"\nResolved {len(tables)} table(s)")
        if len(tables) > max_tables:
            raise ValueError(f"The selection covers {len(tables)} tables, more than the limit of {max_tables}")

        # Current UC descriptions become each suggestion's base text
        described: Dict[str, Tuple[str, Optional[str], Dict[str, Optional[str]]]] = {}
        for fqn in tables:
            try:
                described[fqn] = describe_table(spark, fqn)
            except Exception as e:
                print(f"Skipping {fqn}: cannot describe ({e})")

        targets = [
            fqn for fqn, (_, table_comment, columns) in described.items()
            if regenerate_existing or not is_fully_described(table_comment, columns)
        ]
        print(f"{len(targets)} table(s) need descriptions")

        results_table = f"{output_prefix}.{RESULTS_TABLE}"
        spark.createDataFrame([], RESULTS_SCHEMA).write.mode("append").saveAsTable(results_table)
        # Re-running the job for the same Ontos run replaces its rows
        spark.sql(f"DELETE FROM {quote_fqn(results_table)} WHERE ontos_run_id = '{run_id}'")

        if not targets:
            print("Nothing to generate.")
            return

        started_us = spark.sql("SELECT unix_micros(current_timestamp()) AS us").first()["us"]

        from dbxmetagen.main import main as dbxmetagen_main
        dbxmetagen_main({
            "catalog_name": args.output_catalog,
            "schema_name": args.output_schema,
            "table_names": ",".join(targets),
            "mode": "comment",
            "model": args.model,
            "comment_style": args.comment_style,
            "allow_data": str(allow_data).lower(),
            "allow_data_in_comments": str(allow_data).lower(),
            "sample_size": args.sample_size if allow_data else "0",
            # Column statistics, tags and constraints. Passed as a bool: dbxmetagen
            # doesn't parse this flag, so the string "false" would count as on
            "add_metadata": add_metadata,
            "apply_ddl": "false",
            "apply_tags": "false",
            "incremental": "false",
            "allow_manual_override": "false",
            "grant_permissions_after_creation": "false",
            "enable_benchmarking": "false",
            "cleanup_control_table": "true",
            "volume_name": "metagen_output",
        })

        wanted = {fqn.lower(): fqn for fqn in targets}
        generated = read_generated(spark, f"{output_prefix}.{DBXMETAGEN_LOG_TABLE}", started_us, wanted)

        rows = []
        for (fqn, column), (text, model, created_at) in generated.items():
            object_type, table_comment, columns = described[fqn]
            if column is None:
                rows.append((run_id, object_type, fqn, None, table_comment, text, model, created_at))
            elif column in columns:
                rows.append((run_id, "column", fqn, column, columns[column], text, model, created_at))

        if rows:
            spark.createDataFrame(rows, RESULTS_SCHEMA).write.mode("append").saveAsTable(results_table)
        print(f"\nWrote {len(rows)} suggestion row(s) to {results_table}")

    except Exception as e:
        print(f"\n✗ Metadata generation failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 80)
    print("Metadata Generation workflow completed")
    print("=" * 80)


if __name__ == "__main__":
    main()
