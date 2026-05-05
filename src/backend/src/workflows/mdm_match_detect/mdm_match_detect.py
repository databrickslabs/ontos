"""
MDM Match Detection Workflow

Compares source dataset against master using configurable matching rules.
Generates match candidates for steward review.

This workflow:
1. Loads MDM configuration from the app database
2. Reads master and source data from Unity Catalog tables
3. Applies matching rules (deterministic and probabilistic)
4. Generates match candidates with confidence scores
5. Saves candidates to the database for review
"""

import argparse
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from functools import reduce

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import FloatType
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine

from databricks.sdk import WorkspaceClient


# ============================================================================
# OAuth Token Generation & Database Connection (for Lakebase Postgres)
# ============================================================================

def get_oauth_token(ws_client: WorkspaceClient, instance_name: str) -> Tuple[str, str]:
    """Generate OAuth token for the service principal to access Lakebase Postgres.

    ``instance_name`` is either a provisioned instance name or an autoscale
    endpoint resource name (``projects/…/endpoints/…``).  The correct SDK API
    is chosen automatically.
    """
    if not instance_name or instance_name == 'None' or instance_name == '':
        raise RuntimeError(
            "Lakebase identifier is required but was not provided.\n"
            "This is auto-detected from the Databricks App resources.\n"
            "Ensure your app has a Lakebase database resource configured."
        )

    is_autoscale = instance_name.startswith("projects/")
    print(f"  Generating OAuth token for {'autoscale' if is_autoscale else 'provisioned'} Lakebase: {instance_name}")

    current_user = ws_client.current_user.me().user_name
    print(f"  Service Principal: {current_user}")

    try:
        if is_autoscale:
            cred = ws_client.postgres.generate_database_credential(
                endpoint=instance_name,
            )
        else:
            cred = ws_client.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[instance_name],
            )
    except AttributeError as e:
        raise RuntimeError(
            f"Failed to generate OAuth token: {e}\n"
            "This may indicate that the Databricks SDK version doesn't support database OAuth,\n"
            "or that the workspace client is not properly initialized.\n"
            "Please ensure you're using databricks-sdk >= 0.81.0."
        )

    print(f"  ✓ Successfully generated OAuth token")
    return current_user, cred.token


def build_db_url(
    host: str,
    db: str, 
    port: str, 
    schema: str,
    instance_name: str,
    ws_client: WorkspaceClient
) -> Tuple[str, str]:
    """Build PostgreSQL connection URL using OAuth authentication.
    
    Returns: (connection_url, auth_user)
    """
    
    print(f"  POSTGRES_HOST: {host}")
    print(f"  POSTGRES_DB: {db}")
    print(f"  POSTGRES_PORT: {port}")
    print(f"  POSTGRES_DB_SCHEMA: {schema}")
    print(f"  LAKEBASE_INSTANCE_NAME: {instance_name}")
    print(f"  Authentication: OAuth (Lakebase Postgres)")
    
    # Generate OAuth token
    oauth_user, oauth_token = get_oauth_token(ws_client, instance_name)
    print(f"  Using OAuth user: {oauth_user}")
    
    if not all([host, oauth_user, oauth_token, db]):
        missing = []
        if not host: missing.append("host")
        if not oauth_user: missing.append("oauth_user")
        if not oauth_token: missing.append("oauth_token")
        if not db: missing.append("db")
        raise RuntimeError(f"Missing required Postgres parameters: {', '.join(missing)}")
    
    query = f"?options=-csearch_path%3D{schema}" if schema else ""
    connection_url = f"postgresql+psycopg2://{oauth_user}:****@{host}:{port}/{db}{query}"
    print(f"  Connection URL (token redacted): {connection_url}")
    
    actual_url = f"postgresql+psycopg2://{oauth_user}:{oauth_token}@{host}:{port}/{db}{query}"
    return actual_url, oauth_user


def create_engine_from_params(
    ws_client: WorkspaceClient,
    host: str,
    db: str,
    port: str,
    schema: str,
    instance_name: str
) -> Engine:
    """Create SQLAlchemy engine using OAuth authentication."""
    if not instance_name:
        raise RuntimeError("lakebase_instance_name parameter is required")
    
    url, auth_user = build_db_url(host, db, port, schema, instance_name, ws_client)
    return create_engine(url, pool_pre_ping=True)


def get_db_session(
    ws_client: WorkspaceClient,
    host: str,
    db: str,
    port: str,
    schema: str,
    instance_name: str
):
    """Create database session using OAuth authentication."""
    engine = create_engine_from_params(ws_client, host, db, port, schema, instance_name)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def load_config(session, config_id: str) -> Optional[Dict[str, Any]]:
    """Load MDM configuration from database"""
    result = session.execute(
        text("SELECT * FROM mdm_configs WHERE id = :id"),
        {"id": config_id}
    ).fetchone()
    
    if result:
        return dict(result._mapping)
    return None


def load_source_links(session, config_id: str, source_link_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load source links for configuration"""
    if source_link_id:
        result = session.execute(
            text("SELECT * FROM mdm_source_links WHERE config_id = :config_id AND id = :link_id AND status = 'active'"),
            {"config_id": config_id, "link_id": source_link_id}
        ).fetchall()
    else:
        result = session.execute(
            text("SELECT * FROM mdm_source_links WHERE config_id = :config_id AND status = 'active'"),
            {"config_id": config_id}
        ).fetchall()
    
    return [dict(r._mapping) for r in result]


def get_table_from_contract(session, contract_id: str) -> Optional[str]:
    """Get physical table name from contract schema"""
    result = session.execute(
        text("""
            SELECT physical_name FROM data_contract_schema_objects 
            WHERE contract_id = :id LIMIT 1
        """),
        {"id": contract_id}
    ).fetchone()
    
    return result[0] if result else None


def update_run_status(session, run_id: str, status: str, **kwargs):
    """Update match run status"""
    update_fields = ["status = :status"]
    params = {"id": run_id, "status": status}
    
    if "error_message" in kwargs:
        update_fields.append("error_message = :error_message")
        params["error_message"] = kwargs["error_message"]
    
    if "matches_found" in kwargs:
        update_fields.append("matches_found = :matches_found")
        params["matches_found"] = kwargs["matches_found"]
    
    if "new_records" in kwargs:
        update_fields.append("new_records = :new_records")
        params["new_records"] = kwargs["new_records"]
    
    if "total_source_records" in kwargs:
        update_fields.append("total_source_records = :total_source_records")
        params["total_source_records"] = kwargs["total_source_records"]
    
    if "total_master_records" in kwargs:
        update_fields.append("total_master_records = :total_master_records")
        params["total_master_records"] = kwargs["total_master_records"]
    
    if status in ("completed", "failed"):
        update_fields.append("completed_at = :completed_at")
        params["completed_at"] = datetime.utcnow()
    
    query = f"UPDATE mdm_match_runs SET {', '.join(update_fields)} WHERE id = :id"
    session.execute(text(query), params)
    session.commit()


def apply_deterministic_rule(
    df: DataFrame,
    master_fields: List[str],
    source_fields: List[str],
    weight: float
) -> DataFrame:
    """Apply deterministic (exact match) rule"""
    conditions = []
    for mf, sf in zip(master_fields, source_fields):
        conditions.append(F.col(f"master_{mf}") == F.col(f"source_{sf}"))
    
    if conditions:
        combined = reduce(lambda a, b: a & b, conditions)
        return df.withColumn("rule_score", F.when(combined, F.lit(weight)).otherwise(F.lit(0.0)))
    
    return df.withColumn("rule_score", F.lit(0.0))


def apply_fuzzy_rule(
    df: DataFrame,
    master_field: str,
    source_field: str,
    weight: float,
    algorithm: str = "jaro_winkler"
) -> DataFrame:
    """Apply fuzzy matching rule using string similarity"""
    # Register UDF for fuzzy matching
    from fuzzywuzzy import fuzz
    
    if algorithm == "jaro_winkler":
        @F.udf(FloatType())
        def fuzzy_score(a, b):
            if not a or not b:
                return 0.0
            return fuzz.ratio(str(a).lower(), str(b).lower()) / 100.0
    elif algorithm == "levenshtein":
        @F.udf(FloatType())
        def fuzzy_score(a, b):
            if not a or not b:
                return 0.0
            return fuzz.partial_ratio(str(a).lower(), str(b).lower()) / 100.0
    else:
        @F.udf(FloatType())
        def fuzzy_score(a, b):
            if not a or not b:
                return 0.0
            return fuzz.token_sort_ratio(str(a).lower(), str(b).lower()) / 100.0
    
    return df.withColumn(
        "rule_score",
        fuzzy_score(F.col(f"master_{master_field}"), F.col(f"source_{source_field}")) * F.lit(weight)
    )


def find_matches(
    spark: SparkSession,
    master_df: DataFrame,
    source_df: DataFrame,
    matching_rules: List[Dict],
    column_mapping: Dict[str, str],
    key_column: str
) -> Tuple[DataFrame, DataFrame]:
    """
    Find matching records between master and source datasets.
    
    Args:
        column_mapping: Dict mapping source_column → master_column
                       e.g., {'email_address': 'email', 'phone_number': 'phone'}
    
    Returns: (matches_df, new_records_df)
    """
    # Debug: print input info
    print(f"\n  === find_matches Debug ===")
    print(f"  Master columns: {master_df.columns}")
    print(f"  Source columns: {source_df.columns}")
    print(f"  Column mapping (source→master): {column_mapping}")
    print(f"  Matching rules: {matching_rules}")
    print(f"  Key column: {key_column}")
    
    # Create reverse mapping: master_column → source_column
    # This lets us look up "which source column corresponds to this master field?"
    master_to_source = {v: k for k, v in column_mapping.items()}
    print(f"  Reverse mapping (master→source): {master_to_source}")
    
    # Prefix columns to avoid conflicts
    for col in master_df.columns:
        master_df = master_df.withColumnRenamed(col, f"master_{col}")
    
    for col in source_df.columns:
        source_df = source_df.withColumnRenamed(col, f"source_{col}")
    
    # For prototype: use broadcast join for smaller datasets
    # In production: use blocking strategies
    master_count = master_df.count()
    source_count = source_df.count()
    print(f"  Master count: {master_count}, Source count: {source_count}")
    
    # Limit for prototype
    if master_count > 10000:
        master_df = master_df.limit(10000)
        print(f"  Limited master to 10000 records")
    if source_count > 10000:
        source_df = source_df.limit(10000)
        print(f"  Limited source to 10000 records")
    
    # Cross join for comparison (blocking should be used in production)
    combined = master_df.crossJoin(F.broadcast(source_df))
    print(f"  Combined columns after cross join: {combined.columns}")
    
    # Apply matching rules
    rule_scores = []
    rule_weights = []
    
    for i, rule in enumerate(matching_rules):
        rule_name = rule.get('name', f'rule_{i}')
        rule_type = rule.get('type', 'deterministic')
        fields = rule.get('fields', [])
        weight = rule.get('weight', 1.0)
        algorithm = rule.get('algorithm', 'jaro_winkler')
        
        # Matching rules specify MASTER field names
        # Use reverse mapping to find corresponding SOURCE field names
        master_fields = fields
        source_fields = [master_to_source.get(f, f) for f in fields]
        
        print(f"\n  Rule '{rule_name}' ({rule_type}): master_fields={master_fields} → source_fields={source_fields}")
        
        score_col = f"score_{rule_name}"
        rule_applied = False  # Track if rule was actually applied
        
        if rule_type == 'deterministic':
            conditions = []
            for mf, sf in zip(master_fields, source_fields):
                master_col = f"master_{mf}"
                source_col = f"source_{sf}"
                print(f"    Checking: {master_col} == {source_col}")
                if master_col in combined.columns and source_col in combined.columns:
                    # Apply field-specific normalization for better matching
                    if 'phone' in mf.lower() or 'phone' in sf.lower():
                        # Normalize phone numbers: keep only digits, compare last 7 digits
                        # This handles variations like +1-555-0101 vs 555-0101
                        norm_master_expr = f"RIGHT(REGEXP_REPLACE({master_col}, '[^0-9]', ''), 7)"
                        norm_source_expr = f"RIGHT(REGEXP_REPLACE({source_col}, '[^0-9]', ''), 7)"
                        conditions.append(F.expr(norm_master_expr) == F.expr(norm_source_expr))
                        print(f"    ✓ Both columns exist (with phone normalization - last 7 digits)")
                    elif 'email' in mf.lower() or 'email' in sf.lower():
                        # Normalize email: lowercase and trim
                        conditions.append(F.lower(F.trim(F.col(master_col))) == F.lower(F.trim(F.col(source_col))))
                        print(f"    ✓ Both columns exist (with email normalization)")
                    else:
                        conditions.append(F.col(master_col) == F.col(source_col))
                        print(f"    ✓ Both columns exist")
                else:
                    print(f"    ✗ Missing column(s): master_exists={master_col in combined.columns}, source_exists={source_col in combined.columns}")
            
            if conditions:
                combined_cond = reduce(lambda a, b: a & b, conditions)
                combined = combined.withColumn(score_col, F.when(combined_cond, F.lit(weight)).otherwise(F.lit(0.0)))
                rule_applied = True
                print(f"    Applied {len(conditions)} condition(s)")
            else:
                combined = combined.withColumn(score_col, F.lit(0.0))
                print(f"    No valid conditions, score=0 (rule EXCLUDED from total weight)")
        
        elif rule_type in ('probabilistic', 'fuzzy'):
            # Apply fuzzy matching for first field pair
            if master_fields and source_fields:
                master_col = f"master_{master_fields[0]}"
                source_col = f"source_{source_fields[0]}"
                print(f"    Fuzzy matching: {master_col} ~ {source_col}")
                
                if master_col in combined.columns and source_col in combined.columns:
                    from fuzzywuzzy import fuzz
                    
                    @F.udf(FloatType())
                    def calc_fuzzy(a, b):
                        if not a or not b:
                            return 0.0
                        return fuzz.ratio(str(a).lower(), str(b).lower()) / 100.0
                    
                    combined = combined.withColumn(score_col, calc_fuzzy(F.col(master_col), F.col(source_col)) * F.lit(weight))
                    rule_applied = True
                    print(f"    ✓ Applied fuzzy matching")
                else:
                    combined = combined.withColumn(score_col, F.lit(0.0))
                    print(f"    ✗ Missing column(s) (rule EXCLUDED from total weight)")
            else:
                combined = combined.withColumn(score_col, F.lit(0.0))
                print(f"    ✗ No fields specified (rule EXCLUDED from total weight)")
        
        rule_scores.append(score_col)
        # Only count weight for rules that were actually applied
        if rule_applied:
            rule_weights.append(weight)
        else:
            print(f"    ⚠ Rule weight {weight} NOT included in total (missing columns)")
    
    # Calculate overall confidence score
    if rule_scores and rule_weights:
        total_weight = sum(rule_weights)
        if total_weight > 0:
            score_sum = sum([F.col(s) for s in rule_scores])
            combined = combined.withColumn("confidence_score", score_sum / F.lit(total_weight))
            print(f"\n  Calculated confidence_score from {len(rule_scores)} rules, applicable_weight={total_weight}")
        else:
            combined = combined.withColumn("confidence_score", F.lit(0.0))
            print(f"\n  All rules failed (missing columns), confidence_score=0")
    else:
        combined = combined.withColumn("confidence_score", F.lit(0.0))
        print(f"\n  No rule scores, confidence_score=0")
    
    # Filter to potential matches (above minimum threshold)
    min_threshold = min((r.get('threshold', 0.7) for r in matching_rules), default=0.7)
    print(f"  Minimum confidence threshold: {min_threshold}")
    
    # Debug: show distribution of scores before filtering
    try:
        score_stats = combined.agg(
            F.count("*").alias("total_pairs"),
            F.sum(F.when(F.col("confidence_score") > 0, 1).otherwise(0)).alias("non_zero_scores"),
            F.max("confidence_score").alias("max_score"),
            F.avg("confidence_score").alias("avg_score")
        ).collect()[0]
        print(f"  Score stats: total_pairs={score_stats['total_pairs']}, non_zero={score_stats['non_zero_scores']}, max={score_stats['max_score']}, avg={score_stats['avg_score']}")
    except Exception as e:
        print(f"  Could not compute score stats: {e}")
    
    matches = combined.filter(F.col("confidence_score") >= min_threshold)
    match_count = matches.count()
    print(f"  Matches above threshold: {match_count}")
    
    # Identify matched fields
    @F.udf("array<string>")
    def get_matched_fields(*scores_and_names):
        matched = []
        n = len(scores_and_names) // 2
        for i in range(n):
            if scores_and_names[i] and scores_and_names[i] > 0:
                matched.append(scores_and_names[n + i])
        return matched
    
    if rule_scores:
        score_cols = [F.col(s) for s in rule_scores]
        name_lits = [F.lit(r.get('name', f'rule_{i}')) for i, r in enumerate(matching_rules)]
        matches = matches.withColumn("matched_fields", get_matched_fields(*score_cols, *name_lits))
    else:
        matches = matches.withColumn("matched_fields", F.array())
    
    # Find new records (source records that don't match any master record)
    source_key = f"source_{key_column}"
    matched_source_ids = matches.select(source_key).distinct()
    
    new_records = source_df.join(
        matched_source_ids,
        source_df[f"source_{key_column}"] == matched_source_ids[source_key],
        "left_anti"
    )
    
    return matches, new_records


def save_match_candidates(
    session,
    run_id: str,
    config_id: str,
    source_contract_id: str,
    matches: DataFrame,
    master_key: str,
    source_key: str
):
    """Save match candidates to database"""
    candidates = matches.collect()
    
    for row in candidates:
        row_dict = row.asDict()
        
        # Extract master and source data
        master_data = {k.replace("master_", ""): v for k, v in row_dict.items() if k.startswith("master_")}
        source_data = {k.replace("source_", ""): v for k, v in row_dict.items() if k.startswith("source_")}
        
        # Get record IDs
        master_id = master_data.get(master_key)
        source_id = source_data.get(source_key)
        
        # Determine match type based on confidence
        confidence = row_dict.get("confidence_score", 0)
        if confidence >= 0.95:
            match_type = "exact"
        elif confidence >= 0.85:
            match_type = "fuzzy"
        else:
            match_type = "probabilistic"
        
        # Get matched fields
        matched_fields = row_dict.get("matched_fields", [])
        
        session.execute(
            text("""
                INSERT INTO mdm_match_candidates 
                (id, run_id, master_record_id, source_record_id, source_contract_id,
                 confidence_score, match_type, matched_fields, master_record_data, 
                 source_record_data, status)
                VALUES (:id, :run_id, :master_id, :source_id, :source_contract_id,
                        :confidence, :match_type, :matched_fields, :master_data, 
                        :source_data, 'pending')
            """),
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "master_id": str(master_id) if master_id else None,
                "source_id": str(source_id),
                "source_contract_id": source_contract_id,
                "confidence": confidence,
                "match_type": match_type,
                "matched_fields": json.dumps(matched_fields),
                "master_data": json.dumps(master_data, default=str),
                "source_data": json.dumps(source_data, default=str)
            }
        )
    
    session.commit()
    return len(candidates)


def save_new_record_candidates(
    session,
    run_id: str,
    source_contract_id: str,
    new_records: DataFrame,
    source_key: str
):
    """Save new record candidates (no master match) to database"""
    records = new_records.collect()
    
    for row in records:
        row_dict = row.asDict()
        source_data = {k.replace("source_", ""): v for k, v in row_dict.items()}
        source_id = source_data.get(source_key)
        
        session.execute(
            text("""
                INSERT INTO mdm_match_candidates 
                (id, run_id, master_record_id, source_record_id, source_contract_id,
                 confidence_score, match_type, matched_fields, master_record_data, 
                 source_record_data, status)
                VALUES (:id, :run_id, NULL, :source_id, :source_contract_id,
                        1.0, 'new', '[]', NULL, :source_data, 'pending')
            """),
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "source_id": str(source_id),
                "source_contract_id": source_contract_id,
                "source_data": json.dumps(source_data, default=str)
            }
        )
    
    session.commit()
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="MDM Match Detection Workflow")
    parser.add_argument("--run_id", required=True, help="Match run ID")
    parser.add_argument("--config_id", required=True, help="MDM configuration ID")
    parser.add_argument("--source_link_id", default="", help="Specific source link to process")
    parser.add_argument("--lakebase_instance_name", required=True, help="Lakebase instance name for OAuth")
    parser.add_argument("--postgres_host", required=True, help="PostgreSQL host")
    parser.add_argument("--postgres_db", required=True, help="PostgreSQL database")
    parser.add_argument("--postgres_port", default="5432", help="PostgreSQL port")
    parser.add_argument("--postgres_schema", default="public", help="PostgreSQL schema")
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()

    print("=" * 80)
    print("MDM Match Detection Workflow")
    print("=" * 80)
    print(f"\nJob Parameters:")
    print(f"  Run ID: {args.run_id}")
    print(f"  Config ID: {args.config_id}")
    print(f"  Source Link ID: {args.source_link_id or '(all sources)'}")
    print(f"  Lakebase instance: {args.lakebase_instance_name}")

    # Initialize Spark
    print("\nInitializing Spark Session...")
    spark = SparkSession.builder \
        .appName(f"MDM Match Detection - {args.run_id}") \
        .getOrCreate()
    print("✓ Spark session initialized")

    # Initialize Workspace Client (needed for OAuth authentication)
    print("\nInitializing Databricks Workspace Client...")
    ws_client = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("✓ Workspace client initialized")

    # Connect to app database using OAuth
    print("\nConnecting to database...")
    session, engine = get_db_session(
        ws_client=ws_client,
        host=args.postgres_host,
        db=args.postgres_db,
        port=args.postgres_port,
        schema=args.postgres_schema,
        instance_name=args.lakebase_instance_name
    )
    print("✓ Database connection established successfully")

    try:
        # Load configuration
        config = load_config(session, args.config_id)
        if not config:
            raise ValueError(f"MDM config {args.config_id} not found")

        # Update run status to running
        update_run_status(session, args.run_id, "running")

        # Get master table from contract
        master_table = get_table_from_contract(session, config['master_contract_id'])
        if not master_table:
            raise ValueError(f"Master table not found for contract {config['master_contract_id']}")

        # Load master data
        master_df = spark.table(master_table)
        master_count = master_df.count()

        # Get matching rules from config
        matching_rules = config.get('matching_rules', [])
        print(f"\nMatching rules from config: {matching_rules}")
        if not matching_rules:
            # Default rules if none specified
            print("  No rules in config, using default exact match on 'id'")
            matching_rules = [
                {"name": "default_exact", "type": "deterministic", "fields": ["id"], "weight": 1.0, "threshold": 0.7}
            ]
        else:
            print(f"  Found {len(matching_rules)} matching rule(s)")

        # Load source links
        source_link_id = args.source_link_id if args.source_link_id else None
        source_links = load_source_links(session, args.config_id, source_link_id)

        if not source_links:
            raise ValueError("No active source links found for this configuration")

        total_matches = 0
        total_new = 0
        total_source_records = 0

        # Process each source link
        for link in source_links:
            source_table = get_table_from_contract(session, link['source_contract_id'])
            if not source_table:
                print(f"Warning: Source table not found for contract {link['source_contract_id']}, skipping")
                continue

            # Load source data
            source_df = spark.table(source_table)
            source_count = source_df.count()
            total_source_records += source_count

            # Get column mapping and key column
            column_mapping = link.get('column_mapping', {})
            key_column = link.get('key_column', 'id')
            
            print(f"\n  Source link config:")
            print(f"    Key column: {key_column}")
            print(f"    Column mapping: {column_mapping}")

            # Determine master key (the source key maps to this master column)
            master_key = column_mapping.get(key_column, key_column)
            print(f"    Master key (mapped): {master_key}")

            # Find matches
            matches, new_records = find_matches(
                spark=spark,
                master_df=master_df,
                source_df=source_df,
                matching_rules=matching_rules,
                column_mapping=column_mapping,
                key_column=key_column
            )

            # Save match candidates
            match_count = save_match_candidates(
                session=session,
                run_id=args.run_id,
                config_id=args.config_id,
                source_contract_id=link['source_contract_id'],
                matches=matches,
                master_key=master_key,
                source_key=key_column
            )
            total_matches += match_count

            # Save new record candidates
            new_count = save_new_record_candidates(
                session=session,
                run_id=args.run_id,
                source_contract_id=link['source_contract_id'],
                new_records=new_records,
                source_key=key_column
            )
            total_new += new_count

            print(f"Processed source {link['source_contract_id']}: {match_count} matches, {new_count} new records")

        # Update run with final results
        update_run_status(
            session,
            args.run_id,
            "completed",
            matches_found=total_matches,
            new_records=total_new,
            total_source_records=total_source_records,
            total_master_records=master_count
        )

        print(f"MDM matching completed successfully. Found {total_matches} matches and {total_new} new records.")

    except Exception as e:
        print(f"Error during MDM matching: {e}")
        update_run_status(session, args.run_id, "failed", error_message=str(e))
        raise

    finally:
        session.close()
        spark.stop()


if __name__ == "__main__":
    main()

