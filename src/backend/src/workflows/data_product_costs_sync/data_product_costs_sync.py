import os
import argparse
from datetime import date, datetime, timezone
from typing import Optional

from pyspark.sql import SparkSession, functions as F


def month_bounds(yyyymm: str) -> tuple[date, date]:
    y, m = map(int, yyyymm.split("-"))
    start = date(y, m, 1)
    # advance one month
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    return start, end


def main() -> None:
    print("Data Product Costs Sync workflow started")
    parser = argparse.ArgumentParser(description="Aggregate Databricks system table usage into monthly cost items")
    parser.add_argument("--month", type=str, default=datetime.now(timezone.utc).strftime("%Y-%m"), help="Month in YYYY-MM")
    parser.add_argument("--product_tag_key", type=str, default=os.environ.get("COSTS_PRODUCT_TAG", "data_product_id"))
    parser.add_argument("--catalog", type=str, default=os.environ.get("DATABRICKS_CATALOG"))
    parser.add_argument("--schema", type=str, default=os.environ.get("DATABRICKS_SCHEMA"))
    args, _ = parser.parse_known_args()

    month_start, month_end = month_bounds(args.month)
    month_str = args.month

    spark = SparkSession.builder.appName("Ontos-CostsSync").getOrCreate()

    usage = spark.table("system.billing.usage")
    prices = spark.table("system.billing.list_prices")

    # Join usage and price table; attribute by custom tag to data product id
    df = (
        usage
        .where((F.col("usage_date") >= F.lit(month_start.isoformat())) & (F.col("usage_date") < F.lit(month_end.isoformat())))
        .withColumn("product_id", F.element_at(F.col("custom_tags"), F.lit(args.product_tag_key)))
        .where(F.col("product_id").isNotNull())
        .join(prices, (prices["sku_name"] == usage["sku_name"]) & (usage["usage_end_time"] >= prices["price_start_time"]) & (prices["price_end_time"].isNull() | (usage["usage_end_time"] < prices["price_end_time"])), "left")
        .groupBy("product_id")
        .agg((F.sum(F.col("usage_quantity") * F.coalesce(F.col("pricing.effective_list.default"), F.lit(0.0))).alias("total_usd")))
        .withColumn("amount_cents", (F.col("total_usd") * F.lit(100)).cast("bigint"))
        .withColumn("currency", F.lit("USD"))
    )

    # Write into application DB table cost_items (PostgreSQL via JDBC/Delta sharing not handled here)
    # For demo we print SQL upsert statements that the orchestrator could execute against the app DB API.
    rows = df.collect()
    for r in rows:
        product_id = r["product_id"]
        amount_cents = int(r["amount_cents"] or 0)
        currency = r["currency"] or "USD"
        # Construct JSON payload for the app API
        payload = {
            "entity_type": "data_product",
            "entity_id": product_id,
            "title": "Databricks Infra Cost",
            "description": f"Aggregated from system.billing.usage for {month_str}",
            "cost_center": "INFRASTRUCTURE",
            "amount_cents": amount_cents,
            "currency": currency,
            "start_month": f"{month_str}-01",
            "end_month": f"{month_str}-01",
        }
        print("[COSTS] POST /api/entities/data_product/" + product_id + "/cost-items -> ", payload)

    print("Data Product Costs Sync workflow completed")


if __name__ == "__main__":
    main()


