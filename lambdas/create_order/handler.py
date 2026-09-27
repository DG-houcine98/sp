"""
create_order Lambda.

Triggered by API Gateway (POST /orders, Lambda proxy integration). Validates
the request, writes a new order to DynamoDB with status "pending", and
enqueues its order_id on SQS for process_order to pick up.

Only the order_id is sent on the queue (not the full payload) so DynamoDB
stays the single source of truth and SQS messages stay small.
"""
import json
import os
import uuid
from datetime import datetime, timezone

from common.boto3_clients import get_orders_table, sqs_client

REQUIRED_FIELDS = ("customer_id", "item", "quantity")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _validate(payload):
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        return f"Missing required field(s): {', '.join(missing)}"
    if not isinstance(payload["quantity"], (int, float)) or payload["quantity"] <= 0:
        return "quantity must be a positive number"
    return None


def lambda_handler(event, context):
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})

    validation_error = _validate(payload)
    if validation_error:
        return _response(400, {"error": validation_error})

    order_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    table = get_orders_table()
    table.put_item(
        Item={
            "order_id": order_id,
            "customer_id": payload["customer_id"],
            "item": payload["item"],
            "quantity": payload["quantity"],
            "status": "pending",
            "created_at": created_at,
        }
    )

    sqs_client.send_message(
        QueueUrl=os.environ["ORDERS_QUEUE_URL"],
        MessageBody=json.dumps({"order_id": order_id}),
    )

    return _response(201, {"order_id": order_id, "status": "pending"})
