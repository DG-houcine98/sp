from datetime import datetime, timedelta, timezone

from conftest import load_handler_module


def _put_order(table, order_id, status, age_minutes):
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    table.put_item(
        Item={
            "order_id": order_id,
            "customer_id": "cust-1",
            "item": "widget",
            "quantity": 1,
            "status": status,
            "created_at": created_at,
        }
    )


def test_old_pending_order_is_deleted(orders_table, monkeypatch):
    monkeypatch.setenv("STALE_AFTER_MINUTES", "60")
    _put_order(orders_table, "stale-order", status="pending", age_minutes=120)

    handler_module = load_handler_module("cleanup_stale_orders")
    result = handler_module.lambda_handler({}, context=None)

    assert result["deleted_count"] == 1
    assert "Item" not in orders_table.get_item(Key={"order_id": "stale-order"})


def test_recent_pending_order_is_untouched(orders_table, monkeypatch):
    monkeypatch.setenv("STALE_AFTER_MINUTES", "60")
    _put_order(orders_table, "fresh-order", status="pending", age_minutes=5)

    handler_module = load_handler_module("cleanup_stale_orders")
    result = handler_module.lambda_handler({}, context=None)

    assert result["deleted_count"] == 0
    assert "Item" in orders_table.get_item(Key={"order_id": "fresh-order"})


def test_old_completed_order_is_untouched(orders_table, monkeypatch):
    monkeypatch.setenv("STALE_AFTER_MINUTES", "60")
    _put_order(orders_table, "completed-order", status="completed", age_minutes=120)

    handler_module = load_handler_module("cleanup_stale_orders")
    result = handler_module.lambda_handler({}, context=None)

    assert result["deleted_count"] == 0
    assert "Item" in orders_table.get_item(Key={"order_id": "completed-order"})
