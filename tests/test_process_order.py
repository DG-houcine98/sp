import json
from unittest.mock import patch

import boto3

from conftest import TEST_REGION, TEST_TABLE_NAME, load_handler_module


def _sqs_event(order_id, message_id="msg-1"):
    return {"Records": [{"messageId": message_id, "body": json.dumps({"order_id": order_id})}]}


def _put_order(order_id, status="pending"):
    table = boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE_NAME)
    table.put_item(
        Item={
            "order_id": order_id,
            "customer_id": "cust-1",
            "item": "widget",
            "quantity": 2,
            "status": status,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )


def test_pending_order_is_completed_and_notified(orders_table, orders_topic):
    _put_order("order-1", status="pending")
    handler_module = load_handler_module("process_order")

    with patch.object(handler_module.sns_client, "publish") as mock_publish:
        result = handler_module.lambda_handler(_sqs_event("order-1"), context=None)

    assert result["batchItemFailures"] == []
    mock_publish.assert_called_once()

    stored = orders_table.get_item(Key={"order_id": "order-1"})["Item"]
    assert stored["status"] == "completed"


def test_already_completed_order_is_not_republished(orders_table, orders_topic):
    _put_order("order-2", status="completed")
    handler_module = load_handler_module("process_order")

    with patch.object(handler_module.sns_client, "publish") as mock_publish:
        result = handler_module.lambda_handler(_sqs_event("order-2"), context=None)

    assert result["batchItemFailures"] == []
    mock_publish.assert_not_called()  # idempotent no-op, already processed


def test_missing_order_is_reported_as_batch_item_failure(orders_table, orders_topic):
    handler_module = load_handler_module("process_order")

    result = handler_module.lambda_handler(_sqs_event("does-not-exist", message_id="msg-9"), context=None)

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-9"}]


def test_one_bad_record_does_not_fail_the_whole_batch(orders_table, orders_topic):
    _put_order("order-3", status="pending")
    handler_module = load_handler_module("process_order")

    event = {
        "Records": [
            {"messageId": "msg-ok", "body": json.dumps({"order_id": "order-3"})},
            {"messageId": "msg-bad", "body": json.dumps({"order_id": "does-not-exist"})},
        ]
    }

    with patch.object(handler_module.sns_client, "publish"):
        result = handler_module.lambda_handler(event, context=None)

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-bad"}]
    assert orders_table.get_item(Key={"order_id": "order-3"})["Item"]["status"] == "completed"
