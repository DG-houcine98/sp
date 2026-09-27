import json

import boto3

from conftest import TEST_REGION, TEST_TABLE_NAME, load_handler_module


def _invoke(body):
    handler_module = load_handler_module("create_order")
    event = {"body": json.dumps(body)}
    return handler_module.lambda_handler(event, context=None)


def test_valid_order_is_created(orders_table, orders_queue):
    response = _invoke({"customer_id": "cust-1", "item": "widget", "quantity": 2})

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert "order_id" in body
    assert body["status"] == "pending"

    table = boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE_NAME)
    stored = table.get_item(Key={"order_id": body["order_id"]})["Item"]
    assert stored["customer_id"] == "cust-1"
    assert stored["item"] == "widget"
    assert stored["status"] == "pending"

    sqs = boto3.client("sqs", region_name=TEST_REGION)
    messages = sqs.receive_message(QueueUrl=orders_queue, MaxNumberOfMessages=1)["Messages"]
    assert json.loads(messages[0]["Body"])["order_id"] == body["order_id"]


def test_missing_field_returns_400(orders_table, orders_queue):
    response = _invoke({"customer_id": "cust-1", "item": "widget"})  # no quantity

    assert response["statusCode"] == 400
    assert "quantity" in json.loads(response["body"])["error"]


def test_invalid_quantity_returns_400(orders_table, orders_queue):
    response = _invoke({"customer_id": "cust-1", "item": "widget", "quantity": -5})

    assert response["statusCode"] == 400
    assert "quantity" in json.loads(response["body"])["error"]


def test_malformed_json_body_returns_400(orders_table, orders_queue):
    handler_module = load_handler_module("create_order")
    response = handler_module.lambda_handler({"body": "not json"}, context=None)

    assert response["statusCode"] == 400
