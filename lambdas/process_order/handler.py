"""
process_order Lambda.

Triggered by the orders SQS queue (batch of order_id messages). For each
order: fetches it from DynamoDB, marks it "completed", and publishes a
notification to SNS. Uses SQS's partial-batch-failure reporting so a failure
on one message doesn't force a retry of the whole batch - only the failed
messageIds get redelivered.

Packaged as a container image (docker/Dockerfile.lambda) rather than a zip,
to demonstrate that packaging path alongside the zip-based functions.
"""
import json
import logging
import os
import traceback

from common.boto3_clients import get_orders_table, sns_client

logger = logging.getLogger(__name__)


def _process_single_order(order_id):
    table = get_orders_table()
    response = table.get_item(Key={"order_id": order_id})
    order = response.get("Item")
    if order is None:
        raise ValueError(f"order_id {order_id} not found in DynamoDB")

    if order.get("status") == "completed":
        return  # already processed - idempotent no-op on redelivery

    table.update_item(
        Key={"order_id": order_id},
        UpdateExpression="SET #status = :completed",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":completed": "completed"},
    )

    sns_client.publish(
        TopicArn=os.environ["ORDERS_TOPIC_ARN"],
        Subject="Order completed",
        Message=json.dumps(
            {
                "order_id": order_id,
                "customer_id": order.get("customer_id"),
                "item": order.get("item"),
                # DynamoDB's resource API returns numbers as Decimal, which
                # json.dumps cannot serialize by default - cast explicitly.
                "quantity": int(order.get("quantity")),
                "status": "completed",
            }
        ),
    )


def lambda_handler(event, context):
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            _process_single_order(body["order_id"])
        except Exception:
            logger.error("Failed to process message %s:\n%s", message_id, traceback.format_exc())
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
