"""
cleanup_stale_orders Lambda.

Triggered on a schedule by EventBridge (default: every 15 minutes, see
cloudformation/04-compute-api.yaml). Finds orders still stuck at status
"pending" past a staleness threshold - meaning process_order kept failing on
them and they likely ended up in the SQS dead-letter queue - and deletes them.

Uses a full table Scan, which reads every item on every run. That's fine at
this project's scale (single-node table, low item count) but does NOT scale:
a production version would add a Global Secondary Index on `status` and
Query it directly instead of scanning the whole table.
"""
import os
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr

from common.boto3_clients import get_orders_table

STALE_AFTER_MINUTES = int(os.environ.get("STALE_AFTER_MINUTES", "60"))


def _find_stale_orders(table):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_AFTER_MINUTES)).isoformat()

    stale_orders = []
    scan_kwargs = {
        "FilterExpression": Attr("status").eq("pending") & Attr("created_at").lt(cutoff)
    }
    while True:
        response = table.scan(**scan_kwargs)
        stale_orders.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return stale_orders


def lambda_handler(event, context):
    table = get_orders_table()
    stale_orders = _find_stale_orders(table)

    for order in stale_orders:
        table.delete_item(Key={"order_id": order["order_id"]})

    print(f"Deleted {len(stale_orders)} stale order(s) older than {STALE_AFTER_MINUTES} minutes")
    return {"deleted_count": len(stale_orders)}
