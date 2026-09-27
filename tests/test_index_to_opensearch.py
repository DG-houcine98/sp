"""
moto doesn't mock OpenSearch, so these tests avoid any real network/AWS call:
_deserialize_image is tested as pure logic, and lambda_handler is tested by
patching _get_opensearch_client to return a plain Mock instead of a real
OpenSearch client.
"""
from unittest.mock import MagicMock, patch

from conftest import load_handler_module


def test_deserialize_image_unwraps_dynamodb_wire_format():
    handler_module = load_handler_module("index_to_opensearch")

    wire_format = {
        "order_id": {"S": "order-1"},
        "quantity": {"N": "3"},
        "customer_id": {"S": "cust-1"},
    }

    result = handler_module._deserialize_image(wire_format)

    assert result == {"order_id": "order-1", "quantity": 3, "customer_id": "cust-1"}


def _stream_event(event_name, order_id, new_image=None):
    dynamodb_block = {"Keys": {"order_id": {"S": order_id}}}
    if new_image is not None:
        dynamodb_block["NewImage"] = new_image
    return {"Records": [{"eventName": event_name, "dynamodb": dynamodb_block}]}


def test_insert_event_indexes_document():
    handler_module = load_handler_module("index_to_opensearch")
    mock_client = MagicMock()

    with patch.object(handler_module, "_get_opensearch_client", return_value=mock_client):
        event = _stream_event(
            "INSERT",
            "order-1",
            new_image={"order_id": {"S": "order-1"}, "status": {"S": "pending"}},
        )
        handler_module.lambda_handler(event, context=None)

    mock_client.index.assert_called_once_with(
        index="orders", id="order-1", body={"order_id": "order-1", "status": "pending"}
    )
    mock_client.delete.assert_not_called()


def test_remove_event_deletes_document():
    handler_module = load_handler_module("index_to_opensearch")
    mock_client = MagicMock()

    with patch.object(handler_module, "_get_opensearch_client", return_value=mock_client):
        event = _stream_event("REMOVE", "order-2")
        handler_module.lambda_handler(event, context=None)

    mock_client.delete.assert_called_once_with(index="orders", id="order-2", ignore=[404])
    mock_client.index.assert_not_called()
